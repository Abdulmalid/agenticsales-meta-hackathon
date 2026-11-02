import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agentic_sales.channels.adapters import ChannelError, ChannelUnavailable
from agentic_sales.config.business import BusinessConfig, Product, naira
from agentic_sales.core.types import TenantContext
from agentic_sales.memory.store import TenantMemory
from agentic_sales.models.base import ModelResponse, ModelRouter, TaskKind
from agentic_sales.outreach import LAWFUL_BASES, MAX_BODY_WORDS, Outreach, OutreachError

BIZ = BusinessConfig("PhoneHub Lagos", "electronics", agent_name="Ezenna", address="12 Allen Avenue, Ikeja, Lagos",
                     products=[Product("IP15", "iPhone 15", naira(800_000), naira(740_000), "Brand new, sealed")])
ROWS = [{"email": "Ada@Example.com", "name": "Ada Obi", "company": "Obi Stores", "note": "runs a phone retail shop in Yaba"},
        {"email": "bola@example.com", "name": "", "company": "", "note": ""},
        {"email": "not-an-email"}, {"email": "ada@example.com"}, {"email": "a..b@example.com"}]


class Secrets:
    def __init__(self, data=None):
        self.data = data or {}

    def get(self, section):
        return self.data.get(section, {})


class Model:
    name = "scripted"

    def __init__(self, *outs):
        self.outs = [o if isinstance(o, str) else json.dumps(o) for o in outs]
        self.requests = []

    def complete(self, req):
        self.requests.append(req)
        return ModelResponse(self.outs.pop(0), self.name)


def outreach(model=None, address=True, secrets=None):
    root = Path(tempfile.mkdtemp())
    ctx = TenantContext("shop-a")
    mem = TenantMemory(ctx, root)
    cfg = BIZ if address else BusinessConfig("PhoneHub Lagos", "electronics")
    router = ModelRouter(text={TaskKind.CONVERSATION: model}) if model else None
    return Outreach(mem, cfg, router, secrets or Secrets({"email": {}}), "shop-a"), mem


class Sender:
    def __init__(self, fail=None):
        self.sent, self.fail = [], fail

    def __call__(self, to, subject, text, secrets, headers):
        if self.fail:
            raise self.fail
        self.sent.append((to, subject, text, headers))


class Importing(unittest.TestCase):
    def test_import_validates_dedupes_and_requires_the_lawful_attestation(self):
        o, _ = outreach()
        with self.assertRaises(OutreachError):
            o.import_prospects(ROWS, "business_contact", attested=False)
        with self.assertRaises(OutreachError):
            o.import_prospects(ROWS, "scraped", attested=True)
        r = o.import_prospects(ROWS, "business_contact", attested=True)
        self.assertEqual(r, {"added": 2, "duplicates": 1, "invalid": 2, "suppressed": 0})
        self.assertEqual(o.import_prospects(ROWS[:2], "business_contact", True)["duplicates"], 2)        # again: nothing mailed twice
        self.assertEqual(o.list()[-1]["email"], "ada@example.com")                                         # stored lower-case
        self.assertIn("consented", LAWFUL_BASES)

    def test_a_suppressed_address_cannot_be_imported_again(self):
        o, _ = outreach()
        o.suppress("Ada@example.com", "asked to stop")
        r = o.import_prospects(ROWS[:2], "business_contact", True)
        self.assertEqual((r["added"], r["suppressed"]), (1, 1))

    def test_an_address_that_opted_out_of_the_shop_by_replying_stop_is_never_imported(self):
        o, mem = outreach()
        mem.opt_out("email:ada@example.com")
        self.assertEqual(o.import_prospects(ROWS[:1], "existing_relationship", True)["suppressed"], 1)


