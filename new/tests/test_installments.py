"""Instalments: a shop that accepts part payment holds the goods from the first confirmed payment and releases them only when the whole
price is in. Every naira is confirmed by the gateway; a receipt exists only for a payment that was."""
import dataclasses
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from agentic_sales.agents.orchestrator import Orchestrator
from agentic_sales.config.business import naira
from agentic_sales.core.types import TenantContext
from agentic_sales.leads.models import LeadStage
from agentic_sales.models.base import ModelRouter, TaskKind
from agentic_sales.tools.builtin import default_registry
from agentic_sales.webpages import receipt
from tests.test_backend import NOW, FakeGateway, Scripted, cfg, msg


def shop(accepts=True, percent=50, model=None):
    gw = FakeGateway()
    c = dataclasses.replace(cfg(), accepts_installments=accepts, installment_min_percent=percent)
    model = model or Scripted()
    o = Orchestrator(TenantContext("shop-a"), c, Path(tempfile.mkdtemp()), ModelRouter(text={TaskKind.CONVERSATION: model}), default_registry(), gateway=gw)
    lead, _ = o.leads.get_or_create("whatsapp:u1", "whatsapp", NOW)
    return o, gw, lead, model


def pay(gw, ref, kobo):
    gw.paid[ref] = ("success", kobo, "NGN")


class StartingAnInstalmentPlan(unittest.TestCase):
    def test_a_shop_that_does_not_accept_instalments_refuses_part_payment(self):
        o, gw, _, _ = shop(accepts=False)
        r = o.payments.create_order_link("whatsapp:u1", "IP15", 1, "a@b.co", pay_now_kobo=naira(400_000))
        self.assertFalse(r.ok)
        self.assertIn("full payment only", r.message)
        self.assertEqual(gw.links, {})

    def test_the_first_payment_must_meet_the_shops_minimum(self):
        o, gw, _, _ = shop(percent=50)
        low = o.payments.create_order_link("whatsapp:u1", "IP15", 1, "a@b.co", pay_now_kobo=naira(300_000))
        self.assertFalse(low.ok)
        self.assertIn("at least ₦400,000", low.message)
        ok = o.payments.create_order_link("whatsapp:u1", "IP15", 1, "a@b.co", pay_now_kobo=naira(400_000))
        self.assertTrue(ok.ok)
        self.assertEqual((ok.amount_kobo, ok.total_kobo, ok.balance_kobo), (naira(400_000), naira(800_000), naira(400_000)))
        self.assertEqual(gw.links[ok.reference], naira(400_000))

    def test_paying_the_whole_price_is_an_ordinary_order(self):
        o, gw, _, _ = shop()
        r = o.payments.create_order_link("whatsapp:u1", "IP15", 1, "a@b.co", pay_now_kobo=naira(800_000))
        self.assertEqual((r.amount_kobo, r.total_kobo), (naira(800_000), None))
        self.assertEqual(o.payments.payments_for(r.reference), [])


class HoldingTheGoodsUntilTheLastPayment(unittest.TestCase):
    def first(self):
        o, gw, lead, _ = shop()
        r = o.payments.create_order_link("whatsapp:u1", "IP15", 1, "a@b.co", pay_now_kobo=naira(400_000))
        order_ref = r.reference.rsplit("-", 1)[0]
        pay(gw, r.reference, naira(400_000))
        return o, gw, lead, r, order_ref

    def test_the_first_payment_makes_the_order_part_paid_and_does_not_convert_the_lead(self):
        o, gw, lead, r, order_ref = self.first()
        c = o.payments.confirm(r.reference, now=NOW)
        self.assertEqual((c.status, c.paid_kobo, c.balance_kobo), ("verified", naira(400_000), naira(400_000)))
        order = o.payments.order(order_ref)
        self.assertEqual((order["status"], order["paid_kobo"], order["paid_at"]), ("part_paid", naira(400_000), None))
        self.assertNotEqual(o.leads.get(lead.id).stage, LeadStage.CONVERTED)
        self.assertEqual(len(o.leads.purchases()), 0)
        queued = [m for m in o.memory.con.execute("SELECT * FROM outbox")]
        self.assertTrue(any("Balance: ₦400,000" in dict(m)["text"] and "once the full amount is paid" in dict(m)["text"] for m in queued), [dict(m) for m in queued])

    def test_confirming_twice_counts_the_money_once(self):
        o, gw, _, r, order_ref = self.first()
        o.payments.confirm(r.reference, now=NOW)
        again = o.payments.confirm(r.reference, now=NOW)
        self.assertTrue(again.already_recorded)
        self.assertEqual(o.payments.order(order_ref)["paid_kobo"], naira(400_000))

    def test_the_last_payment_completes_the_order_and_converts_the_lead_once(self):
        o, gw, lead, r, order_ref = self.first()
        o.payments.confirm(r.reference, now=NOW)
        rest = o.payments.create_balance_link("whatsapp:u1", order_ref, "a@b.co")
        self.assertEqual((rest.amount_kobo, rest.balance_kobo), (naira(400_000), 0))
        pay(gw, rest.reference, naira(400_000))
        done = o.payments.confirm(rest.reference, now=NOW)
        self.assertEqual((done.status, done.balance_kobo), ("verified", 0))
        order = o.payments.order(order_ref)
        self.assertEqual((order["status"], order["paid_kobo"]), ("paid", naira(800_000)))
        self.assertEqual(o.leads.get(lead.id).stage, LeadStage.CONVERTED)
        self.assertEqual(len(o.leads.purchases()), 1)
        o.payments.confirm(rest.reference, now=NOW)
        self.assertEqual(len(o.leads.purchases()), 1)

    def test_a_wrong_amount_from_the_gateway_is_a_mismatch_and_adds_nothing(self):
        o, gw, _, r, order_ref = self.first()
        pay(gw, r.reference, naira(1))
        self.assertEqual(o.payments.confirm(r.reference, now=NOW).status, "mismatch")
        self.assertEqual(o.payments.order(order_ref)["paid_kobo"], 0)

    def test_a_balance_link_is_only_for_the_customers_own_part_paid_order_and_never_more_than_is_left(self):
        o, gw, _, r, order_ref = self.first()
        o.payments.confirm(r.reference, now=NOW)
        self.assertFalse(o.payments.create_balance_link("whatsapp:other", order_ref, "a@b.co").ok)
        self.assertFalse(o.payments.create_balance_link("whatsapp:u1", order_ref, "a@b.co", naira(500_000)).ok)      # more than the balance
        self.assertFalse(o.payments.create_balance_link("whatsapp:u1", order_ref, "a@b.co", naira(10)).ok)           # below the minimum top-up
        part = o.payments.create_balance_link("whatsapp:u1", order_ref, "a@b.co", naira(100_000))
        self.assertEqual((part.ok, part.balance_kobo), (True, naira(300_000)))

    def test_cancelling_a_part_paid_order_leaves_a_refund_due(self):
        o, gw, _, r, order_ref = self.first()
        o.payments.confirm(r.reference, now=NOW)
        self.assertEqual(o.payments.cancel_order(order_ref)["status"], "refund_due")

    def test_the_order_reference_alone_cannot_be_used_to_confirm_an_instalment_order(self):
        o, gw, _, r, order_ref = self.first()
        self.assertEqual(o.payments.confirm(order_ref).status, "pending")


