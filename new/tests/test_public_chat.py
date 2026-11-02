import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from agentic_sales.config.business import naira
from agentic_sales.language.analyzer import Analyzer
from agentic_sales.models.base import ModelResponse, ModelRouter, TaskKind
from agentic_sales.server.app import create_app
from agentic_sales.server.auth import AuthStore
from agentic_sales.server.runtime import Runtimes
from agentic_sales.vision.reader import PhotoReading

BIZ = {"business_name": "PhoneHub <Lagos>", "industry": "electronics retail", "brand_voice": "warm and direct", "agent_name": "Ezenna",
       "delivery_areas": ["Lagos"], "payment_methods": ["paystack"],
       "products": [{"sku": "IP15", "name": "iPhone 15", "price_kobo": naira(800_000), "floor_price_kobo": naira(740_000),
                     "description": "Brand new", "in_stock": True}],
       "approvals": {"max_discount_pct_auto": 5, "max_discount_pct_hard": 10}}
SESSION = "w1a2b3c4d5e6f7g8"
JPEG = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 60).decode()
CLIP = base64.b64encode(b"\x1a\x45\xdf\xa3" + b"v" * 2000).decode()


class Scripted:
    name = "scripted"

    def __init__(self):
        self.outs, self.requests = [], []

    def push(self, reply):
        self.outs.append(json.dumps({"reply": reply, "actions": []}))

    def complete(self, req):
        self.requests.append(req)
        return ModelResponse(self.outs.pop(0), self.name)


class FakeVoice:
    name = "fake-voice"

    def transcribe(self, audio, mime=None):
        return "abeg how much be the iPhone 15"


class FakeVision:
    def read(self, image, products, references=None, colours=None):
        return PhotoReading("product", "IP15", 0.9, "A phone.", "iPhone 15")


