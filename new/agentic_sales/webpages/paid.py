"""Where a customer lands after paying: a plain "payment received" page, not the chat.

Paystack sends the browser back to the address given when the payment link was made. The page asks the gateway about that one reference
(the same check the webhook runs, and it is idempotent), so it shows "received" only for a payment the gateway confirmed and never from
the browser's say-so. It shows the item, the receipt and tracking links and a way back to the chat; no address, phone or card detail."""
from __future__ import annotations

from html import escape

from .receipt import CSP, _naira, receipt_data  # noqa: F401  (CSP is re-exported for the route)

_ICON = '<svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{}</svg>'
_SVG = {"ok": _ICON.format('<path d="M5 12.5l4.5 4.5L19 7.5"/>'),
        "wait": _ICON.format('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
        "alert": _ICON.format('<path d="M12 6v7M12 17.5v.01"/>')}

MAX_REFRESHES = 10          # "waiting" pages re-check by themselves, a bounded number of times
REFRESH_SECONDS = 6


def paid_data(rt, reference: str) -> dict | None:
    """What to show for one payment reference, or None when we never issued it. Asks the gateway once."""
    pay = rt.orchestrator.payments
    inst = pay._installment(reference)
    order = pay.order(inst["order_reference"]) if inst is not None else pay.order(reference)
    if order is None:
        return None
    state = pay.confirm(reference).status
    state = state if state in ("verified", "failed", "mismatch") else "pending"      # unknown/error/pending all read "still waiting"
    data = {"state": state, "reference": reference, "order": order, "balance_kobo": 0, "amount_kobo": order["amount_kobo"],
            "receipt_url": None, "track_url": None}
    if state == "verified":
        paid = receipt_data(rt, reference)
        if paid is not None:
            data["amount_kobo"], data["balance_kobo"] = paid["amount_kobo"], paid["balance_kobo"]
        data["receipt_url"] = pay.receipt_url(reference)
        if not data["balance_kobo"]:
            data["track_url"] = pay.track_url(order["reference"])
    return data


def render(rt, data: dict, chat_url: str | None = None, refreshes: int = 0) -> str:
    cfg, order, state = rt.cfg, data["order"], data["state"]
    product = cfg.product(order["sku"])
    item = escape(product.name if product else order["sku"]) + (f" ({escape(order['variant'])})" if order.get("variant") else "") + (f" × {order['qty']}" if order["qty"] > 1 else "")
    accent = escape((cfg.brand_colors or {}).get("primary", "#0A7C66"))
    refresh = ""
    if state == "verified":
        mark, tone = _SVG["ok"], accent
        heading = "Payment received"
        if data["balance_kobo"]:
            line = f"We got {escape(_naira(data['amount_kobo']))}. Balance still to pay: {escape(_naira(data['balance_kobo']))}. Your item is held and is delivered after the final payment."
        else:
            line = f"{escape(_naira(data['amount_kobo']))} paid for {item}. {escape(cfg.business_name)} will update you on delivery."
    elif state == "pending":
        mark, tone = _SVG["wait"], "#9a6b00"
        heading = "Waiting for your bank"
        line = "Your payment has not been confirmed yet. This page checks again by itself. If you were charged, do not pay again: tell us in the chat and quote the reference below."
        if refreshes < MAX_REFRESHES:
            refresh = f'<meta http-equiv="refresh" content="{REFRESH_SECONDS};url=?n={refreshes + 1}">'
    else:
        mark, tone = _SVG["alert"], "#b3261e"
        heading = "We could not confirm this payment"
        line = "No goods have been released. Tell us in the chat and quote the reference below, and the team will sort it out."
    links = ""
    for label, url in (("View receipt", data["receipt_url"]), ("Track your order", data["track_url"]), ("Back to the chat", chat_url)):
        if url:
            links += f'<a class="btn" href="{escape(url, quote=True)}">{label}</a>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">{refresh}
<title>{escape(heading)}</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;background:#f6f5f1;color:#1d2b27;margin:0;padding:24px}}
.sheet{{max-width:480px;margin:8vh auto 0;background:#fff;border-radius:14px;padding:32px 28px;box-shadow:0 1px 3px #0002;text-align:center}}
.mark{{width:56px;height:56px;border-radius:50%;margin:0 auto 14px;display:flex;align-items:center;justify-content:center;font-size:28px;color:#fff;background:{tone}}}
h1{{margin:0 0 6px;font-size:22px}} .biz{{color:#5d6b66;font-size:14px;margin-bottom:16px}} p{{margin:0 0 18px}}
.btn{{display:block;margin:8px 0;padding:12px 14px;border-radius:10px;background:{accent};color:#fff;text-decoration:none;font-weight:600}}
.btn:nth-of-type(n+2){{background:#fff;color:{accent};border:1px solid {accent}}}
.ref{{margin-top:18px;color:#8a958f;font-size:12px;word-break:break-all}}</style></head>
<body><div class="sheet"><div class="mark">{mark}</div><h1>{escape(heading)}</h1><div class="biz">{escape(cfg.business_name)}</div>
<p>{line}</p>{links}<div class="ref">Reference {escape(data['reference'])}</div></div></body></html>"""
