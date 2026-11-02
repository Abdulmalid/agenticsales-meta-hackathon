"""Download inbound audio attachments with the tenant's own channel credentials.

WhatsApp media arrives as an id (`whatsapp-media:<media_id>`): resolve it
through the Graph API to a short-lived URL, then download it. Instagram and
Messenger attachments already carry a fetchable payload URL. Every failure
returns None: the caller falls back to a polite "please type it" reply, so a
voice note can never crash a customer turn.
"""
from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import re
import socket
import urllib.parse
import urllib.request

from ..core.types import Attachment

GRAPH = "https://graph.facebook.com/v21.0"
TELEGRAM_API = "https://api.telegram.org"
_TELEGRAM_PATH = re.compile(r"^[A-Za-z0-9_./-]+$")

MAX_AUDIO_BYTES = 16 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):                  # a redirect is how a public address would point us at an internal one
        return None


def public_https(url: str) -> bool:
    """Only an https address that resolves to public internet addresses. The server must never fetch loopback, private-network or cloud
    metadata addresses (169.254.169.254) because a customer-supplied or forged link pointed at them."""
    try:
        parts = urllib.parse.urlparse(url)
        if parts.scheme != "https" or not parts.hostname:
            return False
        return all(ipaddress.ip_address(i[4][0]).is_global for i in socket.getaddrinfo(parts.hostname, parts.port or 443, type=socket.SOCK_STREAM))
    except (ValueError, OSError):
        return False


def _get(url: str, token: str | None, timeout: float, limit: int = MAX_AUDIO_BYTES, guarded: bool = False) -> bytes | None:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if guarded and not public_https(url):
        return None
    try:
        req = urllib.request.Request(url, method="GET", headers=headers)
        opener = urllib.request.build_opener(_NoRedirect) if guarded else urllib.request.build_opener()
        with opener.open(req, timeout=timeout) as resp:
            length = resp.headers.get("Content-Length")
            if length is not None and int(length) > limit:
                return None
            out = bytearray()
            while len(out) <= limit:
                chunk = resp.read(65536)
                if not chunk:
                    return bytes(out)
                out += chunk
            return None
    except Exception:  # noqa: BLE001 - any fetch problem means "fall back", never a 500
        return None


def fetch_media(att: Attachment, secrets: dict, kind: str, limit: int, timeout: float = 30.0) -> bytes | None:
    """Raw bytes for an attachment of the given kind (audio, image), or None when unavailable or too large. Besides channel media
    this takes a `data:` URL, which is how the web playground sends a photo."""
    if att.kind != kind:
        return None
    if att.url.startswith("data:"):
        try:
            data = base64.b64decode(att.url.split(",", 1)[1], validate=True)
        except (IndexError, binascii.Error, ValueError):
            return None
        return data if len(data) <= limit else None
    if att.url.startswith("telegram-file:"):
        token, file_id = secrets.get("bot_token"), att.url.split(":", 1)[1]
        if not token or not file_id:
            return None
        meta = _get(f"{TELEGRAM_API}/bot{token}/getFile?file_id={urllib.parse.quote(file_id, safe='')}", None, timeout)
        try:
            path = ((json.loads(meta.decode("utf-8")) if meta else {}).get("result") or {}).get("file_path")
        except ValueError:
            return None
        if not isinstance(path, str) or ".." in path or not _TELEGRAM_PATH.match(path):
            return None
        return _get(f"{TELEGRAM_API}/file/bot{token}/{path}", None, timeout, limit)
    if att.url.startswith("whatsapp-media:"):
        media_id = att.url.split(":", 1)[1]
        if not media_id or not secrets.get("access_token"):
            return None
        meta = _get(f"{GRAPH}/{media_id}", secrets["access_token"], timeout)
        if not meta:
            return None
        try:
            url = json.loads(meta.decode("utf-8")).get("url")
        except ValueError:
            return None
        if not url:
            return None
        return _get(url, secrets["access_token"], timeout, limit, guarded=True)
    if att.url.startswith("https://"):
        return _get(att.url, None, timeout, limit, guarded=True)
    return None


def fetch_audio(att: Attachment, channel: str, secrets: dict, timeout: float = 30.0) -> bytes | None:
    """Raw audio bytes for an audio attachment, or None when unavailable."""
    return fetch_media(att, secrets, "audio", MAX_AUDIO_BYTES, timeout)


def fetch_image(att: Attachment, secrets: dict, timeout: float = 30.0) -> bytes | None:
    """Raw image bytes for an image attachment, or None when unavailable."""
    return fetch_media(att, secrets, "image", MAX_IMAGE_BYTES, timeout)
