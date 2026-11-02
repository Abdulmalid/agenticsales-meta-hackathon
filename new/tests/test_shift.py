"""'While you were away': the owner's summary is built from real records and says nothing it cannot back up."""
import dataclasses
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from agentic_sales import shift
from agentic_sales.config.business import naira
from agentic_sales.vision.reader import PhotoReading
from tests.test_vision import JPEG, FakeVision, Scripted, photo, plan, runtime, session_id


def paid_order(rt, ref="R1", amount=naira(95_000), paid_at=None):
    paid_at = paid_at or datetime.now(timezone.utc).isoformat()
    with rt.memory.con:
        rt.memory.con.execute("INSERT INTO orders(reference,customer_key,sku,qty,amount_kobo,status,created,paid_at) VALUES(?,?,?,?,?,?,?,?)",
                              (ref, "web:u1", "AP2", 1, amount, "paid", paid_at, paid_at))


class ShiftReport(unittest.TestCase):
    def busy_shop(self):
        old = session_id(datetime.now(timezone.utc) - timedelta(days=9))
        model = Scripted(plan("Thanks, let me confirm it."), plan("Sure, the AirPods are in stock."))
        rt = runtime(model, FakeVision(PhotoReading("payment_receipt", None, 0.9, "A transfer.", "", old, "Phone Hub Ltd", naira(95_000))))
        with mock.patch("agentic_sales.server.runtime.fetch_image", return_value=JPEG):
            rt.handle_and_reply(photo("I have paid"))
        rt.vision = FakeVision(PhotoReading("product", "AP2", 0.8, "Earbuds.", ""))
        with mock.patch("agentic_sales.server.runtime.fetch_image", return_value=JPEG):
            rt.handle_and_reply(dataclasses.replace(photo("do you have these?", url="whatsapp-media:78"), message_id="m2"))
        paid_order(rt)
        return rt

    def test_the_numbers_come_from_what_happened(self):
        r = shift.report(self.busy_shop(), 12)
        self.assertEqual((r["conversations"], r["messages_in"], r["replies"]), (1, 2, 2))
        self.assertEqual((r["orders_paid"], r["revenue_kobo"], r["units_sold"]), (1, naira(95_000), 1))
        self.assertEqual((r["photos"], r["receipts_flagged"]), (2, 1))
        self.assertEqual(r["quiet_alerts"], {})                       # a bad receipt is rejected by the agent, not queued for the owner
        self.assertEqual(r["waiting_on_you"], 0)
        self.assertTrue(r["languages"])

    def test_the_headline_says_what_was_done_and_held_back(self):
        h = shift.report(self.busy_shop(), 12)["headline"]
        for part in ("spoke with 1 customer", "took 1 paid order worth ₦95,000", "held back 1 payment screenshot"):
            self.assertIn(part, h)

    def test_a_window_after_everything_happened_is_empty_and_honest(self):
        rt = self.busy_shop()
        r = shift.report(rt, 1, now=datetime.now(timezone.utc) + timedelta(days=3))
        self.assertEqual((r["conversations"], r["orders_paid"], r["photos"], r["receipts_flagged"]), (0, 0, 0, 0))
        self.assertIn("Nothing needed", r["headline"])

    def test_only_customers_who_wrote_at_night_in_lagos_count_as_after_hours(self):
        rt = self.busy_shop()
        lagos = timezone(timedelta(hours=1))
        with rt.memory.con:
            rt.memory.con.execute("UPDATE messages SET ts=? WHERE role='user'", (datetime(2026, 10, 29, 2, 30, tzinfo=lagos).isoformat(),))
        r = shift.report(rt, 24, now=datetime(2026, 10, 29, 8, 0, tzinfo=lagos))
        self.assertEqual((r["conversations"], r["after_hours"]), (1, 1))
        with rt.memory.con:
            rt.memory.con.execute("UPDATE messages SET ts=? WHERE role='user'", (datetime(2026, 10, 29, 14, 0, tzinfo=lagos).isoformat(),))
        self.assertEqual(shift.report(rt, 24, now=datetime(2026, 10, 29, 15, 0, tzinfo=lagos))["after_hours"], 0)


if __name__ == "__main__":
    unittest.main()
