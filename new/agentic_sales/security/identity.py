"""Honesty about what the agent is, enforced in code rather than left to the prompt (like prices and payment confirmation).

The agent does not announce that it is automated in every greeting, and it can have a name. But it never claims to be a person, and when a
customer sincerely asks whether they are talking to a person or a bot, the reply must say plainly that it is the business's virtual
assistant and that a team member can take over. A prompt can be dodged ("Na Tunde here, I dey with the sales team"); this cannot.
"""
from __future__ import annotations

import re

from ..language.analysis import Register

_KINDS = r"(?:person|human|bot|robot|machine|ai|chatbot|man|woman|somebody|someone|computer|program)"

# a customer asking what they are talking to (English and Nigerian Pidgin)
_ASKS = [
    re.compile(rf"\b(?:are|r|be|dey)\s+(?:you|u|una)\s+(?:a\s+|an\s+)?(?:real\s+|actual\s+|live\s+)?{_KINDS}\b", re.I),
    re.compile(rf"\b(?:you|u)\s+(?:be|dey)\s+(?:a\s+)?(?:real\s+|actual\s+)?{_KINDS}\b", re.I),
    re.compile(r"\b(?:real|actual|live)\s+(?:person|human|man|woman|somebody|someone)\b", re.I),
    re.compile(rf"\b(?:is|na)\s+(?:this|dis|it|that|una)\s+(?:a\s+|an\s+)?{_KINDS}\b", re.I),
    re.compile(r"\b(?:talking|speaking|chatting|texting|dey (?:talk|chat))\s+(?:to|with)\s+(?:a\s+|an\s+)?(?:real\s+)?(?:bot|robot|machine|ai|chatbot|human|person|computer)\b", re.I),
    re.compile(r"\bna\s+(?:bot|robot|machine|ai|chatbot)\b", re.I),
]

# a reply that already tells the truth
_DISCLOSES = re.compile(r"\b(?:virtual|automated|automatic|chatbot|bot|robot|software|not (?:a )?(?:real )?(?:person|human)|no be (?:a )?(?:real )?(?:person|human))\b", re.I)

# a reply that pretends to be a person
_CLAIMS_HUMAN = [
    re.compile(r"\bi(?:'m| am| be)\s+(?:a\s+)?(?:real\s+|actual\s+|live\s+)?(?:person|human|man|woman|guy|girl|human being)\b", re.I),
    re.compile(r"\b(?:i(?:'m| am)\s+not|no be|not)\s+(?:a\s+|an\s+)?(?:bot|robot|machine|ai|chatbot|computer|program)\b", re.I),
    re.compile(r"\b(?:real|actual) (?:person|human)\s+(?:here|dey|is here|speaking|typing)\b", re.I),
]


def asks_if_automated(text: str) -> bool:
    return any(rx.search(text) for rx in _ASKS)


def discloses(reply: str) -> bool:
    return bool(_DISCLOSES.search(reply))


def claims_human(reply: str) -> bool:
    return any(rx.search(reply) for rx in _CLAIMS_HUMAN)


def check_identity(reply: str) -> list[str]:
    """Violations in the shape the reply guard uses; empty means the reply is fine."""
    return ["claims to be a human being (it must never do that)"] if claims_human(reply) else []


def disclosure_reply(business: str, agent_name: str, register: Register) -> str:
    """The truthful answer, in the customer's register. It names the assistant if the business gave it a name."""
    who = agent_name.strip()
    if register in (Register.PIDGIN, Register.SOCIAL):
        intro = f"I be {who}, {business} virtual assistant" if who else f"I be {business} virtual assistant"
        return f"{intro}, no be person o. Person for the team fit take over anytime you want am. Wetin I fit help you with?"
    intro = f"I'm {who}, {business}'s virtual assistant" if who else f"I'm {business}'s virtual assistant"
    return f"{intro}, so I'm not a person. A member of the team can take over whenever you prefer. How can I help you?"
