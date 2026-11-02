"""Post videos: composed from the script's beats (Muse Image + ffmpeg), approved like any post, then posted as a Reel."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentic_sales.agents.content import ContentAgent, ContentError
from agentic_sales.content import reel
from agentic_sales.content.publishers import FacebookPublisher, InstagramPublisher, TelegramPublisher
from agentic_sales.content.store import ContentStore
from agentic_sales.core.types import TenantContext
from agentic_sales.memory.store import TenantMemory
from agentic_sales.models.base import ModelError, ModelRouter, TaskKind
from tests.test_backend import cfg

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 40
SCRIPT = {"duration_seconds": 8, "beats": [
    {"t": "0-3s", "visual": "an iPhone on a desk", "voiceover": "", "on_screen_text": "iPhone 15, brand new"},
    {"t": "3-8s", "visual": "a hand opening the box", "voiceover": "", "on_screen_text": "₦800,000, 1-year warranty"}]}


class FakeImages:
    def __init__(self, fail_after: int | None = None):
        self.prompts, self.fail_after = [], fail_after

    def generate(self, prompt, **kw):
        if self.fail_after is not None and len(self.prompts) >= self.fail_after:
            raise ModelError("Meta image: blocked")
        self.prompts.append(prompt)
        return PNG


class Beats(unittest.TestCase):
    def test_a_beat_is_as_long_as_its_time_range_within_watchable_limits(self):
        self.assertEqual([b[2] for b in reel.beats_of(SCRIPT)], [3.0, 5.0])
        self.assertEqual(reel._seconds("0-1s"), reel.MIN_SECONDS)
        self.assertEqual(reel._seconds("0-30s"), reel.MAX_SECONDS)
        self.assertEqual(reel._seconds("nonsense"), 3.0)

    def test_scripts_are_bounded_and_bad_beats_skipped(self):
        many = {"beats": [{"t": "0-2s", "visual": "x", "on_screen_text": "y" * 500}] * 20 + ["junk"]}
        got = reel.beats_of(many)
        self.assertEqual(len(got), reel.MAX_BEATS)
        self.assertLessEqual(len(got[0][1]), 90)
        self.assertEqual(reel.beats_of(None), [])

    def test_the_ffmpeg_command_joins_every_frame_and_only_adds_text_when_there_is_a_font(self):
        frames = [reel.Frame(PNG, "Hello", 3), reel.Frame(PNG, "", 2)]
        with_font = " ".join(reel.command("ffmpeg", frames, ["f0.png", "f1.png"], ["t0.txt", None], "o.mp4", "C:/Windows/Fonts/arialbd.ttf"))
        self.assertIn("concat=n=2", with_font)
        self.assertEqual(with_font.count("drawtext"), 1)                              # only the frame that has text
        self.assertIn("C\\:/Windows/Fonts/arialbd.ttf", with_font)                   # a drive colon would break the filter otherwise
        self.assertNotIn("drawtext", " ".join(reel.command("ffmpeg", frames, ["f0.png", "f1.png"], ["t0.txt", None], "o.mp4", None)))

    def test_without_ffmpeg_the_reason_is_plain(self):
        with mock.patch("agentic_sales.content.reel.ffmpeg_path", return_value=None):
            with self.assertRaises(reel.ReelError) as e:
                reel.render([reel.Frame(PNG)], Path(tempfile.mkdtemp()) / "x.mp4")
        self.assertIn("ffmpeg", str(e.exception))


class MakingTheVideo(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.store = ContentStore(TenantMemory(TenantContext("bola"), self.root))
        self.images = FakeImages()
        self.agent = ContentAgent(cfg(), self.root, "bola", ModelRouter(media={TaskKind.IMAGE: self.images}), self.store, None)

    def item(self, platform="instagram", script=SCRIPT, status="pending_approval"):
        return self.store.add(campaign_id="c", platform=platform, caption="New stock", hashtags=[], cta="DM us", image_prompt="a phone", video_script=script,
                              status=status, violations=[])

    def render_ok(self, frames, out):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        self.rendered = frames
        return out

    def test_one_picture_per_beat_then_a_video_is_attached_to_the_post(self):
        i = self.item()
        with mock.patch("agentic_sales.content.reel.render", side_effect=self.render_ok):
            path = self.agent.generate_reel(i)
        self.assertEqual(len(self.images.prompts), 2)
        self.assertIn("an iPhone on a desk", self.images.prompts[0])
        self.assertEqual([f.text for f in self.rendered], ["iPhone 15, brand new", "₦800,000, 1-year warranty"])
        self.assertEqual(self.store.get(i)["media_path"], str(path))
        self.assertTrue(str(path).endswith(".mp4"))

    def test_one_blocked_picture_reuses_the_last_one_but_a_blocked_first_picture_fails(self):
        self.agent.router = ModelRouter(media={TaskKind.IMAGE: FakeImages(fail_after=1)})
        with mock.patch("agentic_sales.content.reel.render", side_effect=self.render_ok):
            self.agent.generate_reel(self.item())
        self.assertEqual(self.rendered[0].image, self.rendered[1].image)
        self.agent.router = ModelRouter(media={TaskKind.IMAGE: FakeImages(fail_after=0)})
        i = self.item()
        with self.assertRaises(ContentError):
            self.agent.generate_reel(i)
        self.assertIn("blocked", self.store.get(i)["error"])

    def test_it_refuses_platforms_without_video_posts_and_posts_without_a_script(self):
        for bad in (self.item(platform="x"), self.item(script=None), self.item(status="published")):
            with self.assertRaises(ContentError):
                self.agent.generate_reel(bad)

    def test_the_owners_real_product_photo_opens_and_closes_the_video_and_costs_no_credit(self):
        self.agent.save_product_image("IP15", PNG + b"REAL")
        i = self.store.add(campaign_id="c", platform="meta", surface="instagram", caption="x", hashtags=[], cta="", image_prompt="p", video_script=SCRIPT,
                           status="pending_approval", violations=[], product_sku="IP15")
        self.assertEqual(self.agent.reel_frames(i), 0)                 # both beats are the real photo
        with mock.patch("agentic_sales.content.reel.render", side_effect=self.render_ok):
            self.agent.generate_reel(i)
        self.assertEqual(self.images.prompts, [])
        self.assertTrue(all(f.image.endswith(b"REAL") for f in self.rendered))

    def test_the_credit_count_matches_the_pictures_made(self):
        self.assertEqual(self.agent.reel_frames(self.item()), 2)
        self.assertEqual(self.agent.reel_frames(self.item(script=None)), 0)

    def test_only_a_generated_mp4_gets_a_public_link_and_nothing_else_in_the_folder(self):
        i = self.item()
        with mock.patch("agentic_sales.content.reel.render", side_effect=self.render_ok):
            self.agent.generate_reel(i)
        url = self.agent.public_image_url(self.store.get(i), "https://api.example", "bola")
        self.assertRegex(url, r"^https://api\.example/media/bola/[0-9a-f]{32}\.mp4$")


class ThePictureMatchesThePost(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.store = ContentStore(TenantMemory(TenantContext("bola"), self.root))
        self.images = FakeImages()
        self.agent = ContentAgent(cfg(), self.root, "bola", ModelRouter(media={TaskKind.IMAGE: self.images}), self.store, None)

    def add(self, **over):
        f = dict(campaign_id="c", platform="meta", surface="facebook", caption="Upgrade to the iPhone 15 for ₦800,000 today. We deliver in Lagos.",
                 hashtags=[], cta="DM us", image_prompt="A woman holding the phone", status="pending_approval", violations=[])
        return self.store.add(**{**f, **over})

    def test_the_brief_names_the_real_product_and_what_the_post_says_without_the_price(self):
        item = self.store.get(self.add())
        brief = self.agent.image_brief(item)
        self.assertIn("The product being sold: iPhone 15", brief)
        self.assertIn("Scene: A woman holding the phone", brief)
        self.assertIn("Upgrade to the iPhone 15", brief)
        self.assertNotIn("800,000", brief)                              # an image model would try to draw the price
        self.assertIn("clear hero", brief)

    def test_a_post_with_no_matching_product_still_gets_a_usable_brief(self):
        brief = self.agent.image_brief(self.store.get(self.add(caption="Fresh stock this week", image_prompt="A shop shelf")))
        self.assertNotIn("The product being sold", brief)
        self.assertIn("Scene: A shop shelf", brief)

    def test_the_owner_can_replace_the_picture_idea_and_the_new_idea_is_what_is_drawn(self):
        i = self.add()
        self.agent.generate_image(i, "The iPhone 15 box on a Lagos market table, daylight")
        self.assertIn("Scene: The iPhone 15 box on a Lagos market table, daylight", self.images.prompts[-1])
        self.assertEqual(self.store.get(i)["image_prompt"], "The iPhone 15 box on a Lagos market table, daylight")


class PostingTheVideo(unittest.TestCase):
    ITEM = {"caption": "New stock", "hashtags": ["Lagos"], "video_url": "https://api.example/media/bola/a.mp4", "image_url": None}

    def test_facebook_gets_the_video_by_url(self):
        calls = []
        ref = FacebookPublisher(lambda url, h, b, **k: calls.append((url, b)) or {"id": "77"}).publish(self.ITEM, {"access_token": "t", "page_id": "9"})
        self.assertEqual(ref, "facebook:77")
        self.assertTrue(calls[0][0].endswith("/9/videos"))
        self.assertEqual(calls[0][1]["file_url"], self.ITEM["video_url"])

    def test_instagram_makes_a_reel_waits_until_it_is_processed_then_publishes(self):
        calls, statuses = [], iter(["IN_PROGRESS", "FINISHED"])
        pub = InstagramPublisher(lambda url, h, b, **k: calls.append((url.rsplit("/", 1)[1], b)) or {"id": "55"},
                                 get=lambda url, token: {"status_code": next(statuses)})
        with mock.patch("agentic_sales.content.publishers._sleep"):
            ref = pub.publish(self.ITEM, {"access_token": "t", "ig_user_id": "1"})
        self.assertEqual(ref, "instagram:55")
        self.assertEqual([c[0] for c in calls], ["media", "media_publish"])
        self.assertEqual((calls[0][1]["media_type"], calls[0][1]["video_url"]), ("REELS", self.ITEM["video_url"]))

    def test_instagram_does_not_publish_a_video_it_could_not_process(self):
        from agentic_sales.content.publishers import PublishError
        pub = InstagramPublisher(lambda *a, **k: {"id": "55"}, get=lambda url, token: {"status_code": "ERROR"})
        with mock.patch("agentic_sales.content.publishers._sleep"), self.assertRaises(PublishError):
            pub.publish(self.ITEM, {"access_token": "t", "ig_user_id": "1"})

    def test_instagram_says_why_when_it_refuses_to_report_on_the_video(self):
        from agentic_sales.content.publishers import PublishError

        def refused(url, token):
            raise PublishError("HTTP 400: (#10) Application does not have permission for this action")
        calls = []
        pub = InstagramPublisher(lambda url, h, b, **k: calls.append(url) or {"id": "55"}, get=refused)
        with mock.patch("agentic_sales.content.publishers._sleep") as slept, self.assertRaises(PublishError) as e:
            pub.publish(self.ITEM, {"access_token": "t", "ig_user_id": "1"})
        self.assertIn("does not have permission", str(e.exception))
        self.assertEqual(slept.call_count, 0)                      # it did not wait five minutes for an answer that was never coming
        self.assertEqual(len(calls), 1)                            # and never tried to publish

    def test_instagram_reports_its_own_processing_error(self):
        from agentic_sales.content.publishers import PublishError
        pub = InstagramPublisher(lambda *a, **k: {"id": "55"}, get=lambda url, token: {"status_code": "ERROR", "status": "Error: video codec not supported"})
        with mock.patch("agentic_sales.content.publishers._sleep"), self.assertRaises(PublishError) as e:
            pub.publish(self.ITEM, {"access_token": "t", "ig_user_id": "1"})
        self.assertIn("video codec not supported", str(e.exception))

    def test_when_instagram_gives_no_status_at_all_it_keeps_trying_to_publish_until_the_video_is_ready(self):
        from agentic_sales.content.publishers import PublishError
        calls = []

        def post(url, h, b, **k):
            calls.append(url.rsplit("/", 1)[1])
            if url.endswith("media_publish") and calls.count("media_publish") < 3:
                raise ModelError("HTTP 400: Media ID is not available (code 9007): media is not ready to be published")
            return {"id": "55"}
        pub = InstagramPublisher(post, get=lambda url, token: {})              # a token that can publish but not read status answers {}
        with mock.patch("agentic_sales.content.publishers._sleep"):
            self.assertEqual(pub.publish(self.ITEM, {"access_token": "t", "ig_user_id": "1"}), "instagram:55")
        self.assertEqual(calls, ["media", "media_publish", "media_publish", "media_publish"])

        def refuses(url, h, b, **k):
            if url.endswith("media_publish"):
                raise ModelError("HTTP 400: The video codec is not supported")
            return {"id": "55"}
        with mock.patch("agentic_sales.content.publishers._sleep") as slept, self.assertRaises(PublishError) as e:
            InstagramPublisher(refuses, get=lambda url, token: {}).publish(self.ITEM, {"access_token": "t", "ig_user_id": "1"})
        self.assertIn("codec", str(e.exception))
        self.assertEqual(slept.call_count, 0)                                  # a real refusal is reported at once, not retried

    def test_telegram_sends_the_video(self):
        calls = []
        TelegramPublisher(lambda url, h, b, **k: calls.append((url, b)) or {"ok": True, "result": {"message_id": 3}}).publish(self.ITEM, {"bot_token": "b", "channel_id": "@c"})
        self.assertTrue(calls[0][0].endswith("/sendVideo"))
        self.assertEqual(calls[0][1]["video"], self.ITEM["video_url"])


if __name__ == "__main__":
    unittest.main()
