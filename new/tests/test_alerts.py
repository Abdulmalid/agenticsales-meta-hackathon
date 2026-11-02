import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agentic_sales import alerts
from agentic_sales.agents import orchestrator as orch_module
from agentic_sales.agents.orchestrator import Orchestrator
from agentic_sales.channels.adapters import ADAPTERS
from agentic_sales.channels.dispatch import SecretStore
from agentic_sales.config.business import BusinessConfig, Product, naira
from agentic_sales.core.types import Channel, InboundMessage, TenantContext
from agentic_sales.language.analyzer import Analyzer
from agentic_sales.models.base import ModelResponse, ModelRouter, TaskKind
from agentic_sales.server import runtime as runtime_module
from agentic_sales.server.runtime import TenantRuntime
from agentic_sales.tools.builtin import default_registry

NOW = datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)
BIZ = BusinessConfig("PhoneHub Lagos", "electronics", agent_name="Ezenna", products=[
    Product("IP15", "iPhone 15", naira(800_000), naira(740_000), "Brand new, sealed")])


class Scripted:
    name = "scripted"

    def __init__(self, *outs):
        self.outs = [json.dumps(o) for o in outs]
        self.requests = []

    def complete(self, req):
        self.requests.append(req)
        return ModelResponse(self.outs.pop(0), self.name)


def runtime(model):
    root = Path(tempfile.mkdtemp())
    ctx = TenantContext("shop-a")
    orch = Orchestrator(ctx, BIZ, root, ModelRouter(text={TaskKind.CONVERSATION: model}), default_registry(), None, Analyzer(None), None)
    rt = TenantRuntime(ctx, root, orch, None, SecretStore(ctx, root))
    rt.secrets.set("telegram", {"bot_token": "123456789:AAtest", "bot_username": "phonehub_bot"})
    return rt


def tg(text, user="900", n=1):
    return InboundMessage(Channel.TELEGRAM, user, user, text, NOW, message_id=f"t{n}-{user}")


class Linking(unittest.TestCase):
    def setUp(self):
        self.rt = runtime(Scripted())
        patcher = mock.patch.object(ADAPTERS["telegram"], "send")
        self.send = patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_owner_links_their_chat_with_the_code_and_nobody_else_can(self):
        code = self.rt.alerts.code()
        self.assertEqual(code, self.rt.alerts.code())                                    # stable once created
        self.rt.handle_and_reply(tg("/owner wrongcode", user="666"))
        self.assertIsNone(self.rt.alerts.owner_chat())
        res = self.rt.handle_and_reply(tg(f"/owner {code}", user="111"))
        self.assertEqual(self.rt.alerts.owner_chat(), "111")
        self.assertEqual(res.flags, ["owner_command"])
        self.assertIn("Done", self.send.call_args.args[1])
        self.assertEqual(self.send.call_args.args[0], "111")
        self.assertNotEqual(self.rt.alerts.code(), code)                                  # the used code is dead: it cannot link a second chat
        self.rt.alerts.handle_command("777", f"/owner {code}")
        self.assertEqual(self.rt.alerts.owner_chat(), "111")

    def test_the_command_never_reaches_the_agent_as_a_customer_message(self):
        model = Scripted()
        rt = runtime(model)
        rt.handle_and_reply(tg(f"/owner {rt.alerts.code()}", user="111"))
        self.assertEqual(model.requests, [])
        self.assertEqual(rt.memory.history("111"), [])

    def test_guessing_the_code_is_limited_and_off_only_works_from_the_linked_chat(self):
        for i in range(alerts.MAX_BAD_CODES):
            self.rt.alerts.handle_command("666", f"/owner guess{i}")
        self.assertIn("Too many", self.rt.alerts.handle_command("666", f"/owner {self.rt.alerts.code()}"))   # even the right code waits
        self.assertIsNone(self.rt.alerts.owner_chat())
        self.rt.alerts._bad.clear()
        self.rt.alerts.handle_command("111", f"/owner {self.rt.alerts.code()}")
        self.assertIn("not receiving", self.rt.alerts.handle_command("666", "/owner off"))
        self.assertEqual(self.rt.alerts.owner_chat(), "111")
        self.assertIn("off", self.rt.alerts.handle_command("111", "/owner off"))
        self.assertIsNone(self.rt.alerts.owner_chat())

    def test_state_reports_the_bot_and_whether_it_is_linked_and_a_test_alert_is_delivered(self):
        st = self.rt.alerts.state()
        self.assertEqual((st["bot"], st["bot_ready"], st["linked"]), ("@phonehub_bot", True, False))
        self.assertFalse(self.rt.alerts.test())                                          # nowhere to send yet
        self.rt.alerts.handle_command("111", f"/owner {st['code']}")
        self.assertTrue(self.rt.alerts.test())
        self.assertIn("test alert", self.send.call_args.args[1])


