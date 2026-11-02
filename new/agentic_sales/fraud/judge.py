"""Wonder-powered second opinion on ambiguous fraud postures.

Safety contract (non-negotiable): the deterministic rules in `engine.assess`
always decide the floor. The judge runs ONLY on MEDIUM — the uncertain band —
and can only recommend human escalation. It can never clear a case to LOW and
never blocks fulfilment itself; HIGH still comes from rules alone. A judge
failure degrades to the rules posture, never a 500.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..models.base import Message, ModelError, ModelRequest, TextModel
from .engine import FraudAssessment, Risk

DEFAULT_MODEL = "muse-wonder-1.0"

_SYSTEM = """You are a fraud analyst second opinion for a Nigerian e-commerce sales agent.
A deterministic rules engine scored this conversation MEDIUM risk (uncertain). Review the
evidence and decide whether a human owner should look before any fulfilment promise.
Rules: weak signals never convict. Recommend escalation only when two or more INDEPENDENT
evidence families point the same way, or one concrete fact (amount mismatch, verified
contradiction) supports it. Single weak signals (one urgency phrase, one new-customer flag)
stay unescalated. Never accuse the customer; reasons are internal.
Return ONE JSON object: {"escalate": boolean, "reasons": ["..."]}.
Verdict vocabulary (evidence families): payment, pressure, identity, system, pattern."""


@dataclass(frozen=True)
class JudgeOpinion:
    recommend_escalation: bool
    reasons: tuple[str, ...] = ()
    error: str = ""


class FraudJudge:
    """Reviews MEDIUM rules postures with a strong reasoning model (Wonder)."""

    def __init__(self, model: TextModel | None, max_tokens: int = 2048):
        self.model = model
        self.max_tokens = max_tokens

    @property
    def name(self) -> str:
        return self.model.name if self.model else "none"

    def review(self, assessment: FraudAssessment, customer_text: str) -> JudgeOpinion:
        if self.model is None or assessment.risk is not Risk.MEDIUM:
            return JudgeOpinion(False)
        evidence = (f"rules risk={assessment.risk.value} confidence={assessment.confidence} "
                    f"families={','.join(assessment.families)} reasons={'; '.join(assessment.reasons)}")
        try:
            resp = self.model.complete(ModelRequest(
                _SYSTEM, (Message("user", f"Evidence: {evidence}\nCustomer message: {customer_text[:800]}"),),
                max_tokens=self.max_tokens, temperature=0.0, json_mode=True))
            data = json.loads(resp.text)
            reasons = tuple(str(r)[:200] for r in data.get("reasons", []) if isinstance(r, str))
            return JudgeOpinion(bool(data.get("escalate")), reasons)
        except Exception as e:  # noqa: BLE001 - any judge failure degrades to the rules posture
            return JudgeOpinion(False, (), type(e).__name__)
