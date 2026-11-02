"""Retrieval over real Nigerian forum commerce dialogue (Nairaland market boards).

Source: caleb-mnb/nairaland-conversations (CC-BY-NC-4.0; attribution required).
Unlike the synthetic corpora, these are real multi-party bargaining threads, so
they serve as usage examples: how Nigerians actually phrase offers, haggling,
trust probes and delivery talk. Replies are never copied as templates; the
agent's wording stays bound by policy and brand voice.
"""
from __future__ import annotations

from .families import NG_DIALOGUE
from .store import CorpusStore

_MAX_CHARS = 700


def _clip(text: str, limit: int = _MAX_CHARS) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


_DIALOGUE_SIGNALS = {"negotiation", "price_inquiry", "trust_concern", "stalling",
                     "delivery_concern", "competitor_comparison"}


def dialogue_reference(store: CorpusStore, text: str, names: set[str]) -> str:
    """Real-utterance examples for commerce situations. Empty when the turn is
    not a commerce situation, so ordinary messages pay no prompt cost."""
    if not (names & _DIALOGUE_SIGNALS):
        return ""
    out = []
    for h in store.search(NG_DIALOGUE, text, limit=2):
        sample = h.record.get("dialogue_sample")
        if not isinstance(sample, list) or not sample:
            continue
        quotes = []
        for post in sample[:3]:
            if not isinstance(post, dict):
                continue
            t = str(post.get("text") or "").strip()
            if len(t) >= 20:
                quotes.append(f"\"{_clip(t, 180)}\"")
            if len(quotes) >= 2:
                break
        if quotes:
            out.append(f"[dialogue:{h.record.get('board', '?')}] " + " / ".join(quotes))
    return "\n".join(out)
