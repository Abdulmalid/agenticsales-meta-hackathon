"""Receipts and invoices: one printable page per payment (receipt) and one per order (invoice, with what is paid and what is left).

Both are built from the stored orders and payments only. A receipt exists only for a payment the gateway confirmed, so the page can
never be used to "prove" a payment that did not happen. The references are unguessable, so the link works without a login."""
from __future__ import annotations

from datetime import datetime
from html import escape

CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"


def _naira(kobo: int) -> str:
    return f"₦{kobo // 100:,}" if kobo % 100 == 0 else f"₦{kobo / 100:,.2f}"


def _date(iso: str | None) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %Y, %H:%M") if iso else ""
    except ValueError:
        return ""


def receipt_data(rt, reference: str) -> dict | None:
    """A confirmed payment, as data. Covers both a single full payment and one instalment of a larger order."""
    pay = rt.orchestrator.payments
    inst = pay._installment(reference)
    if inst is not None:
        if inst["status"] != "paid":
            return None
        order = pay.order(inst["order_reference"])
        amount, paid_at, ref = inst["amount_kobo"], inst["paid_at"], inst["reference"]
        paid_total = sum(p["amount_kobo"] for p in pay.payments_for(order["reference"]) if p["status"] == "paid" and (p["paid_at"] or "") <= (paid_at or ""))
    else:
        order = pay.order(reference)
        if order is None or order["status"] not in ("paid", "paid_oversold"):
            return None
        amount, paid_at, ref, paid_total = order["amount_kobo"], order["paid_at"], order["reference"], order["amount_kobo"]
    return {"kind": "receipt", "reference": ref, "order": order, "amount_kobo": amount, "paid_at": paid_at,
            "balance_kobo": max(0, order["amount_kobo"] - paid_total)}


def invoice_data(rt, order_reference: str) -> dict | None:
    pay = rt.orchestrator.payments
    order = pay.order(order_reference)
    if order is None:
        return None
    pays = [p for p in pay.payments_for(order_reference) if p["status"] == "paid"]
    paid = sum(p["amount_kobo"] for p in pays) if pays else (order["amount_kobo"] if order["status"] in ("paid", "paid_oversold") else 0)
    return {"kind": "invoice", "reference": order_reference, "order": order, "payments": pays, "paid_kobo": paid,
            "balance_kobo": max(0, order["amount_kobo"] - paid)}


def render(rt, data: dict) -> str:
    cfg, order = rt.cfg, data["order"]
    product = cfg.product(order["sku"])
    item = escape(product.name if product else order["sku"]) + (f" ({escape(order['variant'])})" if order.get("variant") else "")
    unit = order["amount_kobo"] // max(1, order["qty"])
    title = "Receipt" if data["kind"] == "receipt" else "Invoice"
    rows = [("Item", f"{item} × {order['qty']}"), ("Unit price", _naira(unit)), ("Order total", _naira(order["amount_kobo"]))]
    if data["kind"] == "receipt":
        rows += [("Paid now", _naira(data["amount_kobo"])), ("Paid on", _date(data["paid_at"])), ("Balance still to pay", _naira(data["balance_kobo"]))]
        note = "Delivery follows the final payment." if data["balance_kobo"] else "Paid in full. Thank you."
    else:
        for i, p in enumerate(data["payments"], 1):
            rows.append((f"Payment {i} · {_date(p['paid_at'])}", _naira(p["amount_kobo"])))
        rows += [("Paid so far", _naira(data["paid_kobo"])), ("Balance due", _naira(data["balance_kobo"]))]
        note = "Paid in full." if not data["balance_kobo"] else "The goods are delivered after the full price is paid."
    body = "".join(f"<tr><th>{escape(k)}</th><td>{escape(v) if k not in ('Item',) else v}</td></tr>" for k, v in rows)
    extra = "".join(f"<div>{escape(x)}</div>" for x in (cfg.address, cfg.whatsapp, f"RC {cfg.cac_number}" if cfg.cac_number else "") if x)
    accent = escape((cfg.brand_colors or {}).get("primary", "#0A7C66"))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} {escape(data['reference'])}</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;background:#f6f5f1;color:#1d2b27;margin:0;padding:24px}}
.sheet{{max-width:520px;margin:0 auto;background:#fff;border-radius:14px;padding:28px;box-shadow:0 1px 3px #0002}}
h1{{margin:0 0 2px;font-size:22px}} .kind{{color:{accent};font-weight:700;letter-spacing:.08em;text-transform:uppercase;font-size:12px}}
.meta{{color:#5d6b66;font-size:14px;margin-bottom:18px}} table{{width:100%;border-collapse:collapse}}
th{{text-align:left;font-weight:500;color:#5d6b66;padding:8px 0;border-bottom:1px solid #eee}} td{{text-align:right;padding:8px 0;border-bottom:1px solid #eee;font-weight:600}}
.note{{margin-top:18px;padding:12px 14px;border-radius:10px;background:{accent}14;border-left:3px solid {accent}}}
.ref{{margin-top:16px;color:#8a958f;font-size:12px;word-break:break-all}} @media print{{body{{background:#fff;padding:0}} .sheet{{box-shadow:none}}}}</style></head>
<body><div class="sheet"><div class="kind">{title}</div><h1>{escape(cfg.business_name)}</h1><div class="meta">{extra}</div>
<table>{body}</table><div class="note">{escape(note)}</div><div class="ref">Reference {escape(data['reference'])}</div></div></body></html>"""
