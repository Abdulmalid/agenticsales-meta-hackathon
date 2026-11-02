import io
import json
import wave
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agentic_sales.agents.orchestrator import Orchestrator
from agentic_sales.channels.dispatch import SecretStore
from agentic_sales.config.business import BusinessConfig, Product, naira
from agentic_sales.core.types import Attachment, Channel, InboundMessage, TenantContext
from agentic_sales.language.analyzer import Analyzer
from agentic_sales.models.base import ModelError, ModelResponse, ModelRouter, TaskKind
from agentic_sales.server.runtime import TenantRuntime, VOICE_FALLBACK
from agentic_sales.tools.builtin import default_registry
from agentic_sales.voice import convert
from agentic_sales.voice.transcribe import MetaVoice

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)


def wav_bytes(rate=16000, channels=1, width=2, frames=800) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x00" * frames * channels * width)
    return buf.getvalue()


OK_WAV = wav_bytes()


def cfg() -> BusinessConfig:
    return BusinessConfig("PhoneHub", "electronics", products=[
        Product("IP15", "iPhone 15", naira(800_000), naira(740_000), "Brand new, sealed")])


class Scripted:
    name = "scripted"

    def __init__(self):
        self.outs: list[str] = []
        self.requests = []

    def push(self, obj):
        self.outs.append(json.dumps(obj))

    def complete(self, req):
        self.requests.append(req)
        return ModelResponse(self.outs.pop(0), self.name)


class FakeVoice:
    name = "fake-voice"

    def __init__(self, transcript="Abeg how much be iPhone 15?"):
        self.transcript = transcript
        self.calls = []

    def transcribe(self, audio, mime=None):
        self.calls.append((audio, mime))
        return self.transcript


def runtime(scripted, voice):
    root = Path(tempfile.mkdtemp())
    ctx = TenantContext("shop-a")
    router = ModelRouter(text={TaskKind.CONVERSATION: scripted, TaskKind.REASONING: scripted})
    orch = Orchestrator(ctx, cfg(), root, router, default_registry(), None, Analyzer(None), None)
    return TenantRuntime(ctx, root, orch, None, SecretStore(ctx, root), voice=voice)


def voice_note(text=""):
    return InboundMessage(Channel.WEB, "u1", "c1", text, NOW,
                          (Attachment("audio", "whatsapp-media:123", "audio/ogg"),), "m1")


