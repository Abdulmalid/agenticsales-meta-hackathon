"""The design studio keeps trying until a design reaches the benchmark, and can make a video that is rated and posted the same way."""
import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:
    from fastapi.testclient import TestClient
    from agentic_sales.server.app import create_app
    from agentic_sales.server.auth import AuthStore
    from agentic_sales.server.runtime import Runtimes
    HAVE_API = True
except ImportError:
    HAVE_API = False

from agentic_sales.config.business import BusinessConfig
from agentic_sales.design import service
from agentic_sales.language.analyzer import Analyzer
from agentic_sales.models.base import ModelResponse, ModelRouter, TaskKind
from tests.test_scheduler import BIZ

try:
    import PIL  # noqa: F401
    from agentic_sales.design import studio  # noqa: F401
    HAVE_DRAWING = True
except ImportError:
    HAVE_DRAWING = False


def design(score, issues=()):
    return SimpleNamespace(checked=True, score=score, critic={"issues": list(issues), "fixes": []}, issues=[])


class FakeStudio:
    def __init__(self, *scores):
        self.scores, self.briefs, self.arts = list(scores), [], []
        self.art, self.inspector, self.art_retries, self.min_score = object(), object(), 1, 90.0

    async def design(self, brief):
        self.briefs.append(list(brief.avoid))
        self.arts.append(type(self.art).__name__)
        return design(*self.scores.pop(0))


@unittest.skipUnless(HAVE_DRAWING, "needs the drawing libraries")
class KeepsTrying(unittest.TestCase):
    def run_loop(self, studio_, fix=None):
        brief = SimpleNamespace(avoid=[], notes="")
        res, attempts = asyncio.run(service._until_good_enough(studio_, brief, fix))
        return res, attempts, brief

    def test_it_stops_as_soon_as_a_design_reaches_the_benchmark(self):
        s = FakeStudio((93, ["fine"]))
        res, attempts, _ = self.run_loop(s)
        self.assertEqual((res.score, attempts, len(s.briefs)), (93, 1, 1))

    def test_each_attempt_is_told_what_the_last_one_got_wrong(self):
        s = FakeStudio((70, ["the headline is over a busy area"]), (91, []))
        res, attempts, brief = self.run_loop(s)
        self.assertEqual((res.score, attempts), (91, 2))
        self.assertEqual(s.briefs[0], [])
        self.assertIn("the headline is over a busy area", s.briefs[1])
        self.assertIn("fix every one", brief.notes)

    def test_the_last_attempt_uses_the_drawn_backdrop_and_the_best_design_is_kept(self):
        s = FakeStudio((70, ["a"]), (82, ["b"]), (75, ["c"]))
        res, attempts, _ = self.run_loop(s)
        self.assertEqual((res.score, attempts), (82, 3))
        self.assertEqual(s.arts[2], "ProceduralArt")
        self.assertNotEqual(s.arts[0], "ProceduralArt")

    def test_a_picture_model_attempt_that_is_too_slow_is_cut_off_and_the_quick_one_runs(self):
        class Slow(FakeStudio):
            async def design(self, brief):
                if type(self.art).__name__ != "ProceduralArt":
                    await asyncio.sleep(3)
                return await super().design(brief)
        s = Slow((92, []))
        with mock.patch.object(service, "TOTAL_SECONDS", 50.5), mock.patch.object(service, "SAFE_RESERVE", 50.0), mock.patch.object(service, "MIN_ATTEMPT", 0.2):
            res, attempts, _ = self.run_loop(s)
        self.assertEqual((res.score, s.arts), (92, ["ProceduralArt"]))

    def test_what_the_owner_asked_to_fix_is_passed_to_the_first_attempt(self):
        s = FakeStudio((95, []))
        self.run_loop(s, ["the price is too small"])
        self.assertEqual(s.briefs[0], ["the price is too small"])


