"""A customer who says they have paid, or pastes the reference, is checked with the payment gateway by the server before the rep answers."""
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
from agentic_sales.models.base import ModelRouter, TaskKind
from tests.test_backend import FakeGateway
from tests.test_inventory_api import BIZ
from tests.test_public_chat import Scripted


@unittest.skipUnless(HAVE_API, "needs fastapi + httpx (use the project .venv)")
class PaymentClaims(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.model = Scripted()
        self.auth = AuthStore(self.root)
        self.key = self.auth.create_tenant("shoes", BIZ, plan="growth")
        self.runtimes = Runtimes(self.root, None, ModelRouter(text={TaskKind.CONVERSATION: self.model}), Analyzer(None))
        self.c = TestClient(create_app(self.root, self.runtimes, self.auth))
        self.H = {"Authorization": f"Bearer {self.key}"}
        self.pay = self.runtimes.get("shoes").orchestrator.payments
        self.pay.gateway = FakeGateway()

    def say(self, text, user="u1"):
        self.model.push("Okay.")
        r = self.c.post("/v1/chat", headers=self.H, json={"user_id": user, "text": text})
        self.assertEqual(r.status_code, 200, r.text)
        return self.model.requests[-1].system

    def link(self, paid=False, customer="web:u1"):
        ref = self.pay.create_order_link(customer, "BOOT", 1, "a@b.co").reference
        if paid:
            self.pay.gateway.paid[ref] = ("success", naira(45_000), "NGN")
        return ref

    def test_a_reference_that_the_gateway_says_is_paid_is_confirmed_by_the_server(self):
        ref = self.link(paid=True)
        system = self.say(f"Reference {ref} payment successful with this reference")
        self.assertIn("VERIFIED by the payment gateway", system)
        self.assertEqual(self.pay.order(ref)["status"], "paid")

    def test_saying_they_paid_without_a_reference_checks_their_latest_unpaid_order(self):
        ref = self.link(paid=True)
        system = self.say("i have made the payment")
        self.assertIn("VERIFIED by the payment gateway", system)
        self.assertEqual(self.pay.order(ref)["status"], "paid")

    def test_a_payment_the_gateway_has_not_received_is_never_called_confirmed(self):
        ref = self.link(paid=False)
        system = self.say(f"I have paid, the reference is {ref}")
        self.assertIn("has NOT received it yet", system)
        self.assertNotIn("VERIFIED by the payment gateway", system)
        self.assertEqual(self.pay.order(ref)["status"], "awaiting_payment")

    def test_a_reference_that_belongs_to_another_customer_is_not_accepted(self):
        ref = self.link(paid=True, customer="web:someone-else")
        system = self.say(f"{ref} paid", user="u1")
        self.assertIn("was not issued to this customer", system)
        self.assertEqual(self.pay.order(ref)["status"], "awaiting_payment")

    def test_a_message_that_is_not_about_payment_asks_the_gateway_nothing(self):
        self.link(paid=True)
        self.assertNotIn("done by the server just now", self.say("how much is the boot?"))


if __name__ == "__main__":
    unittest.main()
