"""Videos: the console can play them (byte ranges), and publishing one runs in the background instead of timing out the request."""
import tempfile
import threading
import time
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
from agentic_sales.models.base import ModelRouter
from tests.test_api import BIZ

MP4 = b"\x00\x00\x00\x18ftypmp42" + bytes(range(200)) * 5          # 1,016 bytes that start like an MP4


class SlowPublisher:
    """Stands in for Instagram: takes a while, like a Reel being processed."""
    def __init__(self):
        self.release, self.seen = threading.Event(), []

    def publish(self, item, secrets):
        self.seen.append(item.get("media_path"))
        self.release.wait(10)
        return "instagram:99"


@unittest.skipUnless(HAVE_API, "needs fastapi + httpx (use the project .venv)")
class Videos(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.auth = AuthStore(self.root)
        self.key = self.auth.create_tenant("shop-a", BIZ, plan="growth")
        self.c = TestClient(create_app(self.root, Runtimes(self.root, None, ModelRouter(), Analyzer(None)), self.auth))
        self.rt = self.c.app.state.runtimes.get("shop-a")
        media = self.root / "tenants" / "shop-a" / "media"
        media.mkdir(parents=True, exist_ok=True)
        (media / "item-1.mp4").write_bytes(MP4)
        self.item = self.rt.content.store.add(campaign_id="c", platform="meta", surface="instagram", caption="New stock", hashtags=[], cta="DM us",
                                              status="approved", violations=[], media_path=str(media / "item-1.mp4"), decided_by="admin:test#1")

    def H(self):
        return {"Authorization": f"Bearer {self.key}"}

    def test_the_whole_video_is_served_and_says_it_can_be_read_in_pieces(self):
        r = self.c.get(f"/v1/content/{self.item}/media", headers=self.H())
        self.assertEqual((r.status_code, r.headers["content-type"], r.headers["accept-ranges"], len(r.content)), (200, "video/mp4", "bytes", len(MP4)))

    def test_a_player_can_ask_for_a_piece_of_it(self):
        for rng, want in (("bytes=0-99", MP4[0:100]), ("bytes=1000-", MP4[1000:]), ("bytes=-16", MP4[-16:])):
            r = self.c.get(f"/v1/content/{self.item}/media", headers={**self.H(), "Range": rng})
            self.assertEqual((r.status_code, r.content), (206, want), rng)
        r = self.c.get(f"/v1/content/{self.item}/media", headers={**self.H(), "Range": "bytes=0-99"})
        self.assertEqual(r.headers["content-range"], f"bytes 0-99/{len(MP4)}")
        self.assertEqual(self.c.get(f"/v1/content/{self.item}/media", headers={**self.H(), "Range": "bytes=5000-6000"}).status_code, 416)

    def test_publishing_a_video_answers_at_once_and_finishes_in_the_background(self):
        slow = SlowPublisher()
        self.rt.content.publishers["instagram"] = slow
        started = time.monotonic()
        r = self.c.post(f"/v1/content/{self.item}/publish", headers=self.H())
        self.assertEqual((r.status_code, r.json()["status"]), (202, "publishing"))
        self.assertLess(time.monotonic() - started, 3)                                   # it did not wait for the platform
        row = self.rt.content.store.get(self.item)
        self.assertEqual(row["status"], "approved")
        self.assertIsNotNone(row["publishing"])                                          # the console shows "publishing"
        again = self.c.post(f"/v1/content/{self.item}/publish", headers=self.H())
        self.assertEqual(again.status_code, 409)                                         # not twice at once
        slow.release.set()
        for _ in range(50):
            row = self.rt.content.store.get(self.item)
            if row["status"] == "published":
                break
            time.sleep(0.1)
        self.assertEqual((row["status"], row["published_ref"], row["publishing"]), ("published", "instagram:99", None))

    def test_a_failed_background_publish_leaves_the_reason_on_the_post_and_clears_the_marker(self):
        class Failing:
            def publish(self, item, secrets):
                from agentic_sales.content.publishers import PublishError
                raise PublishError("Instagram could not process the video")
        self.rt.content.publishers["instagram"] = Failing()
        self.assertEqual(self.c.post(f"/v1/content/{self.item}/publish", headers=self.H()).status_code, 202)
        for _ in range(50):
            row = self.rt.content.store.get(self.item)
            if row["publishing"] is None:
                break
            time.sleep(0.1)
        self.assertEqual((row["status"], row["publishing"]), ("approved", None))
        self.assertIn("could not process", row["error"])

    def test_an_unapproved_post_is_refused_before_anything_starts(self):
        self.rt.content.store.update(self.item, status="draft")
        r = self.c.post(f"/v1/content/{self.item}/publish", headers=self.H())
        self.assertEqual(r.status_code, 409)


if __name__ == "__main__":
    unittest.main()
