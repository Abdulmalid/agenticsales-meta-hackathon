import os
import unittest
from unittest import mock

from agentic_sales.agents.sales import build_system
from agentic_sales.channels.adapters import InstagramDM, TelegramBot
from agentic_sales.config.business import BusinessConfig, Product, naira
from agentic_sales.language.analysis import detect_register, extract_signals, plan_style
from agentic_sales.server.runtime import human_pause
from agentic_sales.tools.builtin import default_registry

# Phrases the prompt must not push the agent to volunteer. ("virtual assistant" is deliberately NOT in this list: the prompt's honesty rule
# has to be able to say it, because a customer who sincerely asks whether they are talking to a bot gets a truthful answer. See security/identity.py.)
AI_TELLS = ("artificial intelligence", "as an AI", "as a bot",
            "language model", "I am a bot", "I am an AI", "AI assistant")


def cfg(**kw):
    d = dict(business_name="PhoneHub", industry="electronics",
             products=[Product("IP15", "iPhone 15", naira(800_000), naira(740_000), "Brand new")])
    d.update(kw)
    return BusinessConfig(**d)


def system(**kw):
    c = cfg(**kw)
    text = "abeg wetin be last price"
    reading = detect_register(text)
    return build_system(c, "whatsapp", reading, extract_signals(text),
                        plan_style(reading, [], c.brand_voice), "", default_registry(), {})


class Persona(unittest.TestCase):
    def test_no_ai_tells_in_prompt(self):
        low = system(agent_name="Adaeze").lower()
        for tell in AI_TELLS:
            self.assertNotIn(tell.lower(), low)
        self.assertIn("do not announce what you are", low)          # natural: no "I'm an AI" in greetings
        self.assertIn("never claim to be a human being", low)       # but never pretend either
        self.assertNotIn("answer as the rep would", low)            # and no instruction to dodge a sincere question

    def test_named_rep_persona(self):
        s = system(agent_name="Adaeze")
        self.assertIn("Adaeze", s)
        self.assertIn("sales rep", s)

    def test_unnamed_business_still_has_rep_persona(self):
        s = system()
        self.assertIn("sales rep on the PhoneHub team", s)

    def test_chat_text_rules_present(self):
        s = system(agent_name="Adaeze")
        self.assertIn('exception to "no lists"', s)                       # a list only when there are three or more counts or options
        self.assertIn("no asterisks or bold markup", s)


class TypingIndicators(unittest.TestCase):
    def test_instagram_login_typing(self):
        with mock.patch("agentic_sales.channels.adapters.post_json") as post:
            InstagramDM().typing("cust1", {"access_token": "tok", "login": "instagram", "ig_user_id": "99"})
        url, headers, body = post.call_args[0]
        self.assertIn("graph.instagram.com", url)
        self.assertIn("/99/messages", url)
        self.assertEqual(body["sender_action"], "typing_on")

    def test_page_typing(self):
        with mock.patch("agentic_sales.channels.adapters.post_json") as post:
            InstagramDM().typing("cust1", {"access_token": "tok", "page_id": "7"})
        url, headers, body = post.call_args[0]
        self.assertIn("graph.facebook.com", url)
        self.assertEqual(body["sender_action"], "typing_on")

    def test_telegram_typing(self):
        with mock.patch("agentic_sales.channels.adapters.post_json") as post:
            TelegramBot().typing("123", {"bot_token": "tok"})
        url, headers, body = post.call_args[0]
        self.assertIn("api.telegram.org", url)
        self.assertTrue(url.endswith("/sendChatAction"))
        self.assertEqual(body, {"chat_id": "123", "action": "typing"})

    def test_typing_never_raises(self):
        with mock.patch("agentic_sales.channels.adapters.post_json", side_effect=RuntimeError("net down")):
            TelegramBot().typing("123", {"bot_token": "tok"})
            InstagramDM().typing("c", {"access_token": "t"})


class HumanPause(unittest.TestCase):
    def test_off_by_default(self):
        os.environ.pop("HUMAN_REPLY_DELAY", None)
        with mock.patch("agentic_sales.server.runtime.time.sleep") as sleep:
            human_pause("hello there, the price is 800k")
        sleep.assert_not_called()

    def test_scaled_pause_when_enabled(self):
        with mock.patch.dict(os.environ, {"HUMAN_REPLY_DELAY": "1"}):
            with mock.patch("agentic_sales.server.runtime.time.sleep") as sleep:
                human_pause("x" * 250)
        (secs,), _ = sleep.call_args
        self.assertAlmostEqual(secs, min(0.8 + 250 / 25.0, 7.0))


if __name__ == "__main__":
    unittest.main()
