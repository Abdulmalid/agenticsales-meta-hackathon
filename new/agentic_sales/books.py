"""The owner's books, kept by talking to the rep: expenses in, profit out.

Money in is never typed here. Revenue is read from payments the gateway confirmed (whole orders and every confirmed instalment), so the
profit figure cannot be inflated by anything a customer or the owner says. Expenses are what the owner tells the rep ("spent 5k on
transport"), by text or voice note, or enters in the console."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone

_SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, amount_kobo INTEGER NOT NULL, category TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'owner');
CREATE TABLE IF NOT EXISTS book_limits(key TEXT PRIMARY KEY, kobo INTEGER NOT NULL);
"""
CATEGORIES = {
    "transport": ("transport", "bolt", "uber", "bus", "okada", "keke", "logistics", "dispatch", "delivery", "waybill", "fare"),
    "fuel & power": ("fuel", "petrol", "diesel", "generator", "gen ", "nepa", "light bill", "electricity"),
    "stock": ("stock", "restock", "goods", "supplier", "wholesale", "inventory", "buy new", "bought"),
    "rent": ("rent", "shop fee", "service charge"),
    "staff": ("salary", "wages", "staff", "worker", "commission"),
    "data & airtime": ("data", "airtime", "wifi", "internet", "subscription"),
    "packaging": ("packaging", "nylon", "box", "wrap", "tape"),
    "marketing": ("ads", "advert", "boost", "promo", "flyer", "marketing", "influencer"),
}
MAX_EXPENSE_KOBO = 100_000_000 * 100
_AMOUNT = r"(?:₦|ngn\s?|n(?=\d))?\s?(\d[\d,]*(?:\.\d+)?\s?[km]?)\b"
_SPENT = re.compile(rf"(?i)^\s*/?(?:i\s+)?(?:spent|spend|expense|paid\s+out|paid)\s+{_AMOUNT}\s*(?:on|for|to|towards)?\s*(.*)$")
_LATER = re.compile(rf"(?i)^\s*/?(?:i\s+)?(?:spent|spend|expense|paid\s+out|paid)\b(.*?)\b{_AMOUNT}(?!\d)\s*(?:on|for)?\s*(.*)$")
_RANGE = re.compile(r"(?i)\b(today|yesterday|week|month)\b")


def _kobo(token: str) -> int | None:
    t = token.replace(",", "").replace(" ", "").lower()
    mult = 1_000 if t.endswith("k") else 1_000_000 if t.endswith("m") else 1
    try:
        return round(float(t.rstrip("km")) * mult * 100)
    except ValueError:
        return None


def parse_expense(text: str) -> tuple[int, str] | None:
    """'spent 5k on transport' / 'expense ₦12,000 generator fuel' -> (kobo, 'transport'). None when it is not an expense."""
    m = _SPENT.match(text or "")
    token, note = (m.group(1), m.group(2)) if m else (None, None)
    if token is None:
        m = _LATER.match(text or "")
        if not m:
            return None
        token, note = m.group(2), (m.group(1) + " " + m.group(3)).strip()
    kobo = _kobo(token)
    if not kobo or not 0 < kobo <= MAX_EXPENSE_KOBO:
        return None
    return kobo, " ".join(note.split())[:120]


def categorize(note: str) -> str:
    low = f" {note.lower()} "
    for name, words in CATEGORIES.items():
        if any(w in low for w in words):
            return name
    return "other"


def window(word: str | None, now: datetime) -> tuple[datetime, datetime, str]:
    """The Lagos-time day, week or month the owner asked about, as UTC bounds."""
    lagos = timezone(timedelta(hours=1))
    local = now.astimezone(lagos)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    word = (word or "today").lower()
    if word == "yesterday":
        return (start - timedelta(days=1)).astimezone(timezone.utc), start.astimezone(timezone.utc), "yesterday"
    if word == "week":
        return (start - timedelta(days=start.weekday())).astimezone(timezone.utc), now, "this week"
    if word == "month":
        return start.replace(day=1).astimezone(timezone.utc), now, "this month"
    return start.astimezone(timezone.utc), now, "today"


class OverLimit(ValueError):
    """An expense above the owner's own limit. The message says which limit and what to do."""


