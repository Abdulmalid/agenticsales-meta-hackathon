"""Design studio for a tenant: a flyer, banner or social creative from the owner's request, with the prices and contact details coming from the
business record, never from a model. Muse Spark writes and checks, Muse Image paints the picture, the studio sets the type."""
from __future__ import annotations

import asyncio
import base64
import re
import secrets
import threading
import time
from pathlib import Path

from ..config.business import BusinessConfig
from ..models.base import ModelRouter, TaskKind
from ..models.meta import MetaImage

MAX_REQUEST = 600
DEFAULT_FORMAT = "ig_post"


class DesignError(RuntimeError):
    pass


def available() -> str | None:
    """None when the drawing libraries are installed, else what is missing."""
    try:
        import fontTools, numpy, PIL, resvg_py  # noqa: F401,E401
    except ImportError as e:
        return f"The design studio needs {e.name or 'extra libraries'} installed on this server."
    return None


def formats() -> list[dict]:
    from .studio import FORMATS
    return [{"name": f.name, "w": f.w, "h": f.h, "note": f.note} for f in FORMATS.values()]


def _naira(kobo: int) -> str:
    n = kobo / 100
    return "₦" + (f"{int(n):,}" if n == int(n) else f"{n:,.2f}")


def _brand(cfg: BusinessConfig):
    from .studio import BrandKit
    colours = [c for c in (cfg.brand_colors.get("primary"), cfg.brand_colors.get("accent")) if c]
    return BrandKit(name=cfg.business_name, industry=cfg.industry, colors=colours, whatsapp=cfg.whatsapp, phone=cfg.whatsapp,
                    address=cfg.address, voice=cfg.brand_voice)


def build_studio(router: ModelRouter, out_dir: Path, photo: bytes | None = None):
    """Muse Spark as the brain and critic. The picture is the owner's real photo when there is one, else Muse Image (a drawn backdrop if that fails)."""
    from .studio import DesignStudio, FixedArt, auto_art, muse_llm
    text = router.text.get(TaskKind.REASONING) or router.text.get(TaskKind.CONVERSATION)
    image = router.media.get(TaskKind.IMAGE)
    studio = DesignStudio(muse_llm(text) if text is not None else None, art=FixedArt(photo) if photo else auto_art(image if isinstance(image, MetaImage) else None),
                          critic=text is not None, out_dir=out_dir, max_repairs=4)       # lint repairs cost no model calls: let all of them run
    if photo:
        studio.fixed_recipe, studio.inspector = "split_panel", None                      # a real photo is not inspected for stray text, and gets the panel layout
    return studio


MAX_DESIGNS, GIVE_UP_AFTER = 2, 200.0


async def _until_good_enough(studio, brief):
    """Designs until one reaches the benchmark, at most MAX_DESIGNS and not past GIVE_UP_AFTER seconds (each takes minutes). The best is kept."""
    started, best = time.monotonic(), None
    for attempt in range(1, MAX_DESIGNS + 1):
        res = await studio.design(brief)
        if best is None or res.score > best.score:
            best = res
        if best.checked and best.score >= studio.min_score:
            break
        if time.monotonic() - started > GIVE_UP_AFTER:
            break
    return best, attempt


def suggested_caption(brief, cfg: BusinessConfig) -> str:
    """A caption made only from facts in the brief (headline, offer, price, contact), so there is nothing for a model to invent."""
    bits = [brief.headline or brief.offer, brief.offer if brief.headline and brief.offer != brief.headline else "", brief.price,
            *(brief.details[:2] if brief.details else []), brief.cta, f"WhatsApp {cfg.whatsapp}" if cfg.whatsapp else ""]
    return ". ".join(b.strip(" .") for b in bits if b and b.strip())[:600]


