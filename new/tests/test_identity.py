import json
import tempfile
import unittest
from pathlib import Path

from agentic_sales.agents.orchestrator import Orchestrator
from agentic_sales.config.business import BusinessConfig, Product, naira
from agentic_sales.core.types import Channel, InboundMessage, TenantContext
from agentic_sales.language.analysis import Register
from agentic_sales.language.analyzer import Analyzer
from agentic_sales.models.base import ModelResponse, ModelRouter, TaskKind
from agentic_sales.security import identity
from agentic_sales.tools.builtin import default_registry


class Detection(unittest.TestCase):
    def test_sincere_questions_about_what_they_are_talking_to_are_recognised(self):
        for text in ("Are you a real person?", "are u a bot", "you be real person or na bot?", "Abeg wait, you be real person or na bot?",
                     "Is this a bot?", "am I talking to a human", "I want to speak to a real person", "na bot dey reply me?",
                     "Are you AI?", "chatting with a robot or what", "is dis a machine"):
            self.assertTrue(identity.asks_if_automated(text), text)

    def test_ordinary_sales_talk_is_not_mistaken_for_that_question(self):
        for text in ("How much is the iPhone 15?", "Are you in Lagos?", "Do you sell a robot vacuum?", "is this iPhone original", "Abeg make I see the person wey go deliver",
                     "You be good shop?", "Are you open on Sunday", "the AI features on the phone", "na person wey sell me last time"):
            self.assertFalse(identity.asks_if_automated(text), text)

    def test_a_reply_that_pretends_to_be_a_person_is_caught(self):
        for reply in ("Yes, I'm a real person!", "I am a human, how can I help?", "No, I'm not a bot.", "I no be bot o", "Real person here, tell me what you need"):
            self.assertTrue(identity.claims_human(reply), reply)
            self.assertTrue(identity.check_identity(reply), reply)
        for reply in ("The iPhone 15 is ₦800,000.", "I'm Ezenna from PhoneHub.", "I'm Ezenna, PhoneHub's virtual assistant, so I'm not a person."):
            self.assertFalse(identity.claims_human(reply), reply)

    def test_what_counts_as_an_honest_answer(self):
        for reply in ("I'm PhoneHub's virtual assistant.", "I be bot o", "I'm an automated assistant.", "I'm not a person, but a team member can help."):
            self.assertTrue(identity.discloses(reply), reply)
        for reply in ("Na Tunde here, I dey with PhoneHub Lagos sales team.", "Yes of course, how can I help?"):
            self.assertFalse(identity.discloses(reply), reply)

    def test_the_disclosure_is_truthful_and_in_the_customers_register(self):
        english = identity.disclosure_reply("PhoneHub Lagos", "Ezenna", Register.FORMAL)
        self.assertEqual(english, "I'm Ezenna, PhoneHub Lagos's virtual assistant, so I'm not a person. A member of the team can take over whenever you prefer. How can I help you?")
        pidgin = identity.disclosure_reply("PhoneHub Lagos", "", Register.PIDGIN)
        self.assertIn("virtual assistant", pidgin)
        self.assertIn("no be person", pidgin)
        for text in (english, pidgin):
            self.assertTrue(identity.discloses(text))
            self.assertFalse(identity.claims_human(text))


BIZ = BusinessConfig("PhoneHub Lagos", "electronics", agent_name="Ezenna", products=[
    Product("IP15", "iPhone 15", naira(800_000), naira(740_000), "Brand new, sealed")])


class Scripted:
    name = "scripted"

    def __init__(self, *replies):
        self.outs = [json.dumps({"reply": r, "actions": []}) for r in replies]
        self.requests = []

    def complete(self, req):
        self.requests.append(req)
        return ModelResponse(self.outs.pop(0), self.name)


def turn(model, text, n=1):
    root = Path(tempfile.mkdtemp())
    ctx = TenantContext("shop-a")
    orch = Orchestrator(ctx, BIZ, root, ModelRouter(text={TaskKind.CONVERSATION: model}), default_registry(), None, Analyzer(None), None)
    res = orch.handle(InboundMessage(Channel.WEB, "u1", "c1", text, message_id=f"m{n}"))
    return res, orch


class InTheSalesTurn(unittest.TestCase):
    def test_a_dodging_answer_to_are_you_a_bot_is_replaced_by_the_truth(self):
        res, orch = turn(Scripted("Na Tunde here, I dey with PhoneHub Lagos sales team. You wan make I keep that iPhone 15 for you?"),
                         "Abeg wait, you be real person or na bot?")
        self.assertIn("virtual assistant", res.reply)
        self.assertIn("no be person", res.reply)                                   # answered in Pidgin, the customer's register
        self.assertNotIn("Tunde", res.reply)
        self.assertIn("identity_disclosure", res.flags)
        self.assertIn("identity_disclosure", [e["kind"] for e in orch.audit.trace(res.trace)])

    def test_an_honest_answer_is_left_alone(self):
        honest = "I'm Ezenna, PhoneHub's virtual assistant. A team member can take over if you prefer."
        res, _ = turn(Scripted(honest), "Are you a real person?")
        self.assertEqual(res.reply, honest)
        self.assertNotIn("identity_disclosure", res.flags)

    def test_a_reply_that_claims_to_be_human_is_rewritten_and_then_handed_to_a_person_if_it_insists(self):
        model = Scripted("Yes, I'm a real person!", "I am a human being, trust me.")
        res, orch = turn(model, "How much is the iPhone 15?")
        self.assertNotIn("human", res.reply.lower())
        self.assertIn("handed to a human", " ".join(res.flags) + res.reply.lower() + str(res.escalated).lower().replace("true", "handed to a human"))
        kinds = [e["kind"] for e in orch.audit.trace(res.trace)]
        self.assertIn("reply_retry", kinds)
        self.assertIn("reply_blocked", kinds)
        fixed, _ = turn(Scripted("Yes, I'm a real person!", "The iPhone 15 is ₦800,000."), "How much is the iPhone 15?")
        self.assertEqual(fixed.reply, "The iPhone 15 is ₦800,000.")                 # a clean rewrite goes through

    def test_it_does_not_announce_what_it_is_in_a_normal_conversation(self):
        res, _ = turn(Scripted("Hello! Welcome to PhoneHub Lagos. What phone are you looking for?"), "Hello")
        self.assertNotIn("virtual", res.reply)
        self.assertNotIn("identity_disclosure", res.flags)

    def test_the_prompt_forbids_pretending_and_does_not_tell_the_agent_to_announce_itself(self):
        model = Scripted("ok")
        turn(model, "Hello")
        system = model.requests[0].system
        self.assertIn("Never claim to be a human being", system)
        self.assertIn("Do not announce what you are", system)                          # natural: no "I'm an AI" in every greeting
        self.assertIn("sincerely asks whether they are talking to a person or a bot", system)
        for deceptive in ("answer as the rep would", "Never volunteer that this chat is automated", "AI sales assistant"):
            self.assertNotIn(deceptive, system)


if __name__ == "__main__":
    unittest.main()
