"""Design studio for a tenant: a flyer, banner or social creative from the owner's request, with the prices and contact details coming from the
business record, never from a model. Muse Spark writes and checks, Muse Image paints the picture, the studio sets the type."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import secrets
import threading
import time
from pathlib import Path

from ..config.business import BusinessConfig
from ..models.base import Message, ModelError, ModelRequest, ModelRouter, TaskKind
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


MIN_ATTEMPT = 30.0
MAX_DESIGNS, TOTAL_SECONDS, SAFE_RESERVE = 3, 190.0, 50.0          # the whole job should not run past about three minutes


def _found(res) -> list[str]:
    """What the art director and the checks found wrong with a design, in plain words."""
    c = res.critic or {}
    out = [str(x) for x in (c.get("issues") or []) + (c.get("fixes") or [])] + [str(i) for i in res.issues if i.severity == "error"]
    return list(dict.fromkeys(" ".join(x.split())[:200] for x in out if x))[:8]


def _learn(brief, problems: list[str]) -> None:
    """Tell the next design what the last one got wrong."""
    if problems:
        brief.avoid = [*brief.avoid, *problems][:10]
        brief.notes = (brief.notes + " Problems found in the previous attempt, fix every one: " + "; ".join(problems))[:1500]


async def _until_good_enough(studio, brief, fix: list[str] | None = None):
    """Designs until one reaches the benchmark, learning from what each attempt got wrong. Two attempts with the picture model, then (or sooner, if time
    is short) a last attempt on a drawn backdrop, which is fast and always leaves calm space for the words. The best is kept."""
    from .studio import FixedArt, ProceduralArt
    started, best = time.monotonic(), None
    _learn(brief, fix or [])
    for attempt in range(1, MAX_DESIGNS + 1):
        left = TOTAL_SECONDS - (time.monotonic() - started)
        last = attempt == MAX_DESIGNS or left < SAFE_RESERVE + MIN_ATTEMPT          # no time for another picture-model attempt
        if last and not isinstance(studio.art, FixedArt):
            studio.art, studio.inspector, studio.art_retries = ProceduralArt(), None, 0
        if attempt > 1:
            studio.art_retries = 0
        res = None
        try:
            res = await (studio.design(brief) if last else asyncio.wait_for(studio.design(brief), max(MIN_ATTEMPT, left - SAFE_RESERVE)))
        except asyncio.TimeoutError:
            pass                                                           # too slow: the next attempt is the quick one
        if res is not None and (best is None or res.score > best.score):
            best = res
        if (best is not None and best.checked and best.score >= studio.min_score) or last:
            break
        if res is not None:
            _learn(brief, _found(res))
    return best, attempt


def suggested_caption(brief, cfg: BusinessConfig) -> str:
    """A caption made only from facts in the brief (headline, offer, price, contact), so there is nothing for a model to invent."""
    bits = [brief.headline or brief.offer, brief.offer if brief.headline and brief.offer != brief.headline else "", brief.price,
            *(brief.details[:2] if brief.details else []), brief.cta, f"WhatsApp {cfg.whatsapp}" if cfg.whatsapp else ""]
    return ". ".join(b.strip(" .") for b in bits if b and b.strip())[:600]


def make(router: ModelRouter, cfg: BusinessConfig, out_dir: Path, request: str, fmt: str = DEFAULT_FORMAT, sku: str | None = None,
         photo: Path | None = None, fix: list[str] | None = None) -> dict:
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
        res, attempts = await _until_good_enough(studio, brief, [" ".join(str(x).split())[:200] for x in (fix or [])][:8])
        png = res.files["png"].read_bytes()
        jpg = res.files["jpg"].read_bytes()
        passed = res.checked and res.score >= studio.min_score
        digits = re.sub(r"\D", "", (brief.price or "").split(".")[0])
        price_kobo = int(digits) * 100 if digits else None
        return {"image": "data:image/jpeg;base64," + base64.b64encode(jpg).decode(), "png_bytes": len(png), "score": round(res.score),
                "passed": passed, "checked": res.checked, "min_score": round(studio.min_score), "attempts": attempts, "caption": suggested_caption(brief, cfg), "price_kobo": price_kobo,
                "improve": [] if passed else _found(res), "kind": "image", "summary": res.summary(), "notes": res.notes, "issues": [str(i) for i in res.issues if i.severity == "error"],
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


VIDEO_SYSTEM = """You plan a short silent vertical video ad (4 scenes, about 12 seconds) for a small Nigerian business, from the owner's request.
Reply with JSON only: {"beats":[{"visual":"what the picture shows","text":"words on screen"}]}.
Each visual describes the product and its setting only: no people, hands or faces, and no text in the picture. Each text is at most 6 words, plain and true to
the request: no prices, phone numbers, discounts or claims the request did not give. The first scene is a hook and the last is the call to order."""
VIDEO_SECONDS, VIDEO_TRIES = 3.0, 3
MAX_INLINE_VIDEO = 3_000_000          # the console reaches the server through a proxy that cannot carry more than a few MB in one answer


def _plan_beats(model, request: str, product, cfg: BusinessConfig) -> list[tuple[str, str]]:
    """(what the picture shows, words on screen) for each scene. Muse Spark writes them from the owner's request; if it cannot, plain ones are made from the product."""
    name = product.name if product else " ".join(request.split()[:6])
    plain = [(f"{name}, hero shot on a clean styled surface", name), (f"Close-up of the details of {name}", ""),
             (f"{name} in a believable everyday setting", ""), (f"{name} front and centre", "Order today")]
    if model is None:
        return plain
    facts = f"Business: {cfg.business_name}. " + (f"Product: {product.name}. {product.description}. " if product else "") + f"Request: {request}"
    try:
        res = model.complete(ModelRequest(VIDEO_SYSTEM, (Message("user", facts),), max_tokens=1200, temperature=0.4))
        m = re.search(r"[{].*[}]", res.text, re.S)
        beats = [(" ".join(str(b.get("visual") or "").split())[:300], " ".join(str(b.get("text") or "").split()[:6]))
                 for b in (json.loads(m.group(0)).get("beats") or []) if isinstance(b, dict)][:4] if m else []
        return beats if len(beats) >= 2 and all(v for v, _ in beats) else plain
    except Exception:                                                      # noqa: BLE001 - a plan that fails is replaced by the plain one
        return plain


