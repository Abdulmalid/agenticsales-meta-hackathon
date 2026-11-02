import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agentic_sales.agents import sales
from agentic_sales.agents.orchestrator import Orchestrator
from agentic_sales.channels.dispatch import SecretStore
from agentic_sales.config.business import BusinessConfig, Product, naira
from agentic_sales.core.types import Channel, InboundMessage, TenantContext
from agentic_sales.language.analyzer import Analyzer
from agentic_sales.language.humanize import humanize
from agentic_sales.models.base import ModelResponse, ModelRouter, TaskKind
from agentic_sales.security.reply_guard import amounts_kobo
from agentic_sales.security.untrusted import MAX_CUSTOMER_CHARS, clean
from agentic_sales.server import runtime as runtime_module
from agentic_sales.server.runtime import TenantRuntime
from agentic_sales.tools.builtin import default_registry

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
BIZ = BusinessConfig("PhoneHub Lagos", "electronics", agent_name="Ezenna", products=[
    Product("IP15", "iPhone 15", naira(800_000), naira(740_000), "Brand new, sealed")])


class Plain(unittest.TestCase):
    def test_dashes_semicolons_and_stacked_exclamations_become_plain_texting(self):
        cases = {
            "Thanks Mohammad-Yasin — I've flagged your request; someone will follow up!!": "Thanks Mohammad-Yasin, I've flagged your request, someone will follow up!",
            "iPhone 15 128GB — brand new, sealed — for ₦800,000.": "iPhone 15 128GB, brand new, sealed, for ₦800,000.",
            "Great choice! Wow! Really!": "Great choice! Wow. Really.",
            "Delivery takes 3–5 days": "Delivery takes 3-5 days",
            "Price is ₦10–20k": "Price is ₦10-20k",
            "It is “nice”… and ‘good’": "It is \"nice\"... and 'good'",
            "**Great** deal": "Great deal",
            "- one\n- two\n1. three": "- one\n- two\n1. three",        # two or more list lines are a real list and stay, one per line
            "* a lone stray marker": "a lone stray marker",
            "Hello  there ,friend": "Hello there,friend",
        }
        for raw, want in cases.items():
            self.assertEqual(humanize(raw), want, raw)

    def test_names_words_and_amounts_are_never_changed_and_plain_text_is_left_alone(self):
        for plain in ("The iPhone 15 128GB is ₦800,000, in stock. Want pickup or delivery?", "Abeg we no get iPhone 17 for now o.", "Mohammad-Yasin, Ilorin and Kebbi", ""):
            self.assertEqual(humanize(plain), plain)
        for raw in ("a — b; c!!", "x – y", "**bold** - item"):
            self.assertEqual(humanize(humanize(raw)), humanize(raw))                       # idempotent

    def test_a_price_followed_by_a_word_starting_with_k_or_m_is_not_a_bigger_price(self):
        self.assertEqual(amounts_kobo("Want me to hold one at ₦800,000 meanwhile?"), {80_000_000})
        self.assertEqual(amounts_kobo("₦95,000 kindly confirm"), {9_500_000})
        self.assertEqual(amounts_kobo("₦800k, ₦2 million or ₦1.5m"), {80_000_000, 200_000_000, 150_000_000})
        self.assertEqual(amounts_kobo("NGN 50,000 kobo?"), {5_000_000})


class Scripted:
    name = "scripted"

    def __init__(self, *replies):
        self.outs = [json.dumps({"reply": r, "actions": []}) for r in replies]
        self.requests = []

    def complete(self, req):
        self.requests.append(req)
        return ModelResponse(self.outs.pop(0), self.name)


def orchestrator(model):
    root = Path(tempfile.mkdtemp())
    ctx = TenantContext("shop-a")
    return Orchestrator(ctx, BIZ, root, ModelRouter(text={TaskKind.CONVERSATION: model}), default_registry(), None, Analyzer(None), None)


def say(orch, text, n=1):
    return orch.handle(InboundMessage(Channel.WEB, "u1", "c1", text, message_id=f"m{n}"))


