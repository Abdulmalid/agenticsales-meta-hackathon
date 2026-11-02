import json
import unittest
from unittest import mock

from agentic_sales.channels import adapters
from agentic_sales.channels.adapters import ADAPTERS, ChannelError, ChannelUnavailable
from agentic_sales.core.types import Channel
from agentic_sales.models.base import ModelError
from agentic_sales.voice import media

BOT = ADAPTERS["telegram"]
SECRETS = {"bot_token": "123456789:AAH_testtokenABCDEFGHIJKLMNOPQRSTUVW", "webhook_secret": "s3cret-value"}


def update(**message):
    base = {"message_id": 5, "date": 1760000000, "chat": {"id": 777, "type": "private"}, "from": {"id": 777, "is_bot": False, "first_name": "Ada"}}
    return {"update_id": 42, "message": {**base, **message}}


class Parsing(unittest.TestCase):
    def test_a_text_message_becomes_a_telegram_customer_message(self):
        (m,) = BOT.parse(update(text="abeg how much be the iPhone 15?"), SECRETS)
        self.assertEqual((m.channel, m.user_id, m.conversation_id, m.text, m.message_id), (Channel.TELEGRAM, "777", "777", "abeg how much be the iPhone 15?", "42"))
        self.assertEqual(m.attachments, ())

    def test_the_first_tap_on_start_is_a_greeting_not_a_command(self):
        for text in ("/start", "/start ref123", "/START", "/start@my_shop_bot"):
            self.assertEqual(BOT.parse(update(text=text), SECRETS)[0].text, "Hello" if text.split()[0].lower().split("@")[0] == "/start" else text, text)

    def test_the_largest_photo_size_is_taken_and_the_caption_is_the_text(self):
        photo = [{"file_id": "small", "width": 90, "height": 90, "file_size": 1200}, {"file_id": "big", "width": 1280, "height": 960, "file_size": 150000},
                 {"file_id": "mid", "width": 320, "height": 240, "file_size": 20000}]
        (m,) = BOT.parse(update(photo=photo, caption="do you have this?"), SECRETS)
        self.assertEqual((m.text, [(a.kind, a.url, a.mime) for a in m.attachments]), ("do you have this?", [("image", "telegram-file:big", "image/jpeg")]))

    def test_a_voice_note_becomes_an_audio_attachment(self):
        (m,) = BOT.parse(update(voice={"file_id": "v1", "duration": 4, "mime_type": "audio/ogg"}), SECRETS)
        self.assertEqual((m.text, [(a.kind, a.url, a.mime) for a in m.attachments]), ("", [("audio", "telegram-file:v1", "audio/ogg")]))

    def test_only_private_chats_with_people_are_customer_messages(self):
        self.assertEqual(BOT.parse(update(text="hi", chat={"id": -100, "type": "supergroup"}), SECRETS), [])      # a bot in a group must not answer everyone
        self.assertEqual(BOT.parse(update(text="hi", **{"from": {"id": 9, "is_bot": True}}), SECRETS), [])
        self.assertEqual(BOT.parse(update(text="hi", chat={"type": "private"}), SECRETS), [])
        for other in ({"edited_message": {"text": "x"}}, {"channel_post": {"text": "x"}}, {"message": "not a dict"}, {}):
            self.assertEqual(BOT.parse(other, SECRETS), [])
        self.assertEqual(BOT.parse(update(sticker={"file_id": "s"}), SECRETS), [])                               # nothing we can read

    def test_there_is_no_get_handshake(self):
        self.assertEqual(BOT.handshake({"hub.mode": "subscribe"}, SECRETS)[0], 404)


class Verification(unittest.TestCase):
    def test_the_secret_header_must_match_exactly(self):
        self.assertTrue(BOT.verify_post({"x-telegram-bot-api-secret-token": "s3cret-value"}, b"{}", SECRETS))
        for headers in ({}, {"x-telegram-bot-api-secret-token": "s3cret-valu"}, {"x-telegram-bot-api-secret-token": "S3CRET-VALUE"}, {"x-telegram-bot-api-secret-token": ""}):
            self.assertFalse(BOT.verify_post(headers, b"{}", SECRETS))
        self.assertFalse(BOT.verify_post({"x-telegram-bot-api-secret-token": ""}, b"{}", {}))                    # no secret configured: nothing passes
        self.assertFalse(BOT.verify_post({"x-telegram-bot-api-secret-token": "anything"}, b"{}", {"webhook_secret": ""}))


