"""The owner's team: employers (admin) add and remove employees (staff); nobody but the platform operator makes an admin."""
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

from agentic_sales.language.analyzer import Analyzer
from agentic_sales.models.base import ModelRouter
from tests.test_api import BIZ


@unittest.skipUnless(HAVE_API, "needs fastapi + httpx (use the project .venv)")
class Team(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.auth = AuthStore(self.root)
        self.owner = self.auth.create_tenant("shop-a", BIZ, plan="growth")
        self.other = self.auth.create_tenant("shop-b", {**BIZ, "business_name": "Other"}, plan="growth")
        self.op = self.auth.issue_platform_key("tester")
        self.c = TestClient(create_app(self.root, Runtimes(self.root, None, ModelRouter(), Analyzer(None)), self.auth))

    def H(self, key):
        return {"Authorization": f"Bearer {key}"}

    def hire(self, label="Bola (sales)", **extra):
        r = self.c.post("/v1/team", headers=self.H(self.owner), json={"label": label, **extra})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["key"]

    def test_the_owner_adds_a_staff_member_who_can_sign_in_and_is_only_staff(self):
        key = self.hire()
        me = self.c.get("/v1/me", headers=self.H(key)).json()
        self.assertEqual((me["role"], me["key_label"], me["tenant_id"]), ("staff", "Bola (sales)", "shop-a"))
        self.assertEqual(me["can"], {"books": False, "publish": False, "team": False})

    def test_there_is_no_way_to_ask_for_an_admin(self):
        r = self.c.post("/v1/team", headers=self.H(self.owner), json={"label": "Sneaky", "role": "admin"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["role"], "staff")
        self.assertEqual(self.c.get("/v1/me", headers=self.H(r.json()["key"])).json()["role"], "staff")

    def test_staff_cannot_manage_the_team(self):
        staff = self.hire()
        self.assertEqual(self.c.get("/v1/team", headers=self.H(staff)).status_code, 403)
        self.assertEqual(self.c.post("/v1/team", headers=self.H(staff), json={"label": "Friend"}).status_code, 403)
        self.assertEqual(self.c.delete("/v1/team/1", headers=self.H(staff)).status_code, 403)

    def test_the_owner_can_remove_staff_but_never_an_admin_key(self):
        staff = self.hire()
        rows = self.c.get("/v1/team", headers=self.H(self.owner)).json()
        admin_row = next(r for r in rows if r["role"] == "admin")
        staff_row = next(r for r in rows if r["role"] == "staff")
        self.assertTrue(admin_row["you"])
        self.assertEqual(self.c.delete(f"/v1/team/{admin_row['id']}", headers=self.H(self.owner)).status_code, 403)       # no lock-out, no admin changes
        self.assertEqual(self.c.get("/v1/me", headers=self.H(self.owner)).status_code, 200)
        self.assertEqual(self.c.delete(f"/v1/team/{staff_row['id']}", headers=self.H(self.owner)).status_code, 200)
        self.assertEqual(self.c.get("/v1/me", headers=self.H(staff)).status_code, 401)

    def test_one_business_cannot_see_or_remove_another_businesss_people(self):
        theirs = self.c.post("/v1/team", headers=self.H(self.other), json={"label": "Their staff"}).json()
        other_rows = self.c.get("/v1/team", headers=self.H(self.other)).json()
        their_id = next(r["id"] for r in other_rows if r["role"] == "staff")
        self.assertNotIn("Their staff", [r["label"] for r in self.c.get("/v1/team", headers=self.H(self.owner)).json()])
        self.assertEqual(self.c.delete(f"/v1/team/{their_id}", headers=self.H(self.owner)).status_code, 404)
        self.assertEqual(self.c.get("/v1/me", headers=self.H(theirs["key"])).status_code, 200)

    def test_new_staff_keys_expire_by_default_and_the_plan_key_limit_applies(self):
        self.hire()
        row = next(r for r in self.c.get("/v1/team", headers=self.H(self.owner)).json() if r["role"] == "staff")
        self.assertIsNotNone(row["expires"])
        starter = self.auth.create_tenant("tiny", BIZ, plan="starter")
        codes = [self.c.post("/v1/team", headers=self.H(starter), json={"label": f"Person {i}"}).status_code for i in range(8)]
        self.assertIn(402, codes)

    def test_every_change_is_in_the_audit_log(self):
        self.hire("Bola (sales)")
        row = next(r for r in self.c.get("/v1/team", headers=self.H(self.owner)).json() if r["role"] == "staff")
        self.c.delete(f"/v1/team/{row['id']}", headers=self.H(self.owner))
        actions = [a["action"] for a in self.c.get("/admin/audit", headers=self.H(self.op)).json()]
        self.assertIn("team_staff_added", actions)
        self.assertIn("team_staff_removed", actions)

    def test_staff_do_not_see_the_books_or_publish_unless_the_owner_allows_it(self):
        staff = self.hire()
        self.assertEqual(self.c.get("/v1/books", headers=self.H(staff)).status_code, 403)
        self.assertEqual(self.c.post("/v1/content/1/publish", headers=self.H(staff)).status_code, 403)
        self.assertEqual(self.c.post("/v1/content/publish-due", headers=self.H(staff)).status_code, 403)
        self.assertEqual(self.c.get("/v1/books", headers=self.H(self.owner)).status_code, 200)
        cfg = self.c.get("/v1/config", headers=self.H(self.owner)).json()
        r = self.c.put("/v1/config", headers=self.H(self.owner), json={**cfg, "staff_can_see_books": True, "staff_can_publish": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.c.get("/v1/books", headers=self.H(staff)).status_code, 200)
        self.assertNotEqual(self.c.post("/v1/content/publish-due", headers=self.H(staff)).status_code, 403)
        self.assertEqual(self.c.get("/v1/me", headers=self.H(staff)).json()["can"], {"books": True, "publish": True, "team": False})

    def test_who_decided_is_recorded_by_name(self):
        staff = self.hire("Bola (sales)")
        rt = self.c.app.state.runtimes.get("shop-a")
        aid = rt.memory.request_approval("a" * 16, "web:c1", "human_handoff", {"reason": "x"}, ("x",))
        self.assertEqual(self.c.post(f"/v1/approvals/{aid}/decision", headers=self.H(staff), json={"approve": False}).status_code, 200)
        trace = self.c.get("/v1/audit/" + "a" * 16, headers=self.H(self.owner)).json()
        self.assertTrue(any("Bola (sales)" in str(e) for e in trace), trace)


if __name__ == "__main__":
    unittest.main()
