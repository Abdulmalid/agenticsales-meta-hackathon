"""Checks on a payment screenshot that no one has to trust the customer for.

A Nigerian instant-transfer (NIP) session ID is 30 digits: a 6-digit institution code, a 12-digit YYMMDDHHMMSS timestamp (Lagos time) and a
12-digit sequence. A recycled screenshot of an old transfer, or an ID typed by hand, usually breaks one of those rules. These checks catch that.

What this can never do: confirm a payment. Only the payment gateway (verify_payment) does that. A clean receipt here only means "nothing
suspicious in what was readable"; a finding is a reason to look closer and to tell the owner quietly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

LAGOS = timezone(timedelta(hours=1))
MAX_AGE = timedelta(hours=24)
CLOCK_SLACK = timedelta(minutes=10)
_DIGITS = re.compile(r"\D+")


@dataclass(frozen=True)
class ReceiptFacts:
    """What was read off the screenshot (by the vision model; bounded and validated before it gets here)."""
    session_id: str = ""
    beneficiary: str = ""
    amount_kobo: int | None = None


@dataclass
class Findings:
    problems: list[str] = field(default_factory=list)
    session_time: datetime | None = None

    @property
    def suspicious(self) -> bool:
        return bool(self.problems)


def normalise_session_id(raw: str) -> str:
    return _DIGITS.sub("", raw or "")


def decode_session_time(session_id: str) -> datetime | None:
    """The transfer time embedded in a 30-digit session ID, or None if it is not a real date."""
    if len(session_id) != 30:
        return None
    t = session_id[6:18]
    try:
        return datetime(2000 + int(t[0:2]), int(t[2:4]), int(t[4:6]), int(t[6:8]), int(t[8:10]), int(t[10:12]), tzinfo=LAGOS)
    except ValueError:
        return None


def _tokens(name: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", name.lower()) if len(w) > 2}


def check(facts: ReceiptFacts, now: datetime | None = None, expected_names: tuple[str, ...] = (),
          expected_amount_kobo: int | None = None) -> Findings:
    now = now or datetime.now(timezone.utc)
    out = Findings()
    sid = normalise_session_id(facts.session_id)
    if not sid:
        out.problems.append("no session ID could be read from the screenshot")
    elif len(sid) != 30:
        out.problems.append(f"the session ID has {len(sid)} digits, a real one has 30")
    else:
        when = decode_session_time(sid)
        if when is None:
            out.problems.append("the session ID does not contain a real date")
        else:
            out.session_time = when
            if when > now + CLOCK_SLACK:
                out.problems.append("the session ID is dated in the future")
            elif now - when > MAX_AGE:
                out.problems.append(f"the session ID is from {when:%d %b %Y}, not from today's transfer")
    names = [_tokens(n) for n in expected_names if n]
    if facts.beneficiary and names:
        seen = _tokens(facts.beneficiary)
        if not any(len(seen & n) / len(n) >= 0.5 for n in names if n):
            out.problems.append("the receiving account name does not match the business")
    if expected_amount_kobo is not None and facts.amount_kobo is not None and facts.amount_kobo != expected_amount_kobo:
        out.problems.append("the amount on the screenshot differs from the order")
    return out
