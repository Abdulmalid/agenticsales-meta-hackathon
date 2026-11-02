"""Muse Voice Transcribe via the Meta Model API (stdlib only, no SDK dependency).

Batch endpoint for finished recordings such as WhatsApp voice notes:
POST https://api.meta.ai/v1/asr/transcribe as multipart/form-data with the
audio file, authenticated with the same Bearer MODEL_API_KEY as Muse Spark.
"""
from __future__ import annotations

import json
import os
import uuid
import urllib.error
import urllib.request

from ..models.base import ModelError
from .convert import to_wav

URL = "https://api.meta.ai/v1/asr/transcribe"

DEFAULT_MODEL = "muse-voice-transcribe-1.0"


def _key(explicit: str | None) -> str:
    key = explicit or os.environ.get("META_MODEL_API_KEY") or os.environ.get("MODEL_API_KEY")
    if not key:
        raise ModelError("META_MODEL_API_KEY (or MODEL_API_KEY) is not set")
    return key



def _multipart(audio: bytes, filename: str, mime: str, model: str, encoding: str) -> tuple[bytes, str]:
    import json as _json

    boundary = f"----agentic{uuid.uuid4().hex}"
    request = _json.dumps({"model": model, "audioEncoding": encoding}).encode()
    parts: list[bytes] = []
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="request"\r\n'
                 "Content-Type: application/json\r\n\r\n".encode() + request + b"\r\n")
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="{filename}"\r\n'
                 f"Content-Type: {mime}\r\n\r\n".encode() + audio + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class MetaVoice:
    """Speech-to-text for customer voice notes. `transcribe` returns plain text."""

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None,
                 timeout: float = 90.0):
        self.name = model
        self._key = _key(api_key)
        self._timeout = timeout

    def transcribe(self, audio: bytes, mime: str | None = None, encoding: str | None = None) -> str:
        if not audio:
            raise ModelError("Meta transcribe: empty audio")
        wav = to_wav(audio)                      # the API takes only mono 16-bit PCM WAV at 16/24 kHz; `mime` and `encoding` are kept for callers
        body, content_type = _multipart(wav, "note.wav", "audio/wav", self.name, "WAV")
        req = urllib.request.Request(URL, data=body, method="POST",
                                     headers={"Authorization": f"Bearer {self._key}",
                                              "Content-Type": content_type})
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.load(e).get("error", {}).get("message", "")[:200]
            except Exception:
                pass
            raise ModelError(f"Meta transcribe HTTP {e.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ModelError(f"Meta transcribe unreachable: {type(e).__name__}") from None
        # never echo the audio or the key in errors
        for key in ("text", "transcript", "transcription"):
            text = data.get(key)
            if isinstance(text, str) and text.strip():
                return text.strip()
        segments = data.get("segments")
        if isinstance(segments, list):
            text = " ".join(s.get("text", "") for s in segments if isinstance(s, dict)).strip()
            if text:
                return text
        raise ModelError("Meta transcribe returned no text")
