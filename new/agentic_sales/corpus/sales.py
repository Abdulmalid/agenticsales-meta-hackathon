"""Task-routed retrieval over the sales corpora (domains NG_SALES, SALES_GENERAL).

These 30k records are indexed but had no live call site: the leadgen corpus is
B2B outbound/channel playbooks (never conversational negotiation material) and
the conversion/retention corpora are general methodology. They are therefore
reference material only, extracted the same way as guardrails: transferable
tactics (SOPs, failure modes, principles, anti-patterns), never the corpus'
sample scripts, statistics, or price/benchmark figures, and never this
business's facts.
"""
from __future__ import annotations

from .families import NG_SALES, SALES_GENERAL
from .store import CorpusStore

_MAX_CHARS = 700


def _clip(text: str, limit: int = _MAX_CHARS) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def _first(rec: dict, *keys: str):
    for k in keys:
        if rec.get(k):
            return rec[k]
    return None


def conversion_reference(store: CorpusStore, text: str, names: set[str]) -> str:
    """Negotiation/stalling tactics for a live sales turn. Empty when the turn
    is not a negotiation, so ordinary questions pay no prompt cost."""
    if not (names & {"negotiation", "price_inquiry", "competitor_comparison", "stalling"}):
        return ""
    out = []
    for h in store.search(SALES_GENERAL, text, limit=2, family="conversion"):
        sop = h.record.get("actionable_sop")
        fail = h.record.get("failure_mode_analysis")
        thesis = h.record.get("executive_thesis")
        bits = []
        if isinstance(thesis, str) and thesis.strip():
            bits.append(f"tactic: {_clip(thesis, 220)}")
        if isinstance(sop, str) and sop.strip():
            bits.append(f"steps: {_clip(sop, 280)}")
        if isinstance(fail, str) and fail.strip():
            bits.append(f"avoid: {_clip(fail, 220)}")
        if bits:
            out.append("[conversion] " + " | ".join(bits))
    return "\n".join(out)


_PURPOSE_QUERIES = {
    "purchase_confirmation": "order confirmation reassurance message",
    "satisfaction_check": "post purchase satisfaction check message",
    "usage_followup": "product usage follow up message",
    "related_product": "cross sell related product message",
    "retention_campaign": "win back dormant customer campaign message",
    "abandoned_lead_recovery": "abandoned lead recovery follow up message",
}


def retention_reference(store: CorpusStore, purpose: str) -> str:
    """Playbook guidance for composing a follow-up of the given purpose."""
    query = _PURPOSE_QUERIES.get(purpose, purpose.replace("_", " ") + " follow up message")
    out = []
    for h in store.search(SALES_GENERAL, query, limit=2, family="retention"):
        bits = []
        principles = h.record.get("key_principles")
        insights = h.record.get("actionable_insights")
        anti = h.record.get("anti_patterns")
        if isinstance(principles, (str, list)) and principles:
            bits.append(f"principles: {_clip(principles if isinstance(principles, str) else ' '.join(map(str, principles)), 240)}")
        if isinstance(insights, (str, list)) and insights:
            bits.append(f"insights: {_clip(insights if isinstance(insights, str) else ' '.join(map(str, insights)), 240)}")
        if isinstance(anti, (str, list)) and anti:
            bits.append(f"avoid: {_clip(anti if isinstance(anti, str) else ' '.join(map(str, anti)), 200)}")
        if bits:
            out.append("[retention] " + " | ".join(bits))
    return "\n".join(out)


def leadgen_reference(store: CorpusStore, query: str, limit: int = 3) -> list[str]:
    """Nigerian lead-generation channel playbooks (outbound/SMM planning material)."""
    out = []
    for h in store.search(NG_SALES, query, limit=limit):
        summary = h.record.get("summary")
        principles = h.record.get("key_principles")
        bits = []
        if isinstance(summary, str) and summary.strip():
            bits.append(_clip(summary, 260))
        if isinstance(principles, (str, list)) and principles:
            bits.append("principles: " + _clip(principles if isinstance(principles, str) else " ".join(map(str, principles)), 240))
        if bits:
            out.append("[leadgen] " + " | ".join(bits))
    return out