class Sending(unittest.TestCase):
    def test_a_reply_goes_to_the_chat_through_the_bots_token(self):
        with mock.patch.object(adapters, "post_json", return_value={"ok": True}) as post:
            BOT.send("777", "x" * 5000, SECRETS)
        url, headers, body = post.call_args.args[:3]
        self.assertEqual(url, "https://api.telegram.org/bot123456789:AAH_testtokenABCDEFGHIJKLMNOPQRSTUVW/sendMessage")
        self.assertEqual((headers, body["chat_id"], len(body["text"])), ({}, "777", 4096))

    def test_failures_are_clear_and_never_carry_the_token(self):
        with self.assertRaises(ChannelUnavailable):
            BOT.send("777", "hi", {})
        with mock.patch.object(adapters, "post_json", side_effect=ModelError("Telegram HTTP 403: Forbidden: bot was blocked by the user")):
            with self.assertRaises(ChannelError) as cm:
                BOT.send("777", "hi", SECRETS)
        self.assertIn("blocked by the user", str(cm.exception))
        self.assertNotIn("AAH_test", str(cm.exception))


class Typing(unittest.TestCase):
    def test_the_typing_indicator_is_sent_to_the_chat_and_never_blocks(self):
        with mock.patch.object(adapters, "post_json", return_value={"ok": True}) as post:
            BOT.typing("777", SECRETS)
        self.assertEqual(post.call_args.args[0], "https://api.telegram.org/bot123456789:AAH_testtokenABCDEFGHIJKLMNOPQRSTUVW/sendChatAction")
        self.assertEqual(post.call_args.args[2], {"chat_id": "777", "action": "typing"})
        self.assertEqual(post.call_args.kwargs["retries"], 0)                                              # one quick try, never a delay
        with mock.patch.object(adapters, "post_json") as post:
            BOT.typing("777", {})                                                                          # no token: nothing happens
        post.assert_not_called()


class Downloads(unittest.TestCase):
    ATT = adapters.Attachment("audio", "telegram-file:FILE_1", "audio/ogg")

    def test_a_file_is_resolved_through_getfile_then_downloaded(self):
        calls = []

        def fake_get(url, token, timeout, limit=0):
            calls.append((url, token, limit))
            return json.dumps({"ok": True, "result": {"file_path": "voice/file_7.oga"}}).encode() if "getFile" in url else b"OGG-bytes"
        with mock.patch.object(media, "_get", fake_get):
            self.assertEqual(media.fetch_audio(self.ATT, "telegram", SECRETS), b"OGG-bytes")
        self.assertEqual(calls[0][0], "https://api.telegram.org/bot123456789:AAH_testtokenABCDEFGHIJKLMNOPQRSTUVW/getFile?file_id=FILE_1")
        self.assertEqual(calls[1][0], "https://api.telegram.org/file/bot123456789:AAH_testtokenABCDEFGHIJKLMNOPQRSTUVW/voice/file_7.oga")
        self.assertEqual((calls[0][1], calls[1][1], calls[1][2]), (None, None, media.MAX_AUDIO_BYTES))          # the token travels in the URL path, never a header

    def test_unsafe_or_missing_answers_from_telegram_are_refused(self):
        for answer in (b"not json", json.dumps({"ok": False}).encode(), json.dumps({"result": {"file_path": "../../etc/passwd"}}).encode(),
                       json.dumps({"result": {"file_path": "voice/a b.oga"}}).encode(), json.dumps({"result": {"file_path": 7}}).encode(), None):
            with mock.patch.object(media, "_get", return_value=answer):
                self.assertIsNone(media.fetch_audio(self.ATT, "telegram", SECRETS), answer)
        self.assertIsNone(media.fetch_audio(self.ATT, "telegram", {}))                                            # no token
        self.assertIsNone(media.fetch_audio(adapters.Attachment("audio", "telegram-file:", "audio/ogg"), "telegram", SECRETS))


if __name__ == "__main__":
    unittest.main()