class Drafting(unittest.TestCase):
    def test_a_good_model_draft_is_kept_and_a_bad_one_falls_back_to_the_safe_template(self):
        good = {"subject": "Phones for Obi Stores", "body": "Hi Ada,\n\nI'm Ezenna at PhoneHub Lagos. We stock iPhone 15 for shops like yours.\n\nReply if you'd like details."}
        bad = {"subject": "Re: our chat", "body": "Hi, as we discussed, the iPhone 15 is ₦700,000, certified and 100% genuine!!"}
        model = Model(good, bad)
        o, _ = outreach(model)
        o.import_prospects(ROWS[:2], "business_contact", True)
        r = o.draft("We supply brand new phones to retailers", limit=10)
        self.assertEqual((r["drafted"], r["failed"], r["left"]), (2, 0, 0))
        rows = {p["email"]: p for p in o.list()}
        self.assertEqual(rows["ada@example.com"]["subject"], "Phones for Obi Stores")
        second = rows["bola@example.com"]
        self.assertNotIn("₦", second["body"])
        self.assertFalse(second["subject"].lower().startswith("re:"))
        self.assertNotIn("as we discussed", second["body"])
        self.assertIn("<prospect>", model.requests[0].messages[0].content)                         # recipient data is fenced as data

    def test_problems_catch_prices_claims_false_familiarity_reply_subjects_length_and_unsubscribe_lines(self):
        o, _ = outreach()
        self.assertEqual(o.problems("Hello", "Hi Ada, a quick note about phones. Reply if useful."), [])
        for subject, body in (("Hello", "The iPhone 15 is ₦800,000 for you."), ("Hello", "We are a registered company, CAC certified."),
                              ("Hello", "Following up on our call"), ("Hello", "You signed up on our site."), ("Re: hello", "Hi"),
                              ("", "Hi"), ("Hello", "word " * (MAX_BODY_WORDS + 1)), ("Hello", "Hi. Click unsubscribe below."),
                              ("Hello", "I am a real person, not a bot.")):
            self.assertTrue(o.problems(subject, body), (subject, body[:30]))

    def test_the_offer_is_required_and_edits_are_checked_again(self):
        o, _ = outreach()
        o.import_prospects(ROWS[:1], "business_contact", True)
        with self.assertRaises(OutreachError):
            o.draft("   ")
        o.draft("We supply phones")
        pid = o.list()[0]["id"]
        o.edit(pid, "A better subject", "Hi Ada, a shorter note. Reply if useful.")
        self.assertEqual(o.list()[0]["subject"], "A better subject")
        with self.assertRaises(OutreachError):
            o.edit(pid, "Hello", "It costs ₦500,000 today.")