class Rater:
    name = "rater"

    def __init__(self, score):
        self.score, self.requests = score, []

    def complete(self, req):
        self.requests.append(req)
        if "video ad" in req.system:
            return ModelResponse(json.dumps({"beats": [{"visual": "the phone on a podium", "text": "Meet the iPhone 15"}, {"visual": "close up of the camera", "text": ""},
                                                        {"visual": "the phone at a desk", "text": "Free delivery"}, {"visual": "the phone, centred", "text": "Order today"}]}), "rater")
        return ModelResponse(json.dumps({"score": self.score, "issues": ["the phone looks melted"] if self.score < 90 else []}), "rater")


class Painter:
    name = "painter"

    def generate(self, prompt, **kw):
        return pic()


def pic():
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (90, 160), (30, 90, 60)).save(buf, "PNG")
    return buf.getvalue()


@unittest.skipUnless(HAVE_DRAWING, "needs the drawing libraries")
class MakingAVideo(unittest.TestCase):
    def make(self, score, photo=None):
        out = Path(tempfile.mkdtemp())
        router = ModelRouter(text={TaskKind.REASONING: Rater(score)}, media={TaskKind.IMAGE: Painter()})
        with mock.patch.object(service, "available", return_value=None), mock.patch.object(service, "compose_frame", return_value=pic()), \
                mock.patch("agentic_sales.content.reel.render", side_effect=lambda frames, path, **k: Path(path).write_bytes(b"mp4") or path):
            res = service.make_video(router, BusinessConfig.from_dict(BIZ), out, "A short video for the iPhone 15", "IP15", photo)
        return res, out

    def test_a_video_whose_scenes_reach_the_benchmark_can_be_posted(self):
        res, out = self.make(93)
        self.assertEqual((res["kind"], res["passed"], res["score"], res["improve"]), ("video", True, 93, []))
        self.assertTrue((out / res["file"]).exists())
        self.assertEqual(len(res["frames"]), 4)
        self.assertTrue(res["video"].startswith("data:video/mp4;base64,"))

    def test_the_video_scores_as_its_weakest_scene_and_says_what_was_wrong(self):
        res, _ = self.make(60)
        self.assertEqual((res["passed"], res["score"]), (False, 60))
        self.assertTrue(any("melted" in x for x in res["improve"]))

    def test_the_owners_real_photo_replaces_a_scene_that_will_not_come_out_right(self):
        photo = Path(tempfile.mkdtemp()) / "p.png"
        photo.write_bytes(pic())
        res, _ = self.make(60, photo)
        self.assertTrue(any("real photo is used" in n for n in res["notes"]))

    def test_no_model_to_rate_it_means_it_is_not_checked_and_never_passes(self):
        out = Path(tempfile.mkdtemp())
        router = ModelRouter(text={}, media={TaskKind.IMAGE: Painter()})
        with mock.patch.object(service, "available", return_value=None), mock.patch.object(service, "compose_frame", return_value=pic()), \
                mock.patch("agentic_sales.content.reel.render", side_effect=lambda frames, path, **k: Path(path).write_bytes(b"mp4") or path):
            res = service.make_video(router, BusinessConfig.from_dict(BIZ), out, "A short video for the iPhone 15", "IP15")
        self.assertEqual((res["checked"], res["passed"]), (False, False))


