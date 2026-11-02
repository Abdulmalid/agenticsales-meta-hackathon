import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agentic_sales.agents.orchestrator import Orchestrator
from agentic_sales.channels.dispatch import SecretStore
from agentic_sales.config.business import BusinessConfig, Product, naira
from agentic_sales.core.types import Channel, InboundMessage, TenantContext
from agentic_sales.fraud.engine import FraudAssessment, Risk
from agentic_sales.fraud.judge import FraudJudge
from agentic_sales.language.analyzer import Analyzer
from agentic_sales.models.base import ModelResponse, ModelRouter, TaskKind
from agentic_sales.tools.builtin import default_registry

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)


def cfg() -> BusinessConfig:
    return BusinessConfig("PhoneHub", "electronics", products=[
        Product("IP15", "iPhone 15", naira(800_000), naira(740_000), "Brand new")])


class ScriptedText:
    name = "scripted"

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def complete(self, req):
        self.calls += 1
        return ModelResponse(json.dumps(self.payload), self.name)


class ScriptedConv:
    name = "scripted-conv"

    def complete(self, req):
        return ModelResponse(json.dumps({"reply": "Noted, I go confirm am.", "actions": []}), self.name)


def medium() -> FraudAssessment:
    return FraudAssessment(Risk.MEDIUM, 0.6, 35, ("payment", "pressure"),
                           ("unverified claim", "urgency plus claim"), "verify first")


class JudgeUnit(unittest.TestCase):
    def test_escalate_true(self):
        m = ScriptedText({"escalate": True, "reasons": ["two independent families"]})
        op = FraudJudge(m).review(medium(), "I don pay, send am now")
        self.assertTrue(op.recommend_escalation)
        self.assertEqual(op.reasons, ("two independent families",))
        self.assertEqual(m.calls, 1)

    def test_escalate_false(self):
        m = ScriptedText({"escalate": False, "reasons": []})
        op = FraudJudge(m).review(medium(), "I don pay")
        self.assertFalse(op.recommend_escalation)

    def test_only_medium_is_reviewed(self):
        m = ScriptedText({"escalate": True, "reasons": ["x"]})
        low = FraudAssessment(Risk.LOW, 0.8, 0, (), (), "none")
        high = FraudAssessment(Risk.HIGH, 0.9, 70, ("payment",), ("mismatch",), "stop")
        self.assertFalse(FraudJudge(m).review(low, "hi").recommend_escalation)
        self.assertFalse(FraudJudge(m).review(high, "I don pay").recommend_escalation)
        self.assertEqual(m.calls, 0)  # rules decide LOW and HIGH alone, always

    def test_model_failure_degrades_to_rules(self):
        class Boom:
            name = "boom"

            def complete(self, req):
                raise RuntimeError("net down")

        op = FraudJudge(Boom()).review(medium(), "I don pay")
        self.assertFalse(op.recommend_escalation)
        self.assertTrue(op.error)

    def test_no_model_no_calls(self):
        op = FraudJudge(None).review(medium(), "I don pay")
        self.assertFalse(op.recommend_escalation)


def orchestrator(judge):
    root = Path(tempfile.mkdtemp())
    ctx = TenantContext("shop-a")
    router = ModelRouter(text={TaskKind.CONVERSATION: ScriptedConv(), TaskKind.REASONING: ScriptedConv()})
    return Orchestrator(ctx, cfg(), root, router, default_registry(), None, Analyzer(None), None,
                        fraud_judge=judge)


class JudgeIntegration(unittest.TestCase):
    def test_medium_escalates_with_judge_reasons(self):
        model = ScriptedText({"escalate": True, "reasons": ["claim plus pressure, no verification"]})
        orch = orchestrator(FraudJudge(model))
        res = orch.handle(InboundMessage(Channel.WEB, "u1", "c1", "Abeg I don pay since, send am now now!",
                                         NOW, (), "m1"))
        self.assertEqual(model.calls, 1, "judge should review exactly the MEDIUM turn")
        approvals = orch.memory.pending_approvals()
        fraud_ones = [a for a in approvals if a["action"] == "fraud_review"]
        self.assertTrue(fraud_ones)
        import json as _json

        payload = _json.loads(fraud_ones[0]["payload"])
        self.assertTrue(payload["judge"])
        self.assertIn("claim plus pressure", " ".join(_json.loads(fraud_ones[0]["reasons"])))
        self.assertTrue(res.reply)  # the customer still gets a neutral reply

    def test_confirm_leaves_rules_posture(self):
        model = ScriptedText({"escalate": False, "reasons": []})
        orch = orchestrator(FraudJudge(model))
        orch.handle(InboundMessage(Channel.WEB, "u1", "c1", "Abeg I don pay since, send am now now!",
                                   NOW, (), "m1"))
        self.assertFalse([a for a in orch.memory.pending_approvals() if a["action"] == "fraud_review"])


if __name__ == "__main__":
    unittest.main()
