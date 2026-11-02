"""While you were away: what the sales rep did in a window of time, read from the records that already exist.

Nothing here is estimated. Messages and approvals come from the tenant's database, paid orders and stock movements from the order and
inventory tables, and the finer counts (voice notes heard, photos read, screenshots flagged, drafts the price and claims guards corrected)
from the audit trail. The point is to let an owner see, in ten seconds, that the shop kept selling and what was held back for them.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

LAGOS = timezone(timedelta(hours=1))
AFTER_HOURS = (22, 7)                    # 10pm to 7am Lagos time
AUDIT_TAIL_BYTES = 20_000_000            # a long-running shop's audit file can be large; the window is always recent
LANGUAGE_NAMES = {"pidgin": "Pidgin", "formal": "Formal English", "casual": "Casual English", "yoruba": "Yoruba", "igbo": "Igbo", "hausa": "Hausa"}


def _lagos_hour(iso: str) -> int | None:
    try:
        return datetime.fromisoformat(iso).astimezone(LAGOS).hour
    except ValueError:
        return None


def _audit_since(path, since: str):
    """Audit lines newer than `since` (ISO strings from the same clock compare correctly as text)."""
    if not path.exists():
        return
    with path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - AUDIT_TAIL_BYTES))
        if size > AUDIT_TAIL_BYTES:
            fh.readline()                # a cut-off first line
        for raw in fh:
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            if str(e.get("ts", "")) >= since:
                yield e


def _money(kobo: int) -> str:
    return f"₦{kobo // 100:,}"


def report(rt, hours: int = 12, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(hours=hours)).isoformat()
    con = rt.memory.con

    heard = {r[0] for r in con.execute("SELECT DISTINCT customer_key FROM messages WHERE role='user' AND ts>=?", (since,))}
    messages_in = con.execute("SELECT COUNT(*) FROM messages WHERE role='user' AND ts>=?", (since,)).fetchone()[0]
    replies = con.execute("SELECT COUNT(*) FROM messages WHERE role='assistant' AND ts>=?", (since,)).fetchone()[0]
    night = set()
    for key, ts in con.execute("SELECT customer_key, ts FROM messages WHERE role='user' AND ts>=?", (since,)):
        h = _lagos_hour(ts)
        if h is not None and (h >= AFTER_HOURS[0] or h < AFTER_HOURS[1]):
            night.add(key)

    paid = con.execute("SELECT COUNT(*), COALESCE(SUM(amount_kobo),0), COALESCE(SUM(qty),0) FROM orders WHERE paid_at>=? AND status IN ('paid','paid_oversold')",
                       (since,)).fetchone()
    links = con.execute("SELECT COUNT(*) FROM orders WHERE created>=?", (since,)).fetchone()[0]

    quiet = Counter(r[0] for r in con.execute("SELECT action FROM approvals WHERE created>=?", (since,)))
    waiting = len(rt.memory.pending_approvals())

    kinds, registers, flagged = Counter(), Counter(), 0
    for e in _audit_since(rt.orchestrator.audit.path, since):
        kind = e.get("kind")
        kinds[kind] += 1
        if kind == "analysis" and e.get("register"):
            registers[str(e["register"])] += 1
        elif kind == "receipt_checked" and e.get("findings"):
            flagged += 1
    corrected = kinds["reply_blocked"] + kinds["reply_retry"]

    languages = [{"name": LANGUAGE_NAMES.get(k, k.replace("_", " ").title()), "turns": n} for k, n in registers.most_common(4)]
    rep = (getattr(rt.cfg, "agent_name", "") or "").strip() or "Your rep"
    bits = []
    if heard:
        bits.append(f"spoke with {len(heard)} customer{'s' if len(heard) != 1 else ''}")
    if paid[0]:
        bits.append(f"took {paid[0]} paid order{'s' if paid[0] != 1 else ''} worth {_money(paid[1])}")
    if flagged:
        bits.append(f"held back {flagged} payment screenshot{'s' if flagged != 1 else ''} for you to check")
    window = f"{hours} hours" if hours != 1 else "hour"
    headline = (f"In the last {window}, {rep} " + ", ".join(bits[:-1]) + (" and " if len(bits) > 1 else "") + bits[-1] + ".") if bits \
        else f"Nothing needed {rep} in the last {window}."
    return {"window_hours": hours, "since": since, "headline": headline,
            "conversations": len(heard), "messages_in": messages_in, "replies": replies, "after_hours": len(night),
            "orders_paid": paid[0], "revenue_kobo": int(paid[1]), "units_sold": int(paid[2]), "payment_links": links,
            "voice_notes": kinds["voice_transcribed"], "photos": kinds["photo_read"], "receipts_flagged": flagged,
            "drafts_corrected": corrected, "quiet_alerts": dict(quiet), "waiting_on_you": waiting, "languages": languages}
