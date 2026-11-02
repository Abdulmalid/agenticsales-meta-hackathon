"""Where leads come from (first touch), and the 'ideal customers' suggestions: honest about what they are."""
import json
import unittest
from datetime import datetime, timezone

from agentic_sales import analytics, growth
from agentic_sales.channels.adapters import ADAPTERS
from agentic_sales.config.business import naira
from agentic_sales.leads.models import LeadStage
from agentic_sales.models.base import ModelError
from tests.test_backend import NOW, Scripted, cfg, mk
from tests.test_installments import shop
from unittest import mock
from tests.test_comments import feed
from tests.test_vision import FakeVision, plan, runtime
from agentic_sales.channels.adapters import public_comments
from agentic_sales.vision.reader import PhotoReading


class FirstTouchOrigin(unittest.TestCase):
    def test_the_first_origin_sticks_and_later_ones_do_not_overwrite_it(self):
        o, *_ = shop()
        o.leads.get_or_create("web:a1", "web")
        o.leads.set_origin("web:a1", "chat_link", "instagram_bio")
        o.leads.set_origin("web:a1", "landing_page")
        lead = o.leads.get_by_key("web:a1")
        self.assertEqual((lead.attrs["origin"], lead.attrs["origin_detail"]), ("chat_link", "instagram_bio"))

    def test_a_lead_with_no_recorded_origin_is_credited_to_its_channel(self):
        o, *_ = shop()
        o.leads.get_or_create("telegram:9", "telegram")
        self.assertEqual(analytics.origin_of(o.leads.get_by_key("telegram:9")), ("telegram", ""))

    def test_the_funnel_counts_leads_hot_customers_and_money_per_origin_and_per_post(self):
        o, gw, *_ = shop()
        for key, origin, detail in (("facebook:1", "page_comment", "POST_A"), ("facebook:2", "page_comment", "POST_A"),
                                    ("web:w1", "chat_link", "instagram_bio"), ("telegram:5", None, "")):
            o.leads.get_or_create(key, key.split(":")[0])
            if origin:
                o.leads.set_origin(key, origin, detail)
        buyer = o.leads.get_by_key("facebook:1")
        buyer.stage = LeadStage.CONVERTED
        o.leads.save(buyer)
        with o.memory.con:
            o.memory.con.execute("INSERT INTO purchases(lead_id,sku,amount_kobo,reference,ts) VALUES(?,?,?,?,?)",
                                 (buyer.id, "IP15", naira(800_000), "R1", NOW.isoformat()))
        f = analytics.funnel(o.leads)
        self.assertEqual(f["by_source"]["page_comment"], {"leads": 2, "converted": 1, "hot": 0, "revenue_kobo": naira(800_000)})
        self.assertEqual(f["by_source"]["chat_link"]["leads"], 1)
        self.assertEqual(f["by_source"]["telegram"]["leads"], 1)
        post = next(d for d in f["by_detail"] if d["detail"] == "POST_A")
        self.assertEqual((post["origin"], post["leads"], post["converted"]), ("page_comment", 2, 1))


class CommentsBecomeLeadsWithTheirPost(unittest.TestCase):
    def test_a_commenter_is_a_lead_credited_to_the_post(self):
        rt = runtime(Scripted(plan("Yes we have it. Message us to order!")), FakeVision(PhotoReading("other", None, 0.5, "", "")))
        with mock.patch.object(ADAPTERS["facebook"], "reply_comment"):
            rt.handle_comment(public_comments(feed(post="1405_9"))[0])
        lead = rt.orchestrator.leads.get_by_key("facebook:555")
        self.assertEqual((lead.attrs["origin"], lead.attrs["origin_detail"]), ("page_comment", "1405_9"))


def segs(**over):
    base = {"name": "Office upgraders", "who": "Salaried people in Lagos.", "why": "They want a reliable phone.", "fit": 88, "skus": ["IP15", "NOPE"],
            "hook": "Your next phone, sealed.", "post": "Brand new iPhone 15 in stock. DM us.", "reply": "It is ₦800,000, brand new and sealed."}
    return json.dumps({"segments": [{**base, **over}]})


class IdealCustomers(unittest.TestCase):
    def test_a_good_answer_is_cleaned_and_bounded(self):
        got = growth.parse(segs(fit=250), cfg())
        self.assertEqual((got[0]["fit"], got[0]["skus"], got[0]["needs_edit"]), (100, ["IP15"], []))     # unknown SKU dropped, fit clamped

    def test_a_price_that_is_not_the_shops_is_never_shown_as_advice(self):
        got = growth.parse(segs(post="Only ₦500,000 today!", reply="It is ₦800,000."), cfg())
        self.assertEqual(got[0]["post"], "")
        self.assertEqual(got[0]["needs_edit"], ["post"])
        self.assertIn("₦800,000", got[0]["reply"])

    def test_segments_are_ranked_by_fit_and_limited(self):
        many = json.dumps({"segments": [{"name": f"Group {i}", "fit": i * 10} for i in range(8)]})
        got = growth.parse(many, cfg())
        self.assertEqual(len(got), growth.MAX_SEGMENTS)
        self.assertEqual([s["fit"] for s in got], sorted([s["fit"] for s in got], reverse=True))

    def test_garbage_is_an_error_not_a_made_up_answer(self):
        for bad in ("no json", "{}", '{"segments": []}', '{"segments": [{"fit": 5}]}'):
            with self.assertRaises(ModelError):
                growth.parse(bad, cfg())

    def test_the_request_carries_only_the_shops_own_catalogue(self):
        model = Scripted(json.loads(segs()))
        got = growth.suggest(model, cfg())
        self.assertEqual(got[0]["name"], "Office upgraders")
        system = model.requests[0].system
        self.assertIn("IP15: iPhone 15, ₦800,000", system)
        self.assertIn("Do not invent products, prices", system)


if __name__ == "__main__":
    unittest.main()