def make(router: ModelRouter, cfg: BusinessConfig, out_dir: Path, request: str, fmt: str = DEFAULT_FORMAT, sku: str | None = None,
         photo: Path | None = None) -> dict:
    """One finished design. With a `sku` the headline and price are the catalogue's own; otherwise a model reads the request into a brief, and the
    claim guard strips anything in the copy the request did not say."""
    missing = available()
    if missing:
        raise DesignError(missing)
    from .studio import FORMATS, Brief
    request = " ".join(request.split())[:MAX_REQUEST]
    if len(request) < 8:
        raise DesignError("Say what the design is for, in a sentence.")
    if fmt not in FORMATS:
        raise DesignError("Unknown format.")
    out_dir.mkdir(parents=True, exist_ok=True)
    studio = build_studio(router, out_dir, photo.read_bytes() if photo is not None and sku and photo.exists() else None)
    brand = _brand(cfg)

    async def run() -> dict:
        from .studio import DesignService
        if sku:
            product = next((p for p in cfg.products if p.sku == sku), None)
            if product is None:
                raise DesignError("That product is not in your catalogue.")
            brief = Brief(brand=brand, kind="product_ad", format=fmt, headline=product.name, price=_naira(product.price_kobo),
                          details=[product.description] if product.description else [], goal=request, cta="Order on WhatsApp" if cfg.whatsapp else "",
                          notes=request, variants=1)
            res, questions = None, []
        else:
            brief, questions = await DesignService(studio).intake(request, brand)
            brief.format, brief.variants = fmt, 1
            res = None
        res, attempts = await _until_good_enough(studio, brief)
        png = res.files["png"].read_bytes()
        jpg = res.files["jpg"].read_bytes()
        passed = res.checked and res.score >= studio.min_score
        digits = re.sub(r"\D", "", (brief.price or "").split(".")[0])
        price_kobo = int(digits) * 100 if digits else None
        return {"image": "data:image/jpeg;base64," + base64.b64encode(jpg).decode(), "png_bytes": len(png), "score": round(res.score),
                "passed": passed, "checked": res.checked, "min_score": round(studio.min_score), "attempts": attempts, "caption": suggested_caption(brief, cfg), "price_kobo": price_kobo,
                "summary": res.summary(), "notes": res.notes, "issues": [str(i) for i in res.issues if i.severity == "error"],
                "art": studio.art.name, "brain": bool(studio.llm), "asked": questions, "price": brief.price, "headline": brief.headline,
                "file": re.sub(r"^.*[\\/]", "", str(res.files["png"]))}

    try:
        return asyncio.run(run())
    except DesignError:
        raise
    except Exception as e:                                                       # noqa: BLE001 - one failed design must not take the server down
        raise DesignError(f"The design could not be made: {type(e).__name__}") from None


_fonts = None


def compose_frame(cfg: BusinessConfig, picture: bytes, headline: str, product=None) -> bytes:
    """One frame of a video: `picture` with `headline` set as vector type in the 9:16 story layout. With a `product` (the closing frame) the catalogue
    price and the call to order are added, from the business record. Returns a PNG."""
    global _fonts
    from .studio import (FORMATS, Brief, Composer, DesignSpec, FontBook, apply_repairs, complete_palette, enforce_facts, lint_layout,
                         prepare_art, render_svg)
    fmt, brand = FORMATS["ig_story"], _brand(cfg)
    _fonts = _fonts or FontBook()
    brief = Brief(brand=brand, kind="video_frame", format="ig_story", headline=headline,
                  price=_naira(product.price_kobo) if product else "", cta="Order on WhatsApp" if product and cfg.whatsapp else "")
    copy = {"headline": headline, "badge": brief.price, "cta": brief.cta, "contact": []}
    spec = DesignSpec(name="scene", palette=complete_palette({}, brand, []), display_font="anton", recipe="story_stack", align="left", scrim="both", copy=copy)
    spec = enforce_facts(spec, brief)
    b64, _img, cols = prepare_art(picture, fmt.w, fmt.h)
    for _ in range(3):                                                              # lint, repair, once more: the same checks a flyer gets
        cv = Composer(_fonts, fmt, spec, brief, b64, cols).build()
        base = render_svg(cv.to_svg(layers=("art", "shade", "shape", "fx")), fmt.w // 2, fmt.h // 2)
        errors = [i for i in lint_layout(cv, base, fmt, 0.5) if i.severity == "error"]
        if not errors or not apply_repairs(spec, errors):
            break
    return render_svg(cv.to_svg(), 720, 1280)


class Jobs:
    """A design takes one to three minutes (Muse Image is slow), longer than a web request may last, so it runs in the background and the console
    asks how it is going. Held in memory: a restart loses unfinished jobs, and the credit for a failed one is given back."""
    KEEP_SECONDS, MAX_PER_TENANT = 1800, 6

    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def start(self, tenant_id: str, work, refund) -> str:
        now = time.time()
        with self._lock:
            for k in [k for k, j in self._jobs.items() if now - j["at"] > self.KEEP_SECONDS]:
                del self._jobs[k]
            if sum(1 for j in self._jobs.values() if j["tenant"] == tenant_id and j["status"] == "working") >= self.MAX_PER_TENANT:
                raise DesignError("Wait for your other designs to finish first.")
            job_id = secrets.token_urlsafe(9)
            self._jobs[job_id] = {"tenant": tenant_id, "status": "working", "at": now}

        def run() -> None:
            try:
                out = work()
                update = {"status": "done", "result": out}
            except DesignError as e:
                refund()
                update = {"status": "error", "error": str(e)}
            except Exception:                                              # noqa: BLE001 - the thread must always end with a recorded outcome
                refund()
                update = {"status": "error", "error": "The design could not be made. Try again."}
            with self._lock:
                self._jobs[job_id].update(update)

        threading.Thread(target=run, daemon=True, name=f"design-{job_id}").start()
        return job_id

    def get(self, tenant_id: str, job_id: str) -> dict | None:
        with self._lock:
            j = self._jobs.get(job_id)
            return None if j is None or j["tenant"] != tenant_id else {k: v for k, v in j.items() if k not in ("tenant", "at")}
