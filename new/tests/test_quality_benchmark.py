"""The quality benchmark (90 out of 100) for flyers, pictures and video frames, the design-to-post route, and the job that makes posts by itself."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

try:
    from fastapi.testclient import TestClient
    from agentic_sales.server.app import create_app
    from agentic_sales.server.auth import AuthStore
    from agentic_sales.server.runtime import Runtimes
    HAVE_API = True
except ImportError:
    HAVE_API = False

from agentic_sales.agents.content import ContentAgent
from agentic_sales.content.store import ContentStore
from agentic_sales.core.types import TenantContext
from agentic_sales.design import quality
from agentic_sales.language.analyzer import Analyzer
from agentic_sales.memory.store import TenantMemory
from agentic_sales.models.base import ModelResponse, ModelRouter, TaskKind
from agentic_sales.scheduler import Scheduler
from agentic_sales.server.plans import Gate
from tests.test_backend import cfg
from tests.test_scheduler import BIZ

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 40


class Rater:
    """A Muse Spark that rates pictures with the scores it is given, one per call."""
    name = "rater"

    def __init__(self, *scores):
        self.scores, self.requests = list(scores), []

    def complete(self, req):
        self.requests.append(req)
        s = self.scores.pop(0)
        return ModelResponse(json.dumps({"score": s, "issues": ["the phone looks melted"] if s < 90 else []}), "rater")


class Painter:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt, **kw):
        self.prompts.append(prompt)
        return PNG


class Rating(unittest.TestCase):
    def test_a_rating_is_a_score_and_the_defects_or_nothing_at_all(self):
        self.assertEqual(quality.rate_picture(Rater(95), PNG, "a phone"), (95.0, []))
        self.assertEqual(quality.rate_picture(Rater(40), PNG, "a phone"), (40.0, ["the phone looks melted"]))
        self.assertEqual(quality.rate_picture(None, PNG, "a phone"), (None, []))                  # no model: not rated, never "passed"

        class Garbled:
            def complete(self, req):
                return ModelResponse("looks fine to me", "x")
        self.assertEqual(quality.rate_picture(Garbled(), PNG, "a phone"), (None, []))

        class Wild:
            def complete(self, req):
                return ModelResponse('{"score": 900}', "x")
        self.assertEqual(quality.rate_picture(Wild(), PNG, "a phone")[0], 100.0)                 # out of range is clamped

    def test_the_benchmark_is_ninety_and_the_flyer_score_has_no_free_points(self):
        from agentic_sales.design.studio import DesignStudio
        self.assertEqual(quality.MIN_SCORE, 90.0)
        self.assertEqual(DesignStudio._score({"overall": 9.5}, [], [], False), 95.0)
        self.assertEqual(DesignStudio._score({"overall": 9.5}, [], [object()], False), 89.0)      # one warning is enough to miss it
        self.assertEqual(DesignStudio._score({"overall": 9.5}, [object()], [], True), 58.0)
        self.assertEqual(DesignStudio._score(None, [], [], False), 0.0)                           # no critic: it cannot be certified


class OwnerPhoto(unittest.TestCase):
    def test_the_owners_photo_is_placed_in_the_free_half_whole_and_nothing_is_drawn(self):
        import io
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("needs Pillow (use the project .venv)")
        from agentic_sales.design.studio import FixedArt
        buf = io.BytesIO()
        Image.new("RGB", (800, 800), (200, 30, 30)).save(buf, "PNG")
        out = FixedArt(buf.getvalue()).generate("ignored", width=1080, height=1350)
        img = Image.open(io.BytesIO(out)).convert("RGB")
        self.assertEqual(img.size, (1080, 1350))
        r, g, b = img.getpixel((800, 600))                              # the right half shows the photo (red)
        self.assertGreater(r, 150)


class PicturesAndVideoFrames(unittest.TestCase):
    def agent(self, rater):
        root = Path(tempfile.mkdtemp())
        self.painter = Painter()
        router = ModelRouter(text={TaskKind.REASONING: rater} if rater else {}, media={TaskKind.IMAGE: self.painter})
        self.store = ContentStore(TenantMemory(TenantContext("bola"), root))
        return ContentAgent(cfg(), root, "bola", router, self.store, None)

    def post(self):
        return self.store.add(campaign_id="c", platform="meta", surface="instagram", caption="New iPhone 15 stock", hashtags=[], cta="DM us",
                              image_prompt="the iPhone 15 on a desk", status="pending_approval", violations=[])

    def test_a_picture_below_the_benchmark_is_redrawn_with_what_was_wrong_and_the_good_one_is_kept(self):
        a = self.agent(Rater(60, 95))
        i = self.post()
        a.generate_image(i)
        self.assertEqual(len(self.painter.prompts), 2)
        self.assertIn("the phone looks melted", self.painter.prompts[1])
        self.assertEqual(self.store.get(i)["violations"], [])

    def test_a_picture_that_never_gets_there_is_kept_but_flagged_so_it_cannot_be_approved(self):
        a = self.agent(Rater(50, 70, 60))
        i = self.post()
        a.generate_image(i)
        self.assertEqual(len(self.painter.prompts), 3)
        flags = self.store.get(i)["violations"]
        self.assertEqual(len(flags), 1)
        self.assertTrue(flags[0].startswith("quality: the picture rated 70/100, below the 90 benchmark"), flags)       # the best attempt is the one kept
        self.assertFalse(a.approve(i, "owner"))

    def test_remaking_a_picture_clears_an_old_quality_flag_once_it_passes(self):
        a = self.agent(Rater(50, 50, 50, 93))
        i = self.post()
        a.generate_image(i)
        self.assertTrue(self.store.get(i)["violations"])
        a.generate_image(i)
        self.assertEqual(self.store.get(i)["violations"], [])

    def test_with_no_model_to_rate_it_the_first_picture_is_used_and_nothing_is_claimed(self):
        a = self.agent(None)
        i = self.post()
        a.generate_image(i)
        self.assertEqual(len(self.painter.prompts), 1)
        self.assertEqual(self.store.get(i)["violations"], [])

    def test_each_video_scene_is_rated_and_the_weakest_decides(self):
        script = {"duration_seconds": 6, "beats": [{"t": "0-3s", "visual": "the box on a counter", "voiceover": "", "on_screen_text": "New"},
                                                    {"t": "3-6s", "visual": "the phone on a table", "voiceover": "", "on_screen_text": "Order"}]}
        a = self.agent(Rater(95, 55, 50))
        i = self.store.add(campaign_id="c", platform="meta", surface="instagram", caption="x", hashtags=[], cta="DM us", image_prompt="p", video_script=script,
                           status="pending_approval", violations=[])
        with mock.patch("agentic_sales.agents.content.reel.render", side_effect=lambda frames, out, **k: (out.parent.mkdir(parents=True, exist_ok=True), out.write_bytes(b"mp4"), out)[2]):
            a.generate_reel(i)
        flags = self.store.get(i)["violations"]
        self.assertTrue(flags and flags[0].startswith("quality: the weakest scene of the video rated 55/100"), flags)
        self.assertEqual(len(self.painter.prompts), 3)                                           # scene 1 first time, scene 2 twice


@unittest.skipUnless(HAVE_API, "needs fastapi + httpx (use the project .venv)")
class PostingAndAutomation(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"PUBLIC_BASE_URL": "https://api.example.com"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.root = Path(tempfile.mkdtemp())
        self.auth = AuthStore(self.root)
        self.key = self.auth.create_tenant("shop-a", BIZ, plan="growth")
        self.staff = self.auth.issue_key("shop-a", "staff")
        self.runtimes = Runtimes(self.root, None, ModelRouter(), Analyzer(None))
        self.c = TestClient(create_app(self.root, self.runtimes, self.auth))
        self.H = {"Authorization": f"Bearer {self.key}"}
        self.rt = self.runtimes.get("shop-a")
        self.designs = self.rt.content.media_dir / "designs"
        self.designs.mkdir(parents=True, exist_ok=True)
        (self.designs / "flyer.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 30)

    def made(self, **over):
        out = {"image": "data:image/jpeg;base64,AA==", "png_bytes": 1, "score": 93, "passed": True, "checked": True, "min_score": 90, "attempts": 1,
               "caption": "iPhone 15. ₦800,000", "price_kobo": 80_000_000, "summary": "", "notes": [], "issues": [], "art": "x", "brain": True,
               "asked": [], "price": "₦800,000", "headline": "iPhone 15", "file": "flyer.png"}
        return {**out, **over}

    def finished_design(self, **over):
        import time
        with mock.patch("agentic_sales.server.app.design.make", return_value=self.made(**over)),              mock.patch("agentic_sales.server.app.design.available", return_value=None):       # the design itself is mocked, so the drawing libraries are not needed
            job = self.c.post("/v1/design", headers=self.H, json={"request": "Flyer for the iPhone 15", "sku": "IP15"}).json()["job"]
            for _ in range(100):
                if self.c.get(f"/v1/design/jobs/{job}", headers=self.H).json()["status"] != "working":
                    break
                time.sleep(0.1)
        return job

    def test_a_design_that_met_the_benchmark_becomes_posts_waiting_for_approval(self):
        job = self.finished_design()
        r = self.c.post(f"/v1/design/jobs/{job}/items", headers=self.H, json={"platforms": ["instagram", "facebook"], "caption": "iPhone 15. ₦800,000. Order on WhatsApp"})
        self.assertEqual(r.status_code, 200, r.text)
        items = r.json()["items"]
        self.assertEqual([(i["platform_key"], i["status"], i["violations"]) for i in items], [("instagram", "pending_approval", []), ("facebook", "pending_approval", [])])
        row = self.rt.content.store.get(items[0]["id"])
        self.assertTrue(row["media_path"].endswith("flyer.jpg"))
        self.assertEqual(self.c.post(f"/v1/content/{items[0]['id']}/approve", headers=self.H).status_code, 200)

    def test_a_design_below_the_benchmark_cannot_be_posted_at_all(self):
        job = self.finished_design(score=84, passed=False)
        r = self.c.post(f"/v1/design/jobs/{job}/items", headers=self.H, json={"platforms": ["instagram"], "caption": "iPhone 15"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("below the 90", r.json()["detail"])

    def test_the_caption_gets_the_same_checks_as_any_post(self):
        job = self.finished_design()
        r = self.c.post(f"/v1/design/jobs/{job}/items", headers=self.H, json={"platforms": ["instagram"], "caption": "iPhone 15 for ₦650,000, pay to 0123456789"})
        item = r.json()["items"][0]
        self.assertEqual(item["status"], "draft")
        self.assertTrue(any("price" in v for v in item["violations"]) and any("payment" in v for v in item["violations"]), item["violations"])
        self.assertEqual(self.c.post(f"/v1/content/{item['id']}/approve", headers=self.H).status_code, 409)

    def test_staff_cannot_post_unless_the_owner_allows_it_and_other_businesses_cannot_see_the_job(self):
        job = self.finished_design()
        body = {"platforms": ["instagram"], "caption": "iPhone 15"}
        self.assertEqual(self.c.post(f"/v1/design/jobs/{job}/items", headers={"Authorization": f"Bearer {self.staff}"}, json=body).status_code, 403)
        other = self.auth.create_tenant("shop-b", BIZ, plan="growth")
        self.assertEqual(self.c.post(f"/v1/design/jobs/{job}/items", headers={"Authorization": f"Bearer {other}"}, json=body).status_code, 404)

    # ---- the job that makes posts by itself ----------------------------------------------------------------
    def scheduler(self):
        return Scheduler(self.runtimes, self.auth, Gate(self.auth))

    def plan_returning_items(self, platforms):
        def fake(sku, plats, objective, **kw):
            ids = [self.rt.content.store.add(campaign_id="c", platform="meta", surface=p, caption="Fresh stock", hashtags=[], cta="DM us", image_prompt="x",
                                              status="pending_approval", violations=[], product_sku=sku) for p in plats]
            return mock.Mock(items=[{"id": i, "platform_key": p} for i, p in zip(ids, plats)])
        return mock.patch.object(type(self.rt.content), "plan_product", side_effect=fake)

    def put(self, **config):
        return self.c.put("/v1/automation/content_auto", headers=self.H, json={"enabled": True, **({"config": config} if config else {})})

    def test_it_cannot_be_switched_on_without_platforms_and_only_knows_real_ones(self):
        self.assertEqual(self.put().status_code, 422)
        self.assertEqual(self.put(platforms="myspace").status_code, 422)
        self.assertEqual(self.put(platforms="instagram, facebook", count="9").status_code, 422)
        self.assertEqual(self.put(platforms="instagram, facebook", count="2").status_code, 200)

    def test_it_makes_the_post_and_a_flyer_and_leaves_them_for_approval(self):
        self.put(platforms="instagram")
        with self.plan_returning_items(["instagram"]), mock.patch("agentic_sales.scheduler.design.make", return_value=self.made()):
            r = self.scheduler().run(self.rt, "shop-a", "content_auto", datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc))
        self.assertEqual(r["status"], "ok", r)
        self.assertIn("1 reached the 90 benchmark", r["detail"])
        row = self.rt.content.store.list()[0]
        self.assertEqual((row["status"], row["violations"]), ("pending_approval", []))
        self.assertTrue(row["media_path"].endswith("flyer.jpg"))

    def test_a_flyer_below_the_benchmark_is_flagged_and_cannot_be_approved(self):
        self.put(platforms="instagram")
        with self.plan_returning_items(["instagram"]), mock.patch("agentic_sales.scheduler.design.make", return_value=self.made(score=81, passed=False)):
            r = self.scheduler().run(self.rt, "shop-a", "content_auto", datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc))
        self.assertIn("1 did not", r["detail"])
        row = self.rt.content.store.list()[0]
        self.assertEqual(row["status"], "draft")
        self.assertTrue(row["violations"][0].startswith("quality: the flyer rated 81/100"))
        self.assertEqual(self.c.post(f"/v1/content/{row['id']}/approve", headers=self.H).status_code, 409)

    def test_a_product_is_not_promoted_again_inside_the_gap_and_nothing_is_posted_by_the_job(self):
        self.put(platforms="instagram", gap_days="7")
        now = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)
        with self.plan_returning_items(["instagram"]) as plan, mock.patch("agentic_sales.scheduler.design.make", return_value=self.made()):
            self.scheduler().run(self.rt, "shop-a", "content_auto", now)
            again = self.scheduler().run(self.rt, "shop-a", "content_auto", now)
        self.assertEqual(plan.call_count, 1)
        self.assertIn("promoted in the last 7 days", again["detail"])
        self.assertEqual({i["status"] for i in self.rt.content.store.list()}, {"pending_approval"})        # approval is still the owner's

    def test_a_plan_without_image_creation_is_blocked_not_charged(self):
        self.auth.create_tenant("tiny", BIZ, plan="starter")
        tiny = self.runtimes.get("tiny")
        r = self.scheduler().run(tiny, "tiny", "content_auto", datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc))
        self.assertEqual(r["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
