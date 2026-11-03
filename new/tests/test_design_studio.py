"""The design studio: Meta-only, facts from the business record, and a finished image even when no model is reachable."""
import re
import tempfile
import unittest
from pathlib import Path

try:
    import fontTools, numpy, PIL, resvg_py  # noqa: F401,E401
    HAVE_DRAW = True
except ImportError:
    HAVE_DRAW = False
try:
    from fastapi.testclient import TestClient
    from agentic_sales.server.app import create_app
    from agentic_sales.server.auth import AuthStore
    from agentic_sales.server.runtime import Runtimes
    HAVE_API = True
except ImportError:
    HAVE_API = False

from agentic_sales.language.analyzer import Analyzer
from agentic_sales.models.base import ModelResponse, ModelRouter, TaskKind
from tests.test_scheduler import BIZ

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "agentic_sales" / "design" / "studio.py"


class Offline:
    """Stands in for a Muse Spark that is unreachable."""
    name = "offline"

    def complete(self, req):
        raise RuntimeError("down")


class Painter:
    name = "muse-image-1.0"

    def __init__(self):
        self.prompts = []

    def generate(self, prompt, **options):
        self.prompts.append(prompt)
        raise RuntimeError("no network in tests")


class MetaOnly(unittest.TestCase):
    def test_no_other_vendor_is_called_from_the_studio(self):
        text = STUDIO.read_text(encoding="utf-8") + (STUDIO.parent / "service.py").read_text(encoding="utf-8")
        for word in ("gemini", "genai", "veo", "lyria", "anthropic", "openai", "elevenlabs"):
            self.assertIsNone(re.search(rf"\b{word}\b", text, re.I), word)


@unittest.skipUnless(HAVE_DRAW and HAVE_API, "needs the drawing libraries and fastapi (use the project .venv)")
class Studio(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.auth = AuthStore(self.root)
        self.key = self.auth.create_tenant("shop-a", BIZ, plan="growth")
        self.auth.create_tenant("tiny", BIZ, plan="starter")
        self.router = ModelRouter()
        self.runtimes = Runtimes(self.root, None, self.router, Analyzer(None))
        self.c = TestClient(create_app(self.root, self.runtimes, self.auth))
        self.H = {"Authorization": f"Bearer {self.key}"}

    def design(self, **body):
        """Start a design and wait for it, as the console does. Returns (status code, final body)."""
        import time
        r = self.c.post("/v1/design", headers=self.H, json=body)
        if r.status_code != 200:
            return r.status_code, r.json()
        for _ in range(200):
            j = self.c.get(f"/v1/design/jobs/{r.json()['job']}", headers=self.H).json()
            if j["status"] != "working":
                return 200, j
            time.sleep(0.5)
        self.fail("the design never finished")

    def test_a_product_design_takes_its_price_from_the_catalogue_even_with_no_model(self):
        status, j = self.design(request="Poster for our iPhone 15 stock", sku="IP15")
        self.assertEqual((status, j["status"]), (200, "done"), j)
        d = j["result"]
        self.assertEqual((d["price"], d["headline"]), ("₦800,000", "iPhone 15"))
        self.assertTrue(d["image"].startswith("data:image/jpeg;base64,"))
        self.assertFalse(d["brain"])
        self.assertEqual(d["issues"], [])

    def test_the_picture_comes_from_muse_image_and_a_failure_falls_back_to_a_drawn_backdrop(self):
        painter = Painter()
        from agentic_sales.models.meta import MetaImage
        painter.__class__ = type("FakeMetaImage", (Painter, MetaImage), {})
        self.router.media[TaskKind.IMAGE] = painter
        status, j = self.design(request="Poster for our iPhone 15 stock", sku="IP15")
        self.assertEqual((status, j["status"]), (200, "done"), j)
        self.assertGreaterEqual(len(painter.prompts), 1)
        self.assertIn("no text", painter.prompts[0].lower())                                  # the model is asked for a picture with no lettering in it

    def test_unknown_product_format_and_empty_requests_are_refused(self):
        for body in ({"request": "Poster for something", "sku": "NOPE"}, {"request": "Poster for our phones", "format": "nope"}):
            self.assertEqual(self.c.post("/v1/design", headers=self.H, json=body).status_code, 422)
        self.assertEqual(self.c.post("/v1/design", headers=self.H, json={"request": "hi"}).status_code, 422)
        self.assertEqual(self.c.get("/v1/design/jobs/nope", headers=self.H).status_code, 404)
        self.assertEqual(self.c.get("/v1/design/jobs/nope", headers=self.H).status_code, 404)

    def test_a_plan_without_image_creation_cannot_use_it(self):
        key = self.auth.issue_key("tiny", "admin")
        r = self.c.post("/v1/design", headers={"Authorization": f"Bearer {key}"}, json={"request": "Poster for our phones"})
        self.assertIn(r.status_code, (402, 403))

    def test_the_format_list_names_the_sizes(self):
        d = self.c.get("/v1/design/formats", headers=self.H).json()
        self.assertIn("ig_post", {f["name"] for f in d["formats"]})
        self.assertIsNone(d["problem"])


if __name__ == "__main__":
    unittest.main()
