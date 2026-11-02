import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from agentic_sales.channels.adapters import ADAPTERS
from agentic_sales.config.business import naira
from agentic_sales.language.analyzer import Analyzer
from agentic_sales.models.base import ModelRouter
from agentic_sales.server.app import create_app
from agentic_sales.server.auth import AuthStore
from agentic_sales.server.runtime import Runtimes

BIZ = {"business_name": "PhoneHub Lagos", "industry": "electronics retail", "brand_voice": "warm", "agent_name": "Ezenna", "address": "12 Allen Avenue, Ikeja, Lagos",
       "delivery_areas": ["Lagos"], "payment_methods": ["paystack"],
       "products": [{"sku": "IP15", "name": "iPhone 15", "price_kobo": naira(800_000), "floor_price_kobo": naira(740_000), "description": "Brand new", "in_stock": True}],
       "approvals": {"max_discount_pct_auto": 5, "max_discount_pct_hard": 10}}
SMTP = {"smtp_host": "smtp.example.com", "smtp_port": 465, "username": "u", "password": "p", "from_addr": "hello@phonehub.example"}


class OutreachApi(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"PUBLIC_BASE_URL": "https://api.example.com"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.root = Path(tempfile.mkdtemp())
        self.auth = AuthStore(self.root)
        self.key = self.auth.create_tenant("shop-a", BIZ)
        self.app = create_app(self.root, Runtimes(self.root, None, ModelRouter(), Analyzer(None)), self.auth)
        self.c = TestClient(self.app)
        self.h = {"Authorization": f"Bearer {self.key}"}
        self.rt = self.app.state.runtimes.get("shop-a")
        self.rt.secrets.set("email", SMTP)

    def test_the_whole_flow_import_draft_approve_send_and_unsubscribe(self):
        r = self.c.post("/v1/outreach/import", headers=self.h, json={"rows": [{"email": "ada@example.com", "name": "Ada"}, {"email": "bad"}], "basis": "business_contact"})
        self.assertEqual(r.status_code, 422)                                              # not attested
        r = self.c.post("/v1/outreach/import", headers=self.h, json={"rows": [{"email": "ada@example.com", "name": "Ada"}, {"email": "bad"}],
                                                                       "basis": "business_contact", "attested": True})
        self.assertEqual(r.json(), {"added": 1, "duplicates": 0, "invalid": 1, "suppressed": 0})
        self.assertEqual(self.c.post("/v1/outreach/draft", headers=self.h, json={"offer": "We supply phones"}).json()["drafted"], 1)
        state = self.c.get("/v1/outreach", headers=self.h).json()
        pid = state["prospects"][0]["id"]
        self.assertEqual(state["summary"]["counts"], {"drafted": 1})
        self.assertEqual(self.c.put(f"/v1/outreach/prospects/{pid}", headers=self.h, json={"subject": "Hi", "body": "It costs ₦5,000."}).status_code, 422)
        self.assertEqual(self.c.post("/v1/outreach/approve", headers=self.h, json={}).json(), {"approved": 1})
        with mock.patch.object(ADAPTERS["email"], "send_message") as send:
            out = self.c.post("/v1/outreach/send", headers=self.h).json()
        self.assertEqual((out["sent"], out["blocked"]), (1, ""))
        to, subject, text, _, headers = send.call_args.args
        self.assertEqual(to, "ada@example.com")
        self.assertIn("List-Unsubscribe", headers)
        self.assertNotIn("http", text)                                                    # no link in a cold email's body; it lands in spam
        url = headers["List-Unsubscribe"].split("<https://api.example.com")[1].rstrip(">")      # the one-click link lives in the header only
        page = self.c.get(url)                                                            # a link scanner opening it unsubscribes nobody
        self.assertIn("Unsubscribe</button>", page.text)
        self.assertFalse(self.rt.outreach.is_suppressed("ada@example.com"))
        done = self.c.post(url)
        self.assertIn("will not email you again", done.text)
        self.assertTrue(self.rt.outreach.is_suppressed("ada@example.com"))
        self.assertEqual(self.c.post("/unsubscribe/shop-a/not-a-token").status_code, 200)  # an unknown token reveals nothing
        self.assertEqual(self.c.get("/unsubscribe/nope/x").status_code, 404)

    def test_outreach_needs_a_business_key_and_the_import_is_bounded(self):
        self.assertEqual(self.c.get("/v1/outreach").status_code, 401)
        rows = [{"email": f"p{i}@example.com"} for i in range(501)]
        self.assertEqual(self.c.post("/v1/outreach/import", headers=self.h, json={"rows": rows, "basis": "consented", "attested": True}).status_code, 422)

    def test_an_inbound_stop_email_suppresses_the_sender(self):
        self.rt.outreach.import_prospects([{"email": "ada@example.com"}], "consented", True)
        self.rt.outreach.on_inbound("ada@example.com", "STOP please")
        self.assertTrue(self.rt.outreach.is_suppressed("ada@example.com"))


if __name__ == "__main__":
    unittest.main()