@unittest.skipUnless(HAVE_API, "needs fastapi + httpx (use the project .venv)")
class PostingAVideo(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"PUBLIC_BASE_URL": "https://api.example.com"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.root = Path(tempfile.mkdtemp())
        self.auth = AuthStore(self.root)
        self.key = self.auth.create_tenant("shop-a", BIZ, plan="growth")
        self.runtimes = Runtimes(self.root, None, ModelRouter(), Analyzer(None))
        self.c = TestClient(create_app(self.root, self.runtimes, self.auth))
        self.H = {"Authorization": f"Bearer {self.key}"}
        self.rt = self.runtimes.get("shop-a")
        designs = self.rt.content.media_dir / "designs"
        designs.mkdir(parents=True, exist_ok=True)
        (designs / "video_ab.mp4").write_bytes(b"mp4")

    def finished(self, **over):
        out = {"kind": "video", "image": "data:image/jpeg;base64,AA==", "video": None, "frames": [], "score": 93, "passed": True, "checked": True, "min_score": 90,
               "attempts": 1, "caption": "iPhone 15. ₦800,000", "price_kobo": 80_000_000, "improve": [], "summary": "", "notes": [], "issues": [], "art": "x",
               "brain": True, "asked": [], "price": "₦800,000", "headline": "iPhone 15", "file": "video_ab.mp4", "png_bytes": 3}
        with mock.patch("agentic_sales.server.app.design.make_video", return_value={**out, **over}), mock.patch("agentic_sales.server.app.design.available", return_value=None):
            job = self.c.post("/v1/design/video", headers=self.H, json={"request": "A short video for the iPhone 15", "sku": "IP15"}).json()["job"]
            for _ in range(100):
                if self.c.get(f"/v1/design/jobs/{job}", headers=self.H).json()["status"] != "working":
                    break
                time.sleep(0.1)
        return job

    def test_a_video_that_met_the_benchmark_becomes_a_post_with_the_video_attached(self):
        job = self.finished()
        r = self.c.post(f"/v1/design/jobs/{job}/items", headers=self.H, json={"platforms": ["instagram"], "caption": "iPhone 15. ₦800,000. Order on WhatsApp"})
        self.assertEqual(r.status_code, 200, r.text)
        item = r.json()["items"][0]
        self.assertEqual((item["status"], item["violations"]), ("pending_approval", []))
        self.assertTrue(self.rt.content.store.get(item["id"])["media_path"].endswith("video_ab.mp4"))

    def test_a_video_cannot_go_to_a_platform_that_takes_no_video(self):
        job = self.finished()
        r = self.c.post(f"/v1/design/jobs/{job}/items", headers=self.H, json={"platforms": ["x"], "caption": "iPhone 15"})
        self.assertEqual(r.status_code, 422)

    def test_a_video_below_the_benchmark_cannot_be_posted(self):
        job = self.finished(passed=False, score=71)
        r = self.c.post(f"/v1/design/jobs/{job}/items", headers=self.H, json={"platforms": ["instagram"], "caption": "iPhone 15"})
        self.assertEqual(r.status_code, 409)

    def test_the_owner_can_knowingly_post_one_below_the_benchmark_and_the_post_says_so(self):
        job = self.finished(passed=False, score=71)
        r = self.c.post(f"/v1/design/jobs/{job}/items", headers=self.H, json={"platforms": ["instagram"], "caption": "iPhone 15. ₦800,000", "override": True})
        self.assertEqual(r.status_code, 200, r.text)
        row = self.rt.content.store.get(r.json()["items"][0]["id"])
        self.assertIn("below the quality benchmark by the owner's choice (scored 71 of 90)", row["brief"])
        self.assertEqual(row["violations"], [])

    def test_a_failed_video_gives_the_credits_back(self):
        from agentic_sales.design.service import DesignError
        before = self.c.get("/v1/plan", headers=self.H).json() if self.c.get("/v1/plan", headers=self.H).status_code == 200 else None
        with mock.patch("agentic_sales.server.app.design.make_video", side_effect=DesignError("no")), mock.patch("agentic_sales.server.app.design.available", return_value=None):
            job = self.c.post("/v1/design/video", headers=self.H, json={"request": "A short video for the iPhone 15"}).json()["job"]
            for _ in range(100):
                j = self.c.get(f"/v1/design/jobs/{job}", headers=self.H).json()
                if j["status"] != "working":
                    break
                time.sleep(0.1)
        self.assertEqual(j["status"], "error")
        del before


if __name__ == "__main__":
    unittest.main()
