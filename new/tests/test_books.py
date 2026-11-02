"""The owner's books: expenses by chat, profit from gateway-confirmed money only."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agentic_sales import books
from agentic_sales.channels.adapters import ADAPTERS
from agentic_sales.config.business import naira
from agentic_sales.core.types import Channel, InboundMessage, TenantContext
from agentic_sales.memory.store import TenantMemory
from agentic_sales.payments.service import PaymentService
from tests.test_installments import pay, shop
from tests.test_backend import NOW

LAGOS = timezone(timedelta(hours=1))
DAY = datetime(2026, 10, 30, 14, 0, tzinfo=LAGOS)


def fresh():
    return books.Books(TenantMemory(TenantContext("shop-a"), Path(tempfile.mkdtemp())))


class ReadingWhatTheOwnerSays(unittest.TestCase):
    def test_amounts_and_notes_in_the_ways_people_write_them(self):
        for text, kobo, note in (("spent 5k on transport", naira(5_000), "transport"),
                                 ("Spent ₦12,500 for generator fuel", naira(12_500), "generator fuel"),
                                 ("/spent 800 airtime", naira(800), "airtime"),
                                 ("expense 1.5m rent", naira(1_500_000), "rent"),
                                 ("I paid the dispatch rider 3000", naira(3_000), "the dispatch rider")):
            got = books.parse_expense(text)
            self.assertIsNotNone(got, text)
            self.assertEqual(got[0], kobo, text)
            self.assertIn(note, got[1], text)

    def test_other_messages_are_not_expenses(self):
        for text in ("do you have the iPhone 15", "how much is delivery", "spent", "", "paid"):
            self.assertIsNone(books.parse_expense(text), text)

    def test_categories(self):
        self.assertEqual(books.categorize("bolt to the market"), "transport")
        self.assertEqual(books.categorize("generator fuel"), "fuel & power")
        self.assertEqual(books.categorize("restock airpods"), "stock")
        self.assertEqual(books.categorize("a gift"), "other")


class TheOwnerTalksToTheBooks(unittest.TestCase):
    def test_logging_summing_and_undoing(self):
        b = fresh()
        r1 = books.owner_reply(b, "spent 5k on transport", DAY)
        self.assertIn("Logged ₦5,000 · transport", r1)
        self.assertIn("Spent today: ₦5,000", r1)
        books.owner_reply(b, "spent 2,000 on data", DAY)
        day = b.summary(*books.window("today", DAY)[:2])
        self.assertEqual((day["expenses_kobo"], day["by_category"]), (naira(7_000), {"transport": naira(5_000), "data & airtime": naira(2_000)}))
        self.assertIn("Removed ₦2,000", books.owner_reply(b, "/undo", DAY))
        self.assertEqual(b.summary(*books.window("today", DAY)[:2])["expenses_kobo"], naira(5_000))

    def test_anything_else_is_left_for_the_normal_conversation(self):
        self.assertIsNone(books.owner_reply(fresh(), "hello, are you there?", DAY))

    def test_a_negative_or_absurd_amount_is_refused(self):
        with self.assertRaises(ValueError):
            fresh().add(0)
        with self.assertRaises(ValueError):
            fresh().add(books.MAX_EXPENSE_KOBO + 1)


class ProfitIsBuiltFromConfirmedMoneyOnly(unittest.TestCase):
    def test_instalments_count_when_confirmed_and_whole_orders_count_once(self):
        o, gw, _, _ = shop()
        b = books.Books(o.memory)
        r = o.payments.create_order_link("whatsapp:u1", "IP15", 1, "a@b.co", pay_now_kobo=naira(400_000))
        start, end = NOW - timedelta(hours=1), NOW + timedelta(hours=1)
        self.assertEqual(b.revenue(start, end), 0)                                    # a link is not money
        pay(gw, r.reference, naira(400_000))
        o.payments.confirm(r.reference, now=NOW)
        self.assertEqual(b.revenue(start, end), naira(400_000))
        whole = o.payments.create_order_link("whatsapp:u2", "IP15", 1, "a@b.co")
        pay(gw, whole.reference, naira(800_000))
        o.payments.confirm(whole.reference, now=NOW)
        self.assertEqual(b.revenue(start, end), naira(1_200_000))
        o.payments.confirm(whole.reference, now=NOW)
        self.assertEqual(b.revenue(start, end), naira(1_200_000))                     # confirming twice does not add twice
        b.add(naira(50_000), "restock", now=NOW)
        s = b.summary(start, end)
        self.assertEqual((s["revenue_kobo"], s["expenses_kobo"], s["profit_kobo"]), (naira(1_200_000), naira(50_000), naira(1_150_000)))

    def test_the_profit_message_says_where_the_money_in_comes_from(self):
        o, gw, _, _ = shop()
        b = books.Books(o.memory)
        b.add(naira(10_000), "bolt", now=DAY)
        msg = books.owner_reply(b, "/profit today", DAY)
        self.assertIn("profit -₦10,000", msg)
        self.assertIn("payment gateway confirmed", msg)


class OnlyTheLinkedOwnerChatReachesTheBooks(unittest.TestCase):
    def test_a_customer_saying_the_same_words_is_just_a_customer(self):
        o, gw, _, model = shop()
        from tests.test_vision import FakeVision, runtime
        from tests.test_vision import Scripted, plan
        rt = runtime(Scripted(plan("Sure, tell me more.")), FakeVision(None))
        sent = []
        with mock.patch.object(ADAPTERS["telegram"], "send", side_effect=lambda to, text, s: sent.append((to, text))):
            rt.secrets.set("telegram", {"bot_token": "t"})
            rt.secrets.set("alerts", {"owner_chat_id": "111", "code": "x"})
            owner = InboundMessage(Channel.TELEGRAM, "111", "111", "spent 5k on transport", NOW, (), "t1")
            res = rt.handle_and_reply(owner)
            self.assertIn("owner_books", res.flags)
            self.assertIn("Logged ₦5,000", sent[0][1])
            customer = InboundMessage(Channel.TELEGRAM, "222", "222", "spent 5k on transport", NOW, (), "t2")
            res2 = rt.handle_and_reply(customer)
            self.assertNotIn("owner_books", res2.flags)
            self.assertEqual(rt.books.summary(datetime.now(timezone.utc) - timedelta(days=1), datetime.now(timezone.utc) + timedelta(days=1))["expenses_kobo"], naira(5_000))


if __name__ == "__main__":
    unittest.main()
