"""Public comments on the Page's posts: answered in public, briefly, and never with a link or a number anyone could misuse."""
import json
import unittest
from unittest import mock

from agentic_sales.channels.adapters import ADAPTERS, PUBLIC_FALLBACK, ChannelError, public_comments, public_safe
from tests.test_vision import FakeVision, Scripted, plan, runtime
from agentic_sales.vision.reader import PhotoReading

PAGE = "1405021206032775"


def feed(text="how much is the iPhone 15?", who="555", cid="p_1", post="1405_9", parent=None, verb="add", item="comment"):
    v = {"item": item, "verb": verb, "comment_id": cid, "post_id": post, "parent_id": parent or post, "message": text,
         "from": {"id": who, "name": "Ada"}, "created_time": 1793300000}
    return {"entry": [{"id": PAGE, "changes": [{"field": "feed", "value": v}]}]}


class WhichCommentsAreAnswered(unittest.TestCase):
    def test_a_new_top_level_comment_by_someone_else(self):
        (c,) = public_comments(feed())
        self.assertEqual((c["comment_id"], c["user_id"], c["text"]), ("p_1", "555", "how much is the iPhone 15?"))

    def test_the_pages_own_comments_replies_in_a_thread_and_other_events_are_skipped(self):
        self.assertEqual(public_comments(feed(who=PAGE)), [])                       # our own reply must not start a loop
        self.assertEqual(public_comments(feed(parent="1405_9_77")), [])             # customers talking to each other
        self.assertEqual(public_comments(feed(verb="edited")), [])
        self.assertEqual(public_comments(feed(item="reaction")), [])
        self.assertEqual(public_comments(feed(text="  ")), [])


class WhatIsSafeToSayInPublic(unittest.TestCase):
    def test_short_friendly_text_passes_and_is_bounded(self):
        self.assertEqual(public_safe("Yes, we have it. Message us to order!"), "Yes, we have it. Message us to order!")
        self.assertLessEqual(len(public_safe("word " * 200)), 300)
        self.assertIn("₦800,000", public_safe("The iPhone 15 is ₦800,000, message us to order."))

    def test_links_and_long_numbers_never_reach_a_public_thread(self):
        for risky in ("Pay here https://pay.example/abc", "Send to 0123456789 GTBank", "call 0803 123 4567", "www.shop.ng/x"):
            self.assertEqual(public_safe(risky), PUBLIC_FALLBACK, risky)


class AnsweringInPublic(unittest.TestCase):
    def test_the_rep_replies_under_the_comment_and_the_turn_is_recorded(self):
        rt = runtime(Scripted(plan("Yes, we have the iPhone 15! Message us to order.")), FakeVision(PhotoReading("other", None, 0.5, "", "")))
        with mock.patch.object(ADAPTERS["facebook"], "reply_comment") as post:
            res = rt.handle_comment(public_comments(feed())[0])
        post.assert_called_once()
        self.assertEqual(post.call_args.args[0], "p_1")
        self.assertIn("iPhone 15", post.call_args.args[1])
        kinds = [e["kind"] for e in rt.orchestrator.audit.trace(res.trace)]
        self.assertIn("comment_replied", kinds)

    def test_a_reply_with_a_payment_detail_is_replaced_before_it_is_posted(self):
        rt = runtime(Scripted(plan("Pay to 0123456789 at GTBank and send the receipt.")), FakeVision(PhotoReading("other", None, 0.5, "", "")))
        with mock.patch.object(ADAPTERS["facebook"], "reply_comment") as post:
            rt.handle_comment(public_comments(feed())[0])
        self.assertEqual(post.call_args.args[1], PUBLIC_FALLBACK)

    def test_the_same_comment_delivered_twice_is_answered_once(self):
        rt = runtime(Scripted(plan("Yes, message us!"), plan("Yes, message us!")), FakeVision(PhotoReading("other", None, 0.5, "", "")))
        c = public_comments(feed())[0]
        with mock.patch.object(ADAPTERS["facebook"], "reply_comment") as post:
            rt.handle_comment(c)
            rt.handle_comment(c)
        self.assertEqual(post.call_count, 1)

    def test_a_failed_post_is_recorded_and_never_raised(self):
        rt = runtime(Scripted(plan("Yes, message us!")), FakeVision(PhotoReading("other", None, 0.5, "", "")))
        with mock.patch.object(ADAPTERS["facebook"], "reply_comment", side_effect=ChannelError("no permission")):
            res = rt.handle_comment(public_comments(feed())[0])
        self.assertIn("comment_reply_failed", [e["kind"] for e in rt.orchestrator.audit.trace(res.trace)])


if __name__ == "__main__":
    unittest.main()
