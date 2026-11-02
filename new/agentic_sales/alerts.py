"""Silent alerts to the business owner.

When the agent needs a person (a discount to approve, a payment that does not match, a customer it should not answer alone) it does not tell the
customer "I'm handing you to the team". It keeps the conversation natural and quietly sends the owner a short message on Telegram.

The owner links their own Telegram account once: the console shows a code, the owner sends `/owner <code>` to the business's bot, and from then on
alerts arrive in that chat. The code is random per business and the link is a secret like the bot token (stored encrypted, never in the audit log).
"""
from __future__ import annotations

import hmac
import secrets as _secrets
import threading
import time

from .channels.adapters import ADAPTERS, ChannelError, ChannelUnavailable

SECTION = "alerts"                       # in the tenant's SecretStore: {"code": ..., "owner_chat_id": ...}
THROTTLE_SECONDS = 300                   # one alert per customer per five minutes; the approvals queue still holds every request
MAX_BAD_CODES = 8                        # wrong /owner codes tolerated per window before the command is ignored
BAD_CODE_WINDOW = 900

LABELS = {
    "human_handoff": "Needs a person",
    "discount": "Discount request",
    "fraud_review": "Possible fraud, please review",
    "payment_mismatch": "Payment does not match the order",
    "order": "Order waiting for your approval",
    "oversold": "Oversold, stock ran out",
}


def compose(business: str, row: dict, customer_text: str, name: str, console_url: str) -> str:
    import json

    try:
        payload = json.loads(row.get("payload") or "{}")
    except ValueError:
        payload = {}
    try:
        reasons = json.loads(row.get("reasons") or "[]")
    except ValueError:
        reasons = []
    why = str(payload.get("reason") or (reasons[0] if reasons else "") or "").strip()
    lines = [f"{business}: {LABELS.get(row.get('action'), 'Needs your attention')}",
             f"Customer: {name + ' (' + row['customer_key'] + ')' if name else row['customer_key']}"]
    if why:
        lines.append(f"Why: {why[:300]}")
    if customer_text:
        lines.append(f"Last message: \"{customer_text[:300]}\"")
    lines.append("Reply to them yourself, or approve it in the console." + (f"\n{console_url}" if console_url else ""))
    return "\n".join(lines)


class OwnerAlerts:
    def __init__(self, runtime):
        self.rt = runtime
        self._sent: dict[str, float] = {}
        self._bad: list[float] = []
        self._lock = threading.Lock()

    # ---- state -------------------------------------------------------------------------------------------------------------
    def _section(self) -> dict:
        return self.rt.secrets.get(SECTION)

    def code(self) -> str:
        """The owner's linking code, created on first use. Not guessable: 40 random bits plus a limit on wrong tries."""
        sec = self._section()
        if not sec.get("code"):
            sec = {**sec, "code": _secrets.token_hex(5)}
            self.rt.secrets.set(SECTION, sec)
        return sec["code"]

    def owner_chat(self) -> str | None:
        return self._section().get("owner_chat_id") or None

    def bot_ready(self) -> bool:
        return bool(self.rt.secrets.get("telegram").get("bot_token"))

    def state(self) -> dict:
        tg = self.rt.secrets.get("telegram")
        return {"bot": f"@{tg['bot_username']}" if tg.get("bot_username") else None, "bot_ready": self.bot_ready(),
                "linked": self.owner_chat() is not None, "code": self.code()}

    def unlink(self) -> None:
        sec = dict(self._section())
        sec.pop("owner_chat_id", None)
        self.rt.secrets.set(SECTION, sec)

    # ---- the /owner command, sent by the owner to the business's bot -----------------------------------------------------------
    def handle_command(self, chat_id: str, text: str) -> str:
        """Returns the bot's answer. `/owner <code>` links this chat, `/owner off` unlinks it (only from the linked chat)."""
        arg = text.split(None, 1)[1].strip() if len(text.split(None, 1)) > 1 else ""
        if arg.lower() == "off":
            if self.owner_chat() == chat_id:
                self.unlink()
                return "Alerts are off. Send /owner and your code again to turn them back on."
            return "This chat is not receiving alerts."
        now = time.monotonic()
        with self._lock:
            self._bad = [t for t in self._bad if now - t < BAD_CODE_WINDOW]
            if len(self._bad) >= MAX_BAD_CODES:
                return "Too many wrong codes. Try again in a few minutes."
        if arg and hmac.compare_digest(arg.encode(), self.code().encode()):
            sec = dict(self._section())
            sec["owner_chat_id"] = chat_id
            sec["code"] = _secrets.token_hex(5)             # a code works once: a copy that was seen or screenshotted cannot link another chat later
            self.rt.secrets.set(SECTION, sec)
            return f"Done. You will get a message here whenever {self.rt.cfg.business_name} needs you. Send /owner off to stop."
        with self._lock:
            self._bad.append(now)
        return "That code is not right. Copy it from Settings in your console."

    # ---- sending ---------------------------------------------------------------------------------------------------------
    def _send(self, text: str) -> bool:
        chat = self.owner_chat()
        tg = self.rt.secrets.get("telegram")
        if not chat or not tg.get("bot_token"):
            return False
        try:
            ADAPTERS["telegram"].send(chat, text, tg)
            return True
        except (ChannelUnavailable, ChannelError):
            return False

    def test(self) -> bool:
        return self._send(f"{self.rt.cfg.business_name}: this is a test alert. You will get messages like this when a customer needs you.")

    def notify(self, approval_id: int, row: dict) -> None:
        """Called whenever something is added to the approvals queue. Never raises: the customer's turn must not depend on the owner's phone."""
        try:
            ckey = row["customer_key"]
            now = time.monotonic()
            with self._lock:
                if now - self._sent.get(ckey, -1e9) < THROTTLE_SECONDS:
                    return
                self._sent[ckey] = now
            if not self.owner_chat():
                return
            last = self.rt.memory.con.execute("SELECT text FROM messages WHERE customer_key=? AND role='user' ORDER BY id DESC LIMIT 1", (ckey,)).fetchone()
            name = self.rt.memory.facts(ckey).get("name", "")
            import os
            ok = self._send(compose(self.rt.cfg.business_name, row, last["text"] if last else "", name, os.environ.get("CONSOLE_URL", "")))
            self.rt.orchestrator.audit.record(row.get("trace") or "", "owner_alert", approval=approval_id, delivered=ok)
        except Exception:  # noqa: BLE001
            pass
