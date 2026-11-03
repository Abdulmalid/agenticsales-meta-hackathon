"""The quality benchmark. Nothing is treated as finished below MIN_SCORE (90 out of 100 unless DESIGN_MIN_SCORE says otherwise): flyers are rated by
the design studio's art director, and every picture and video frame by Muse Spark looking at it. Without a model the picture cannot be rated, and
an unrated picture never claims to have passed."""
from __future__ import annotations

import json
import os
import re

from ..models.base import Image, Message, ModelRequest

MIN_SCORE = float(os.environ.get("DESIGN_MIN_SCORE", "90"))
MAX_PICTURE_TRIES = 3

PICTURE_SYSTEM = """You inspect one picture that a Nigerian business wants to post, as a product photo or as a frame of a short video. Be strict and calibrated.
Score 0 to 100. 90 or more means a professional would publish it unchanged. Subtract for: warped, melted, duplicated or impossible objects; a product that is
not clearly the subject; wrong or extra objects for the scene described; any text, letters, numbers, logos or watermarks inside the picture; people, hands
or faces when none were asked for; dull light, clutter, awkward framing, bars or empty bands, low detail.
Reply with JSON only: {"score": <0 to 100>, "issues": ["each visible defect, short and specific"]}"""


def rate_picture(model, picture: bytes, scene: str) -> tuple[float | None, list[str]]:
    """(score, defects) for a picture meant to show `scene`, or (None, []) when there is no model or it gave no usable answer."""
    if model is None or not hasattr(model, "complete"):
        return None, []
    mime = "image/png" if picture[:4] == b"\x89PNG" else "image/jpeg"
    try:
        res = model.complete(ModelRequest(PICTURE_SYSTEM, (Message("user", f"The picture is meant to show: {scene[:400]}"),), max_tokens=400, temperature=0.0,
                                          images=(Image(mime, picture),)))
        m = re.search(r"\{.*\}", res.text, re.S)
        d = json.loads(m.group(0)) if m else {}
        return max(0.0, min(100.0, float(d["score"]))), [str(x)[:120] for x in (d.get("issues") or [])][:5]
    except Exception:                                  # noqa: BLE001 - a rating that fails is "not rated", never "passed"
        return None, []
