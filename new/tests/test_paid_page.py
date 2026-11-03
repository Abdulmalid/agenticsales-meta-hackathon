"""The page a customer lands on after paying: it asks the gateway, shows what happened, and never says "received" for an unpaid reference."""
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
from tests.test_backend import FakeGateway
from tests.test_inventory_api import BIZ


@unittest.skipUnless(HAVE_API, "needs fastapi + httpx (use the project .venv)")
class PaidPage(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.auth = AuthStore(self.root)
        self.auth.create_tenant("shoes", BIZ, plan="growth")
        self.runtimes = Runtimes(self.root, None, ModelRouter(), Analyzer(None))
        self.c = TestClient(create_app(self.root, self.runtimes, self.auth))
        self.rt = self.runtimes.get("shoes")
        self.pay = self.rt.orchestrator.payments
        self.pay.gateway = FakeGateway()
        self.pay.receipt_base = "https://shop.test/receipt/shoes"
        self.rt.memory.remember("web:u1", "delivery_address", "12 Allen Ave, Ikeja", "test")

    def link(self):
        return self.pay.create_order_link("web:u1", "BOOT", 1, "a@b.co")

    def test_the_payment_link_sends_the_browser_to_our_page_for_that_payment(self):
        r = self.link()
        self.assertEqual(self.pay.gateway.callbacks[r.reference], f"https://shop.test/paid/shoes/{r.reference}")

    def test_a_confirmed_payment_shows_received_with_receipt_and_tracking_and_no_private_details(self):
        r = self.link()
        self.pay.gateway.paid[r.reference] = ("success", naira(45_000), "NGN")
        page = self.c.get(f"/paid/shoes/{r.reference}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Payment received", page.text)
        self.assertIn(f"https://shop.test/receipt/shoes/{r.reference}", page.text)
        self.assertIn(f"https://shop.test/track/shoes/{r.reference}", page.text)
        self.assertNotIn("Allen Ave", page.text)                                                   # no address on a link-only page
        self.assertNotIn("a@b.co", page.text)
        self.assertEqual(self.pay.order(r.reference)["status"], "paid")                           # the page confirmed it with the gateway, once
        paid_at = self.pay.order(r.reference)["paid_at"]
        stock = self.rt.cfg.product("BOOT").stock if hasattr(self.rt.cfg.product("BOOT"), "stock") else None
        self.assertEqual(self.c.get(f"/paid/shoes/{r.reference}").status_code, 200)               # a reload changes nothing
        self.assertEqual(self.pay.order(r.reference)["paid_at"], paid_at)
        if stock is not None:
            self.assertEqual(self.rt.cfg.product("BOOT").stock, stock)

    def test_an_unpaid_reference_never_reads_received_and_waits_a_bounded_number_of_times(self):
        r = self.link()
        page = self.c.get(f"/paid/shoes/{r.reference}")
        self.assertNotIn("Payment received", page.text)
        self.assertIn("Waiting for your bank", page.text)
        self.assertIn('http-equiv="refresh"', page.text)
        self.assertEqual(self.pay.order(r.reference)["status"], "awaiting_payment")
        self.assertNotIn('http-equiv="refresh"', self.c.get(f"/paid/shoes/{r.reference}?n=10").text)   # stops re-checking by itself
        self.assertEqual(self.c.get(f"/paid/shoes/{r.reference}?n=-5").status_code, 200)

    def test_a_failed_or_wrong_amount_payment_says_so_and_releases_nothing(self):
        r = self.link()
        self.pay.gateway.paid[r.reference] = ("success", naira(1_000), "NGN")                    # paid far less than the price
        page = self.c.get(f"/paid/shoes/{r.reference}")
        self.assertIn("could not confirm", page.text)
        self.assertNotIn("Payment received", page.text)
        self.assertEqual(self.pay.order(r.reference)["status"], "mismatch")

    def test_unknown_references_and_other_businesses_look_the_same(self):
        self.assertEqual(self.c.get("/paid/shoes/AS-nope").status_code, 404)
        self.assertEqual(self.c.get("/paid/nobody/AS-nope").status_code, 404)

    def test_the_page_is_locked_down(self):
        r = self.link()
        page = self.c.get(f"/paid/shoes/{r.reference}")
        self.assertIn("default-src 'none'", page.headers["content-security-policy"])
        self.assertEqual(page.headers["cache-control"], "private, no-store")


if __name__ == "__main__":
    unittest.main()
