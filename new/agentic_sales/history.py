"""The history page: one dated line, to the second, for everything the rep and the team did with money and stock.

Built only from records that already exist (orders, order payments, stock movements, delivery updates, approvals and the rep's tool calls
in the audit trail), merged newest first. Nothing is estimated and nothing is stored twice: the page is a reading of the real tables, so it
cannot disagree with them."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .payments.delivery import LABELS

KINDS = ("sales", "stock", "delivery", "approvals", "agent")
REASONS = {"manual": "set by hand", "restock": "restocked", "shop_sale": "sold at the shop", "damaged": "marked damaged", "correction": "corrected",
           "sale": "sold by the rep", "restore": "put back after a cancelled order", "sheet_edit": "changed in the Google Sheet",
           "sheet_removed": "removed in the Google Sheet"}
APPROVAL = {"discount": "a discount", "order": "an order", "oversold": "an oversold order", "payment_mismatch": "a payment that did not match",
            "fraud_review": "a payment to double-check", "human_handoff": "a customer who needs a person"}
AGENT_TOOLS = {"propose_price": "handled a price request", "verify_payment": "checked a payment with the gateway", "escalate_to_human": "alerted you about a customer",
               "track_order": "told a customer where their order is", "create_instalment_link": "sent a payment link for the rest of an order"}
AUDIT_TAIL_BYTES = 8_000_000
MAX_LIMIT = 300


def _naira(kobo: int | None) -> str:
    return f"₦{(kobo or 0) // 100:,}"


def _audit_tail(path, floor: str):
    if path is None or not path.exists():
        return
    with path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - AUDIT_TAIL_BYTES))
        if size > AUDIT_TAIL_BYTES:
            fh.readline()
        for raw in fh:
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            if str(e.get("ts", "")) >= floor:
                yield e


def feed(rt, limit: int = 100, before: str | None = None, kind: str | None = None) -> dict:
    limit = max(1, min(limit, MAX_LIMIT))
    want = {kind} if kind in KINDS else set(KINDS)
    con, cfg = rt.memory.con, rt.cfg
    names = {}

    def who(key: str) -> str:
        if key not in names:
            names[key] = (rt.memory.facts(key).get("name") or "").strip() or key.split(":", 1)[-1]
        return names[key]

    def item(sku: str, variant: str = "") -> str:
        p = cfg.product(sku)
        return (p.name if p else sku) + (f" ({variant})" if variant else "")

    cut = before or "9999"
    rows: list[dict] = []

    def add(ts, k, text, actor="", ref=""):
        if ts and ts < cut and k in want:
            rows.append({"ts": ts, "kind": k, "text": text, "actor": actor, "ref": ref})

    if "sales" in want:
        for o in con.execute("SELECT * FROM orders WHERE created<? OR paid_at<? ORDER BY created DESC LIMIT ?", (cut, cut, limit * 2)):
            what = f"{o['qty']} × {item(o['sku'], o['variant'])}"
            add(o["created"], "sales", f"Sent a payment link for {what} ({_naira(o['amount_kobo'])}) to {who(o['customer_key'])}.", "rep", o["reference"])
            if o["paid_at"]:
                add(o["paid_at"], "sales", f"Sold {what} for {_naira(o['amount_kobo'])} to {who(o['customer_key'])}. The payment gateway confirmed it.", "gateway", o["reference"])
        for pay in con.execute("SELECT * FROM order_payments WHERE paid_at<? AND status='paid' ORDER BY paid_at DESC LIMIT ?", (cut, limit)):
            o = con.execute("SELECT * FROM orders WHERE reference=?", (pay["order_reference"],)).fetchone()
            if o is not None:
                add(pay["paid_at"], "sales", f"Instalment of {_naira(pay['amount_kobo'])} received for {item(o['sku'], o['variant'])} from {who(o['customer_key'])}.", "gateway", o["reference"])
    if "stock" in want:
        for m in rt.inventory.movements(limit * 2):
            what = item(m["sku"], m["variant"])
            change = f"{'+' if m['delta'] > 0 else ''}{m['delta']}"
            left = f", {m['after_qty']} left" if m["after_qty"] is not None else ""
            add(m["ts"], "stock", f"Stock {change} for {what} ({REASONS.get(m['reason'], m['reason'])}{left}).", m["actor"] or "", m["ref"] or "")
    if "delivery" in want:
        for e in con.execute("SELECT * FROM order_events WHERE created<? ORDER BY id DESC LIMIT ?", (cut, limit)):
            o = con.execute("SELECT * FROM orders WHERE reference=?", (e["reference"],)).fetchone()
            if o is None:
                continue
            extra = " ".join(x for x in (e["note"], f"Courier {e['carrier']}." if e["carrier"] else "", f"Tracking {e['tracking_code']}." if e["tracking_code"] else "") if x)
            add(e["created"], "delivery", f"{item(o['sku'], o['variant'])} for {who(o['customer_key'])} is now: {LABELS.get(e['stage'], e['stage'])}. {extra}".strip(), e["by"], e["reference"])
    if "approvals" in want:
        for a in con.execute("SELECT * FROM approvals WHERE created<? OR decided<? ORDER BY id DESC LIMIT ?", (cut, cut, limit)):
            label = APPROVAL.get(a["action"], a["action"])
            add(a["created"], "approvals", f"Asked for your decision on {label} ({who(a['customer_key'])}).", "rep")
            if a["decided"]:
                add(a["decided"], "approvals", f"Decision made on {label} ({who(a['customer_key'])}): {a['status']}.", "")
    if "agent" in want:
        floor = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        for e in _audit_tail(rt.orchestrator.audit.path, floor):
            if e.get("kind") == "tool_call" and e.get("status") == "ok" and e.get("tool") in AGENT_TOOLS:
                add(str(e.get("ts", "")), "agent", f"The rep {AGENT_TOOLS[e['tool']]}.", "rep", str(e.get("trace", "")))
            elif e.get("kind") == "owner_alert":
                add(str(e.get("ts", "")), "agent", "The rep sent you an alert.", "rep", str(e.get("trace", "")))

    rows.sort(key=lambda r: r["ts"], reverse=True)
    seen, out = set(), []
    for r in rows:
        key = (r["ts"], r["text"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    page = out[:limit]
    return {"items": page, "next_before": page[-1]["ts"] if len(out) > limit else None}