class InTheTurn(unittest.TestCase):
    def test_the_reply_that_reaches_the_customer_is_plain_and_not_blocked_by_a_word_after_the_price(self):
        orch = orchestrator(Scripted("Yes, in stock — ₦800,000 meanwhile; want pickup or delivery!!"))
        res = say(orch, "iPhone 15?")
        self.assertEqual(res.reply, "Yes, in stock, ₦800,000 meanwhile, want pickup or delivery!")
        self.assertNotIn("reply_retry", [e["kind"] for e in orch.audit.trace(res.trace)])      # the old guard read "meanwhile" as ₦800 billion

    def test_a_rewrite_after_an_unsupported_claim_keeps_the_correct_price(self):
        model = Scripted("Yes, it is ₦800,000 with a 1 year warranty.", "Yes, it is ₦800,000 and in stock.")
        res = say(orchestrator(model), "how much is the iPhone 15?")
        self.assertEqual(res.reply, "Yes, it is ₦800,000 and in stock.")
        fix = model.requests[1].messages[-1].content
        self.assertIn("removing ONLY what the check names", fix)
        self.assertIn("including the correct listed price", fix)
        self.assertNotIn("or amounts", fix)                                                     # the old wording made the model drop the price too

    def test_the_model_is_asked_with_a_low_temperature_so_the_same_question_gets_the_same_facts(self):
        model = Scripted("The iPhone 15 is ₦800,000.")
        say(orchestrator(model), "How much is the iPhone 15?")
        self.assertLessEqual(model.requests[0].temperature, 0.2)
        self.assertIn("give the same facts as before", model.requests[0].system)

    def test_a_long_message_gets_the_long_message_rule_and_a_short_one_does_not(self):
        short, long_ = Scripted("ok"), Scripted("ok")
        say(orchestrator(short), "hello")
        say(orchestrator(long_), "I would like to know about the iPhone 15. " + "Please also tell me about delivery and payment. " * 30)
        self.assertNotIn("# This message is long", short.requests[0].system)
        self.assertIn("# This message is long", long_.requests[0].system)
        self.assertIn("not a reason to hand over to a person", long_.requests[0].system)

    def test_the_prompt_asks_for_plain_punctuation_and_no_thanks_name_opener(self):
        model = Scripted("ok")
        say(orchestrator(model), "hello")
        self.assertIn("Do not use em dashes", model.requests[0].system)
        self.assertIn('Do not start every message with "Thanks"', model.requests[0].system)

    def test_the_message_limit_no_longer_cuts_a_long_message_after_two_thousand_characters(self):
        self.assertGreaterEqual(MAX_CUSTOMER_CHARS, 6000)
        text = "word " * 1000                                                                  # 5000 characters
        self.assertEqual(len(clean(text)), len(text.strip()))
        self.assertEqual(len(clean("x" * 20_000)), MAX_CUSTOMER_CHARS)                         # still bounded


def runtime(model):
    root = Path(tempfile.mkdtemp())
    ctx = TenantContext("shop-a")
    router = ModelRouter(text={TaskKind.CONVERSATION: model})
    orch = Orchestrator(ctx, BIZ, root, router, default_registry(), None, Analyzer(None), None)
    return TenantRuntime(ctx, root, orch, None, SecretStore(ctx, root))


def part(text, user="u1", n=1):
    return InboundMessage(Channel.TELEGRAM, user, user, text, NOW, message_id=f"p{n}-{user}")


class SplitLongMessages(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(runtime_module, "COALESCE_SECONDS", 0.4)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_parts_of_one_long_message_are_answered_once_together(self):
        model = Scripted("Got your whole message, the iPhone 15 is ₦800,000.")
        rt = runtime(model)
        first, second = part("FIRST-PART " + "a" * 1600, n=1), part("SECOND-PART " + "b" * 1600, n=2)
        results = []
        t1 = threading.Thread(target=lambda: results.append(rt.handle_and_reply(first)))
        t2 = threading.Thread(target=lambda: (time.sleep(0.1), results.append(rt.handle_and_reply(second))))
        t1.start(); t2.start(); t1.join(); t2.join()
        self.assertEqual(len(model.requests), 1)                                                # one model turn, not two
        sent = model.requests[0].messages[-1].content
        self.assertIn("FIRST-PART", sent)
        self.assertIn("SECOND-PART", sent)
        self.assertLess(sent.index("FIRST-PART"), sent.index("SECOND-PART"))
        replies = sorted(r.reply for r in results)
        self.assertEqual(replies[0], "")                                                        # the first part got no separate reply
        self.assertEqual(replies[1], "Got your whole message, the iPhone 15 is ₦800,000.")
        self.assertIn("merged_into_next", [f for r in results for f in r.flags])

    def test_short_messages_are_never_delayed_and_different_customers_never_merge(self):
        model = Scripted("hi", "A", "B")
        rt = runtime(model)
        with mock.patch.object(runtime_module.time, "sleep") as sleep:
            self.assertEqual(rt.handle_and_reply(part("hello")).reply, "hi")
        sleep.assert_not_called()                                                               # no waiting for a short message
        out = []
        threads = [threading.Thread(target=lambda u=u: out.append(rt.handle_and_reply(part("x" * 1600, user=u, n=3)))) for u in ("alice", "bob")]
        [t.start() for t in threads]; [t.join() for t in threads]
        self.assertEqual(sorted(r.reply for r in out), ["A", "B"])                              # each long message answered on its own

    def test_a_single_long_message_is_answered_after_a_short_wait(self):
        rt = runtime(Scripted("done"))
        res = rt.handle_and_reply(part("x" * 1600))
        self.assertEqual(res.reply, "done")


if __name__ == "__main__":
    unittest.main()
