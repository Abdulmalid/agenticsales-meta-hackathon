"""The timer for follow-ups, queued messages and the lead pipeline: off by default, owner-controlled, and never sending anything the owner did not approve."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

try:
    from fastapi.testclient import TestClient
    from agentic_sales.server.app import create_app
    from agentic_sales.server.auth import AuthStore
    from agentic_sales.server.runtime import Runtimes
    HAVE_API = True
except ImportError:
    HAVE_API = False

from agentic_sales.channels.adapters import ADAPTERS
from agentic_sales.config.business import naira
from agentic_sales.language.analyzer import Analyzer
from agentic_sales.models.base import ModelRouter
from agentic_sales.scheduler import Schedule, ScheduleError, Scheduler, in_sending_hours, read_rows
from agentic_sales.server.plans import Gate

BIZ = {"business_name": "PhoneHub Lagos", "industry": "electronics retail", "brand_voice": "warm", "agent_name": "Ezenna", "address": "12 Allen Avenue, Ikeja, Lagos",
       "delivery_areas": ["Lagos"], "payment_methods": ["paystack"],
       "products": [{"sku": "IP15", "name": "iPhone 15", "price_kobo": naira(800_000), "floor_price_kobo": naira(740_000), "description": "Brand new", "in_stock": True}],
       "approvals": {"max_discount_pct_auto": 5, "max_discount_pct_hard": 10}}
SMTP = {"smtp_host": "smtp.example.com", "smtp_port": 465, "username": "u", "password": "p", "from_addr": "hello@phonehub.example"}
SHEET = "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789/edit?gid=0"
CSV = "Full Name,Business,Role,E-mail,About\nAda Obi,Obi Stores,Owner,ada@example.com,sells phones\nTunde,,,tunde@example.com,\nnot a person,,,nope,\n"
MONDAY_10AM_LAGOS = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)          # Monday 10:00 in Lagos
SUNDAY_NOON = datetime(2026, 11, 1, 11, 0, tzinfo=timezone.utc)


@unittest.skipUnless(HAVE_API, "needs fastapi + httpx (use the project .venv)")
class SchedulerTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"PUBLIC_BASE_URL": "https://api.example.com"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.root = Path(tempfile.mkdtemp())
        self.auth = AuthStore(self.root)
        self.key = self.auth.create_tenant("shop-a", BIZ, plan="growth")
        self.staff = self.auth.issue_key("shop-a", "staff")
        self.auth.create_tenant("tiny", BIZ, plan="starter")
        self.runtimes = Runtimes(self.root, None, ModelRouter(), Analyzer(None))
        self.app = create_app(self.root, self.runtimes, self.auth)
        self.c = TestClient(self.app)
        self.rt = self.runtimes.get("shop-a")
        self.rt.secrets.set("email", SMTP)
        self.fetched = []
        self.sheet_text = CSV
        self.sched = Scheduler(self.runtimes, self.auth, Gate(self.auth), fetch=self._fetch)

    def _fetch(self, link):
        self.fetched.append(link)
        if isinstance(self.sheet_text, Exception):
            raise self.sheet_text
        return self.sheet_text

    def H(self, key=None):
        return {"Authorization": f"Bearer {key or self.key}"}

    def put(self, job, **body):
        return self.c.put(f"/v1/automation/{job}", headers=self.H(), json=body)

    # ---------------------------------------------------------------- off by default, owner in control
    def test_every_job_is_off_until_the_owner_turns_it_on_and_the_timer_itself_is_opt_in(self):
        state = self.c.get("/v1/automation", headers=self.H()).json()
        self.assertFalse(state["timer_on"])
        self.assertEqual([j["enabled"] for j in state["jobs"]], [False] * 7)
        self.assertEqual(self.sched.tick(MONDAY_10AM_LAGOS), 0)                                   # nothing runs for a business that switched nothing on
        self.assertFalse(self.app.state.scheduler.running)

    def test_only_an_admin_can_read_or_change_the_schedule(self):
        self.assertEqual(self.c.get("/v1/automation").status_code, 401)
        self.assertEqual(self.c.get("/v1/automation", headers=self.H(self.staff)).status_code, 403)
        self.assertEqual(self.c.put("/v1/automation/flush", headers=self.H(self.staff), json={"enabled": True}).status_code, 403)
        self.assertEqual(self.c.post("/v1/automation/flush/run", headers=self.H(self.staff)).status_code, 403)
        self.assertEqual(self.put("nope", enabled=True).status_code, 404)

    def test_a_job_that_needs_settings_cannot_be_switched_on_without_them(self):
        r = self.put("lead_import", enabled=True)
        self.assertEqual(r.status_code, 422)
        self.assertIn("url", r.json()["detail"])
        self.assertEqual(self.put("lead_import", config={"url": "https://evil.example/sheet"}).status_code, 422)         # only Google Sheets links
        self.assertEqual(self.put("lead_draft", enabled=True, config={"offer": "hi"}).status_code, 422)                    # an offer is a real sentence
        self.assertEqual(self.put("flush", every_minutes=1).status_code, 422)                                              # not more often than every 5 minutes
        ok = self.put("lead_import", enabled=True, config={"url": SHEET, "basis": "business_contact", "attested": True})
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(self.put("lead_import", config={"basis": "because"}).status_code, 422)

    # ---------------------------------------------------------------- timing
    def test_a_job_runs_when_due_and_not_again_before_its_interval(self):
        self.put("flush", enabled=True, every_minutes=10)
        self.assertEqual(self.sched.tick(MONDAY_10AM_LAGOS), 1)
        self.assertEqual(self.sched.tick(MONDAY_10AM_LAGOS + timedelta(minutes=9)), 0)
        self.assertEqual(self.sched.tick(MONDAY_10AM_LAGOS + timedelta(minutes=10)), 1)
        row = Schedule(self.rt.memory).row("flush")
        self.assertEqual(row["last_status"], "ok")
        self.assertIn("sent 0", row["last_detail"])

    def test_the_sending_window_is_monday_to_saturday_eight_to_six_in_lagos(self):
        for when, want in ((MONDAY_10AM_LAGOS, True), (SUNDAY_NOON, False), (datetime(2026, 11, 2, 6, 59, tzinfo=timezone.utc), False),      # 07:59 Lagos
                           (datetime(2026, 11, 2, 7, 0, tzinfo=timezone.utc), True), (datetime(2026, 11, 2, 16, 59, tzinfo=timezone.utc), True),
                           (datetime(2026, 11, 2, 17, 0, tzinfo=timezone.utc), False), (datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc), True)):
            self.assertEqual(in_sending_hours(when), want, when)

    # ---------------------------------------------------------------- the lead pipeline
    def test_import_then_draft_then_send_only_what_the_owner_approved_and_only_in_hours(self):
        self.put("lead_import", enabled=True, every_minutes=60, config={"url": SHEET, "basis": "business_contact", "attested": True})
        self.put("lead_draft", enabled=True, config={"offer": "We supply phones to shops at trade prices."})
        self.put("outreach_send", enabled=True)
        self.assertEqual(self.sched.tick(MONDAY_10AM_LAGOS), 3)
        people = self.rt.outreach.list()
        self.assertEqual(sorted(p["email"] for p in people), ["ada@example.com", "tunde@example.com"])        # the invalid row is not a person
        self.assertEqual({p["status"] for p in people}, {"drafted"})
        self.assertEqual(next(p for p in people if p["email"] == "ada@example.com")["title"], "Owner")        # headings named differently still map
        self.assertEqual(self.rt.outreach.summary()["sent_today"], 0)                                          # nothing is sent before approval
        with mock.patch.object(ADAPTERS["email"], "send_message") as send:
            self.sched.tick(MONDAY_10AM_LAGOS + timedelta(hours=2))
            send.assert_not_called()
        self.rt.outreach.approve([next(p["id"] for p in people if p["email"] == "ada@example.com")])
        with mock.patch.object(ADAPTERS["email"], "send_message") as send:
            self.assertEqual(self.sched.run(self.rt, "shop-a", "outreach_send", SUNDAY_NOON)["status"], "waiting")      # a Sunday: not sent
            send.assert_not_called()
            self.sched.tick(MONDAY_10AM_LAGOS + timedelta(hours=3))
            self.assertEqual(send.call_count, 1)
            self.assertEqual(send.call_args.args[0], "ada@example.com")                                         # only the approved one
        self.assertEqual({p["email"]: p["status"] for p in self.rt.outreach.list()}, {"ada@example.com": "sent", "tunde@example.com": "drafted"})

    def test_a_waiting_run_does_not_use_up_the_slot_so_sending_starts_as_soon_as_the_window_opens(self):
        self.put("outreach_send", enabled=True, every_minutes=60)
        self.sched.tick(SUNDAY_NOON)
        row = Schedule(self.rt.memory).row("outreach_send")
        self.assertEqual((row["last_status"], row["last_run"]), ("waiting", None))
        self.assertEqual(self.sched.tick(MONDAY_10AM_LAGOS), 1)                                             # due straight away on Monday morning
        self.assertNotEqual(Schedule(self.rt.memory).row("outreach_send")["last_run"], None)

    def test_a_sheet_that_cannot_be_read_is_reported_and_other_jobs_still_run(self):
        self.sheet_text = RuntimeError("boom")
        self.put("lead_import", enabled=True, config={"url": SHEET, "basis": "business_contact", "attested": True})
        self.put("flush", enabled=True)
        self.assertEqual(self.sched.tick(MONDAY_10AM_LAGOS), 2)
        rows = {j["job"]: j for j in self.c.get("/v1/automation", headers=self.H()).json()["jobs"]}
        self.assertEqual(rows["lead_import"]["last_status"], "error")
        self.assertEqual(rows["flush"]["last_status"], "ok")
        self.assertNotIn("Traceback", rows["lead_import"]["last_detail"])

    def test_a_sheet_without_an_email_column_says_so(self):
        with self.assertRaises(ScheduleError):
            read_rows("Name,Phone\nAda,0801\n")
        self.assertEqual(read_rows(""), [])

    # ---------------------------------------------------------------- plan and run-now
    def test_a_plan_without_follow_ups_cannot_use_the_gated_jobs_but_can_flush(self):
        tiny = self.runtimes.get("tiny")
        self.assertEqual(self.sched.run(tiny, "tiny", "followups")["status"], "blocked")
        self.assertEqual(self.sched.run(tiny, "tiny", "outreach_send", MONDAY_10AM_LAGOS)["status"], "blocked")
        self.assertEqual(self.sched.run(tiny, "tiny", "flush")["status"], "ok")

    def test_run_now_works_even_when_the_job_is_off_and_reports_what_happened(self):
        r = self.c.post("/v1/automation/followups/run", headers=self.H())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")
        self.assertIn("queued 0", r.json()["detail"])
        self.assertEqual(self.c.post("/v1/automation/lead_draft/run", headers=self.H()).json()["status"], "needs attention")     # no offer yet: says what to fix
        self.assertEqual(self.c.post("/v1/automation/nope/run", headers=self.H()).status_code, 404)
        jobs = {j["job"]: j for j in self.c.get("/v1/automation", headers=self.H()).json()["jobs"]}
        self.assertEqual(jobs["followups"]["last_status"], "ok")
        self.assertFalse(jobs["followups"]["enabled"])

    def test_the_timer_only_starts_when_the_server_asks_for_it(self):
        with mock.patch.dict(os.environ, {"SCHEDULER": "1"}):
            app = create_app(self.root, self.runtimes, self.auth)
        try:
            self.assertTrue(app.state.scheduler.running)
        finally:
            app.state.scheduler.stop()


if __name__ == "__main__":
    unittest.main()
