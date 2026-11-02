"""Meta Model API providers: Muse Spark text and Muse Image generation.

OpenAI-compatible endpoint (no SDK dependency, same stdlib style as the
Gemini/Anthropic providers). Docs: create a key at dev.meta.ai, point an
OpenAI-compatible client at https://api.meta.ai/v1, set the model id.

Text: POST {BASE}/chat/completions with {model, messages, temperature,
max_tokens, response_format} and Bearer MODEL_API_KEY auth.
Image: POST {BASE}/images/generations with {model, prompt} (muse-image-1.0).
"""
from __future__ import annotations

import base64
import os
import urllib.request

from .base import ModelError, ModelRequest, ModelResponse
from .http import post_json

BASE = "https://api.meta.ai/v1"
BASETEN_BASE = "https://inference.baseten.co/v1"      # Baseten serves Meta's open-weight models behind an OpenAI-compatible API
OPEN_WEIGHTS_MODEL = "meta-models/muse-spark-open-1026"   # the hackathon build of Muse Spark Open (the docs' plain name is not the one to use)

DEFAULT_REASONING_MODEL = "muse-spark-1.3"
DEFAULT_CONVERSATION_MODEL = "muse-spark-1.3"
DEFAULT_IMAGE_MODEL = "muse-image-1.0"

# Muse Spark reasons silently before it answers, and those tokens count against max_tokens (measured on the live API: a one-line
# greeting used 454 reasoning tokens by default, 197 at "low", 39 at "minimal"). `reasoning_effort` turns it down, and the headroom
# below is added to the caller's max_tokens so the visible answer is never squeezed out and returned empty.
REASONING_HEADROOM = {"minimal": 600, "low": 1800, "medium": 4000, "high": 8000}
RETRY_EXTRA_TOKENS = 3000      # when a long or tricky input still uses up the whole budget, one quick retry with minimal reasoning and this much more room


def _key(explicit: str | None) -> str:
    key = explicit or os.environ.get("META_MODEL_API_KEY") or os.environ.get("MODEL_API_KEY")
    if not key:
        raise ModelError("META_MODEL_API_KEY (or MODEL_API_KEY) is not set")
    return key


class MetaText:
    """Muse Spark via Meta Model API chat completions."""

    def __init__(self, model: str = DEFAULT_CONVERSATION_MODEL, api_key: str | None = None,
                 timeout: float = 60.0, retries: int = 2, effort: str | None = None):
        self.name = model
        self._key = _key(api_key)
        self._timeout = timeout
        self.effort = effort or os.environ.get("META_REASONING_EFFORT", "low")
        if self.effort not in REASONING_HEADROOM:
            raise ModelError(f"reasoning effort must be one of {', '.join(REASONING_HEADROOM)}, not {self.effort!r}")
        # Same fail-fast posture as GeminiText: a customer is waiting, so 2
        # retries then raise so the orchestrator can fall back / escalate.
        self._retries = retries
        self._base = BASE
        self._sends_effort = True

    def _post(self, body: dict) -> dict:
        return post_json(f"{self._base}/chat/completions", {"Authorization": f"Bearer {self._key}"}, body, timeout=self._timeout, retries=self._retries,
                         provider="Meta Model API")

    def complete(self, req: ModelRequest) -> ModelResponse:
        messages = [{"role": "system", "content": req.system}] if req.system else []
        messages += [{"role": m.role, "content": m.content} for m in req.messages]
        if req.images:                                      # OpenAI-style content parts: the text, then each picture as a data URI
            last = max(i for i, m in enumerate(messages) if m["role"] == "user")
            messages[last] = {"role": "user", "content": [{"type": "text", "text": messages[last]["content"]}] + [
                {"type": "image_url", "image_url": {"url": f"data:{img.mime};base64,{base64.b64encode(img.data).decode()}"}} for img in req.images]}
        body: dict = {"model": self.name, "messages": messages, "temperature": req.temperature,
                      "max_tokens": req.max_tokens + REASONING_HEADROOM[self.effort]}
        if self._sends_effort:
            body["reasoning_effort"] = self.effort
        if req.json_mode:
            body["response_format"] = {"type": "json_object"}
        data = self._post(body)
        choices = data.get("choices") or []
        if choices and not ((choices[0].get("message") or {}).get("content") or "") and choices[0].get("finish_reason") == "length":
            # The silent reasoning used the whole budget (seen on long customer messages). One retry, thinking as little as possible and with more room,
            # beats handing the customer to a person for an answer the model could have given.
            data = self._post({**body, **({"reasoning_effort": "minimal"} if self._sends_effort else {}), "max_tokens": body["max_tokens"] + RETRY_EXTRA_TOKENS})
            choices = data.get("choices") or []
        if not choices:
            raise ModelError("Meta Model API returned no output (no choices)")
        text = ((choices[0].get("message") or {}).get("content") or "")
        if not text and choices[0].get("finish_reason") not in ("stop", None):
            # Spark is a reasoning model: a small max_tokens budget can be
            # exhausted by reasoning tokens, leaving content null. Surface it
            # so the caller falls back instead of sending an empty reply.
            raise ModelError(
                f"Meta Model API returned no content (finish_reason={choices[0].get('finish_reason')})")
        usage = data.get("usage", {})
        return ModelResponse(text, self.name, usage.get("prompt_tokens", 0),
                             usage.get("completion_tokens", 0))


class OpenWeightsText(MetaText):
    """Muse Spark Open (Meta's open-weight model) served by Baseten. Same chat shape as Muse Spark on the Meta Model API, so it drops in
    wherever MetaText is used. Needs BASETEN_API_KEY; BASETEN_BASE_URL overrides the endpoint. `reasoning_effort` is not sent: that field is
    a Meta Model API setting and an open-weight server may reject it."""

    def __init__(self, model: str = OPEN_WEIGHTS_MODEL, api_key: str | None = None, base: str | None = None,
                 timeout: float = 90.0, retries: int = 2):
        key = api_key or os.environ.get("BASETEN_API_KEY")
        if not key:
            raise ModelError("BASETEN_API_KEY is not set")
        super().__init__(model, key, timeout, retries, effort="low")
        self._base = (base or os.environ.get("BASETEN_BASE_URL") or BASETEN_BASE).rstrip("/")
        self._sends_effort = False


class MetaImage:
    """Muse Image via Meta Model API: text -> PNG/JPEG bytes."""

    def __init__(self, model: str = DEFAULT_IMAGE_MODEL, api_key: str | None = None,
                 timeout: float = 120.0):
        self.name = model
        self._key = _key(api_key)
        self._timeout = timeout

    def generate(self, prompt: str, **options: object) -> bytes:
        body: dict = {"model": self.name, "prompt": prompt}
        if options.get("size"):
            body["size"] = options["size"]
        data = post_json(f"{BASE}/images/generations", {"Authorization": f"Bearer {self._key}"},
                         body, timeout=self._timeout, provider="Meta image")
        items = data.get("data") or []
        if not items:
            raise ModelError("Meta image: no image in response (prompt may have been blocked)")
        first = items[0]
        for key in ("b64_json", "base64", "image"):
            if first.get(key):
                return base64.b64decode(first[key])
        url = first.get("url")
        if not url:
            raise ModelError("Meta image: no image in response (prompt may have been blocked)")
        http = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(http, timeout=self._timeout) as resp:
                return resp.read()
        except Exception as e:  # noqa: BLE001 - network fetch of a provider URL
            raise ModelError(f"Meta image download failed: {type(e).__name__}") from None