class SilentEscalation(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(ADAPTERS["telegram"], "send")
        self.send = patcher.start()
        self.addCleanup(patcher.stop)

    def test_when_the_agent_escalates_the_owner_is_told_and_the_customer_is_not(self):
        model = Scripted({"reply": "Let me check that and come back to you.", "actions": [{"tool": "escalate_to_human", "args": {"reason": "Wants a refund"}}]})
        rt = runtime(model)
        rt.alerts.handle_command("111", f"/owner {rt.alerts.code()}")
        self.send.reset_mock()
        res = rt.handle_and_reply(tg("I want my money back for the phone I bought last week", user="900"))
        self.assertEqual(res.reply, orch_module.SAFE_FALLBACK)                       # a tool escalation swaps in the neutral fallback
        self.assertNotIn("team", res.reply.lower())
        alert_calls = [c for c in self.send.call_args_list if c.args[0] == "111"]
        self.assertEqual(len(alert_calls), 1)
        text = alert_calls[0].args[1]
        self.assertIn("PhoneHub Lagos: Needs a person", text)
        self.assertIn("telegram:900", text)
        self.assertIn("Wants a refund", text)
        self.assertIn("I want my money back", text)
        self.assertEqual(self.send.call_args_list[-1].args[0], "900")                    # and the customer still got their reply

    def test_one_customer_does_not_flood_the_owner(self):
        rt = runtime(Scripted())
        rt.alerts.handle_command("111", f"/owner {rt.alerts.code()}")
        self.send.reset_mock()
        for i in range(3):
            rt.memory.request_approval("t", "telegram:900", "human_handoff", {"reason": f"r{i}"}, ("x",))
        self.assertEqual(len([c for c in self.send.call_args_list if c.args[0] == "111"]), 1)
        self.assertEqual(len(rt.memory.pending_approvals()), 3)                           # every request is still in the queue
        rt.memory.request_approval("t", "telegram:901", "discount", {}, ("x",))          # a different customer is a different alert
        self.assertEqual(len([c for c in self.send.call_args_list if c.args[0] == "111"]), 2)

    def test_no_linked_owner_or_a_failing_telegram_never_breaks_the_customers_turn(self):
        rt = runtime(Scripted())
        aid = rt.memory.request_approval("t", "telegram:900", "human_handoff", {"reason": "x"}, ("x",))
        self.assertGreater(aid, 0)                                                        # no owner linked: nothing sent, nothing raised
        rt.alerts.handle_command("111", f"/owner {rt.alerts.code()}")
        self.send.side_effect = alerts.ChannelError("telegram down")
        self.assertGreater(rt.memory.request_approval("t", "telegram:902", "human_handoff", {"reason": "x"}, ("x",)), aid)

    def test_the_alert_names_the_customer_the_reason_and_what_they_said(self):
        row = {"action": "discount", "customer_key": "telegram:900", "payload": json.dumps({"reason": "Asked for 20% off"}), "reasons": "[]"}
        text = alerts.compose("PhoneHub Lagos", row, "Can you do 600k?", "Amaka", "https://console.example")
        self.assertEqual(text.splitlines()[0], "PhoneHub Lagos: Discount request")
        self.assertIn("Amaka (telegram:900)", text)
        self.assertIn("Asked for 20% off", text)
        self.assertIn("Can you do 600k?", text)
        self.assertIn("https://console.example", text)


class CustomerNeverHearsAboutAHandoff(unittest.TestCase):
    def test_the_fallbacks_and_prompt_do_not_announce_a_handover(self):
        for text in (orch_module.SAFE_FALLBACK, runtime_module.HOLDING_REPLY):
            for phrase in ("team", "human", "hand", "someone will", "follow up"):
                self.assertNotIn(phrase, text.lower(), text)
        model = Scripted({"reply": "ok", "actions": []})
        rt = runtime(model)
        rt.handle_and_reply(InboundMessage(Channel.WEB, "u", "c", "hello", NOW, message_id="w1"))
        system = model.requests[0].system
        self.assertIn("never tell the customer you are handing over", system)
        self.assertNotIn("say you will confirm with the team", system)


if __name__ == "__main__":
    unittest.main()