class VoiceNotes(unittest.TestCase):
    def test_transcript_flows_into_the_sales_turn(self):
        model, voice = Scripted(), FakeVoice()
        model.push({"reply": "The iPhone 15 is ₦800,000.", "actions": []})
        rt = runtime(model, voice)
        with mock.patch("agentic_sales.server.runtime.fetch_audio", return_value=b"ogg-bytes") as fetch:
            res = rt.handle_and_reply(voice_note())
        fetch.assert_called_once()
        self.assertEqual(voice.calls, [(b"ogg-bytes", "audio/ogg")])
        self.assertEqual(len(model.requests), 1)  # one plan call, no tool follow-up
        self.assertIn("Abeg how much be iPhone 15?", model.requests[0].messages[-1].content)
        self.assertEqual(res.reply, "The iPhone 15 is ₦800,000.")

    def test_the_agent_is_told_a_transcript_may_contain_mistakes(self):
        model, voice = Scripted(), FakeVoice("Which phone unastickets")
        model.push({"reply": "Sorry, I didn't catch that. Could you type it?", "actions": []})
        rt = runtime(model, voice)
        with mock.patch("agentic_sales.server.runtime.fetch_audio", return_value=b"ogg-bytes"):
            rt.handle_and_reply(voice_note())
        said = model.requests[0].messages[-1].content
        self.assertIn("Which phone unastickets", said)
        self.assertIn("transcribed automatically", said)
        self.assertIn("ask the customer to repeat it", said)

    def test_a_voice_turn_is_one_trace_and_the_transcription_is_timed(self):
        model, voice = Scripted(), FakeVoice()
        model.push({"reply": "The iPhone 15 is ₦800,000.", "actions": []})
        rt = runtime(model, voice)
        with mock.patch("agentic_sales.server.runtime.fetch_audio", return_value=b"ogg-bytes"):
            res = rt.handle_and_reply(voice_note())
        events = rt.orchestrator.audit.trace(res.trace)
        heard = next(e for e in events if e["kind"] == "voice_transcribed")
        self.assertEqual((heard["model"], isinstance(heard["ms"], int)), ("fake-voice", True))
        self.assertIn("reply_sent", [e["kind"] for e in events])

    def test_unheard_voice_note_falls_back_without_a_model_call(self):
        model = Scripted()
        rt = runtime(model, FakeVoice())
        with mock.patch("agentic_sales.server.runtime.fetch_audio", return_value=None):
            res = rt.handle_and_reply(voice_note())
        self.assertEqual(res.reply, VOICE_FALLBACK)
        self.assertIn("voice_note_unheard", res.flags)
        self.assertEqual(model.requests, [])

    def test_failed_transcription_falls_back_without_a_model_call(self):
        model = Scripted()
        rt = runtime(model, FakeVoice())

        def boom(audio, mime=None):
            raise ModelError("Meta transcribe HTTP 400: bad audio")

        rt.voice.transcribe = boom
        with mock.patch("agentic_sales.server.runtime.fetch_audio", return_value=b"ogg-bytes"):
            res = rt.handle_and_reply(voice_note())
        self.assertEqual(res.reply, VOICE_FALLBACK)
        self.assertEqual(model.requests, [])

    def test_typed_text_with_audio_attachment_skips_transcription(self):
        model, voice = Scripted(), FakeVoice()
        model.push({"reply": "ok", "actions": []})
        rt = runtime(model, voice)
        with mock.patch("agentic_sales.server.runtime.fetch_audio") as fetch:
            rt.handle_and_reply(voice_note("how much?"))
        fetch.assert_not_called()
        self.assertEqual(voice.calls, [])

    def test_no_voice_configured_typed_fallback(self):
        model = Scripted()
        rt = runtime(model, None)
        with mock.patch("agentic_sales.server.runtime.fetch_audio") as fetch:
            res = rt.handle_and_reply(voice_note())
        fetch.assert_not_called()
        self.assertEqual(res.reply, VOICE_FALLBACK)


class FakeResp:
    def __init__(self, payload: bytes):
        self._buf = io.BytesIO(payload)

    def __enter__(self):
        return self._buf

    def __exit__(self, *exc):
        return False


class MetaVoiceParsing(unittest.TestCase):
    def v(self):
        return MetaVoice(api_key="dummy")

    def test_reads_text_field(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResp(b'{"text":"  hello  "}')):
            self.assertEqual(self.v().transcribe(OK_WAV), "hello")

    def test_reads_segments_fallback(self):
        body = json.dumps({"segments": [{"text": "how far"}, {"text": "na how much"}]}).encode()
        with mock.patch("urllib.request.urlopen", return_value=FakeResp(body)):
            self.assertEqual(self.v().transcribe(OK_WAV), "how far na how much")

    def test_empty_transcript_raises_instead_of_returning_blank(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResp(b'{"text":" "}')):
            with self.assertRaises(ModelError):
                self.v().transcribe(OK_WAV)

    def test_http_error_is_key_safe(self):
        err = urllib.error.HTTPError("https://api.meta.ai/v1/asr/transcribe", 400, "bad", {},
                                     io.BytesIO(b'{"error":{"message":"bad audio"}}'))
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(ModelError) as cm:
                self.v().transcribe(OK_WAV)
        self.assertNotIn("dummy", str(cm.exception))


