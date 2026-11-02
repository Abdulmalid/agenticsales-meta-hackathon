import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agentic_sales.agents.orchestrator import Orchestrator
from agentic_sales.channels.adapters import ADAPTERS
from agentic_sales.channels.dispatch import SecretStore
from agentic_sales.config.business import BusinessConfig, Product, naira
from agentic_sales.core.types import Channel, InboundMessage, TenantContext
from agentic_sales.language.analyzer import Analyzer
from agentic_sales.language.humanize import humanize
from agentic_sales.models.base import ModelResponse, ModelRouter, TaskKind
from agentic_sales.server.runtime import TenantRuntime
from agentic_sales.tools.builtin import default_registry

NOW = datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)
BIZ = BusinessConfig("PhoneHub Lagos", "electronics", agent_name="Ezenna", products=[
    Product("IP15", "iPhone 15", naira(800_000), naira(740_000), "Brand new, sealed")])


class Fillers(unittest.TestCase):
    def test_template_openers_and_filler_sentences_are_removed_and_the_answer_is_kept(self):
        self.assertEqual(humanize("Certainly! The iPhone 15 is ₦800,000."), "The iPhone 15 is ₦800,000.")
        self.assertEqual(humanize("Absolutely, we have it in stock."), "We have it in stock.")
        self.assertEqual(humanize("Great question! It comes with a charger."), "It comes with a charger.")
        self.assertEqual(humanize("Yes it is available. Feel free to reach out anytime."), "Yes it is available.")
        for plain in ("Of course not, that is a different phone.", "Sure, pickup works.", "Certainly the best price we have."):
            self.assertEqual(humanize(plain), plain if not plain.startswith("Certainly the") else plain)

    def test_the_prompt_bans_stock_phrases_and_asks_for_statement_endings(self):
        from agentic_sales.agents import sales
        self.assertIn('Never use stock phrases like "Certainly!"', sales.SYSTEM_TEMPLATE)
        self.assertIn("About one reply in three should end on a plain, confident statement", sales.SYSTEM_TEMPLATE)


class SlowModel:
    name = "slow"

    def __init__(self):
        self.calls, self.requests = 0, []
        self.first_started = threading.Event()

    def complete(self, req):
        self.calls += 1
        self.requests.append(req)
        n = self.calls
        if n == 1:
            self.first_started.set()
            time.sleep(0.6)
        return ModelResponse(json.dumps({"reply": f"answer {n}", "actions": []}), self.name)


def runtime(model):
    root = Path(tempfile.mkdtemp())
    ctx = TenantContext("shop-a")
    orch = Orchestrator(ctx, BIZ, root, ModelRouter(text={TaskKind.CONVERSATION: model}), default_registry(), None, Analyzer(None), None)
    return TenantRuntime(ctx, root, orch, None, SecretStore(ctx, root))


def tg(text, n):
    return InboundMessage(Channel.TELEGRAM, "900", "900", text, NOW, message_id=f"b{n}")


class Interrupted(unittest.TestCase):
    def test_a_reply_composed_while_the_customer_kept_typing_is_dropped_and_the_burst_is_answered_once(self):
        model = SlowModel()
        rt = runtime(model)
        out = []
        with mock.patch.object(ADAPTERS["telegram"], "send") as send, mock.patch.object(ADAPTERS["telegram"], "typing"):
            t1 = threading.Thread(target=lambda: out.append(rt.handle_and_reply(tg("how much is the iPhone 15", 1))))
            t1.start()
            model.first_started.wait(5)
            out.append(rt.handle_and_reply(tg("and do you deliver to Lekki", 2)))              # arrives while answer 1 is being written
            t1.join()
        self.assertEqual([c.args[1] for c in send.call_args_list], ["answer 2"])               # only the answer to the whole burst went out
        self.assertIn("reply_superseded", [f for r in out for f in r.flags])
        second_prompt = model.requests[1].messages
        joined = " ".join(m.content for m in second_prompt)
        self.assertIn("how much is the iPhone 15", joined)
        self.assertIn("do you deliver to Lekki", joined)
        self.assertNotIn("answer 1", joined)                                                      # the unsent reply is not in the history
        kinds = [e["kind"] for e in rt.orchestrator.audit.trace(next(r.trace for r in out if "reply_superseded" in r.flags))]
        self.assertIn("reply_superseded", kinds)

    def test_a_single_message_is_sent_normally(self):
        rt = runtime(SlowModel())
        rt.orchestrator.router.text[TaskKind.CONVERSATION].calls = 1                            # skip the slow first call
        with mock.patch.object(ADAPTERS["telegram"], "send") as send, mock.patch.object(ADAPTERS["telegram"], "typing"):
            res = rt.handle_and_reply(tg("hello", 1))
        self.assertEqual(res.reply, "answer 2")
        send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
