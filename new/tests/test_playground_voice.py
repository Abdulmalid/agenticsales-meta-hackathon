"""The Playground can send a voice note: it is transcribed, the reply says what was heard, and the Under the hood trace records the voice step."""
import base64
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
    from agentic_sales.server.app import create_app
    from agentic_sales.server.auth import AuthStore
    from agentic_sales.server.runtime import Runtimes
    HAVE_API = True
except ImportError:
    HAVE_API = False

from agentic_sales.language.analyzer import Analyzer
from agentic_sales.models.base import ModelRouter, TaskKind
from tests.test_public_chat import BIZ, CLIP, JPEG, Scripted


class FakeVoice:
    name = "muse-voice-transcribe-1.0"

    def transcribe(self, audio, mime=None):
        return "abeg how much be the iPhone 15"


@unittest.skipUnless(HAVE_API, "needs fastapi + httpx (use the project .venv)")
class PlaygroundVoice(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.model = Scripted()
        self.auth = AuthStore(self.root)
        self.key = self.auth.create_tenant("shop-a", BIZ)
        self.c = TestClient(create_app(self.root, Runtimes(self.root, None, ModelRouter(text={TaskKind.CONVERSATION: self.model}), Analyzer(None)), self.auth))
        self.c.app.state.runtimes.get("shop-a").voice = FakeVoice()
        self.H = {"Authorization": f"Bearer {self.key}"}

    def chat(self, **body):
        return self.c.post("/v1/chat", headers=self.H, json={"user_id": "playground-abc", **body})

    def test_a_voice_note_is_transcribed_answered_and_shows_what_was_heard(self):
        self.model.push("The iPhone 15 is ₦800,000.")
        r = self.chat(audio=CLIP, audio_mime="audio/webm;codecs=opus")
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual((d["reply"], d["heard"]), ("The iPhone 15 is ₦800,000.", "abeg how much be the iPhone 15"))
        self.assertIn("abeg how much be the iPhone 15", self.model.requests[-1].messages[-1].content)

    def test_the_voice_step_is_in_the_under_the_hood_trace_with_the_model_name(self):
        self.model.push("Yes.")
        trace = self.chat(audio=CLIP, audio_mime="audio/webm").json()["trace"]
        events = self.c.get(f"/v1/audit/{trace}", headers=self.H).json()
        voice = next(e for e in events if e.get("kind") == "voice_transcribed")
        self.assertEqual((voice["model"], voice["chars"]), ("muse-voice-transcribe-1.0", len("abeg how much be the iPhone 15")))
        self.assertIsNotNone(voice.get("ms"))

    def test_text_replies_carry_no_heard_field_and_bad_voice_input_is_refused_before_any_model_call(self):
        self.model.push("Hello.")
        self.assertIsNone(self.chat(text="hi").json()["heard"])
        for body in ({"audio": "@@@"}, {"audio": base64.b64encode(b"tiny").decode()}, {"audio": CLIP, "text": "and words"}, {"audio": CLIP, "image": JPEG},
                     {"audio": CLIP, "audio_mime": "text/html"}):
            self.assertEqual(self.chat(**body).status_code, 422, body)
        self.assertEqual(len(self.model.requests), 1)


if __name__ == "__main__":
    unittest.main()
