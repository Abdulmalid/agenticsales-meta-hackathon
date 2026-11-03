"""The owner's spending limits: a guard against typing slips, enforced in code, with a deliberate way past it in the console."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

try:
    from fastapi.testclient import TestClient
    from agentic_sales.server.app import create_app
    from agentic_sales.server.auth import AuthStore
    from agentic_sales.server.runtime import Runtimes
    HAVE_API = True
except ImportError:
    HAVE_API = False

from agentic_sales import books
from agentic_sales.core.types import TenantContext
from agentic_sales.language.analyzer import Analyzer
from agentic_sales.memory.store import TenantMemory
from agentic_sales.models.base import ModelRouter
from agentic_sales.server.plans import Gate
from tests.test_scheduler import BIZ

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc)


class Limits(unittest.TestCase):
    def setUp(self):
        self.b = books.Books(TenantMemory(TenantContext("shop-a"), Path(tempfile.mkdtemp())))

    def test_nothing_is_limited_until_the_owner_sets_a_limit(self):
        self.assertEqual(self.b.limits(), {"per_expense_kobo": None, "daily_kobo": None})
        self.assertEqual(self.b.add(100_000_000, "big", now=NOW)["amount_kobo"], 100_000_000)

    def test_one_expense_above_the_limit_is_refused_unless_confirmed(self):
        self.b.set_limits(20_000_000, None)
        with self.assertRaises(books.OverLimit) as cm:
            self.b.add(100_000_000, "Quillox", now=NOW)
        self.assertIn("₦200,000", str(cm.exception))
        self.assertEqual(self.b.recent(5), [])
        self.assertEqual(self.b.add(100_000_000, "Quillox", now=NOW, confirmed=True)["amount_kobo"], 100_000_000)
        self.assertEqual(self.b.add(20_000_000, "at the limit", now=NOW)["amount_kobo"], 20_000_000)

    def test_the_daily_limit_counts_what_was_already_spent_today(self):
        self.b.set_limits(None, 50_000_000)
        self.b.add(30_000_000, "fuel", now=NOW)
        with self.assertRaises(books.OverLimit) as cm:
            self.b.add(30_000_000, "stock", now=NOW)
        self.assertIn("already spent today", str(cm.exception))
        self.b.add(20_000_000, "airtime", now=NOW)

    def test_a_chat_message_over_the_limit_is_not_logged_and_says_why(self):
        self.b.set_limits(100_000, None)
        reply = books.owner_reply(self.b, "spent 5k on transport", NOW)
        self.assertIn("Not logged", reply)
        self.assertEqual(self.b.recent(5), [])
        self.assertIn("Logged", books.owner_reply(self.b, "spent 800 on bolt", NOW))

    def test_removing_a_limit(self):
        self.b.set_limits(100, 200)
        self.b.set_limits(None, None)
        self.assertEqual(self.b.limits(), {"per_expense_kobo": None, "daily_kobo": None})


@unittest.skipUnless(HAVE_API, "needs fastapi + httpx (use the project .venv)")
class Api(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.auth = AuthStore(self.root)
        self.key = self.auth.create_tenant("shop-a", BIZ, plan="growth")
        self.staff = self.auth.issue_key("shop-a", "staff")
        self.c = TestClient(create_app(self.root, Runtimes(self.root, None, ModelRouter(), Analyzer(None)), self.auth))
        self.H = {"Authorization": f"Bearer {self.key}"}

    def test_limits_are_set_by_the_admin_and_an_over_limit_expense_needs_confirming(self):
        self.assertEqual(self.c.put("/v1/books/limits", headers={"Authorization": f"Bearer {self.staff}"}, json={"per_expense_kobo": 1}).status_code, 403)
        self.assertEqual(self.c.put("/v1/books/limits", headers=self.H, json={"per_expense_kobo": 500_000, "daily_kobo": 100_000}).status_code, 422)
        self.assertEqual(self.c.put("/v1/books/limits", headers=self.H, json={"per_expense_kobo": 20_000_000}).status_code, 200)
        self.assertEqual(self.c.get("/v1/books", headers=self.H).json()["limits"]["per_expense_kobo"], 20_000_000)
        r = self.c.post("/v1/expenses", headers=self.H, json={"amount_kobo": 100_000_000, "note": "Quillox"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("above your limit", r.json()["detail"])
        self.assertEqual(self.c.post("/v1/expenses", headers=self.H, json={"amount_kobo": 100_000_000, "note": "Quillox", "confirm": True}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
