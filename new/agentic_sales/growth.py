"""Growth: who is most likely to buy what this shop sells, and how to reach them.

The model reads the owner's own catalogue and describes buyer segments (who they are, why they would buy, a hook, a sample post, a reply
script). It never sees or finds anyone's contact details: nobody is messaged because of this. The fit score is the model's estimate from
the catalogue, labelled as such, not measured demand, and the sample text is held to the shop's real prices."""
from __future__ import annotations

import json
import re

from .models.base import Message, ModelError, ModelRequest
from .security import untrusted

MAX_SEGMENTS = 4
SYSTEM = """You help a small online seller in Nigeria work out who is most likely to buy what they sell and how to reach them honestly.
Use only the business details and products below. Do not invent products, prices, discounts, guarantees, delivery times or facts about the shop.
Return JSON only, in this shape:
{"segments": [{"name": "<2-4 words>", "who": "<one sentence: who these people are>", "why": "<one sentence: why they would buy>",
 "fit": <0 to 100, how well this group matches the catalogue>, "skus": ["<sku from the list>"],
 "hook": "<one short line that would make them stop scrolling>", "post": "<a short social post, no prices unless copied from the list>",
 "reply": "<what the shop's rep should say when one of them asks the price question, no invented figures>"}]}
Give 3 or 4 different segments, best fit first. Write in simple friendly English that Nigerian shoppers use.

Business: {business} ({industry})
Audience the owner described: {audience}
Delivery areas: {areas}
Voice: {voice}
Products:
{products}"""
_NAIRA = re.compile(r"(?:₦|ngn\s?|n(?=\d))\s?(\d[\d,]*(?:\.\d+)?)\s?(k)?", re.I)


def _clean(text, n: int) -> str:
    return " ".join(untrusted.clean(str(text or "")).split())[:n]


def _prices_ok(text: str, allowed: set[int]) -> bool:
    """Every naira figure in the text must be a real list price (or a small number such as a delivery fee quoted elsewhere)."""
    for m in _NAIRA.finditer(text):
        value = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
        if value >= 1000 and round(value * 100) not in allowed:
            return False
    return True


def parse(text: str, cfg) -> list[dict]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ModelError("the model did not return JSON")
    try:
        data = json.loads(text[start:end + 1])
    except ValueError as e:
        raise ModelError(f"the model returned broken JSON: {e}") from None
    raw = data.get("segments") if isinstance(data, dict) else None
    if not isinstance(raw, list) or not raw:
        raise ModelError("the model returned no segments")
    skus = {p.sku for p in cfg.products}
    allowed = {p.price_kobo for p in cfg.products}
    out = []
    for s in raw[:MAX_SEGMENTS]:
        if not isinstance(s, dict) or not _clean(s.get("name"), 40):
            continue
        try:
            fit = max(0, min(100, int(float(s.get("fit", 0)))))
        except (TypeError, ValueError):
            fit = 0
        seg = {"name": _clean(s.get("name"), 40), "who": _clean(s.get("who"), 220), "why": _clean(s.get("why"), 220), "fit": fit,
               "skus": [k for k in (s.get("skus") or []) if isinstance(k, str) and k in skus][:6],
               "hook": _clean(s.get("hook"), 140), "post": _clean(s.get("post"), 500), "reply": _clean(s.get("reply"), 400)}
        seg["needs_edit"] = [k for k in ("hook", "post", "reply") if seg[k] and not _prices_ok(seg[k], allowed)]
        for k in seg["needs_edit"]:
            seg[k] = ""                      # a figure that is not one of the shop's prices is never shown as advice
        out.append(seg)
    if not out:
        raise ModelError("the model returned no usable segments")
    return sorted(out, key=lambda s: -s["fit"])


def suggest(model, cfg) -> list[dict]:
    products = "\n".join(f"- {p.sku}: {p.name}, ₦{p.price_kobo // 100:,}. {p.description}".strip() for p in cfg.products[:40]) or "(no products yet)"
    fill = {"business": _clean(cfg.business_name, 80), "industry": _clean(cfg.industry, 80), "audience": _clean(cfg.target_audience, 160) or "not described",
            "areas": _clean(", ".join(cfg.delivery_areas), 160) or "not stated", "voice": _clean(cfg.brand_voice, 80), "products": products}
    system = SYSTEM
    for key, value in fill.items():                      # the template holds a JSON example, so it is filled by name, not with str.format
        system = system.replace("{" + key + "}", value)
    resp = model.complete(ModelRequest(system=system, messages=(Message("user", "Suggest the buyer segments."),), max_tokens=1800,
                                       temperature=0.5, json_mode=True))
    return parse(resp.text, cfg)
