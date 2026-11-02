"""Plain texting punctuation, applied in code to every reply (a prompt alone does not stop a model reaching for an em dash).

Em and en dashes, semicolons, curly quotes, markdown markers and stacks of exclamation marks make a message read like generated text and
show up as stray symbols in a chat app. Amounts, names and the words themselves are never changed, only the punctuation around them.
"""
from __future__ import annotations

import re

_DASH = re.compile(r"\s*[\u2014\u2015]\s*|\s+[\u2013\u2012]\s+|\s+--\s+")            # em dash, horizontal bar, spaced en dash, spaced double hyphen
_RANGE = re.compile(r"(\d)\s*[\u2013\u2012]\s*(\d)")                                     # 10-20, not "10, 20"
_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2026": "..."})
_BOLD = re.compile(r"(\*\*|__)(.+?)\1")
_BULLET = re.compile(r"(?m)^[ \t]*(?:[-*\u2022]|\d+[.)])[ \t]+")
_LIST_LINE = re.compile(r"(?m)^[ \t]*(?:(?P<num>\d+)[.)]|[-*\u2022])[ \t]+(?P<rest>\S.*)$")


# A reply that opens with one of these reads like a template. Only the opener is removed, never anything the customer needs.
_OPENER = re.compile(r"^\s*(?:certainly|absolutely|of course|great question|sure thing)[!.,]\s+(?=\S)", re.I)
_FILLER = re.compile(r"\b(?:i hope this message finds you well|feel free to reach out|i would be delighted to assist)[^.!?\n]*[.!?]?\s*", re.I)


def _tidy_list(t: str) -> str:
    """Two or more list lines are a real list (stock by colour, several prices): keep it, one item per line, as "1." or "-". A lone
    "- " or "1. " is only a stray marker, and is dropped as before."""
    if len(_LIST_LINE.findall(t)) < 2:
        return _BULLET.sub("", t)
    return _LIST_LINE.sub(lambda m: (f"{m.group('num')}. " if m.group("num") else "- ") + m.group("rest").strip(), t)


def humanize(text: str) -> str:
    t = _OPENER.sub("", text.translate(_QUOTES))
    t = _FILLER.sub("", t)
    if t[:1].islower() and text[:1].isupper():
        t = t[:1].upper() + t[1:]
    t = _BOLD.sub(r"\2", t)
    t = _tidy_list(t)
    t = _RANGE.sub(r"\1-\2", t)
    t = _DASH.sub(", ", t)
    t = re.sub(r"\s*;\s*", ", ", t)
    t = re.sub(r"\s+([,.!?])", r"\1", t)                       # no space before punctuation
    t = re.sub(r",(\s*,)+", ",", t)
    t = re.sub(r",\s*([.!?])", r"\1", t)                       # "yes, ." from a dash before a full stop
    t = re.sub(r"[ \t]{2,}", " ", t)
    seen = False                                                 # at most one exclamation mark in a reply
    out = []
    for ch in re.sub(r"!{2,}", "!", t):
        if ch == "!":
            out.append("." if seen else "!")
            seen = True
        else:
            out.append(ch)
    return "".join(out).strip()
