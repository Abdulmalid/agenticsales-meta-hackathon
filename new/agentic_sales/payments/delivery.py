"""Where a paid order is: a short timeline the owner (or staff) moves forward, and the customer can read.

Only the shop knows where the goods are, so every stage here is something a person entered. The rep reads this table to answer
"where is my order" and never guesses a stage, a courier or a date. Delivery starts only once the gateway has confirmed the full
payment (the order is 'paid'); an instalment order that is still part paid is held and has no delivery."""
from __future__ import annotations

import re
from datetime import datetime, timezone

STAGES = ("preparing", "packed", "shipped", "out_for_delivery", "ready_for_pickup", "delivered")
LABELS = {"preparing": "Being prepared", "packed": "Packed and ready", "shipped": "On its way", "out_for_delivery": "Out for delivery",
          "ready_for_pickup": "Ready for pickup", "delivered": "Delivered"}
DELIVERABLE = ("paid", "paid_oversold")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS order_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, reference TEXT NOT NULL, stage TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
  carrier TEXT NOT NULL DEFAULT '', tracking_code TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, by TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_order_events_ref ON order_events(reference, id);
"""
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def _clean(text: object, limit: int) -> str:
    return _CONTROL.sub(" ", str(text or "")).strip()[:limit]


class Delivery:
    def __init__(self, memory):
        self.memory = memory
        memory.con.executescript(_SCHEMA)

    def update(self, order: dict, stage: str, *, note: str = "", carrier: str = "", tracking_code: str = "", by: str = "owner") -> dict:
        if order["status"] not in DELIVERABLE:
            raise ValueError("delivery can only be updated once the order is paid in full")
        if stage not in STAGES:
            raise ValueError(f"stage must be one of: {', '.join(STAGES)}")
        now = self.current(order["reference"])
        if now and now["stage"] == "delivered":
            raise ValueError("this order is already marked delivered")
        note, carrier, code = _clean(note, 200), _clean(carrier, 60), _clean(tracking_code, 60)
        if now and stage == now["stage"] and (note, carrier, code) == (now["note"], now["carrier"], now["tracking_code"]):
            return now                                                          # the same update twice changes nothing
        created = datetime.now(timezone.utc).isoformat()
        with self.memory.con:
            self.memory.con.execute("INSERT INTO order_events(reference, stage, note, carrier, tracking_code, created, by) VALUES(?,?,?,?,?,?,?)",
                                    (order["reference"], stage, note, carrier, code, created, _clean(by, 60)))
        return self.current(order["reference"])

    def current(self, reference: str) -> dict | None:
        r = self.memory.con.execute("SELECT * FROM order_events WHERE reference=? ORDER BY id DESC LIMIT 1", (reference,)).fetchone()
        return dict(r) if r else None

    def history(self, reference: str) -> list[dict]:
        return [dict(r) for r in self.memory.con.execute("SELECT * FROM order_events WHERE reference=? ORDER BY id", (reference,))]

    def where(self, order: dict) -> dict:
        """What can truthfully be said about this order right now, for the customer. Carrier and tracking code come from the shop."""
        status, event = order["status"], self.current(order["reference"])
        if event:
            return {"stage": event["stage"], "label": LABELS[event["stage"]], "note": event["note"], "carrier": event["carrier"],
                    "tracking_code": event["tracking_code"], "updated": event["created"]}
        if status in DELIVERABLE:
            return {"stage": "preparing", "label": "Payment confirmed, being prepared", "note": "", "carrier": "", "tracking_code": "", "updated": order["paid_at"]}
        if status == "part_paid":
            return {"stage": "held", "label": "Part paid. Goods are held until the full price is paid", "note": "", "carrier": "", "tracking_code": "", "updated": None}
        if status in ("cancelled", "refund_due"):
            return {"stage": status, "label": "Cancelled" if status == "cancelled" else "Cancelled, refund being arranged", "note": "", "carrier": "", "tracking_code": "", "updated": None}
        return {"stage": "awaiting_payment", "label": "Waiting for payment", "note": "", "carrier": "", "tracking_code": "", "updated": None}

    def message(self, product: str, event: dict, track_url: str | None) -> str:
        """What the customer is told when the shop moves the order on. Plain, no promises beyond what the shop entered."""
        parts = [f"Update on your order ({product}): {LABELS[event['stage']]}."]
        if event["note"]:
            parts.append(event["note"] if event["note"].endswith((".", "!", "?")) else event["note"] + ".")
        if event["carrier"] or event["tracking_code"]:
            parts.append("Courier: " + " ".join(x for x in (event["carrier"], f"(tracking {event['tracking_code']})" if event["tracking_code"] else "") if x) + ".")
        if track_url:
            parts.append(f"You can follow it here: {track_url}")
        return " ".join(parts)