class Receipts(unittest.TestCase):
    def test_a_receipt_shows_what_was_paid_and_what_is_left_and_only_for_confirmed_payments(self):
        o, gw, _, _ = shop()
        r = o.payments.create_order_link("whatsapp:u1", "IP15", 1, "a@b.co", pay_now_kobo=naira(400_000))
        rt = SimpleNamespace(orchestrator=o, cfg=o.cfg)
        self.assertIsNone(receipt.receipt_data(rt, r.reference))                                   # not paid yet: no receipt
        pay(gw, r.reference, naira(400_000))
        o.payments.confirm(r.reference, now=NOW)
        page = receipt.render(rt, receipt.receipt_data(rt, r.reference))
        for part in ("Receipt", "PhoneHub", "₦400,000", "Balance still to pay", "Delivery follows the final payment"):
            self.assertIn(part, page)
        inv = receipt.invoice_data(rt, r.reference.rsplit("-", 1)[0])
        self.assertEqual((inv["paid_kobo"], inv["balance_kobo"]), (naira(400_000), naira(400_000)))
        self.assertIn("Balance due", receipt.render(rt, inv))
        self.assertIsNone(receipt.receipt_data(rt, "AS-unknown"))

    def test_a_full_single_payment_has_a_receipt_marked_paid_in_full(self):
        o, gw, _, _ = shop()
        r = o.payments.create_order_link("whatsapp:u1", "IP15", 1, "a@b.co")
        pay(gw, r.reference, naira(800_000))
        o.payments.confirm(r.reference, now=NOW)
        rt = SimpleNamespace(orchestrator=o, cfg=o.cfg)
        self.assertIn("Paid in full", receipt.render(rt, receipt.receipt_data(rt, r.reference)))

    def test_text_in_a_name_cannot_break_out_of_the_page(self):
        o, gw, _, _ = shop()
        o.cfg.business_name = "<script>alert(1)</script>"
        r = o.payments.create_order_link("whatsapp:u1", "IP15", 1, "a@b.co")
        pay(gw, r.reference, naira(800_000))
        o.payments.confirm(r.reference, now=NOW)
        rt = SimpleNamespace(orchestrator=o, cfg=o.cfg)
        self.assertNotIn("<script>", receipt.render(rt, receipt.receipt_data(rt, r.reference)))


class TheAgentOffersInstalmentsOnlyWhenTheShopDoes(unittest.TestCase):
    def test_the_prompt_tells_the_agent_which_policy_applies(self):
        for accepts, expect in ((True, "accepts part payment"), (False, "does not accept part payment")):
            o, gw, _, model = shop(accepts=accepts)
            model.outs = [json.dumps({"reply": "ok", "actions": []})]
            o.handle(msg("hi"))
            self.assertIn(expect, model.requests[0].system)

    def test_a_reply_may_quote_the_minimum_deposit_and_the_balance_the_tool_returned(self):
        plan1 = {"reply": "Checking.", "actions": [{"tool": "create_payment_link", "args": {"sku": "IP15", "email": "a@b.co", "pay_now_naira": 400000}}]}
        plan2 = {"reply": "Pay ₦400,000 now with this link, the balance is ₦400,000. The phone is delivered after the full ₦800,000 is paid.", "actions": []}
        o, gw, _, model = shop(model=Scripted(plan1, plan2))
        res = o.handle(msg("I want the iPhone 15, I will pay 400k now and the rest later. my email is a@b.co"))
        self.assertIn("balance is ₦400,000", res.reply)
        self.assertIn(naira(400_000), gw.links.values())


if __name__ == "__main__":
    unittest.main()
