"""The customer's order tracking page: where the goods are, from what the shop recorded. Shows the product and the timeline only: no
address, no phone, no amounts. The order reference we issued is unguessable, so the link works without a login."""
from __future__ import annotations

from html import escape

from ..payments.delivery import LABELS, STAGES
from .receipt import CSP, _date  # noqa: F401  (CSP is re-exported for the route)


def tracking_data(rt, reference: str) -> dict | None:
    pay = rt.orchestrator.payments
    order = pay.order(reference)
    if order is None:
        return None
    return {"order": order, "where": pay.delivery.where(order), "history": pay.delivery.history(reference)}


def render(rt, data: dict) -> str:
    cfg, order, where = rt.cfg, data["order"], data["where"]
    product = cfg.product(order["sku"])
    item = escape(product.name if product else order["sku"]) + (f" ({escape(order['variant'])})" if order.get("variant") else "") + (f" × {order['qty']}" if order["qty"] > 1 else "")
    accent = escape((cfg.brand_colors or {}).get("primary", "#0A7C66"))
    steps = ""
    if where["stage"] in STAGES or where["stage"] == "preparing":
        top = STAGES.index(where["stage"]) if where["stage"] in STAGES else 0
        shown = [s for s in STAGES if s != "ready_for_pickup" or where["stage"] == "ready_for_pickup"]
        for s in shown:
            on = STAGES.index(s) <= top
            steps += f'<li class="{"on" if on else ""}"><span class="dot"></span>{escape(LABELS[s])}</li>'
    events = "".join(
        f"<div class='ev'><strong>{escape(LABELS[e['stage']])}</strong> <span class='when'>{escape(_date(e['created']))}</span>"
        + (f"<div>{escape(e['note'])}</div>" if e["note"] else "")
        + (f"<div class='when'>Courier: {escape(e['carrier'])} {('· tracking ' + escape(e['tracking_code'])) if e['tracking_code'] else ''}</div>" if e["carrier"] or e["tracking_code"] else "")
        + "</div>" for e in reversed(data["history"]))
    extra = "".join(f"<div>{escape(x)}</div>" for x in (cfg.address, cfg.whatsapp) if x)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Order {escape(order['reference'])}</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;background:#f6f5f1;color:#1d2b27;margin:0;padding:24px}}
.sheet{{max-width:520px;margin:0 auto;background:#fff;border-radius:14px;padding:28px;box-shadow:0 1px 3px #0002}}
h1{{margin:0 0 2px;font-size:22px}} .kind{{color:{accent};font-weight:700;letter-spacing:.08em;text-transform:uppercase;font-size:12px}}
.meta{{color:#5d6b66;font-size:14px;margin-bottom:18px}} .now{{margin:14px 0;padding:12px 14px;border-radius:10px;background:{accent}14;border-left:3px solid {accent};font-weight:600}}
ol{{list-style:none;padding:0;margin:18px 0}} li{{display:flex;align-items:center;gap:10px;padding:6px 0;color:#8a958f}} li.on{{color:#1d2b27;font-weight:600}}
.dot{{width:12px;height:12px;border-radius:50%;border:2px solid #c9d1cd;flex:none}} li.on .dot{{background:{accent};border-color:{accent}}}
.ev{{padding:8px 0;border-top:1px solid #eee}} .when{{color:#8a958f;font-size:13px}} .ref{{margin-top:16px;color:#8a958f;font-size:12px;word-break:break-all}}</style></head>
<body><div class="sheet"><div class="kind">Order tracking</div><h1>{escape(cfg.business_name)}</h1><div class="meta">{extra}</div>
<div><strong>{item}</strong></div><div class="now">{escape(where['label'])}</div>
<ol>{steps}</ol>{events}<div class="ref">Reference {escape(order['reference'])}</div></div></body></html>"""