class Sending(unittest.TestCase):
    def ready(self, **kw):
        o, mem = outreach(**kw)
        o.import_prospects(ROWS[:2], "business_contact", True)
        o.draft("We supply brand new phones to retailers")
        return o, mem

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"PUBLIC_BASE_URL": "https://api.example.com", "OUTREACH_DAILY_CAP": "30"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_nothing_is_sent_until_the_owner_approves_and_every_email_carries_the_footer_and_headers(self):
        o, mem = self.ready()
        s = Sender()
        self.assertEqual(o.send_due(sender=s).sent, 0)                                              # drafts are not approved
        self.assertEqual(o.approve(), 2)
        rep = o.send_due(sender=s)
        self.assertEqual((rep.sent, rep.failed), (2, 0))
        to, subject, text, headers = s.sent[0]
        self.assertIn("PhoneHub Lagos, 12 Allen Avenue, Ikeja, Lagos", text)
        self.assertIn("reply STOP", text)
        token = mem.con.execute("SELECT token FROM prospects WHERE email=?", (to,)).fetchone()["token"]
        self.assertNotIn("http", text)                                                              # no link in the body of a cold email: it lands in spam
        self.assertIn(f"<https://api.example.com/unsubscribe/shop-a/{token}>", headers["List-Unsubscribe"])
        self.assertEqual(headers["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
        self.assertEqual(o.send_due(sender=s).sent, 0)                                              # never sent twice
        self.assertEqual(len(mem.history(to)), 1)                                                   # the agent remembers what it wrote

    def test_editing_an_approved_draft_sends_it_back_for_approval(self):
        o, _ = self.ready()
        o.approve()
        pid = o.list()[0]["id"]
        o.edit(pid, "New subject", "Hi, a new note. Reply if useful.")
        self.assertEqual(o.list()[0]["status"], "drafted")
        s = Sender()
        self.assertEqual(o.send_due(sender=s).sent, 1)                                              # only the one still approved

    def test_the_daily_cap_limits_sending(self):
        o, _ = self.ready()
        o.approve()
        with mock.patch.dict(os.environ, {"OUTREACH_DAILY_CAP": "1"}):
            s = Sender()
            rep = o.send_due(sender=s)
            self.assertEqual((rep.sent, rep.remaining_today), (1, 0))
            self.assertEqual(o.send_due(sender=s).sent, 0)

    def test_it_will_not_send_without_a_business_address_a_public_url_or_email_settings(self):
        o, _ = self.ready(address=False)
        o.approve()
        self.assertIn("business address", o.send_due(sender=Sender()).blocked)
        o2, _ = self.ready()
        o2.approve()
        self.assertIn("not set up", o2.send_due().blocked)                                          # no SMTP settings, no test sender
        with mock.patch.dict(os.environ, {"PUBLIC_BASE_URL": ""}):
            self.assertIn("unsubscribe", o2.send_due(sender=Sender()).blocked)

    def test_unsubscribing_by_link_by_reply_or_earlier_opt_out_stops_every_later_email(self):
        o, mem = self.ready()
        o.approve()
        tok = {p["email"]: p["token"] for p in mem.con.execute("SELECT email, token FROM prospects")}
        self.assertTrue(o.unsubscribe(tok["ada@example.com"]))
        self.assertFalse(o.unsubscribe("nope"))
        s = Sender()
        rep = o.send_due(sender=s)
        self.assertEqual((rep.sent, rep.skipped), (1, 0))                                           # the unsubscribed one is no longer approved
        self.assertEqual([x[0] for x in s.sent], ["bola@example.com"])
        o.on_inbound("bola@example.com", "Please STOP emailing me")
        self.assertTrue(o.is_suppressed("bola@example.com"))
        self.assertEqual({p["email"]: p["status"] for p in o.list()}, {"ada@example.com": "unsubscribed", "bola@example.com": "unsubscribed"})

    def test_a_reply_marks_the_prospect_replied_and_a_failed_send_is_recorded_not_retried_forever(self):
        o, _ = self.ready()
        o.approve()
        o.send_due(sender=Sender())
        o.on_inbound("ada@example.com", "Yes, send me the price list")
        self.assertEqual({p["email"]: p["status"] for p in o.list()}["ada@example.com"], "replied")
        o3, _ = self.ready()
        o3.approve()
        rep = o3.send_due(sender=Sender(fail=ChannelError("SMTP failed: SMTPRecipientsRefused")))
        self.assertEqual((rep.sent, rep.failed), (0, 2))
        self.assertEqual({p["status"] for p in o3.list()}, {"failed"})
        o4, _ = self.ready()
        o4.approve()
        self.assertIn("not configured", o4.send_due(sender=Sender(fail=ChannelUnavailable("not configured"))).blocked)
        self.assertEqual({p["status"] for p in o4.list()}, {"approved"})                          # nothing lost when sending is simply unavailable

    def test_summary_and_removal(self):
        o, _ = self.ready()
        self.assertEqual(o.summary()["counts"], {"drafted": 2})
        self.assertTrue(o.summary()["ready_to_send"])
        pid = o.list()[0]["id"]
        self.assertTrue(o.remove(pid))
        self.assertEqual(len(o.list()), 1)


if __name__ == "__main__":
    unittest.main()