def _scene_brief(visual: str, product, note: str = "") -> str:
    named = f" The product: {product.name}. {product.description}".rstrip() if product else ""
    return (f"Vertical 9:16 photograph. Show exactly this: {visual}.{named} Show only the product and its setting: no people, no hands, no faces, no body parts. "
            "No text, letters, numbers, signs, logos or watermarks anywhere. A full-bleed picture that fills the frame edge to edge, with the product in the middle: "
            "no borders, bars or empty bands." + note)


def _jpeg(png: bytes, width: int | None = None, quality: int = 85) -> bytes:
    from PIL import Image
    im = Image.open(io.BytesIO(png)).convert("RGB")
    if width and im.width > width:
        im = im.resize((width, int(im.height * width / im.width)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def make_video(router: ModelRouter, cfg: BusinessConfig, out_dir: Path, request: str, sku: str | None = None, photo: Path | None = None,
               fix: list[str] | None = None) -> dict:
    """A short silent vertical video: Muse Spark plans four scenes, Muse Image draws each (the owner's real photo opens and closes it when there is one),
    the studio sets the words as vector type and ffmpeg joins them. Every scene is rated by Muse Spark looking at it, and a scene that will not reach the
    benchmark is replaced by the owner's real photo when there is one. The video's score is its weakest scene."""
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace
    from ..content import reel
    from . import quality
    missing = available()
    if missing:
        raise DesignError(missing)
    request = " ".join(request.split())[:MAX_REQUEST]
    if len(request) < 8:
        raise DesignError("Say what the video is for, in a sentence.")
    product = cfg.product(sku) if sku else None
    if sku and product is None:
        raise DesignError("That product is not in your catalogue.")
    try:
        media = router.media_model(TaskKind.IMAGE)
    except ModelError as e:
        raise DesignError(str(e)[:200]) from None
    model = router.text.get(TaskKind.REASONING) or router.text.get(TaskKind.CONVERSATION)
    fixes = [" ".join(str(x).split())[:200] for x in (fix or [])][:8]
    beats = _plan_beats(model, request + (" Fix these problems from the last attempt: " + "; ".join(fixes) if fixes else ""), product, cfg)
    real = photo.read_bytes() if photo is not None and sku and photo.exists() else None
    keep_real = {0, len(beats) - 1} if real else set()
    notes: list[str] = []

    def scene(i: int):
        visual, _words = beats[i]
        if i in keep_real:
            return real, quality.rate_picture(model, real, visual)[0], []
        best, note = (None, -1.0, []), ""
        for _ in range(VIDEO_TRIES):
            try:
                data = media.generate(_scene_brief(visual, product, note))
            except ModelError:
                if best[0] is None:
                    raise
                break
            score, issues = quality.rate_picture(model, data, visual)
            if score is None:
                return data, None, []
            if score > best[1]:
                best = (data, score, issues)
            if score >= quality.MIN_SCORE:
                break
            note = " Fix these defects from the last attempt: " + "; ".join(issues) + "."
        if best[1] < quality.MIN_SCORE and real:                              # the owner's own photo beats a picture that will not come out right
            notes.append(f"scene {i + 1}: the drawn picture rated {best[1]:.0f}, so your real photo is used")
            return real, quality.rate_picture(model, real, visual)[0], []
        return best[0], best[1], best[2]

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            got = list(pool.map(scene, range(len(beats))))
    except ModelError as e:
        raise DesignError(f"The pictures could not be made: {str(e)[:160]}") from None
    frames, pngs, scores, defects = [], [], [], []
    for i, ((_visual, words), (pic, score, issues)) in enumerate(zip(beats, got)):
        last = i == len(beats) - 1
        done = compose_frame(cfg, pic, words, product=product if last else None) if (words or last) else pic
        pngs.append(done)
        frames.append(reel.Frame(done, "", VIDEO_SECONDS))
        scores.append(score)
        defects += [f"scene {i + 1}: {x}" for x in issues] if score is not None and score < quality.MIN_SCORE else []
    checked = all(s is not None for s in scores)
    score = round(min(scores)) if checked else 0
    passed = checked and score >= quality.MIN_SCORE
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"video_{secrets.token_hex(5)}.mp4"
    try:
        reel.render(frames, out_dir / name)
    except reel.ReelError as e:
        raise DesignError(str(e)) from None
    size = (out_dir / name).stat().st_size
    headline = product.name if product else next((w for _, w in beats if w), "")
    story = SimpleNamespace(headline=headline, offer="", price=_naira(product.price_kobo) if product else "", details=[], cta="Order on WhatsApp" if cfg.whatsapp else "")
    return {"kind": "video", "image": "data:image/jpeg;base64," + base64.b64encode(_jpeg(pngs[0], 720)).decode(),
            "video": ("data:video/mp4;base64," + base64.b64encode((out_dir / name).read_bytes()).decode()) if size <= MAX_INLINE_VIDEO else None,
            "frames": ["data:image/jpeg;base64," + base64.b64encode(_jpeg(p, 200, 70)).decode() for p in pngs],
            "png_bytes": size, "score": score, "passed": passed, "checked": checked, "min_score": round(quality.MIN_SCORE), "attempts": 1,
            "caption": suggested_caption(story, cfg), "price_kobo": product.price_kobo if product else None, "improve": [] if passed else defects[:8],
            "summary": f"video of {len(frames)} scenes, weakest scene {score}", "notes": notes, "issues": [], "art": "muse-image + studio type", "brain": model is not None,
            "asked": [], "price": story.price, "headline": headline, "file": name}


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