class PublicChat(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.model = Scripted()
        self.auth = AuthStore(self.root)
        self.key_a = self.auth.create_tenant("shop-a", BIZ)
        self.auth.create_tenant("shop-b", {**BIZ, "business_name": "NoSite"})
        site = self.root / "tenants" / "shop-a" / "site"
        site.mkdir(parents=True)
        (site / "index.html").write_text("<p>hi</p>", encoding="utf-8")
        router = ModelRouter(text={TaskKind.CONVERSATION: self.model})
        self.app = create_app(self.root, Runtimes(self.root, None, router, Analyzer(None)), self.auth)
        self.c = TestClient(self.app)
        self.rt = self.app.state.runtimes.get("shop-a")

    def chat(self, tenant="shop-a", **body):
        return self.c.post(f"/public/{tenant}/chat", json={"session": SESSION, **body})

    # ---------------------------------------------------------------- the page
    def test_the_page_is_public_escapes_the_business_and_says_it_is_an_ai(self):
        r = self.c.get("/chat/shop-a")
        self.assertEqual(r.status_code, 200)
        self.assertIn("PhoneHub &lt;Lagos&gt;", r.text)
        self.assertNotIn("PhoneHub <Lagos>", r.text)
        self.assertIn("a virtual sales assistant", r.text)                  # honest that it is automated, without the loaded label
        self.assertIn("Ezenna", r.text)
        self.assertIn("connect-src 'self'", r.headers["content-security-policy"])
        self.assertIn("default-src 'none'", r.headers["content-security-policy"])
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        self.assertIn("const TENANT = \"shop-a\";", r.text)
        self.assertIn('rel="icon"', r.text)                              # no stray favicon request
        self.assertNotIn("innerHTML", r.text)                             # replies are written as text, never as markup

    def test_only_a_business_with_a_published_page_has_a_chat_and_unknown_ones_look_the_same(self):
        for tenant in ("shop-b", "nope", "SHOP-A", "x" * 80):
            self.assertEqual(self.c.get(f"/chat/{tenant}").status_code, 404, tenant)
            self.assertEqual(self.chat(tenant, text="hi").status_code, 404, tenant)
        self.auth.set_disabled("shop-a", True)
        self.assertEqual(self.c.get("/chat/shop-a").status_code, 404)
        self.assertEqual(self.chat(text="hi").status_code, 404)

    def test_building_the_landing_page_adds_the_chat_button_and_the_chat_then_works(self):
        made = self.c.post("/v1/landing", headers={"Authorization": f"Bearer {self.key_a}"}, json={"whatsapp": "2348012345678"})
        self.assertEqual(made.status_code, 200, made.text)
        page = self.c.get("/sites/shop-a").text
        self.assertIn('href="/chat/shop-a"', page)
        self.assertIn("Chat with us here", page)
        self.assertEqual(self.c.get("/chat/shop-a").status_code, 200)

    def test_the_routes_stay_out_of_the_api_schema(self):
        paths = self.c.get("/openapi.json").json()["paths"]
        self.assertFalse([p for p in paths if p.startswith("/chat") or p.endswith("/chat") and p.startswith("/public")])

    # ---------------------------------------------------------------- messages
    def test_a_text_message_gets_the_agents_reply_and_nothing_internal(self):
        self.model.push("The iPhone 15 is ₦800,000.")
        r = self.chat(text="How much is the iPhone 15?")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"reply": "The iPhone 15 is ₦800,000.", "escalated": False, "images": []})   # no trace, lead or fraud details

    def test_visitors_are_kept_apart_by_their_session(self):
        self.model.push("first")
        self.model.push("second")
        self.chat(text="hello")
        self.c.post("/public/shop-a/chat", json={"session": "wZZZZZZZZZZZZ1", "text": "hello"})
        leads = self.rt.orchestrator.leads
        keys = {row[0] for row in self.rt.memory.con.execute("SELECT customer_key FROM leads")}
        self.assertEqual(keys, {f"web:{SESSION}", "web:wZZZZZZZZZZZZ1"})

    def test_a_photo_is_read_and_a_voice_note_is_transcribed(self):
        self.rt.vision, self.rt.voice = FakeVision(), FakeVoice()
        self.model.push("Yes, the iPhone 15 is in stock.")
        photo = self.chat(text="do you have this?", image=JPEG)
        self.assertEqual((photo.status_code, photo.json()["reply"]), (200, "Yes, the iPhone 15 is in stock."))
        self.assertIn('catalogue item "iPhone 15"', self.model.requests[-1].messages[-1].content)
        self.model.push("The iPhone 15 is ₦800,000.")
        voice = self.chat(audio=CLIP, audio_mime="audio/webm;codecs=opus")
        self.assertEqual((voice.status_code, voice.json()["reply"]), (200, "The iPhone 15 is ₦800,000."))
        self.assertIn("abeg how much be the iPhone 15", self.model.requests[-1].messages[-1].content)

    def test_bad_input_is_refused_before_any_model_call(self):
        bad = [{}, {"text": "   "}, {"text": "hi", "image": "not base64 !!"}, {"image": base64.b64encode(b"plain text not an image" * 4).decode()},
               {"audio": "@@@"}, {"audio": base64.b64encode(b"tiny").decode()}, {"audio": CLIP, "text": "and words"},
               {"audio": CLIP, "audio_mime": "text/html"}, {"text": "x" * 1001}]
        for body in bad:
            self.assertEqual(self.chat(**body).status_code, 422, body)
        for session in ("short", "has spaces in it!!", "x" * 41):
            self.assertEqual(self.c.post("/public/shop-a/chat", json={"session": session, "text": "hi"}).status_code, 422, session)
        self.assertEqual(self.model.requests, [])

    # ---------------------------------------------------------------- abuse limits
    def test_one_visitor_cannot_hammer_the_agent(self):
        for _ in range(12):
            self.model.push("ok")
            self.assertEqual(self.chat(text="hello").status_code, 200)
        self.assertEqual(self.chat(text="hello").status_code, 429)

    def test_a_business_has_a_ceiling_across_all_visitors(self):
        clock = mock.patch("agentic_sales.server.app.time.monotonic", return_value=1000.0)     # frozen, so a slow machine cannot slide the one-minute window
        clock.start()
        self.addCleanup(clock.stop)
        for i in range(100):
            self.model.push("ok")
            visitor = TestClient(self.app, client=(f"10.0.{i // 250}.{i % 250}", 40000))                 # a different address each time
            r = visitor.post("/public/shop-a/chat", json={"session": f"w{i:015d}", "text": "hi"})
            self.assertEqual(r.status_code, 200, i)
        self.model.push("ok")
        late = TestClient(self.app, client=("10.9.9.9", 40000))
        self.assertEqual(late.post("/public/shop-a/chat", json={"session": "wsomeoneelse12345", "text": "hi"}).status_code, 429)


if __name__ == "__main__":
    unittest.main()