class Books:
    def __init__(self, memory):
        self.con = memory.con
        self.con.executescript(_SCHEMA)

    def limits(self) -> dict[str, int | None]:
        """The owner's spending limits in kobo: one expense, and everything logged in a Lagos day. None means no limit."""
        got = {k: v for k, v in self.con.execute("SELECT key, kobo FROM book_limits")}
        return {"per_expense_kobo": got.get("per_expense"), "daily_kobo": got.get("daily")}

    def set_limits(self, per_expense_kobo: int | None, daily_kobo: int | None) -> None:
        with self.con:
            for key, v in (("per_expense", per_expense_kobo), ("daily", daily_kobo)):
                if v is None:
                    self.con.execute("DELETE FROM book_limits WHERE key=?", (key,))
                else:
                    self.con.execute("INSERT OR REPLACE INTO book_limits(key,kobo) VALUES(?,?)", (key, int(v)))

    def over_limit(self, amount_kobo: int, now: datetime | None = None) -> str | None:
        """Why this expense is above a limit the owner set, or None."""
        lim, now = self.limits(), now or datetime.now(timezone.utc)
        if lim["per_expense_kobo"] is not None and amount_kobo > lim["per_expense_kobo"]:
            return f"{money_text(amount_kobo)} is above your limit of {money_text(lim['per_expense_kobo'])} for one expense."
        if lim["daily_kobo"] is not None:
            start, end, _ = window("today", now)
            spent = self.summary(start, end)["expenses_kobo"]
            if spent + amount_kobo > lim["daily_kobo"]:
                return f"With the {money_text(spent)} already spent today, {money_text(amount_kobo)} would go over your daily limit of {money_text(lim['daily_kobo'])}."
        return None

    def add(self, amount_kobo: int, note: str = "", category: str | None = None, source: str = "owner", now: datetime | None = None,
            confirmed: bool = False) -> dict:
        if not 0 < amount_kobo <= MAX_EXPENSE_KOBO:
            raise ValueError("the amount must be more than zero")
        if not confirmed and (why := self.over_limit(amount_kobo, now)):
            raise OverLimit(why)
        row = {"ts": (now or datetime.now(timezone.utc)).isoformat(), "amount_kobo": int(amount_kobo), "note": note.strip()[:120],
               "category": (category or categorize(note)).strip()[:30] or "other", "source": source[:20]}
        with self.con:
            cur = self.con.execute("INSERT INTO expenses(ts,amount_kobo,category,note,source) VALUES(?,?,?,?,?)",
                                   (row["ts"], row["amount_kobo"], row["category"], row["note"], row["source"]))
        return {"id": cur.lastrowid, **row}

    def remove(self, expense_id: int | None = None) -> dict | None:
        """Delete one expense (the latest when no id is given). Returns what was removed."""
        sql = "SELECT * FROM expenses " + ("WHERE id=?" if expense_id is not None else "ORDER BY id DESC LIMIT 1")
        row = self.con.execute(sql, (expense_id,) if expense_id is not None else ()).fetchone()
        if row is None:
            return None
        with self.con:
            self.con.execute("DELETE FROM expenses WHERE id=?", (row["id"],))
        return dict(row)

    def recent(self, limit: int = 30) -> list[dict]:
        return [dict(r) for r in self.con.execute("SELECT * FROM expenses ORDER BY ts DESC, id DESC LIMIT ?", (limit,))]

    def revenue(self, start: datetime, end: datetime) -> int:
        """Money the gateway confirmed in the window: every confirmed instalment, plus whole orders paid in one go."""
        s, e = start.isoformat(), end.isoformat()
        try:
            inst = self.con.execute("SELECT COALESCE(SUM(amount_kobo),0) FROM order_payments WHERE status='paid' AND paid_at>=? AND paid_at<=?", (s, e)).fetchone()[0]
            whole = self.con.execute("SELECT COALESCE(SUM(amount_kobo),0) FROM orders WHERE status IN ('paid','paid_oversold') AND paid_at>=? AND paid_at<=? "
                                     "AND reference NOT IN (SELECT order_reference FROM order_payments)", (s, e)).fetchone()[0]
        except sqlite3.OperationalError:          # no orders yet: the payment tables are created with the first payment service
            return 0
        return int(inst) + int(whole)

    def summary(self, start: datetime, end: datetime) -> dict:
        s, e = start.isoformat(), end.isoformat()
        by = {r[0]: int(r[1]) for r in self.con.execute("SELECT category, SUM(amount_kobo) FROM expenses WHERE ts>=? AND ts<=? GROUP BY category ORDER BY 2 DESC", (s, e))}
        spent = sum(by.values())
        revenue = self.revenue(start, end)
        return {"since": s, "until": e, "revenue_kobo": revenue, "expenses_kobo": spent, "profit_kobo": revenue - spent, "by_category": by}


def money_text(kobo: int) -> str:
    sign = "-" if kobo < 0 else ""
    kobo = abs(kobo)
    return f"{sign}₦{kobo // 100:,}" if kobo % 100 == 0 else f"{sign}₦{kobo / 100:,.2f}"


def owner_reply(books: Books, text: str, now: datetime | None = None) -> str | None:
    """The owner's message to their rep, if it is about the books. None means it is something else and the normal conversation goes on."""
    now = now or datetime.now(timezone.utc)
    t = (text or "").strip()
    low = t.lower()
    if low in ("/undo", "undo", "undo that", "/undo expense"):
        gone = books.remove()
        return f"Removed {money_text(gone['amount_kobo'])}{' · ' + gone['note'] if gone['note'] else ''}." if gone else "There is no expense to remove."
    parsed = parse_expense(t)
    if parsed:
        kobo, note = parsed
        try:
            row = books.add(kobo, note, source="chat", now=now)
        except OverLimit as e:
            return f"Not logged. {e} Change your limit or add it yourself in Books on the console."
        start, end, _ = window("today", now)
        day = books.summary(start, end)
        return (f"Logged {money_text(kobo)} · {row['category']}{' (' + note + ')' if note else ''}. "
                f"Spent today: {money_text(day['expenses_kobo'])}. Send /undo if that was a mistake.")
    if low.startswith(("/profit", "/books", "/today", "/week", "/month")) or re.match(r"(?i)^(how much|what).{0,40}\b(profit|made|sold|sales)\b", t):
        r = _RANGE.search(t)
        start, end, label = window(r.group(1) if r else ("week" if "/week" in low else "month" if "/month" in low else "today"), now)
        s = books.summary(start, end)
        lines = [f"{label.capitalize()}: money in {money_text(s['revenue_kobo'])}, spent {money_text(s['expenses_kobo'])}, profit {money_text(s['profit_kobo'])}."]
        if s["by_category"]:
            lines.append("Spent on: " + ", ".join(f"{k} {money_text(v)}" for k, v in list(s["by_category"].items())[:4]) + ".")
        lines.append("Money in counts only payments the payment gateway confirmed.")
        return " ".join(lines)
    return None
