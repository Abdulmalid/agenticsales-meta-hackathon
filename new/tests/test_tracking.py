"""Order tracking: the shop moves a paid order along, the customer can ask the rep or open a link, and nobody can invent a stage."""
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
    from agentic_sales.server.app import create_app
    from agentic_sales.server.auth import AuthStore
    from agentic_sales.server.runtime import Runtimes
    HAVE_API = True
except ImportError:
    HAVE_API = False

from agentic_sales.config.business import naira
from agentic_sales.language.analyzer import Analyzer
from agentic_sales.models.base import ModelRouter
from agentic_sales.tools.registry import Status
from tests.test_backend import FakeGateway
from tests.test_inventory_api import BIZ


@unittest.skipUnless(HAVE_API, "needs fastapi + httpx (use the project .venv)")
class Tracking(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.auth = AuthStore(self.root)
        self.admin = self.auth.create_tenant("shoes", BIZ, plan="growth")
        self.staff = self.auth.issue_key("shoes", "staff")
        self.other = self.auth.create_tenant("other", BIZ, plan="growth")
        self.runtimes = Runtimes(self.root, None, ModelRouter(), Analyzer(None))
        self.c = TestClient(create_app(self.root, self.runtimes, self.auth))
        self.rt = self.runtimes.get("shoes")
        self.pay = self.rt.orchestrator.payments
        self.pay.gateway = FakeGateway()
        self.pay.receipt_base = "https://shop.test/receipt/shoes"
        self.rt.memory.remember("web:u1", "delivery_address", "12 Allen Ave, Ikeja", "test")

    def H(self, key=None):
        return {"Authorization": f"Bearer {key or self.admin}"}

    def order(self, customer="web:u1", paid=True):
        r = self.pay.create_order_link(customer, "BOOT", 1, "a@b.co")
        if paid:
            self.pay.gateway.paid[r.reference] = ("success", naira(45_000), "NGN")
            self.pay.confirm(r.reference)
        return r.reference

    def move(self, ref, key=None, **body):
        return self.c.post(f"/v1/orders/{ref}/delivery", headers=self.H(key), json=body)

    def test_a_paid_order_starts_as_being_prepared_and_the_shop_moves_it_on(self):
        ref = self.order()
        self.assertEqual(self.pay.delivery.where(self.pay.order(ref))["stage"], "preparing")
        r = self.move(ref, stage="shipped", carrier="GIG Logistics", tracking_code="GIG123", note="Leaves Lagos today")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["delivery"]["label"], r.json()["delivery"]["tracking_code"]), ("On its way", "GIG123"))
        feed = self.c.get("/v1/orders", headers=self.H()).json()
        self.assertEqual((feed[0]["delivery"]["stage"], feed[0]["track_url"]), ("shipped", f"https://shop.test/track/shoes/{ref}"))

    def test_the_customer_is_told_when_the_order_moves_and_only_when_it_changes(self):
        ref = self.order()
        self.move(ref, stage="shipped", carrier="GIG", tracking_code="G1")
        self.move(ref, stage="shipped", carrier="GIG", tracking_code="G1")                       # the same update again: nothing new to say
        sent = lambda: [r["text"] for r in self.rt.memory.con.execute("SELECT text FROM outbox WHERE purpose='order_update'")]
        self.assertEqual(len(sent()), 1)
        self.assertIn("On its way", sent()[0])
        self.assertIn(f"https://shop.test/track/shoes/{ref}", sent()[0])
        self.move(ref, stage="delivered", notify=False)                                          # the shop chose not to tell the customer
        self.assertEqual(len(sent()), 1)

    def test_only_a_paid_order_can_be_moved_and_a_delivered_one_stays_delivered(self):
        unpaid = self.order(paid=False)
        self.assertEqual(self.move(unpaid, stage="shipped").status_code, 422)
        self.assertEqual(self.move("AS-nope", stage="shipped").status_code, 404)
        ref = self.order()
        self.assertEqual(self.move(ref, stage="teleported").status_code, 422)
        self.assertEqual(self.move(ref, stage="delivered").status_code, 200)
        self.assertEqual(self.move(ref, stage="shipped").status_code, 422)

    def test_staff_can_update_delivery_and_another_business_cannot(self):
        ref = self.order()
        self.assertEqual(self.move(ref, key=self.staff, stage="packed").status_code, 200)
        self.assertEqual(self.move(ref, key=self.other, stage="shipped").status_code, 404)
        self.assertEqual(self.c.post(f"/v1/orders/{ref}/delivery", json={"stage": "packed"}).status_code, 401)

    def test_the_tracking_page_shows_the_goods_and_never_the_address_or_amount(self):
        ref = self.order()
        self.move(ref, stage="out_for_delivery", note="Rider will call you")
        page = self.c.get(f"/track/shoes/{ref}")
        self.assertEqual(page.status_code, 200)
        for text in ("Leather boot", "Out for delivery", "Rider will call you", ref):
            self.assertIn(text, page.text)
        for text in ("Allen Ave", "45,000", "a@b.co"):
            self.assertNotIn(text, page.text)
        self.assertEqual(self.c.get("/track/shoes/AS-unknown").status_code, 404)
        self.assertEqual(self.c.get(f"/track/other/{ref}").status_code, 404)

    def test_the_note_cannot_run_a_script_on_the_page(self):
        ref = self.order()
        self.move(ref, stage="packed", note="<script>alert(1)</script>")
        page = self.c.get(f"/track/shoes/{ref}")
        self.assertNotIn("<script>alert", page.text)
        self.assertIn("default-src 'none'", page.headers["content-security-policy"])

    def test_the_rep_tool_returns_only_that_customers_orders_and_says_what_the_shop_recorded(self):
        from agentic_sales.tools.commerce import _track

        class Ctx:
            payments = self.pay
            customer_key = "web:u1"
        mine, theirs = self.order("web:u1"), self.order("web:u2")
        self.move(mine, stage="shipped", carrier="GIG", tracking_code="G9")
        res = _track(Ctx, {})
        self.assertEqual(res.status, Status.OK)
        refs = [o["order_reference"] for o in res.data["orders"]]
        self.assertEqual(refs, [mine])
        self.assertEqual(res.data["orders"][0]["tracking_code"], "G9")
        self.assertEqual(_track(Ctx, {"order_reference": theirs}).data["orders"], [])             # someone else's order looks like no order
        Ctx.customer_key = "web:nobody"
        self.assertEqual(_track(Ctx, {}).data["orders"], [])

    def test_a_part_paid_or_cancelled_order_is_never_described_as_on_its_way(self):
        ref = self.order(paid=False)
        self.assertEqual(self.pay.delivery.where(self.pay.order(ref))["stage"], "awaiting_payment")
        paid = self.order()
        self.pay.cancel_order(paid)
        self.assertEqual(self.pay.delivery.where(self.pay.order(paid))["stage"], "refund_due")


if __name__ == "__main__":
    unittest.main()