class WavConversion(unittest.TestCase):
    def test_a_wav_in_the_accepted_format_passes_through_without_ffmpeg(self):
        for rate in (16000, 24000):
            wav = wav_bytes(rate=rate)
            with mock.patch.object(convert, "ffmpeg_path", return_value=None):
                self.assertEqual(convert.to_wav(wav), wav)

    def test_only_mono_16_bit_pcm_at_16_or_24_khz_counts_as_accepted(self):
        self.assertTrue(convert.is_accepted_wav(OK_WAV))
        for bad in (wav_bytes(rate=22050), wav_bytes(rate=8000), wav_bytes(channels=2), wav_bytes(width=1), b"OggS" + b"\x00" * 40, b""):
            self.assertFalse(convert.is_accepted_wav(bad))

    def test_other_audio_is_converted_with_ffmpeg_to_a_file_not_a_pipe(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            open(cmd[-1], "wb").write(OK_WAV)                                  # ffmpeg writes the last argument
            return mock.Mock(returncode=0)
        with mock.patch.object(convert, "ffmpeg_path", return_value="/usr/bin/ffmpeg"), mock.patch.object(convert.subprocess, "run", fake_run):
            self.assertEqual(convert.to_wav(b"OggS-opus-voice-note"), OK_WAV)
        cmd = calls[0]
        self.assertEqual((cmd[0], cmd[cmd.index("-ar") + 1], cmd[cmd.index("-ac") + 1], cmd[cmd.index("-sample_fmt") + 1]), ("/usr/bin/ffmpeg", "16000", "1", "s16"))
        self.assertTrue(cmd[-1].endswith("out.wav") and "pipe:" not in " ".join(cmd))

    def test_conversion_failures_are_clear_and_never_return_unusable_audio(self):
        with self.assertRaisesRegex(ModelError, "empty audio"):
            convert.to_wav(b"")
        with self.assertRaisesRegex(ModelError, "too large"):
            convert.to_wav(b"x" * (convert.MAX_BYTES + 1))
        with mock.patch.object(convert, "ffmpeg_path", return_value=None), self.assertRaisesRegex(ModelError, "ffmpeg"):
            convert.to_wav(b"OggS-opus")
        with mock.patch.object(convert, "ffmpeg_path", return_value="ffmpeg"):
            with mock.patch.object(convert.subprocess, "run", return_value=mock.Mock(returncode=1)), self.assertRaisesRegex(ModelError, "could not convert"):
                convert.to_wav(b"OggS-opus")
            with mock.patch.object(convert.subprocess, "run", side_effect=convert.subprocess.TimeoutExpired("ffmpeg", 30)), self.assertRaisesRegex(ModelError, "too long"):
                convert.to_wav(b"OggS-opus")
            with mock.patch.object(convert.subprocess, "run", side_effect=FileNotFoundError()), self.assertRaisesRegex(ModelError, "could not be started"):
                convert.to_wav(b"OggS-opus")

    def test_the_transcriber_always_uploads_a_wav_named_as_such(self):
        sent = {}

        def fake_urlopen(req, timeout=0):
            sent["body"] = req.data
            return FakeResp(b'{"text":"ok"}')

        def fake_run(cmd, **kw):
            open(cmd[-1], "wb").write(OK_WAV)
            return mock.Mock(returncode=0)
        with mock.patch("urllib.request.urlopen", fake_urlopen), mock.patch.object(convert, "ffmpeg_path", return_value="ffmpeg"), \
                mock.patch.object(convert.subprocess, "run", fake_run):
            self.assertEqual(MetaVoice(api_key="dummy").transcribe(b"OggS-opus", "audio/ogg; codecs=opus"), "ok")
        body = sent["body"]
        self.assertIn(b'"audioEncoding": "WAV"', body)
        self.assertIn(b'filename="note.wav"', body)
        self.assertIn(b"Content-Type: audio/wav", body)
        self.assertIn(OK_WAV, body)
        self.assertNotIn(b"OggS-opus", body)


if __name__ == "__main__":
    unittest.main()
