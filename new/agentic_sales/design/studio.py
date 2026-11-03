"""Design studio: flyers, banners, posters and social creatives for a Nigerian business, from a plain-language brief.

Text is never drawn by an image model. Muse Image paints a text-free hero picture with calm space left for the words; this file lays out
all type, shapes and badges as vector paths (sharp, with the naira sign), then checks the result with deterministic lint (contrast, safe
zones, overlaps, sizes), a claim guard that strips anything the brief did not state, and a Muse Spark critic that can ask for a repair.

Models: Muse Spark (art direction, copy proofreading, critique; reads images) and Muse Image (the picture). Both are Meta models. With no
image model configured the studio falls back to a drawn, palette-driven backdrop so it still works offline.

It needs Pillow, fonttools, numpy and resvg-py (uharfbuzz is optional, for kerning). Fonts are fetched once into STUDIO_FONT_DIR.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import math
import os
import pickle
import random
import re
import shutil
import statistics
import subprocess
import tempfile
import time
import wave
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

log = logging.getLogger("studio")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


OUT_DIR = Path(_env("STUDIO_OUT_DIR", "studio_out"))
FONT_DIR = Path(_env("STUDIO_FONT_DIR", "studio_fonts"))
LLM_TIMEOUT = float(_env("STUDIO_LLM_TIMEOUT", "90"))


# ── FORMATS ────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Format:
    name: str
    w: int
    h: int
    safe: Tuple[float, float, float, float] = (0.06, 0.07, 0.06, 0.07)   # top, right, bottom, left as fractions
    note: str = ""

    @property
    def ratio(self) -> float:
        return self.w / self.h

    def safe_rect(self) -> Tuple[float, float, float, float]:
        t, r, b, l = self.safe
        return (self.w * l, self.h * t, self.w * (1 - r), self.h * (1 - b))


FORMATS: Dict[str, Format] = {f.name: f for f in (
    Format("ig_post", 1080, 1350, note="Instagram / Facebook feed 4:5"),
    Format("ig_square", 1080, 1080, note="Square post / WhatsApp catalog"),
    Format("ig_story", 1080, 1920, safe=(0.13, 0.07, 0.20, 0.07), note="Story / Reel / Status: keep top 13% and bottom 20% clear"),
    Format("whatsapp_status", 1080, 1920, safe=(0.10, 0.07, 0.18, 0.07), note="WhatsApp Status 9:16"),
    Format("tiktok", 1080, 1920, safe=(0.12, 0.14, 0.24, 0.07), note="TikTok: right rail and caption area are covered by UI"),
    Format("fb_post", 1200, 630, safe=(0.08, 0.05, 0.08, 0.05), note="Facebook / link share 1.91:1"),
    Format("fb_cover", 1640, 624, safe=(0.12, 0.18, 0.12, 0.18), note="Facebook cover, centre band survives mobile crop"),
    Format("linkedin_banner", 1584, 396, safe=(0.14, 0.22, 0.14, 0.22), note="LinkedIn profile banner 4:1, left is covered by the photo on desktop"),
    Format("linkedin_post", 1200, 1200, note="LinkedIn square post"),
    Format("x_post", 1600, 900, safe=(0.07, 0.05, 0.07, 0.05), note="X / Twitter 16:9"),
    Format("youtube_thumb", 1280, 720, safe=(0.06, 0.12, 0.14, 0.05), note="YouTube thumbnail, duration badge covers bottom right"),
    Format("flyer_a5", 1748, 2480, safe=(0.05, 0.06, 0.05, 0.06), note="A5 at 300 dpi"),
    Format("flyer_a4", 2480, 3508, safe=(0.05, 0.06, 0.05, 0.06), note="A4 at 300 dpi"),
    Format("poster_a3", 3508, 4961, safe=(0.05, 0.06, 0.05, 0.06), note="A3 at 300 dpi"),
)}

ASPECT_RATIOS = {"1:1": 1.0, "2:3": 2 / 3, "3:2": 1.5, "3:4": 0.75, "4:3": 4 / 3, "4:5": 0.8,
                 "5:4": 1.25, "9:16": 9 / 16, "16:9": 16 / 9, "21:9": 21 / 9}


def nearest_ratio(w: int, h: int) -> str:
    target = w / h
    return min(ASPECT_RATIOS, key=lambda k: abs(math.log(ASPECT_RATIOS[k] / target)))


# ── BRIEF, BRAND, SPEC ─────────────────────────────────────────────────────────
@dataclass
class BrandKit:
    name: str
    tagline: str = ""
    industry: str = ""
    logo_path: Optional[str] = None
    colors: List[str] = field(default_factory=list)        # primary first
    display_font: Optional[str] = None                      # FontBook key, e.g. "anton"
    voice: str = "confident, warm, plain Nigerian English"
    phone: str = ""
    whatsapp: str = ""
    website: str = ""
    instagram: str = ""
    address: str = ""


@dataclass
class Brief:
    brand: BrandKit
    kind: str = "social_post"       # flyer | banner | poster | social_post | story | product_ad | event_invite | thumbnail
    format: str = "ig_post"
    goal: str = ""                  # what the viewer should do
    audience: str = ""
    headline: str = ""
    offer: str = ""
    price: str = ""
    date: str = ""
    venue: str = ""
    cta: str = ""
    details: List[str] = field(default_factory=list)
    tone: str = ""
    language: str = "en"            # en | pidgin | mixed
    must_include: List[str] = field(default_factory=list)
    avoid: List[str] = field(default_factory=list)
    assets: List[str] = field(default_factory=list)   # product / people photos used as visual references
    product_image: Optional[str] = None  # transparent PNG cut-out of the real product, composited in vector (exact fidelity)
    variants: int = 2
    notes: str = ""

    def facts(self) -> str:
        b = self.brand
        rows = [("Business", b.name), ("Tagline", b.tagline), ("Industry", b.industry), ("Headline given", self.headline),
                ("Offer", self.offer), ("Price", self.price), ("Date", self.date), ("Venue", self.venue),
                ("CTA given", self.cta), ("Phone", b.phone), ("WhatsApp", b.whatsapp), ("Website", b.website),
                ("Instagram", b.instagram), ("Address", b.address), ("Details", "; ".join(self.details)),
                ("Must include", "; ".join(self.must_include))]
        return "\n".join(f"- {k}: {v}" for k, v in rows if v)


@dataclass
class DesignSpec:
    name: str = "direction"
    concept: str = ""
    mood: List[str] = field(default_factory=list)
    palette: Dict[str, str] = field(default_factory=dict)
    display_font: str = "anton"
    body_font: str = "poppins"
    case: str = "upper"
    tracking: float = 0.02
    art_prompt: str = ""
    art_notes: str = ""
    recipe: str = "hero"
    align: str = "left"
    scrim: str = "left"
    ornament: str = "none"
    copy: Dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    tweaks: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DesignSpec":
        typ = d.get("typography") or {}
        art = d.get("art") or {}
        lay = d.get("layout") or {}
        return cls(
            name=str(d.get("name") or "direction"), concept=str(d.get("concept") or ""),
            mood=[str(x) for x in (d.get("mood") or [])],
            palette={k: str(v) for k, v in (d.get("palette") or {}).items() if isinstance(v, str)},
            display_font=str(typ.get("display") or "anton"), body_font=str(typ.get("body") or "poppins"),
            case=str(typ.get("case") or "upper"), tracking=float(typ.get("tracking") or 0.02),
            art_prompt=str(art.get("prompt") or ""), art_notes=str(art.get("negative_space") or ""),
            recipe=str(lay.get("recipe") or "hero"), align=str(lay.get("align") or "left"),
            scrim=str(lay.get("scrim") or "left"), ornament=str(lay.get("ornament") or "none"),
            copy=dict(d.get("copy") or {}), rationale=str(d.get("rationale") or ""))


# ── REPORT STORE: retrieval over your 20,000 design reports ─────────────────────
@dataclass
class Report:
    id: str
    source: str          # "art" (art direction) | "layout" (grids, type, vector composition)
    title: str
    text: str
    tags: List[str] = field(default_factory=list)


_STOP = set("the and for with that this from your you are was were will have has had not but can all any its into over "
            "more most such than then them they their there these those which what when where who how why use used using".split())


def _tok(s: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9]+", s.lower()) if len(t) > 2 and t not in _STOP]


class ReportStore:
    """Pure-python BM25 over report files (.json, .jsonl, .md, .txt). Replace with your vector DB by
    passing any callable (query, source, k) -> List[Report] to the director instead."""

    def __init__(self) -> None:
        self.docs: Dict[str, List[Report]] = defaultdict(list)
        self._index: Dict[str, Dict[str, Any]] = {}

    def add(self, report: Report) -> None:
        self.docs[report.source].append(report)
        self._index.pop(report.source, None)

    def add_dir(self, path: Union[str, Path], source: str, limit: Optional[int] = None) -> int:
        n = 0
        for p in sorted(Path(path).rglob("*")):
            if not p.is_file() or p.suffix.lower() not in (".json", ".jsonl", ".md", ".txt"):
                continue
            for rep in self._read(p, source):
                self.add(rep)
                n += 1
                if limit and n >= limit:
                    return n
        log.info("ReportStore: loaded %d '%s' reports from %s", n, source, path)
        return n

    @staticmethod
    def _flatten(obj: Any) -> str:
        if isinstance(obj, str):
            return obj
        if isinstance(obj, dict):
            return "\n".join(f"{k}: {ReportStore._flatten(v)}" for k, v in obj.items())
        if isinstance(obj, list):
            return "\n".join(ReportStore._flatten(x) for x in obj)
        return str(obj) if obj is not None else ""

    def _read(self, p: Path, source: str) -> Iterable[Report]:
        try:
            if p.suffix.lower() == ".jsonl":
                items = [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
            elif p.suffix.lower() == ".json":
                data = json.loads(p.read_text(encoding="utf-8"))
                items = data if isinstance(data, list) else [data]
            else:
                items = [{"title": p.stem, "text": p.read_text(encoding="utf-8")}]
        except Exception as e:
            log.warning("could not read %s: %r", p, e)
            return
        for i, it in enumerate(items):
            if isinstance(it, dict):
                title = str(it.get("title") or it.get("name") or it.get("record_id") or it.get("id") or f"{p.stem}-{i}")
                tags = [str(t) for t in (it.get("tags") or it.get("keywords") or [])]
                text = self._flatten(it)
            else:
                title, tags, text = f"{p.stem}-{i}", [], str(it)
            yield Report(id=f"{p.stem}-{i}", source=source, title=title, text=text, tags=tags)

    def _build(self, source: str) -> Dict[str, Any]:
        idx = self._index.get(source)
        if idx:
            return idx
        docs = self.docs.get(source, [])
        inv: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
        lens: List[int] = []
        for i, d in enumerate(docs):
            toks = _tok(d.title + " " + " ".join(d.tags) + " " + d.text) + _tok(d.title) * 2
            lens.append(len(toks))
            for t, c in Counter(toks).items():
                inv[t].append((i, c))
        idx = {"inv": inv, "lens": lens, "avg": (sum(lens) / len(lens)) if lens else 1.0, "n": len(docs)}
        self._index[source] = idx
        return idx

    def search(self, query: str, source: str, k: int = 3) -> List[Report]:
        docs = self.docs.get(source, [])
        if not docs:
            return []
        idx = self._build(source)
        scores: Dict[int, float] = defaultdict(float)
        for t in set(_tok(query)):
            post = idx["inv"].get(t)
            if not post:
                continue
            idf = math.log(1 + (idx["n"] - len(post) + 0.5) / (len(post) + 0.5))
            for i, tf in post:
                norm = tf * 2.5 / (tf + 1.5 * (0.25 + 0.75 * idx["lens"][i] / idx["avg"]))
                scores[i] += idf * norm
        return [docs[i] for i, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:k]]

    def retriever(self) -> Callable[[str, str, int], List[Report]]:
        return lambda q, src, k: self.search(q, src, k)

    def stats(self) -> Dict[str, int]:
        return {src: len(v) for src, v in self.docs.items()}


# ── PROMPTS ────────────────────────────────────────────────────────────────────
DESIGN_LAWS = """DESIGN LAWS (non-negotiable, in priority order)
1. ONE IDEA. One focal point, one message, one action. A phone user decides in two seconds. If the design needs explaining, it fails.
2. HIERARCHY. The headline is the loudest element (display face, about 8 to 14 percent of the short side). The offer or price is second. Support copy third. The CTA fourth, in the single accent colour. Contact details last but always legible. Never more than three type sizes and two typefaces.
3. LEGIBILITY. Every word must pass 4.5:1 contrast against what is directly behind it (3:1 for very large display text). Put text on calm parts of the art, on a gradient scrim or on a solid panel. Never run text across a busy face, a product edge or a highlight.
4. SPACE. Respect the safe area. Align to one grid. Group related items, separate unrelated ones, keep real negative space. Crowded looks cheap, calm looks premium.
5. COLOUR. Brand colours first. 60 percent dominant, 30 percent secondary, 10 percent accent (the accent is for the CTA and one highlight). Use rich near-black and warm off-white, not pure #000 and #FFF. No rainbow gradients, no neon on neon.
6. DEPTH AND POLISH. Real lighting from one direction, soft long shadows, subtle gradients, 3 to 6 percent film grain, glow only where it earns attention. Layer foreground, subject, background. Avoid clip-art, 90s bevels, heavy outlines and stretched type.
7. TYPE CRAFT. Bold display face plus a clean sans. Tracking: caps +4 to +10 percent, big display 0 to +2. Leading 0.95 to 1.1 for display, 1.3 for body. Max 4 balanced headline lines. Prices are big and use the naira sign.
8. IMAGERY. A hero subject that fits the offer, photoreal, sharp, shallow depth of field, authentic Nigerian settings and people when people appear. No stereotypes or caricature, no poverty imagery, no generic Africa tropes, no stock-photo smiles. No text, logos or watermarks inside the art, type is added later in vector.
9. FORMAT CRAFT. Story, Status, Reel: keep the top 13 and bottom 20 percent clear. Banner, cover: key content sits in the centre band, it will be cropped. Flyer: scannable in five seconds, contact block at the bottom, about 60 words max. Thumbnail: three words, huge, one subject. Product ad: the product is the hero and the price badge is unmissable.
10. TRUTH. Use ONLY facts supplied in the brief: prices, discounts, dates, venues, phone numbers, names, guarantees. Never invent testimonials, before/after claims, awards, stock counts, urgency or scarcity, and never make medical, financial or income claims. If a fact is missing, leave that element out.
11. VOICE. Plain, confident Nigerian English. A light Pidgin hook only when the brand voice and audience fit. No slang overload, no ALL CAPS paragraphs, no exclamation spam.
12. DISTINCT DIRECTIONS. When asked for several directions, make them genuinely different in concept, composition, colour temperature and layout recipe."""

RECIPE_CATALOG = """LAYOUT RECIPES (pick one per direction)
- hero: full-bleed art, copy column on one side (align left or right), scrim from that side. Posts, flyers, general ads.
- poster_center: centred stack, headline in the top or bottom third over a scrim. Events, announcements, quotes.
- split_panel: solid colour panel with a diagonal edge on one side, art on the other. Strong brand colour, busy art, date or price blocks.
- price_burst: product hero, big price badge, short headline. Product ads and promos.
- banner_wide: logo left, headline centre, CTA right. ONLY for aspect ratio 2.2:1 or wider (covers, LinkedIn banners).
- story_stack: vertical safe-zone layout for 9:16, headline up, offer and CTA down, calm middle.
- menu: header over art, then a card listing up to 7 items with prices (price lists, service menus, restaurant and salon flyers). Put the lines in copy.items, taken from the supplied details."""

DIRECTOR_SYSTEM = """You are the creative director of an elite design studio serving Nigerian businesses. You turn a client brief into scroll-stopping, premium flyers, banners, posters and ads.

How the studio works: an image model paints a TEXT-FREE hero image from your art prompt, then a vector engine sets all typography, shapes, badges and buttons on top of it. So you direct two things: the ART (concept, subject, light, composition, colour) and the LAYOUT (recipe, type, palette, copy).

You are given reference reports. ART-DIRECTION REPORTS carry visual concepts, lighting, composition and prompt language. SVG / LAYOUT REPORTS carry grids, typographic systems, vector ornament and composition rules. Extract the principles that fit this brief and apply them. Never copy their wording, and ignore anything that conflicts with the laws below.

""" + DESIGN_LAWS + "\n\n" + RECIPE_CATALOG + """

FONTS. display: anton | bebas | poppins_black | poppins_extrabold | dmserif. The body face is always Poppins. Use "case":"upper" for anton and bebas.
PALETTE. Six hex colours: bg, primary, accent, text, text_alt, scrim. Prefer the client's brand colours. The accent is the CTA colour. The scrim is the colour used to darken or lighten the art behind text.
ART PROMPT (art.prompt). 70 to 130 words in the language of a cinematographer: subject, setting, composition, camera and lens, lighting, colour palette with hex values, mood, texture. State exactly where the calm negative space for copy is (art.negative_space, for example "left 45 percent" or "top 30 percent and bottom 30 percent"). Never ask for text, letters, numbers, logos or watermarks. When product photos are supplied say the product must stay exactly as in the reference. When a product cut-out will be composited on top (the brief says so), the art must NOT contain the product: describe a styled empty set (podium, surface, backdrop, light) with a clear empty area where the product will sit.
COPY. Write sharp, human copy from the supplied facts only. headline: 2 to 7 words, strong. You may wrap the key words of the headline in asterisks (for example Own the *iPhone 15*) to highlight them in the accent colour. kicker: optional 2 to 4 words. sub: one line, max 14 words. offer: only if supplied. badge: a short supplied fact such as a price, a percentage or a date, 1 to 3 short words per line, use \\n for a line break. cta: 2 to 4 words, an action verb. contact: a list of supplied contact strings only. items: for the menu recipe only, up to 7 strings such as "Box braids - ₦25,000" copied from the supplied details. fine_print: only if supplied. Omit any field you cannot fill from the facts.

OUTPUT: ONE JSON object, no markdown fences:
{"directions":[{"name":"short name","concept":"the big idea in one sentence","mood":["..."],
"palette":{"bg":"#","primary":"#","accent":"#","text":"#","text_alt":"#","scrim":"#"},
"typography":{"display":"anton","body":"poppins","case":"upper","tracking":0.03},
"art":{"prompt":"...","negative_space":"..."},
"layout":{"recipe":"hero|poster_center|split_panel|price_burst|banner_wide|story_stack|menu","align":"left","scrim":"left|right|bottom|top|full|none","ornament":"none|dots|lines|frame|burst|stripes"},
"copy":{"headline":"","kicker":"","sub":"","offer":"","badge":"","cta":"","contact":[],"items":[],"fine_print":"","date":"","venue":""},
"rationale":"why this stops the scroll and drives the action"}]}"""

REVISE_SYSTEM = """You are the creative director revising ONE design direction after quality control. You receive the current direction as JSON and a list of issues found by automated lint and by a vision critic. Fix every issue with the smallest change that works: shorten or reword copy, change recipe, alignment or scrim, adjust palette for contrast, or rewrite the art prompt when the art itself is the problem (busy area behind text, wrong subject, no calm space). Keep the strengths. Keep every fact exactly as supplied and never add new claims. Return ONE JSON object with the same schema as a single direction, no fences."""

CRITIC_SYSTEM = """You are a ruthless senior art director reviewing a finished marketing design. Be calibrated: overall 9 or more means an agency would publish it unchanged; most first drafts deserve 6 to 8. Judge it as a phone user would, in two seconds. Score each 1 to 10: hierarchy, legibility, composition, colour, polish, message_clarity. Look hard for: text over busy areas, low contrast, cramped or off-balance layout, awkward line breaks, weak focal point, cheap-looking effects, distorted or odd imagery (hands, faces, products), any stray text or logos inside the art, and anything that makes the offer unclear.
Reply with ONE JSON object, no fences:
{"scores":{"hierarchy":0,"legibility":0,"composition":0,"colour":0,"polish":0,"message_clarity":0},
"overall":0,"verdict":"ship|revise|regenerate_art","issues":["specific, visible problems"],"fixes":["specific, actionable changes"]}"""

INTAKE_SYSTEM = """You turn a customer chat request for a design into a structured brief for a design studio. Extract only what the customer actually said or what the saved brand kit already contains. Never invent prices, dates, phone numbers or offers.
Return ONE JSON object, no fences:
{"kind":"flyer|banner|poster|social_post|story|product_ad|event_invite|thumbnail","format":"ig_post|ig_square|ig_story|whatsapp_status|tiktok|fb_post|fb_cover|linkedin_banner|linkedin_post|x_post|youtube_thumb|flyer_a5|flyer_a4|poster_a3",
"goal":"","audience":"","headline":"","offer":"","price":"","date":"","venue":"","cta":"","details":[],"tone":"","language":"en|pidgin|mixed","must_include":[],"avoid":[],
"missing":["up to 3 short questions for details that are essential and absent"]}
Choose the format from the platform the customer names (WhatsApp status -> whatsapp_status, Instagram post -> ig_post, story or reel -> ig_story, LinkedIn banner -> linkedin_banner, flyer -> flyer_a4). Only list a missing question when the design truly cannot be made well without it (for example no business name, no offer for a promo, no date for an event)."""


PROOF_SYSTEM = """You are a meticulous Nigerian English copy editor for marketing designs. You receive a JSON object of short copy fields. Fix ONLY spelling, grammar, punctuation, capitalisation consistency and awkward phrasing. Never change meaning, numbers, prices, dates, names, phone numbers or the naira sign. Never add claims or new words that carry facts. Keep each field short. Keep any asterisks used for highlight. Return the same JSON keys, nothing else, no fences."""

ART_INSPECTOR_SYSTEM = """You inspect an AI-generated background image BEFORE typography is added. Be strict.
Return ONE JSON object, no fences:
{"has_text":false,"has_logo_or_watermark":false,"defects":["distorted hands, fingers or faces","warped or melted objects","odd artefacts","wrong subject"],
"calm_zone_ok":true,"calm_zone_note":"is the requested area for copy really calm and low-detail?","product_visible":false,
"pass":true,"retry_hint":"one short instruction that would fix the next attempt"}
has_text is true for ANY letters, numbers, signs, labels, captions or squiggles that look like writing, even partial or garbled. Ignore printing that is physically part of a real product shown in a supplied reference photo. pass is false if there is stray text, a logo or watermark, a serious defect, or no calm zone."""


# ── COLOUR HELPERS ─────────────────────────────────────────────────────────────
def valid_hex(s: Any) -> bool:
    return isinstance(s, str) and bool(re.fullmatch(r"#?(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})", s.strip()))


def norm_hex(s: str) -> str:
    h = s.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h.upper()


def hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = norm_hex(h).lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def rgb_to_hex(rgb: Sequence[float]) -> str:
    return "#%02X%02X%02X" % tuple(int(max(0, min(255, round(v)))) for v in rgb)


def _lin(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb: Sequence[float]) -> float:
    return 0.2126 * _lin(rgb[0]) + 0.7152 * _lin(rgb[1]) + 0.0722 * _lin(rgb[2])


def contrast_ratio(l1: float, l2: float) -> float:
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def mix_hex(a: str, b: str, t: float) -> str:
    ra, rb = hex_to_rgb(a), hex_to_rgb(b)
    return rgb_to_hex([ra[i] + (rb[i] - ra[i]) * t for i in range(3)])


def on_color(bg: str, light: str = "#FAF7F2", dark: str = "#101216") -> str:
    lb = luminance(hex_to_rgb(bg))
    return light if contrast_ratio(luminance(hex_to_rgb(light)), lb) >= contrast_ratio(luminance(hex_to_rgb(dark)), lb) else dark


def art_palette(img: Any, k: int = 5) -> List[str]:
    try:
        small = img.convert("RGB").resize((64, 64))
        q = small.quantize(colors=k)
        pal = q.getpalette() or []
        counts = sorted(q.getcolors() or [], reverse=True)
        return [rgb_to_hex(pal[i * 3:i * 3 + 3]) for _, i in counts if i * 3 + 3 <= len(pal)]
    except Exception:
        return []


def complete_palette(given: Dict[str, str], brand: BrandKit, art_cols: Sequence[str]) -> Dict[str, str]:
    base = {"bg": "#101216",
            "primary": brand.colors[0] if brand.colors and valid_hex(brand.colors[0]) else (art_cols[0] if art_cols else "#12343B"),
            "accent": brand.colors[1] if len(brand.colors) > 1 and valid_hex(brand.colors[1]) else "#F5B700",
            "text": "#FAF7F2", "text_alt": "#101216", "scrim": "#0B0C10"}
    out = {k: norm_hex(v) for k, v in base.items()}
    for k, v in given.items():
        if k in out and valid_hex(v):
            out[k] = norm_hex(v)
    if contrast_ratio(luminance(hex_to_rgb(out["accent"])), luminance(hex_to_rgb(out["primary"]))) < 1.6:
        out["accent"] = "#F5B700" if luminance(hex_to_rgb(out["primary"])) < 0.4 else "#D7263D"
    return out


# ── FONTS AND TEXT TO VECTOR PATHS ─────────────────────────────────────────────
FONT_BASE_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/"
FONT_SOURCES = {
    "poppins": "poppins/Poppins-Regular.ttf", "poppins_semibold": "poppins/Poppins-SemiBold.ttf",
    "poppins_bold": "poppins/Poppins-Bold.ttf", "poppins_extrabold": "poppins/Poppins-ExtraBold.ttf",
    "poppins_black": "poppins/Poppins-Black.ttf", "bebas": "bebasneue/BebasNeue-Regular.ttf",
    "anton": "anton/Anton-Regular.ttf", "dmserif": "dmserifdisplay/DMSerifDisplay-Regular.ttf",
}
NAIRA = "\u20A6"


def _ntos(v: float) -> str:
    s = "%.1f" % v
    return s[:-2] if s.endswith(".0") else s


_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B50\u2B55\uFE0F\u200D]")


def clean_text(s: str) -> str:
    s = _EMOJI_RE.sub("", s or "")
    s = s.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2014", ", ").replace("\u2013", "-").replace("\u00a0", " ")
    return re.sub(r"[ \t]+", " ", s).strip()


class FontFace:
    def __init__(self, path: Union[str, Path]):
        from fontTools.ttLib import TTFont
        self.path = str(path)
        self.tt = TTFont(self.path)
        self.upem = self.tt["head"].unitsPerEm
        self.cmap = self.tt.getBestCmap()
        self.gs = self.tt.getGlyphSet()
        self.order = self.tt.getGlyphOrder()
        os2, hhea = self.tt["OS/2"], self.tt["hhea"]
        self.cap = (getattr(os2, "sCapHeight", 0) or int(self.upem * 0.7)) / self.upem
        self.asc, self.desc = hhea.ascent / self.upem, -hhea.descent / self.upem
        self.weight = getattr(os2, "usWeightClass", 400)
        self._hb = None
        try:
            import uharfbuzz as hb
            self._hb = (hb, hb.Font(hb.Face(hb.Blob.from_file_path(self.path))))
        except Exception:
            self._hb = None

    def has(self, ch: str) -> bool:
        return ord(ch) in self.cmap

    def _adv(self, ch: str) -> float:
        name = self.cmap.get(ord(ch))
        return self.tt["hmtx"][name][0] if name else 0

    def _shape_run(self, text: str) -> List[Tuple[str, float, float, float]]:
        if not text:
            return []
        if self._hb:
            hb, font = self._hb
            buf = hb.Buffer()
            buf.add_str(text)
            buf.guess_segment_properties()
            hb.shape(font, buf, {"kern": True, "liga": True})
            return [(self.order[i.codepoint], p.x_advance, p.x_offset, p.y_offset)
                    for i, p in zip(buf.glyph_infos, buf.glyph_positions)]
        return [(self.cmap[ord(c)], self._adv(c), 0, 0) for c in text if ord(c) in self.cmap]

    def layout(self, text: str, size: float, tracking: float = 0.0) -> Tuple[List[Tuple[str, float, float]], float]:
        """Glyph placements [(glyph or NAIRA, x, y_offset)] in px and the total width."""
        text = "".join(ch for ch in text if ch == NAIRA or ch == " " or self.has(ch))
        s = size / self.upem
        x, out = 0.0, []
        for k, seg in enumerate(text.split(NAIRA)):
            if k > 0:
                out.append((NAIRA, x, 0.0))
                x += self._adv("N") * s + tracking * size
            for name, adv, xo, yo in self._shape_run(seg):
                out.append((name, x + xo * s, yo * s))
                x += adv * s + tracking * size
        return out, max(0.0, x - (tracking * size if out else 0.0))

    def width(self, text: str, size: float, tracking: float = 0.0) -> float:
        return self.layout(text, size, tracking)[1]

    def _naira_d(self, size: float, x: float, y: float) -> str:
        from fontTools.pens.boundsPen import BoundsPen
        from fontTools.pens.svgPathPen import SVGPathPen
        from fontTools.pens.transformPen import TransformPen
        s = size / self.upem
        pen = SVGPathPen(self.gs, ntos=_ntos)
        self.gs["N"].draw(TransformPen(pen, (s, 0, 0, -s, x, y)))
        bp = BoundsPen(self.gs)
        self.gs["N"].draw(bp)
        xmin, _, xmax, _ = bp.bounds or (0, 0, self._adv("N"), 0)
        t = size * (0.04 + 0.00008 * self.weight)
        x0, x1 = x + xmin * s - 0.05 * size, x + xmax * s + 0.05 * size
        bars = ""
        for frac in (0.36, 0.64):
            yc = y - self.cap * size * frac
            bars += f"M{_ntos(x0)} {_ntos(yc - t / 2)}H{_ntos(x1)}V{_ntos(yc + t / 2)}H{_ntos(x0)}Z"
        return pen.getCommands() + bars

    def line_d(self, text: str, size: float, x: float, y: float, tracking: float = 0.0) -> str:
        """SVG path data for one line with its baseline at y and its left edge at x."""
        from fontTools.pens.svgPathPen import SVGPathPen
        from fontTools.pens.transformPen import TransformPen
        glyphs, _ = self.layout(text, size, tracking)
        s = size / self.upem
        parts: List[str] = []
        for name, gx, gy in glyphs:
            if name == NAIRA:
                parts.append(self._naira_d(size, x + gx, y))
                continue
            pen = SVGPathPen(self.gs, ntos=_ntos)
            self.gs[name].draw(TransformPen(pen, (s, 0, 0, -s, x + gx, y - gy)))
            cmd = pen.getCommands()
            if cmd:
                parts.append(cmd)
        return "".join(parts)


class FontBook:
    def __init__(self, font_dir: Union[str, Path] = FONT_DIR, extra: Optional[Dict[str, str]] = None,
                 auto_download: bool = True):
        self.dir = Path(font_dir)
        self.extra = dict(extra or {})          # your own brand fonts: {"brand": "/path/Brand-Bold.ttf"}
        self.auto = auto_download
        self._faces: Dict[str, FontFace] = {}

    def _path(self, key: str) -> Path:
        if key in self.extra:
            return Path(self.extra[key])
        if key not in FONT_SOURCES:
            raise KeyError(f"unknown font key '{key}'")
        p = self.dir / Path(FONT_SOURCES[key]).name
        if not p.exists():
            if not self.auto:
                raise FileNotFoundError(f"font missing: {p}")
            self.dir.mkdir(parents=True, exist_ok=True)
            import urllib.request
            log.info("downloading font %s", p.name)
            with urllib.request.urlopen(FONT_BASE_URL + FONT_SOURCES[key], timeout=30) as r:
                p.write_bytes(r.read())
        return p

    def face(self, key: str) -> FontFace:
        if key not in self._faces:
            try:
                self._faces[key] = FontFace(self._path(key))
            except Exception as e:
                if key in ("anton", "poppins_bold"):
                    raise
                log.warning("font '%s' unavailable (%r), using poppins_bold", key, e)
                return self.face("poppins_bold")
        return self._faces[key]


# ── TEXT FITTING ───────────────────────────────────────────────────────────────
@dataclass
class TextLayout:
    lines: List[str]
    size: float
    width: float
    height: float
    line_h: float
    tracking: float
    hi: Set[int] = field(default_factory=set)   # indexes of highlighted words (flattened)


def _parse_highlight(text: str) -> Tuple[str, Set[int]]:
    """Words wrapped in asterisks are highlighted. Spans may cover several words: *the iPhone 15*."""
    hi: Set[int] = set()
    words: List[str] = []
    inside = False
    for tok in text.split():
        starts, ends = tok.startswith("*"), tok.endswith("*") and len(tok.strip("*")) > 0
        if starts:
            inside = True
        if inside and tok.strip("*"):
            hi.add(len(words))
        words.append(tok.replace("*", ""))
        if ends or (starts and tok.endswith("*")):
            inside = False
    return " ".join(w for w in words if w), hi


def wrap_greedy(face: FontFace, text: str, size: float, max_w: float, tracking: float) -> List[str]:
    lines: List[str] = []
    for para in text.split("\n"):
        cur = ""
        for w in para.split():
            trial = (cur + " " + w).strip()
            if cur and face.width(trial, size, tracking) > max_w:
                lines.append(cur)
                cur = w
            else:
                cur = trial
        if cur:
            lines.append(cur)
    return lines


def wrap_balanced(face: FontFace, text: str, size: float, max_w: float, tracking: float) -> List[str]:
    lines = wrap_greedy(face, text, size, max_w, tracking)
    if len(lines) < 2 or "\n" in text:
        return lines
    n, best, lo, hi = len(lines), lines, max_w * 0.4, max_w
    for _ in range(14):
        mid = (lo + hi) / 2
        cand = wrap_greedy(face, text, size, mid, tracking)
        if len(cand) > n:
            lo = mid
        else:
            best, hi = cand, mid
    return best


def fit_text(face: FontFace, text: str, box_w: float, box_h: float, *, max_size: float, min_size: float,
             line_h: float = 1.1, max_lines: int = 4, tracking: float = 0.0, balanced: bool = True) -> TextLayout:
    plain, hi = _parse_highlight(text)
    size = max_size
    while True:
        lines = (wrap_balanced if balanced else wrap_greedy)(face, plain, size, box_w, tracking)
        widths = [face.width(ln, size, tracking) for ln in lines] or [0.0]
        height = face.cap * size + (len(lines) - 1) * size * line_h + 0.22 * size
        ok = len(lines) <= max_lines and max(widths) <= box_w * 1.002 and height <= box_h
        if ok or size <= min_size:
            return TextLayout(lines, size, max(widths), height, line_h, tracking, hi)
        size = max(min_size, size * 0.94)


# ── SVG CANVAS ─────────────────────────────────────────────────────────────────
def _f(v: float) -> str:
    return _ntos(v)


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


class Canvas:
    LAYERS = ("art", "shade", "shape", "fx", "text")

    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.defs: List[str] = []
        self.items: List[Tuple[str, Optional[int], str]] = []
        self.boxes: List[Dict[str, Any]] = []
        self._n = 0
        self._filters: Dict[Tuple[float, float, float], str] = {}

    def uid(self, p: str = "d") -> str:
        self._n += 1
        return f"{p}{self._n}"

    def add(self, layer: str, svg: str, group: Optional[int] = None) -> None:
        self.items.append((layer, group, svg))

    def shadow(self, blur: float, dy: float, opacity: float) -> str:
        key = (round(blur, 1), round(dy, 1), round(opacity, 2))
        if key not in self._filters:
            fid = self.uid("sh")
            self.defs.append(
                f'<filter id="{fid}" x="-25%" y="-25%" width="150%" height="150%"><feGaussianBlur in="SourceAlpha" '
                f'stdDeviation="{_f(blur)}"/><feOffset dy="{_f(dy)}"/><feComponentTransfer><feFuncA type="linear" '
                f'slope="{opacity}"/></feComponentTransfer><feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/>'
                f'</feMerge></filter>')
            self._filters[key] = fid
        return self._filters[key]

    def to_svg(self, *, layers: Sequence[str] = LAYERS, include_static: bool = True,
               groups: Optional[Set[int]] = None) -> str:
        body: List[str] = []
        for layer, group, svg in self.items:
            if layer not in layers:
                continue
            if group is None:
                if include_static:
                    body.append(svg)
            elif groups is None:
                if include_static:
                    body.append(svg)
            elif group in groups:
                body.append(svg)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                f'width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}"><defs>{"".join(self.defs)}</defs>'
                + "".join(body) + "</svg>")


# ── RENDERER ───────────────────────────────────────────────────────────────────
def render_svg(svg: str, w: int, h: int) -> bytes:
    """SVG -> PNG. resvg (filters, blur, grain) first, CairoSVG as a fallback."""
    try:
        import resvg_py
        return bytes(resvg_py.svg_to_bytes(svg_string=svg, width=w, height=h, skip_system_fonts=True))
    except ImportError:
        pass
    try:
        import cairosvg
        return cairosvg.svg2png(bytestring=svg.encode("utf-8"), output_width=w, output_height=h)
    except ImportError as e:
        raise RuntimeError("install a renderer: pip install resvg-py  (or cairosvg)") from e


def _icon_path(kind: str) -> str:
    return {
        "phone": "M6.62 10.79c1.44 2.83 3.76 5.14 6.59 6.59l2.2-2.2c.27-.27.67-.36 1.02-.24 1.12.37 2.33.57 3.57.57.55 0 1 .45 1 1V20c0 .55-.45 1-1 1-9.39 0-17-7.61-17-17 0-.55.45-1 1-1h3.5c.55 0 1 .45 1 1 0 1.25.2 2.45.57 3.57.11.35.03.74-.25 1.02l-2.2 2.2z",
        "pin": "M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z",
        "web": "M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zm6.93 6h-2.95a15.65 15.65 0 0 0-1.38-3.56A8.03 8.03 0 0 1 18.92 8zM12 4.04c.83 1.2 1.48 2.53 1.91 3.96h-3.82c.43-1.43 1.08-2.76 1.91-3.96zM4.26 14C4.1 13.36 4 12.69 4 12s.1-1.36.26-2h3.38c-.08.66-.14 1.32-.14 2 0 .68.06 1.34.14 2H4.26zm.82 2h2.95c.32 1.25.78 2.45 1.38 3.56A7.987 7.987 0 0 1 5.08 16zm2.95-8H5.08a7.987 7.987 0 0 1 4.33-3.56A15.65 15.65 0 0 0 8.03 8zM12 19.96c-.83-1.2-1.48-2.53-1.91-3.96h3.82c-.43 1.43-1.08 2.76-1.91 3.96zM14.34 14H9.66c-.09-.66-.16-1.32-.16-2 0-.68.07-1.35.16-2h4.68c.09.65.16 1.32.16 2 0 .68-.07 1.34-.16 2zm.25 5.56c.6-1.11 1.06-2.31 1.38-3.56h2.95a8.03 8.03 0 0 1-4.33 3.56zM16.36 14c.08-.66.14-1.32.14-2 0-.68-.06-1.34-.14-2h3.38c.16.64.26 1.31.26 2s-.1 1.36-.26 2h-3.38z",
    }.get(kind, "")


def _contact_kind(s: str) -> str:
    low = s.lower()
    if low.startswith("@") or "instagram" in low:
        return "at"
    if re.search(r"\bwww\.|\.(com|ng|co|org|net|io|store|shop)\b", low) and " " not in s.strip():
        return "web"
    if re.search(r"\d{3}[\s-]?\d{3}", s):
        return "phone"
    return "pin"


# ── COMPOSER: copy + art -> layered SVG ────────────────────────────────────────
@dataclass
class _Item:
    kind: str
    text: str = ""
    face: str = "poppins"
    max_size: float = 40
    min_size: float = 20
    max_lines: int = 2
    line_h: float = 1.15
    tracking: float = 0.0
    color: str = "#FFFFFF"
    upper: bool = False
    group: int = 0
    large: bool = False
    gap: float = 0.0
    shadow: bool = False
    balanced: bool = True
    lay: Optional[TextLayout] = None
    h: float = 0.0


class Composer:
    def __init__(self, fonts: FontBook, fmt: Format, spec: DesignSpec, brief: Brief,
                 art_b64: Optional[str], art_cols: Sequence[str] = (), video: bool = False):
        self.fonts, self.fmt, self.spec, self.brief, self.video = fonts, fmt, spec, brief, video
        self.W, self.H = fmt.w, fmt.h
        self.short = min(self.W, self.H)
        self.sx0, self.sy0, self.sx1, self.sy1 = fmt.safe_rect()
        self.art_b64 = art_b64
        self.P = complete_palette(spec.palette, brief.brand, art_cols)
        self.tw = spec.tweaks
        self.cv = Canvas(self.W, self.H)
        self.copy = self._clean_copy(spec.copy)
        self.display = spec.display_font if spec.display_font in FONT_SOURCES or spec.display_font in fonts.extra else "anton"
        if brief.brand.display_font and brief.brand.display_font in (list(FONT_SOURCES) + list(fonts.extra)):
            self.display = brief.brand.display_font
        self.upper = spec.case == "upper"
        self.track = float(spec.tracking or 0.0)

    # copy -----------------------------------------------------------------
    @staticmethod
    def _clean_copy(c: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k, v in (c or {}).items():
            if k in ("contact", "items"):
                lst = v if isinstance(v, list) else [v]
                out[k] = [clean_text(str(x)) for x in lst if str(x).strip()]
            elif v:
                out[k] = "\n".join(clean_text(p) for p in str(v).split("\n"))
        return out

    def _text_color(self, kind: str) -> str:
        ov = (self.tw.get("text_color") or {}).get(kind)
        return ov if ov and valid_hex(ov) else self.P["text"]

    def _scale(self) -> float:
        return float(self.tw.get("size_scale", 1.0))

    # primitives -----------------------------------------------------------
    def _draw_text(self, it: _Item, x: float, y_top: float, w: float, align: str) -> Tuple[float, float, float, float]:
        face = self.fonts.face(it.face)
        lay = it.lay
        assert lay is not None
        parts: List[str] = []
        cx0, cx1 = 1e9, -1e9
        word_i = 0
        for i, ln in enumerate(lay.lines):
            lw = face.width(ln, lay.size, lay.tracking)
            lx = x if align == "left" else (x + w - lw if align == "right" else x + (w - lw) / 2)
            base = y_top + face.cap * lay.size + i * lay.size * lay.line_h
            cx0, cx1 = min(cx0, lx), max(cx1, lx + lw)
            if lay.hi:
                cur = lx
                for wd in ln.split():
                    col = self.P["accent"] if word_i in lay.hi else it.color
                    parts.append(f'<path d="{face.line_d(wd, lay.size, cur, base, lay.tracking)}" fill="{col}"/>')
                    cur += face.width(wd + " ", lay.size, lay.tracking)
                    word_i += 1
            else:
                parts.append(f'<path d="{face.line_d(ln, lay.size, lx, base, lay.tracking)}" fill="{it.color}"/>')
        flt = ""
        if it.shadow:
            flt = f' filter="url(#{self.cv.shadow(self.short * 0.010, self.short * 0.006, 0.5)})"'
        bbox = (cx0, y_top, cx1, y_top + lay.height)
        pad = lay.size * 0.35
        if self.tw.get("plate", {}).get(it.kind):
            self.cv.add("shape", f'<rect x="{_f(bbox[0] - pad)}" y="{_f(bbox[1] - pad * 0.7)}" width="{_f(bbox[2] - bbox[0] + 2 * pad)}" '
                                 f'height="{_f(bbox[3] - bbox[1] + pad * 1.2)}" rx="{_f(pad * 0.6)}" fill="{self.P["scrim"]}" '
                                 f'fill-opacity="0.62"/>', it.group)
        self.cv.add("text", f'<g{flt}>{"".join(parts)}</g>', it.group)
        self.cv.boxes.append({"kind": it.kind, "bbox": bbox, "color": it.color, "large": it.large,
                              "size": lay.size, "group": it.group})
        return bbox

    def _fit(self, it: _Item, w: float, scale: float) -> None:
        face = self.fonts.face(it.face)
        text = it.text.upper() if it.upper else it.text
        it.lay = fit_text(face, text, w, 1e9, max_size=it.max_size * scale, min_size=it.min_size * scale,
                          line_h=it.line_h, max_lines=it.max_lines, tracking=it.tracking, balanced=it.balanced)
        it.h = it.lay.height

    def _fit_button(self, it: _Item, w: float, scale: float) -> None:
        face = self.fonts.face("poppins_bold")
        size, floor = it.max_size * scale, it.min_size * scale * 0.7
        while face.width(it.text, size, it.tracking) + size * 2.2 > w and size > floor:
            size *= 0.94
        it.lay = TextLayout([it.text], size, face.width(it.text, size, it.tracking), size * 2.25, 1.0, it.tracking)

    def _button(self, it: _Item, x: float, y: float, w: float, align: str) -> Tuple[float, float, float, float]:
        face = self.fonts.face("poppins_bold")
        lay = it.lay
        assert lay is not None
        txt = lay.lines[0] if lay.lines else ""
        tw_ = face.width(txt, lay.size, lay.tracking)
        bw, bh = tw_ + lay.size * 2.2, lay.size * 2.25
        bx = x if align == "left" else (x + w - bw if align == "right" else x + (w - bw) / 2)
        fill = self.P["accent"]
        fg = on_color(fill)
        self.cv.add("shape", f'<rect x="{_f(bx)}" y="{_f(y)}" width="{_f(bw)}" height="{_f(bh)}" rx="{_f(bh / 2)}" fill="{fill}" '
                             f'filter="url(#{self.cv.shadow(self.short * 0.012, self.short * 0.008, 0.45)})"/>', it.group)
        ty = y + (bh - face.cap * lay.size) / 2
        self.cv.add("text", f'<path d="{face.line_d(txt, lay.size, bx + (bw - tw_) / 2, ty + face.cap * lay.size, lay.tracking)}" fill="{fg}"/>', it.group)
        self.cv.boxes.append({"kind": "cta", "bbox": (bx, y, bx + bw, y + bh), "color": fg, "large": True,
                              "size": lay.size, "group": it.group, "analytic": True})
        return (bx, y, bx + bw, y + bh)

    def stack(self, items: List[_Item], x: float, y0: float, y1: float, w: float, align: str = "left",
              valign: str = "center") -> Tuple[float, float]:
        items = [i for i in items if i.kind == "rule" or i.text]
        total, scale = 0.0, 1.0
        for scale in (1.0, 0.93, 0.86, 0.80, 0.74, 0.68, 0.62, 0.56, 0.5):
            sc = scale * self._scale()
            total = 0.0
            for it in items:
                if it.kind == "rule":
                    it.h = self.short * 0.010
                elif it.kind == "cta":
                    self._fit_button(it, w, sc)
                    it.h = it.lay.size * 2.25 if it.lay else 0
                else:
                    self._fit(it, w, sc)
                total += it.h + it.gap * sc
            total -= items[-1].gap * sc if items else 0
            if total <= (y1 - y0):
                break
        y = y0 if valign == "top" else (y1 - total if valign == "bottom" else y0 + max(0.0, (y1 - y0 - total) / 2))
        sc = scale * self._scale()
        for it in items:
            if it.kind == "rule":
                rw = self.short * 0.16
                rx = x if align == "left" else (x + w - rw if align == "right" else x + (w - rw) / 2)
                self.cv.add("shape", f'<rect x="{_f(rx)}" y="{_f(y)}" width="{_f(rw)}" height="{_f(it.h)}" rx="{_f(it.h / 2)}" fill="{self.P["accent"]}"/>', it.group)
            elif it.kind == "cta":
                self._button(it, x, y, w, align)
            else:
                self._draw_text(it, x, y, w, align)
            y += it.h + it.gap * sc
        return y0, y

    # elements --------------------------------------------------------------
    def _items(self, *, head_max: float, sub_max: float, kicker_max: float, cta_max: float,
               head_lines: int = 4, align_rule: bool = True, sub_lines: int = 3) -> List[_Item]:
        c, s = self.copy, self.short
        tc = self._text_color
        its: List[_Item] = []
        if c.get("kicker"):
            its.append(_Item("kicker", c["kicker"], "poppins_bold", kicker_max, kicker_max * 0.7, 1, 1.2, 0.16,
                             self.P["accent"], True, 0, False, s * 0.018))
        if c.get("headline"):
            its.append(_Item("headline", c["headline"], self.display, head_max, head_max * 0.55, head_lines, 1.02,
                             self.track, tc("headline"), self.upper, 0, True, s * 0.022, True))
        if align_rule:
            its.append(_Item("rule", gap=s * 0.026, group=0))
        if c.get("sub"):
            its.append(_Item("sub", c["sub"], "poppins_semibold", sub_max, sub_max * 0.75, sub_lines, 1.3, 0.0,
                             tc("sub"), False, 1, False, s * 0.026, False, False))
        if c.get("offer"):
            its.append(_Item("offer", c["offer"], "poppins_bold", sub_max * 1.15, sub_max * 0.8, 2, 1.2, 0.0,
                             self.P["accent"], False, 1, True, s * 0.03, False, False))
        if c.get("cta"):
            its.append(_Item("cta", c["cta"], "poppins_bold", cta_max, cta_max * 0.75, 1, 1.0, 0.02, self.P["accent"], False, 2))
        return its

    def scrim(self, mode: str, strength: float) -> None:
        col = self.P["scrim"]
        strength = min(0.95, strength + float(self.tw.get("scrim_boost", 0.0)))
        cv, W, H = self.cv, self.W, self.H
        reach = min(1.0, 0.62 + float(self.tw.get("scrim_boost", 0.0)))

        def lin(x1: int, y1: int, x2: int, y2: int, stops: List[Tuple[float, float]]) -> None:
            gid = cv.uid("g")
            cv.defs.append(f'<linearGradient id="{gid}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}">' + "".join(
                f'<stop offset="{o}" stop-color="{col}" stop-opacity="{round(a, 3)}"/>' for o, a in stops) + "</linearGradient>")
            cv.add("shade", f'<rect width="{W}" height="{H}" fill="url(#{gid})"/>')

        if mode == "left":
            lin(0, 0, 1, 0, [(0, strength), (reach * 0.55, strength * 0.82), (reach, strength * 0.25), (1, 0)])
        elif mode == "right":
            lin(1, 0, 0, 0, [(0, strength), (reach * 0.55, strength * 0.82), (reach, strength * 0.25), (1, 0)])
        elif mode == "bottom":
            lin(0, 1, 0, 0, [(0, strength), (reach * 0.5, strength * 0.8), (reach, strength * 0.2), (1, 0)])
        elif mode == "top":
            lin(0, 0, 0, 1, [(0, strength), (reach * 0.5, strength * 0.8), (reach, strength * 0.2), (1, 0)])
        elif mode == "both":
            lin(0, 0, 0, 1, [(0, strength * 0.95), (0.34, strength * 0.35), (0.5, 0)])
            lin(0, 1, 0, 0, [(0, strength), (0.38, strength * 0.45), (0.62, 0)])
        elif mode == "full":
            cv.add("shade", f'<rect width="{W}" height="{H}" fill="{col}" fill-opacity="{round(strength * 0.6, 3)}"/>')
        gid = cv.uid("v")                              # gentle vignette for depth
        cv.defs.append(f'<radialGradient id="{gid}" cx="0.5" cy="0.5" r="0.75"><stop offset="0.55" stop-color="{col}" stop-opacity="0"/>'
                       f'<stop offset="1" stop-color="{col}" stop-opacity="0.38"/></radialGradient>')
        cv.add("shade", f'<rect width="{W}" height="{H}" fill="url(#{gid})"/>')

    def logo(self, x: float, y: float, max_w: float, max_h: float, align: str = "left") -> Tuple[float, float, float, float]:
        b = self.brief.brand
        lp = Path(b.logo_path) if b.logo_path else None
        if lp and lp.exists():
            try:
                if lp.suffix.lower() == ".svg":
                    data, mime = lp.read_bytes(), "image/svg+xml"
                    m = re.search(rb'viewBox="[\d.\-]+ [\d.\-]+ ([\d.]+) ([\d.]+)"', data)
                    iw, ih = (float(m.group(1)), float(m.group(2))) if m else (1.0, 1.0)
                else:
                    from PIL import Image
                    im = Image.open(lp)
                    iw, ih = im.size
                    data, mime = lp.read_bytes(), f"image/{'png' if lp.suffix.lower() == '.png' else 'jpeg'}"
                s = min(max_w / iw, max_h / ih)
                w, h = iw * s, ih * s
                lx = x if align == "left" else (x + max_w - w if align == "right" else x + (max_w - w) / 2)
                self.cv.add("shape", f'<image href="data:{mime};base64,{base64.b64encode(data).decode()}" x="{_f(lx)}" y="{_f(y)}" '
                                     f'width="{_f(w)}" height="{_f(h)}"/>', 0)
                self.cv.boxes.append({"kind": "logo", "bbox": (lx, y, lx + w, y + h), "color": "#FFFFFF", "large": True,
                                      "size": h, "group": 0, "analytic": True})
                return (lx, y, lx + w, y + h)
            except Exception as e:
                log.warning("logo failed (%r), using wordmark", e)
        it = _Item("brand", b.name, self.display, max_h * 0.62, max_h * 0.3, 1, 1.0, 0.04, self._text_color("brand"), True, 0, True)
        self._fit(it, max_w, 1.0)
        return self._draw_text(it, x, y, max_w, align)

    def badge(self, cx: float, cy: float, r: float, text: str) -> None:
        if not text:
            return
        cv = self.cv
        n, pts = 18, []
        for i in range(n * 2):
            ang = math.pi * i / n - math.pi / 2 + math.radians(-8)
            rad = r if i % 2 == 0 else r * 0.88
            pts.append(f"{_f(cx + rad * math.cos(ang))},{_f(cy + rad * math.sin(ang))}")
        fill = self.P["accent"]
        cv.add("shape", f'<polygon points="{" ".join(pts)}" fill="{fill}" filter="url(#{cv.shadow(self.short * 0.014, self.short * 0.01, 0.5)})"/>', 1)
        cv.add("shape", f'<circle cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(r * 0.78)}" fill="none" stroke="{on_color(fill)}" stroke-opacity="0.35" stroke-width="{_f(max(2.0, r * 0.02))}"/>', 1)
        fg = on_color(fill)
        lines = [ln for ln in text.split("\n") if ln.strip()][:3]
        inner_w, face_key = r * 1.25, self.display
        its = []
        for k, ln in enumerate(lines):
            its.append(_Item("badge_text", ln, face_key if k == 0 else "poppins_bold", r * (0.62 if k == 0 else 0.3),
                             r * 0.18, 1, 1.0, 0.01, fg, k == 0 and self.upper, 1, True, r * 0.06))
        total = 0.0
        for it in its:
            self._fit(it, inner_w, 1.0)
            total += it.h + it.gap
        total -= its[-1].gap
        y = cy - total / 2
        for it in its:
            self._draw_text(it, cx - inner_w / 2, y, inner_w, "center")
            y += it.h + it.gap

    def contact(self, x0: float, x1: float, y_bottom: float, align: str = "left", color: Optional[str] = None,
                size: Optional[float] = None) -> float:
        entries = (self.copy.get("contact") or [])[:4]
        if not entries:
            return y_bottom
        size = (size if size else self.short * 0.026) * self._scale()
        face = self.fonts.face("poppins_semibold")
        col = color or self._text_color("contact")
        gap, icon = size * 1.6, size * 1.25
        widths = [icon + size * 0.5 + face.width(e, size) for e in entries]
        rows: List[List[int]] = [[]]
        cur = 0.0
        for i, wd in enumerate(widths):
            if rows[-1] and cur + gap + wd > (x1 - x0):
                rows.append([])
                cur = 0.0
            rows[-1].append(i)
            cur += wd + gap
        row_h = size * 2.0
        y = y_bottom - row_h * len(rows)
        for row in rows:
            rw = sum(widths[i] for i in row) + gap * (len(row) - 1)
            x = x0 if align == "left" else (x1 - rw if align == "right" else x0 + ((x1 - x0) - rw) / 2)
            ty = y + (row_h - face.cap * size) / 2
            for i in row:
                kind = _contact_kind(entries[i])
                if kind == "at":
                    self.cv.add("text", f'<path d="{face.line_d("@", icon, x, ty + face.cap * size + (icon - size) * 0.2)}" fill="{self.P["accent"]}"/>', 2)
                else:
                    self.cv.add("shape", f'<path transform="translate({_f(x)} {_f(y + (row_h - icon) / 2)}) scale({_f(icon / 24)})" d="{_icon_path(kind)}" fill="{self.P["accent"]}"/>', 2)
                tx = x + icon + size * 0.5
                self.cv.add("text", f'<path d="{face.line_d(entries[i], size, tx, ty + face.cap * size)}" fill="{col}"/>', 2)
                self.cv.boxes.append({"kind": "contact", "bbox": (tx, ty, tx + face.width(entries[i], size), ty + face.cap * size + size * 0.22),
                                      "color": col, "large": False, "size": size, "group": 2})
                x += widths[i] + gap
            y += row_h
        return y_bottom - row_h * len(rows)

    def ornament(self) -> None:
        kind, cv, s = self.spec.ornament, self.cv, self.short
        P = self.P
        if kind == "dots":
            step, r = s * 0.032, s * 0.0042
            x0, y0 = (self.W - self.sx0 - s * 0.26, self.sy1 - s * 0.26) if self.spec.align != "right" else (self.sx0, self.sy1 - s * 0.26)
            dots = "".join(f'<circle cx="{_f(x0 + i * step)}" cy="{_f(y0 + j * step)}" r="{_f(r)}"/>' for i in range(8) for j in range(8))
            cv.add("shape", f'<g fill="{P["text"]}" fill-opacity="0.22">{dots}</g>')
        elif kind == "lines":
            for k in range(3):
                x = self.W * (0.62 + k * 0.055)
                cv.add("shape", f'<line x1="{_f(x)}" y1="{_f(-s * 0.05)}" x2="{_f(x - s * 0.34)}" y2="{_f(self.H * 1.05)}" stroke="{P["accent"]}" stroke-opacity="{0.55 - k * 0.15}" stroke-width="{_f(s * (0.006 + k * 0.004))}"/>')
        elif kind == "frame":
            m = s * 0.03
            cv.add("shape", f'<rect x="{_f(m)}" y="{_f(m)}" width="{_f(self.W - 2 * m)}" height="{_f(self.H - 2 * m)}" fill="none" stroke="{P["text"]}" stroke-opacity="0.55" stroke-width="{_f(max(2.0, s * 0.003))}"/>')
            for (cx, cy, dx, dy) in ((m, m, 1, 1), (self.W - m, m, -1, 1), (m, self.H - m, 1, -1), (self.W - m, self.H - m, -1, -1)):
                L = s * 0.05
                cv.add("shape", f'<path d="M{_f(cx)} {_f(cy + dy * L)}V{_f(cy)}H{_f(cx + dx * L)}" fill="none" stroke="{P["accent"]}" stroke-width="{_f(s * 0.007)}"/>')
        elif kind == "burst":
            cx, cy = self.W * (0.72 if self.spec.align != "right" else 0.28), self.H * 0.46
            rays = "".join(f'<polygon points="{_f(cx)},{_f(cy)} {_f(cx + math.cos(a) * self.W * 1.3)},{_f(cy + math.sin(a) * self.W * 1.3)} {_f(cx + math.cos(a + 0.09) * self.W * 1.3)},{_f(cy + math.sin(a + 0.09) * self.W * 1.3)}"/>' for a in [i * math.pi / 9 for i in range(18)])
            cv.add("shape", f'<g fill="{P["accent"]}" fill-opacity="0.10">{rays}</g>')
        elif kind == "stripes":
            for k in range(3):
                x = self.W * 0.0 - s * 0.2 + k * s * 0.05
                cv.add("shape", f'<polygon points="{_f(x)},{_f(self.H * 0.88)} {_f(x + s * 0.12)},{_f(self.H * 0.88)} {_f(x + s * 0.30)},{_f(self.H)} {_f(x + s * 0.18)},{_f(self.H)}" fill="{P["accent"]}" fill-opacity="{0.95 - k * 0.25}"/>')

    def grain(self, strength: float = 0.07) -> None:
        fid = self.cv.uid("gr")
        self.cv.defs.append(f'<filter id="{fid}" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency="0.85" '
                            f'numOctaves="2" seed="7" result="n"/><feColorMatrix type="saturate" values="0"/><feComponentTransfer>'
                            f'<feFuncA type="linear" slope="{strength}"/></feComponentTransfer></filter>')
        self.cv.add("fx", f'<rect width="{self.W}" height="{self.H}" filter="url(#{fid})"/>')

    def place_product(self, x0: float, y0: float, x1: float, y1: float) -> None:
        """Composite the client's real product cut-out (transparent PNG) with glow, contact shadow and drop shadow."""
        path = self.brief.product_image
        if not path or not Path(path).exists():
            return
        from PIL import Image
        im = Image.open(path).convert("RGBA")
        bb = im.getchannel("A").getbbox()
        if bb:
            im = im.crop(bb)
        zw, zh = x1 - x0, y1 - y0
        k = min(zw / im.width, zh / im.height)
        w, h = im.width * k, im.height * k
        px, py = x0 + (zw - w) / 2, y0 + (zh - h) / 2
        if max(im.size) > 1600:
            f = 1600 / max(im.size)
            im = im.resize((int(im.width * f), int(im.height * f)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)
        cv, P = self.cv, self.P
        gid, bid = cv.uid("pg"), cv.uid("bl")
        cv.defs.append(f'<radialGradient id="{gid}" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="{P["accent"]}" stop-opacity="0.34"/>'
                       f'<stop offset="1" stop-color="{P["accent"]}" stop-opacity="0"/></radialGradient>')
        cv.defs.append(f'<filter id="{bid}" x="-30%" y="-300%" width="160%" height="700%"><feGaussianBlur stdDeviation="{_f(self.short * 0.012)}"/></filter>')
        cx, cy = px + w / 2, py + h / 2
        r = max(w, h) * 0.78
        cv.add("shape", f'<circle cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(r)}" fill="url(#{gid})"/>')
        cv.add("shape", f'<ellipse cx="{_f(cx)}" cy="{_f(py + h - h * 0.01)}" rx="{_f(w * 0.40)}" ry="{_f(max(6.0, h * 0.045))}" fill="#000" fill-opacity="0.55" filter="url(#{bid})"/>')
        cv.add("shape", f'<image href="data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}" x="{_f(px)}" y="{_f(py)}" '
                        f'width="{_f(w)}" height="{_f(h)}" preserveAspectRatio="xMidYMid meet" '
                        f'filter="url(#{cv.shadow(self.short * 0.018, self.short * 0.012, 0.45)})"/>')
        cv.boxes.append({"kind": "product", "bbox": (px, py, px + w, py + h), "color": "#FFFFFF", "large": True,
                         "size": h, "group": None, "analytic": True})

    # recipes ---------------------------------------------------------------
    def build(self) -> Canvas:
        cv, W, H, s = self.cv, self.W, self.H, self.short
        cv.add("art", f'<rect width="{W}" height="{H}" fill="{self.P["bg"]}"/>')
        if self.art_b64:
            cv.add("art", f'<image href="data:image/jpeg;base64,{self.art_b64}" x="0" y="0" width="{W}" height="{H}" preserveAspectRatio="xMidYMid slice"/>')
        recipe = self.spec.recipe
        ratio = W / H
        if recipe == "banner_wide" and ratio < 2.2:
            recipe = "hero"
        if recipe == "story_stack" and ratio > 0.7:
            recipe = "hero"
        getattr(self, "_r_" + {"hero": "hero", "poster_center": "poster", "split_panel": "split", "price_burst": "price",
                               "banner_wide": "banner", "story_stack": "story", "menu": "menu"}.get(recipe, "hero"))()
        self.ornament()
        self.grain(0.07)
        return cv

    def _hero(self) -> None:
        W, H, s = self.W, self.H, self.short
        right = self.spec.align == "right"
        self.scrim("right" if right else "left", 0.80)
        sw = self.sx1 - self.sx0
        has_p = bool(self.brief.product_image and Path(self.brief.product_image).exists())
        py0 = H * (0.27 if self.copy.get("badge") else 0.16)
        if right:
            self.place_product(self.sx0, py0, self.sx0 + sw * 0.46, H * 0.84)
        else:
            self.place_product(self.sx0 + sw * 0.52, py0, self.sx1, H * 0.84)
        col_w = sw * (0.46 if has_p else (0.52 if W / H > 1.25 else 0.64))
        x = self.sx1 - col_w if right else self.sx0
        lh = s * 0.075
        self.logo(x, self.sy0, col_w * 0.7, lh, "left")
        bottom = self.contact(x, x + col_w, self.sy1, "left")
        its = self._items(head_max=s * 0.135, sub_max=s * 0.036, kicker_max=s * 0.026, cta_max=s * 0.034)
        self.stack(its, x, self.sy0 + lh + s * 0.04, bottom - s * 0.03, col_w, "left", "center")
        if self.copy.get("badge"):
            r = s * 0.115
            self.badge(self.sx0 + r if right else self.sx1 - r, self.sy0 + r * 1.1, r, self.copy["badge"])

    def _r_hero(self) -> None:
        self._hero()

    def _r_poster(self) -> None:
        W, H, s = self.W, self.H, self.short
        top = self.spec.scrim == "top"
        self.scrim("top" if top else "bottom", 0.82)
        sw = self.sx1 - self.sx0
        if top:
            self.place_product(self.sx0 + sw * 0.1, H * 0.40, self.sx1 - sw * 0.1, H * 0.80)
        else:
            self.place_product(self.sx0 + sw * 0.1, H * 0.10, self.sx1 - sw * 0.1, H * 0.50)
        lh = s * 0.07
        self.logo(self.sx0, self.sy0, sw * 0.5, lh, "center" if False else "left")
        bottom = self.contact(self.sx0, self.sx1, self.sy1, "center")
        its = self._items(head_max=s * 0.15, sub_max=s * 0.037, kicker_max=s * 0.027, cta_max=s * 0.036)
        if top:
            self.stack(its, self.sx0, self.sy0 + lh + s * 0.03, self.sy0 + (self.sy1 - self.sy0) * 0.62, sw, "center", "top")
        else:
            self.stack(its, self.sx0, self.sy0 + (self.sy1 - self.sy0) * 0.34, bottom - s * 0.03, sw, "center", "bottom")
        if self.copy.get("badge"):
            r = s * 0.12
            self.badge(self.sx1 - r, (self.sy0 + r * 1.1) if not top else (self.sy1 - r * 1.8), r, self.copy["badge"])

    def _r_split(self) -> None:
        W, H, s = self.W, self.H, self.short
        right = self.spec.align == "right"
        pw, slant = W * 0.54, W * 0.07
        pts = [(0, 0), (pw, 0), (pw - slant, H), (0, H)]
        if right:
            pts = [(W - x, y) for x, y in pts]
        gid = self.cv.uid("pn")
        self.cv.defs.append(f'<linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{mix_hex(self.P["primary"], "#FFFFFF", 0.10)}"/>'
                            f'<stop offset="1" stop-color="{mix_hex(self.P["primary"], "#000000", 0.30)}"/></linearGradient>')
        self.cv.add("shape", f'<polygon points="{" ".join(f"{_f(x)},{_f(y)}" for x, y in pts)}" fill="url(#{gid})" '
                             f'filter="url(#{self.cv.shadow(s * 0.02, 0, 0.5)})"/>')
        fg = on_color(self.P["primary"])
        self.P = dict(self.P, text=fg)
        if right:
            self.place_product(W * 0.05, H * 0.20, W - pw - W * 0.02, H * 0.80)
        else:
            self.place_product(pw + W * 0.02, H * 0.20, W * 0.95, H * 0.80)
        col_w = pw - slant - (self.sx0 * 1.0) - s * 0.03
        x = (W - pw + slant + s * 0.03) if right else self.sx0
        lh = s * 0.07
        self.logo(x, self.sy0, col_w * 0.7, lh, "left")
        bottom = self.contact(x, x + col_w, self.sy1, "left", fg)
        its = self._items(head_max=s * 0.125, sub_max=s * 0.034, kicker_max=s * 0.025, cta_max=s * 0.032)
        self.stack(its, x, self.sy0 + lh + s * 0.04, bottom - s * 0.03, col_w, "left", "center")
        if self.copy.get("badge"):
            r = s * 0.11
            self.badge((W - pw / 2 if right else pw + (W - pw) / 2) * (1 if not right else 1) if False else (pw + (W - pw) * 0.5 if not right else (W - pw) * 0.5), self.sy1 - r * 1.5, r, self.copy["badge"])

    def _r_price(self) -> None:
        W, H, s = self.W, self.H, self.short
        self.scrim("both", 0.82)
        sw = self.sx1 - self.sx0
        self.place_product(self.sx0 + sw * 0.08, H * 0.20, self.sx1 - sw * 0.08, H * 0.62)
        lh = s * 0.065
        self.logo(self.sx0, self.sy0, sw * 0.4, lh, "left")
        c = dict(self.copy)
        head = _Item("headline", c.get("headline", ""), self.display, s * 0.14, s * 0.07, 2, 1.0, self.track, self._text_color("headline"), self.upper, 0, True, 0, True)
        if head.text:
            self._fit(head, sw * 0.9, self._scale())
            self._draw_text(head, self.sx0, self.sy0 + lh + s * 0.03, sw, "left")
        bottom = self.contact(self.sx0, self.sx1, self.sy1, "left")
        low = [i for i in self._items(head_max=1, sub_max=s * 0.034, kicker_max=s * 0.024, cta_max=s * 0.034, align_rule=False) if i.kind in ("sub", "cta")]
        self.stack(low, self.sx0, bottom - s * 0.30, bottom - s * 0.03, sw * 0.58, "left", "bottom")
        if c.get("badge"):
            r = s * 0.20
            self.badge(self.sx1 - r * 0.95, bottom - r * 1.05 - s * 0.02, r, c["badge"])

    def _r_banner(self) -> None:
        W, H = self.W, self.H
        self.scrim("left", 0.84)
        sw = self.sx1 - self.sx0
        self.place_product(W * 0.66, self.sy0, self.sx1, self.sy1)
        lw = sw * 0.20
        self.logo(self.sx0, self.sy0 + (self.sy1 - self.sy0 - H * 0.30) / 2, lw, H * 0.30, "left")
        cx0, cw = self.sx0 + lw + sw * 0.04, sw * 0.46
        its = [i for i in self._items(head_max=H * 0.24, sub_max=H * 0.075, kicker_max=H * 0.058, cta_max=H * 0.08, head_lines=2, align_rule=False, sub_lines=2)
               if i.kind in ("kicker", "headline", "sub")]
        self.stack(its, cx0, self.sy0, self.sy1, cw, "left", "center")
        rx0 = cx0 + cw + sw * 0.03
        rw = self.sx1 - rx0
        right_items = [i for i in self._items(head_max=1, sub_max=1, kicker_max=1, cta_max=H * 0.085, align_rule=False) if i.kind == "cta"]
        if right_items and rw > 0:
            self.stack(right_items, rx0, self.sy0, self.sy1 - (H * 0.17 if self.copy.get("contact") else 0), rw, "right", "center")
        if self.copy.get("contact"):
            self.copy["contact"] = self.copy["contact"][:2]
            self.contact(rx0, self.sx1, self.sy1, "right", size=H * 0.062)


    def _r_menu(self) -> None:
        W, H, s = self.W, self.H, self.short
        self.scrim("both", 0.84)
        sw = self.sx1 - self.sx0
        lh = s * 0.07
        self.logo(self.sx0, self.sy0, sw * 0.5, lh, "left")
        bottom = self.contact(self.sx0, self.sx1, self.sy1, "left")
        head = [i for i in self._items(head_max=s * 0.12, sub_max=s * 0.034, kicker_max=s * 0.026, cta_max=s * 0.034,
                                       head_lines=3, align_rule=False) if i.kind in ("kicker", "headline")]
        _, y_head = self.stack(head, self.sx0, self.sy0 + lh + s * 0.03, self.sy0 + (self.sy1 - self.sy0) * 0.32, sw, "left", "top")
        cta = [i for i in self._items(head_max=1, sub_max=1, kicker_max=1, cta_max=s * 0.034, align_rule=False) if i.kind == "cta"]
        cta_h = s * 0.034 * 2.25 + s * 0.03 if cta else 0.0
        y0, y1 = y_head + s * 0.035, bottom - s * 0.03 - cta_h
        items = (self.copy.get("items") or [])[:7]
        if items and y1 - y0 > s * 0.2:
            pad = s * 0.03
            n = len(items)
            row_h = min(s * 0.088, (y1 - y0 - 2 * pad) / n)
            card_h = row_h * n + 2 * pad
            cy = y0
            fill = mix_hex(self.P["primary"], "#000000", 0.28)
            fg = on_color(fill)
            self.cv.add("shape", f'<rect x="{_f(self.sx0)}" y="{_f(cy)}" width="{_f(sw)}" height="{_f(card_h)}" rx="{_f(s * 0.02)}" fill="{fill}" fill-opacity="0.94" '
                                 f'filter="url(#{self.cv.shadow(s * 0.016, s * 0.01, 0.45)})"/>')
            self.cv.add("shape", f'<rect x="{_f(self.sx0 + s * 0.02)}" y="{_f(cy)}" width="{_f(sw * 0.22)}" height="{_f(s * 0.007)}" rx="{_f(s * 0.0035)}" fill="{self.P["accent"]}"/>')
            fs = row_h * 0.40
            fnm, fpr = self.fonts.face("poppins_semibold"), self.fonts.face("poppins_bold")
            for k, raw in enumerate(items):
                m = re.match(r"^(.*?)\s*(?:[-\u2013\u2014:|]|\.{2,})\s*((?:\u20A6|N(?=\d))?\s?\d[\d,\.]*.*)$", raw)
                name, price = (m.group(1).strip(), m.group(2).strip()) if m else (raw, "")
                base = cy + pad + k * row_h + (row_h + fnm.cap * fs) / 2
                x0, x1 = self.sx0 + pad, self.sx1 - pad
                pw = fpr.width(price, fs) if price else 0.0
                avail = (x1 - x0) - pw - fs * 1.2
                size = fs
                while fnm.width(name, size) > avail and size > fs * 0.6:
                    size *= 0.94
                nw = fnm.width(name, size)
                self.cv.add("text", f'<path d="{fnm.line_d(name, size, x0, base)}" fill="{fg}"/>')
                self.cv.boxes.append({"kind": "item", "bbox": (x0, base - fnm.cap * size, x0 + nw, base + size * 0.22), "color": fg, "large": False, "size": size, "group": None})
                if price:
                    self.cv.add("text", f'<path d="{fpr.line_d(price, fs, x1 - pw, base)}" fill="{self.P["accent"]}"/>')
                    self.cv.boxes.append({"kind": "price", "bbox": (x1 - pw, base - fpr.cap * fs, x1, base + fs * 0.22), "color": self.P["accent"], "large": False, "size": fs, "group": None})
                    ly = base - fnm.cap * size * 0.35
                    self.cv.add("shape", f'<line x1="{_f(x0 + nw + fs * 0.5)}" y1="{_f(ly)}" x2="{_f(x1 - pw - fs * 0.5)}" y2="{_f(ly)}" stroke="{fg}" stroke-opacity="0.35" '
                                         f'stroke-width="{_f(max(2.0, fs * 0.09))}" stroke-dasharray="1 {_f(fs * 0.5)}" stroke-linecap="round"/>')
                if k < n - 1:
                    sy = cy + pad + (k + 1) * row_h
                    self.cv.add("shape", f'<line x1="{_f(x0)}" y1="{_f(sy)}" x2="{_f(x1)}" y2="{_f(sy)}" stroke="{fg}" stroke-opacity="0.12" stroke-width="{_f(max(1.0, s * 0.0012))}"/>')
            y_cta = cy + card_h + s * 0.03
        else:
            y_cta = y0
        if cta:
            self.stack(cta, self.sx0, y_cta, bottom - s * 0.02, sw, "left", "top")

    def _r_story(self) -> None:
        W, H, s = self.W, self.H, self.short
        self.scrim("both", 0.84)
        sw = self.sx1 - self.sx0
        self.place_product(self.sx0 + sw * 0.05, H * 0.37, self.sx1 - sw * 0.05, H * 0.63)
        lh = s * 0.07
        self.logo(self.sx0, self.sy0, sw * 0.5, lh, "left")
        its = self._items(head_max=s * 0.15, sub_max=s * 0.04, kicker_max=s * 0.028, cta_max=s * 0.04)
        top_items = [i for i in its if i.kind in ("kicker", "headline", "rule")]
        low_items = [i for i in its if i.kind in ("sub", "offer", "cta")]
        bottom = self.contact(self.sx0, self.sx1, self.sy1, "left")
        self.stack(top_items, self.sx0, self.sy0 + lh + s * 0.03, self.sy0 + (self.sy1 - self.sy0) * 0.42, sw, "left", "top")
        self.stack(low_items, self.sx0, bottom - (self.sy1 - self.sy0) * 0.32, bottom - s * 0.03, sw * 0.86, "left", "bottom")
        if self.copy.get("badge"):
            r = s * 0.12
            self.badge(self.sx1 - r, self.sy0 + (self.sy1 - self.sy0) * 0.5, r, self.copy["badge"])


# ── LINT: deterministic quality gates ──────────────────────────────────────────
@dataclass
class Issue:
    kind: str
    severity: str          # error | warn
    target: str
    detail: str
    fix: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.severity}] {self.kind}/{self.target}: {self.detail}"


_TEXTY = {"headline", "kicker", "sub", "offer", "contact", "brand", "fine", "item", "price"}


def lint_layout(cv: Canvas, base_png: bytes, fmt: Format, scale: float = 1.0) -> List[Issue]:
    """base_png may be rendered at a reduced `scale` for speed (print formats)."""
    import numpy as np
    from PIL import Image
    issues: List[Issue] = []
    arr = np.asarray(Image.open(io.BytesIO(base_png)).convert("RGB")).astype("float64") / 255.0
    lin = np.where(arr <= 0.03928, arr / 12.92, ((arr + 0.055) / 1.055) ** 2.4)
    lum = 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]
    short = min(fmt.w, fmt.h)
    sc = scale
    sx0, sy0, sx1, sy1 = fmt.safe_rect()
    tol = short * 0.015
    for b in cv.boxes:
        x0, y0, x1, y1 = b["bbox"]
        if b["kind"] in _TEXTY and not b.get("analytic"):
            ix0, iy0, ix1, iy1 = int(max(0, x0 * sc)), int(max(0, y0 * sc)), int(min(lum.shape[1], x1 * sc)), int(min(lum.shape[0], y1 * sc))
            if ix1 - ix0 > 2 and iy1 - iy0 > 2:
                reg = lum[iy0:iy1, ix0:ix1]
                lf = luminance(hex_to_rgb(b["color"]))
                worst = float(np.percentile(reg, 92)) if lf > float(reg.mean()) else float(np.percentile(reg, 8))
                ratio = contrast_ratio(lf, worst)
                need = 3.0 if b.get("large") else 4.5
                if ratio < need:
                    issues.append(Issue("contrast", "error" if ratio < need * 0.8 else "warn", b["kind"],
                                        f"{ratio:.1f}:1, needs {need}:1", {"block": b["kind"], "ratio": ratio}))
        if x0 < sx0 - tol or x1 > sx1 + tol or y0 < sy0 - tol or y1 > sy1 + tol:
            if b["kind"] not in ("badge_text",):
                issues.append(Issue("safe_zone", "warn", b["kind"], "outside the platform safe area", {"block": b["kind"]}))
    solid = [b for b in cv.boxes if b["kind"] in _TEXTY | {"cta", "logo", "badge_text", "product"}]
    for i in range(len(solid)):
        for j in range(i + 1, len(solid)):
            a, c = solid[i]["bbox"], solid[j]["bbox"]
            ox, oy = min(a[2], c[2]) - max(a[0], c[0]), min(a[3], c[3]) - max(a[1], c[1])
            if ox > 0 and oy > 0:
                small = min((a[2] - a[0]) * (a[3] - a[1]), (c[2] - c[0]) * (c[3] - c[1]))
                if small > 0 and ox * oy / small > 0.08:
                    issues.append(Issue("overlap", "error", f"{solid[i]['kind']}+{solid[j]['kind']}", "elements overlap",
                                        {"block": solid[j]["kind"]}))
    heads = [b for b in cv.boxes if b["kind"] == "headline"]
    subs = [b for b in cv.boxes if b["kind"] == "sub"]
    if heads and heads[0]["size"] < short * 0.045 and fmt.ratio < 2.2:
        issues.append(Issue("min_size", "warn", "headline", f"headline is only {heads[0]['size']:.0f}px", {"block": "headline"}))
    if heads and subs and heads[0]["size"] < subs[0]["size"] * 1.5:
        issues.append(Issue("hierarchy", "warn", "headline", "headline is not clearly bigger than the support line", {}))
    for b in cv.boxes:
        if b["kind"] == "contact" and b["size"] < short * 0.016:
            issues.append(Issue("min_size", "warn", "contact", f"contact text is only {b['size']:.0f}px", {}))
            break
    return issues


def apply_repairs(spec: DesignSpec, issues: List[Issue]) -> bool:
    """Mutates spec.tweaks. Order of escalation per block: stronger scrim, then a text plate, then flip colour."""
    changed = False
    lvl = spec.tweaks.setdefault("fix_level", {})
    for iss in issues:
        if iss.kind == "contrast":
            blk = iss.fix.get("block", iss.target)
            step = lvl.get(blk, 0)
            if step == 0:
                spec.tweaks["scrim_boost"] = min(0.4, float(spec.tweaks.get("scrim_boost", 0)) + 0.18)
            elif step == 1:
                spec.tweaks.setdefault("plate", {})[blk] = True
            elif step == 2:
                pal = complete_palette(spec.palette, BrandKit(name=""), [])
                spec.tweaks.setdefault("text_color", {})[blk] = on_color(pal["scrim"])
            else:
                continue
            lvl[blk] = step + 1
            changed = True
        elif iss.kind in ("overlap", "min_size") and spec.tweaks.get("size_scale", 1.0) > 0.7:
            spec.tweaks["size_scale"] = round(float(spec.tweaks.get("size_scale", 1.0)) * 0.9, 3)
            changed = True
    return changed


# ── COPY GUARD ─────────────────────────────────────────────────────────────────
_CLAIM_RE = re.compile(r"\b(100\s?%|guarantee[d]?|miracle|cures?|cured|instant(?:ly)?|risk[- ]free|lose \d+|no side effects|"
                       r"doctor[- ]approved|best in (?:nigeria|lagos|africa)|number one|#1)\b", re.I)
_SCARCITY_RE = re.compile(r"\b(only \d+|last chance|limited (?:stock|time|offer|slots?)|selling fast|hurry|while stock lasts|"
                          r"today only|ends (?:tonight|today|soon)|don'?t miss)\b", re.I)


def _digits_set(text: str) -> Set[str]:
    return {re.sub(r"\D", "", m) for m in re.findall(r"\d[\d,\s]*\d|\d", text) if len(re.sub(r"\D", "", m)) >= 2}


def copy_guard(copy: Dict[str, Any], brief: Brief) -> List[Issue]:
    issues: List[Issue] = []
    allowed_text = (brief.facts() + " " + brief.notes + " " + " ".join(brief.must_include)).lower()
    allowed_nums = _digits_set(allowed_text)
    for k, v in copy.items():
        vals = v if isinstance(v, list) else [v]
        for val in vals:
            sv = str(val)
            for n in _digits_set(sv):
                if n not in allowed_nums and not any(n in a for a in allowed_nums):
                    issues.append(Issue("ungrounded", "error", k, f"number '{n}' is not in the brief", {"field": k}))
            for rx, label in ((_CLAIM_RE, "claim"), (_SCARCITY_RE, "scarcity")):
                for m in rx.finditer(sv):
                    if m.group(0).lower() not in allowed_text:
                        issues.append(Issue(label, "error", k, f"'{m.group(0)}' was not supplied by the client", {"field": k}))
    words = lambda t: len(re.findall(r"\w+", t))
    hl = str(copy.get("headline", ""))
    if words(hl) > 9:
        issues.append(Issue("copy_length", "warn", "headline", f"{words(hl)} words, aim for 7 or fewer", {"field": "headline"}))
    total = sum(words(" ".join(map(str, v)) if isinstance(v, list) else str(v)) for v in copy.values())
    if total > 75:
        issues.append(Issue("copy_length", "warn", "copy", f"{total} words is too much text", {}))
    return issues


def strip_ungrounded(copy: Dict[str, Any], issues: List[Issue]) -> Dict[str, Any]:
    out = dict(copy)
    for iss in issues:
        if iss.severity == "error" and iss.kind in ("ungrounded", "claim", "scarcity"):
            f = iss.fix.get("field")
            if f in out and f != "headline":
                out.pop(f, None)
    return out


# ── ART BACKENDS ───────────────────────────────────────────────────────────────
class ArtBackend:
    """Paints the TEXT-FREE hero image. Returns encoded image bytes (PNG or JPEG)."""
    name = "art"

    def generate(self, prompt: str, *, width: int, height: int, refs: Sequence[bytes] = (),
                 seed: Optional[int] = None, palette: Optional[Dict[str, str]] = None) -> bytes:
        raise NotImplementedError


class MuseImageArt(ArtBackend):
    """Muse Image through the app's own Meta client (`agentic_sales.models.meta.MetaImage`): it takes a prompt and returns image bytes.
    Reference photos are not sent: the client has no edit endpoint, so product fidelity comes from compositing, not from the image model."""
    name = "muse_image"

    def __init__(self, client: Any):
        self.client = client

    def generate(self, prompt, *, width, height, refs=(), seed=None, palette=None) -> bytes:
        r = width / height
        size = "1024x1536" if r < 0.9 else ("1536x1024" if r > 1.1 else "1024x1024")
        return self.client.generate(prompt, size=size)

class FixedArt(ArtBackend):
    """The picture is one the owner supplied (a real photo of the product): nothing is drawn, so the item shown is exactly the item sold."""
    name = "owner_photo"

    def __init__(self, picture: bytes):
        self.picture = picture

    def generate(self, prompt, *, width, height, refs=(), seed=None, palette=None) -> bytes:
        """The photo fills the half of the canvas the text panel leaves free (the right half), so the product is never behind the words; the
        panel half is the same photo, blurred and darkened, which the panel then covers."""
        from PIL import Image, ImageEnhance, ImageFilter
        src = Image.open(io.BytesIO(self.picture)).convert("RGB")

        def cover(img: Any, w: int, h: int) -> Any:
            s = max(w / img.width, h / img.height)
            img = img.resize((max(w, int(img.width * s)), max(h, int(img.height * s))), Image.LANCZOS)
            left, top = (img.width - w) // 2, (img.height - h) // 2
            return img.crop((left, top, left + w, top + h))

        canvas = ImageEnhance.Brightness(cover(src, width, height).filter(ImageFilter.GaussianBlur(max(width, height) * 0.03))).enhance(0.55)
        # The whole photo, never sliced: fitted inside the free right side with a margin clear of the panel's diagonal edge and the badge.
        box_w, box_h = int(width * 0.47), int(height * 0.80)
        fit = min(box_w / src.width, box_h / src.height)
        shown = src.resize((max(1, int(src.width * fit)), max(1, int(src.height * fit))), Image.LANCZOS)
        from PIL import ImageDraw
        mask = Image.new("L", shown.size, 0)                         # soft edges, so the photo melts into its own blurred backdrop instead of floating as a tile
        inset = int(min(shown.size) * 0.07)
        ImageDraw.Draw(mask).rectangle([inset, inset, shown.width - inset, shown.height - inset], fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(inset * 0.8))
        canvas.paste(shown, (width - int(width * 0.015) - shown.width, int(height * 0.44 - shown.height / 2)), mask)
        out = io.BytesIO()
        canvas.save(out, "PNG")
        return out.getvalue()


class ArtRouter(ArtBackend):
    """Tries each art backend in order. Procedural art is always the last resort."""
    name = "art_router"

    def __init__(self, backends: Sequence[ArtBackend]):
        self.backends = list(backends)

    def generate(self, prompt, *, width, height, refs=(), seed=None, palette=None) -> bytes:
        last: Optional[BaseException] = None
        for b in self.backends:
            try:
                out = b.generate(prompt, width=width, height=height, refs=refs, seed=seed, palette=palette)
                log.info("art from %s", b.name)
                return out
            except Exception as e:
                last = e
                log.warning("art backend %s failed: %r", b.name, e)
        raise RuntimeError(f"no art backend worked: {last!r}")


class ProceduralArt(ArtBackend):
    """Offline fallback: palette-driven abstract backdrop (soft light, bokeh, rings, grain).
    Not photography, but never fails and keeps the pipeline testable without any API."""
    name = "procedural"

    def generate(self, prompt, *, width, height, refs=(), seed=None, palette=None) -> bytes:
        import numpy as np
        from PIL import Image, ImageDraw, ImageFilter
        pal = palette or {}
        rnd = random.Random(seed if seed is not None else hash(prompt) & 0xFFFF)
        scale = 1280 / max(width, height)
        w, h = max(64, int(width * scale)), max(64, int(height * scale))
        prim = hex_to_rgb(pal.get("primary", "#12343B"))
        acc = hex_to_rgb(pal.get("accent", "#F5B700"))
        bg = hex_to_rgb(pal.get("bg", "#0E0F12"))
        yy, xx = np.mgrid[0:h, 0:w]
        t = np.clip((xx / w) * 0.45 + (yy / h) * 0.55, 0, 1)[..., None]
        lo = np.array([bg[i] + (prim[i] - bg[i]) * 0.25 for i in range(3)])
        hi = np.array([bg[i] + (prim[i] - bg[i]) * 0.95 for i in range(3)])
        base = (lo * (1 - t) + hi * t).astype("uint8")
        img = Image.fromarray(base, "RGB").convert("RGBA")
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(glow)
        for _ in range(rnd.randint(5, 8)):
            r = rnd.uniform(0.08, 0.22) * max(w, h)
            cx, cy = rnd.uniform(0.35, 1.0) * w, rnd.uniform(0.0, 1.0) * h
            k = rnd.random()
            col = tuple(int(prim[i] * (1 - k) + acc[i] * k) for i in range(3))
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col + (rnd.randint(70, 150),))
        img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(max(w, h) * 0.05)))
        rings = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(rings)
        cx, cy = w * rnd.uniform(0.6, 0.85), h * rnd.uniform(0.35, 0.6)
        for i in range(4):
            r = max(w, h) * (0.14 + i * 0.07)
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=acc + (60 - i * 12,), width=max(2, int(w * 0.004)))
        img = Image.alpha_composite(img, rings.filter(ImageFilter.GaussianBlur(1.2)))
        streak = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(streak).polygon([(w * 0.55, 0), (w * 0.75, 0), (w * 0.35, h), (w * 0.15, h)], fill=(255, 255, 255, 28))
        img = Image.alpha_composite(img, streak.filter(ImageFilter.GaussianBlur(max(w, h) * 0.04)))
        out = io.BytesIO()
        img.convert("RGB").save(out, "PNG")
        return out.getvalue()


def prepare_art(raw: bytes, w: int, h: int, max_embed: int = 2600) -> Tuple[str, Any, List[str]]:
    """Cover-crop to the canvas, sharpen if upscaled, return (jpeg base64, PIL image, dominant colours)."""
    from PIL import Image, ImageFilter
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    tw, th = w, h
    if max(tw, th) > max_embed:
        k = max_embed / max(tw, th)
        tw, th = int(tw * k), int(th * k)
    s = max(tw / img.width, th / img.height)
    nw, nh = max(tw, int(img.width * s)), max(th, int(img.height * s))
    up = s > 1.0
    img = img.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - tw) // 2, (nh - th) // 2
    img = img.crop((left, top, left + tw, top + th))
    if up:
        img = img.filter(ImageFilter.UnsharpMask(radius=1.6, percent=45, threshold=3))
    from PIL import ImageEnhance                     # light finishing grade: a touch of punch, never garish
    img = ImageEnhance.Contrast(img).enhance(1.05)
    img = ImageEnhance.Color(img).enhance(1.04)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii"), img, art_palette(img)


# ── LLM ACCESS (Muse Spark through the app's models, or any callable) ────────────────
class FnLLM:
    """Wrap any async function as the studio's brain, for example your own Meta Muse client:
        async def fn(system, user, *, strong=True, max_tokens=4000, temperature=0.8) -> str
    Optionally pass vision(system, user, png_bytes) -> str so the vision critic can run."""

    def __init__(self, fn: Callable[..., Awaitable[str]], vision: Optional[Callable[..., Awaitable[str]]] = None):
        self.fn, self.vision = fn, vision


def muse_llm(text_model: Any, vision_model: Any = None) -> FnLLM:
    """The studio's brain from the app's own models: `text_model` and `vision_model` are anything with `.complete(ModelRequest)` (Muse Spark)."""
    from agentic_sales.models.base import Image, Message, ModelRequest

    def call(model: Any, system: str, user: str, max_tokens: int, temperature: float, images: tuple = ()) -> str:
        return model.complete(ModelRequest(system, (Message("user", user),), max_tokens=max_tokens, temperature=temperature, images=images)).text

    async def fn(system, user, *, strong=True, max_tokens=4000, temperature=0.8) -> str:
        return await asyncio.to_thread(call, text_model, system, user, max_tokens, temperature)

    async def vision(system, user, png: bytes) -> str:
        return await asyncio.to_thread(call, vision_model or text_model, system, user, 900, 0.2, (Image("image/png", png),))

    return FnLLM(fn, vision)


@dataclass
class _ImgAtt:
    data: bytes
    mime: str = "image/png"
    url: Optional[str] = None


async def ask_llm(llm: Any, system: str, user: str, *, strong: bool = True, max_tokens: int = 4000,
                  temperature: float = 0.8) -> str:
    if llm is None:
        raise RuntimeError("no LLM configured")
    if isinstance(llm, (list, tuple)):
        last: Optional[BaseException] = None
        for p in llm:
            try:
                return await ask_llm(p, system, user, strong=strong, max_tokens=max_tokens, temperature=temperature)
            except Exception as e:
                last = e
        raise RuntimeError(f"all LLM providers failed: {last!r}")
    if isinstance(llm, FnLLM):
        return await asyncio.wait_for(llm.fn(system, user, strong=strong, max_tokens=max_tokens, temperature=temperature), LLM_TIMEOUT)
    model = llm.strong_model if strong else llm.fast_model
    res = await asyncio.wait_for(
        llm.complete(system, [{"role": "user", "content": user}], model=model, max_tokens=max_tokens, temperature=temperature),
        LLM_TIMEOUT)
    return res.text


async def ask_vision(llm: Any, system: str, user: str, png: bytes) -> Optional[str]:
    """Returns None when the configured brain has no vision support."""
    if llm is None:
        return None
    if isinstance(llm, (list, tuple)):
        for p in llm:
            out = await ask_vision(p, system, user, png)
            if out:
                return out
        return None
    if isinstance(llm, FnLLM):
        return await asyncio.wait_for(llm.vision(system, user, png), LLM_TIMEOUT) if llm.vision else None
    if not hasattr(llm, "describe_image"):
        return None
    try:
        return await asyncio.wait_for(llm.describe_image(_ImgAtt(png), system + "\n\n" + user, max_tokens=900), LLM_TIMEOUT)
    except NotImplementedError:
        return None


def parse_json(raw: str) -> Optional[Dict[str, Any]]:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    i, j = raw.find("{"), raw.rfind("}")
    cand = raw[i:j + 1] if i != -1 and j > i else raw
    for attempt in (cand, re.sub(r",\s*([}\]])", r"\1", cand)):
        try:
            d = json.loads(attempt)
            if isinstance(d, dict):
                return d
        except Exception:
            continue
    try:
        import json_repair
        d = json_repair.loads(cand)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "design"


# ── DIRECTOR ───────────────────────────────────────────────────────────────────
Retriever = Callable[[str, str, int], List[Report]]


def fallback_direction(brief: Brief, fmt: Format, idx: int = 0) -> DesignSpec:
    """Deterministic direction used when the LLM is unavailable, so a client always gets a clean design."""
    b = brief.brand
    recipe = "banner_wide" if fmt.ratio >= 2.2 else ("story_stack" if fmt.ratio <= 0.6 else ("split_panel" if idx % 2 else "hero"))
    menu = brief.kind in ("flyer", "price_list", "menu") and len(brief.details) >= 3 and fmt.ratio < 1.3
    if menu:
        recipe = "menu"
    contact = [x for x in (b.phone or b.whatsapp, b.website, b.instagram, b.address) if x][:3]
    copy = {"kicker": b.tagline or "", "headline": brief.headline or brief.offer or b.name,
            "sub": (brief.details[0] if brief.details else (brief.offer if brief.headline else "")),
            "badge": brief.price or brief.date or "", "cta": brief.cta or "", "contact": contact,
            "date": brief.date, "venue": brief.venue, "items": brief.details[:7] if menu else []}
    return DesignSpec(
        name=f"clean-{idx + 1}", concept="Clear, confident, product-first layout",
        palette={"primary": b.colors[0] if b.colors else "#12343B", "accent": b.colors[1] if len(b.colors) > 1 else "#F5B700"},
        display_font="anton", recipe=recipe, align="left" if idx % 2 == 0 else "right",
        scrim="left" if idx % 2 == 0 else "right", ornament=["none", "lines", "frame"][idx % 3], copy=copy,
        art_prompt=(f"Premium advertising photograph for a {b.industry or 'Nigerian business'}, hero subject in sharp focus, "
                    f"cinematic soft lighting, shallow depth of field, rich contrast, modern, aspirational, authentic Lagos feel."),
        art_notes="left 45 percent")


def enforce_facts(spec: DesignSpec, brief: Brief) -> DesignSpec:
    """Facts are never retyped by a model. Contact lines, date, venue and the price badge come straight from the brief."""
    b, c = brief.brand, spec.copy
    contact = [x for x in (b.phone or b.whatsapp, b.website, b.instagram, b.address) if x]
    if contact:
        c["contact"] = contact[:4]
    elif "contact" in c:
        c["contact"] = []
    if brief.date:
        c["date"] = brief.date
    if brief.venue:
        c["venue"] = brief.venue
    if str(c.get("kicker") or "").strip().lower() == b.name.strip().lower():
        c["kicker"] = ""                                      # the business name is already printed as the brand mark
    badge = str(c.get("badge") or "")
    digits = lambda t: re.sub(r"\D", "", t)
    if badge and digits(badge) and brief.price and digits(badge) != digits(brief.price):
        c["badge"] = brief.price
    if brief.price and not c.get("badge") and spec.recipe in ("price_burst",):
        c["badge"] = brief.price
    return spec


class DesignDirector:
    def __init__(self, llm: Any, reports: Optional[Union[ReportStore, Retriever]] = None, k: int = 3):
        self.llm, self.k = llm, k
        self.retrieve: Optional[Retriever] = reports.retriever() if isinstance(reports, ReportStore) else reports

    def _refs(self, brief: Brief) -> str:
        if not self.retrieve:
            return ""
        q = " ".join([brief.kind, brief.brand.industry, brief.goal, brief.tone, brief.audience, brief.format, brief.brand.name])
        blocks: List[str] = []
        for src, title in (("art", "ART-DIRECTION REPORTS (visual concept, light, composition, prompt language)"),
                           ("layout", "SVG / LAYOUT REPORTS (grids, typography, vector composition)")):
            try:
                reps = self.retrieve(q, src, self.k)
            except Exception as e:
                log.warning("report retrieval failed: %r", e)
                reps = []
            if reps:
                blocks.append(title + "\n" + "\n---\n".join(f"[{r.title}]\n{r.text[:1100]}" for r in reps))
        return "\n\n".join(blocks)

    @staticmethod
    def _brief_text(brief: Brief, fmt: Format) -> str:
        b = brief.brand
        return (f"BRIEF\nKind: {brief.kind}\nFormat: {fmt.name} {fmt.w}x{fmt.h} ({fmt.note})\nGoal: {brief.goal or 'not stated'}\n"
                f"Audience: {brief.audience or 'general Nigerian consumers'}\nTone: {brief.tone or b.voice}\nLanguage: {brief.language}\n"
                f"Brand colours: {', '.join(b.colors) or 'none given'}\nBrand voice: {b.voice}\n"
                f"Avoid: {'; '.join(brief.avoid) or 'nothing specific'}\nProduct or people photos supplied as references: {'yes' if brief.assets else 'no'}\n"
                f"Product cut-out will be composited on top in vector: {'YES, so the art must contain NO product, only a styled empty set' if brief.product_image else 'no'}\n"
                f"Extra notes: {brief.notes or 'none'}\n\nSUPPLIED FACTS (the only facts you may use)\n{brief.facts()}")

    async def directions(self, brief: Brief, n: int = 2) -> List[DesignSpec]:
        fmt = FORMATS[brief.format]
        user = f"{self._brief_text(brief, fmt)}\n\nProduce {n} genuinely different directions.\n\n{self._refs(brief)}"
        try:
            data = parse_json(await ask_llm(self.llm, DIRECTOR_SYSTEM, user, strong=True, max_tokens=5000, temperature=0.9))
            specs = [DesignSpec.from_dict(d) for d in (data or {}).get("directions", []) if isinstance(d, dict)]
            if specs:
                return specs[:n]
            log.warning("director returned no usable directions")
        except Exception as e:
            log.warning("director failed (%r), using deterministic directions", e)
        return [fallback_direction(brief, fmt, i) for i in range(n)]

    async def proofread(self, copy: Dict[str, Any], brief: Brief) -> Dict[str, Any]:
        """Typos and grammar only. Rejected if any digit, brand name or the naira sign changed."""
        keys = ("headline", "kicker", "sub", "offer", "cta", "fine_print")
        sub = {k: copy[k] for k in keys if copy.get(k)}
        if not sub or self.llm is None:
            return copy
        try:
            data = parse_json(await ask_llm(self.llm, PROOF_SYSTEM, json.dumps(sub, ensure_ascii=False), strong=False, max_tokens=700, temperature=0.1))
        except Exception as e:
            log.warning("proofread skipped: %r", e)
            return copy
        if not data:
            return copy
        out = dict(copy)
        digits = lambda t: re.sub(r"\D", "", t)
        for k, v in data.items():
            if k in sub and isinstance(v, str) and v.strip():
                old = str(sub[k])
                if digits(v) == digits(old) and (NAIRA in old) == (NAIRA in v) and len(v) <= len(old) * 1.4 + 6:
                    if brief.brand.name.lower() in old.lower() and brief.brand.name.lower() not in v.lower():
                        continue
                    out[k] = v.strip()
        return out

    async def revise(self, spec: DesignSpec, brief: Brief, issues: Sequence[Union[Issue, str]]) -> DesignSpec:
        fmt = FORMATS[brief.format]
        cur = {"name": spec.name, "concept": spec.concept, "palette": spec.palette,
               "typography": {"display": spec.display_font, "body": spec.body_font, "case": spec.case, "tracking": spec.tracking},
               "art": {"prompt": spec.art_prompt, "negative_space": spec.art_notes},
               "layout": {"recipe": spec.recipe, "align": spec.align, "scrim": spec.scrim, "ornament": spec.ornament},
               "copy": spec.copy}
        user = (f"{self._brief_text(brief, fmt)}\n\nCURRENT DIRECTION\n{json.dumps(cur, ensure_ascii=False)}\n\nISSUES\n"
                + "\n".join(f"- {i}" for i in issues))
        try:
            data = parse_json(await ask_llm(self.llm, REVISE_SYSTEM, user, strong=True, max_tokens=3000, temperature=0.6))
            if data:
                new = DesignSpec.from_dict(data.get("directions", [data])[0] if "directions" in data else data)
                new.tweaks = dict(spec.tweaks)
                return new
        except Exception as e:
            log.warning("revise failed: %r", e)
        return spec


# ── CRITIC ─────────────────────────────────────────────────────────────────────
class Critic:
    def __init__(self, llm: Any):
        self.llm = llm

    async def review(self, png: bytes, brief: Brief) -> Optional[Dict[str, Any]]:
        from PIL import Image
        im = Image.open(io.BytesIO(png)).convert("RGB")
        if max(im.size) > 1400:
            k = 1400 / max(im.size)
            im = im.resize((int(im.width * k), int(im.height * k)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        user = f"Goal of this design: {brief.goal or 'attract and convert'}. Format: {brief.format}. Business: {brief.brand.name}."
        try:
            raw = await ask_vision(self.llm, CRITIC_SYSTEM, user, buf.getvalue())
        except Exception as e:
            log.warning("critic failed: %r", e)
            return None
        return parse_json(raw) if raw else None


# ── STUDIO ─────────────────────────────────────────────────────────────────────
def build_art_prompt(spec: DesignSpec, brief: Brief, fmt: Format, pal: Dict[str, str]) -> str:
    space = spec.art_notes or {"hero": "the left 45 percent" if spec.align != "right" else "the right 45 percent",
                               "poster_center": "the top 30 percent and the bottom 30 percent",
                               "split_panel": "the " + ("right" if spec.align == "right" else "left") + " 50 percent",
                               "price_burst": "the top 28 percent and the bottom 30 percent",
                               "banner_wide": "the left 60 percent",
                               "story_stack": "the top 25 percent and the bottom 32 percent"}.get(spec.recipe, "the left 45 percent")
    base = spec.art_prompt or (f"Premium advertising photograph for {brief.brand.name}, a {brief.brand.industry or 'Nigerian business'}, "
                               "hero subject in sharp focus, cinematic soft lighting, aspirational.")
    parts = [base,
             f"Composition: keep {space} calm, smooth and low-detail (soft gradient or out-of-focus background) so headline and buttons can be set there. Place the hero subject on the opposite side or centre, large and clear.",
             f"Aspect ratio {nearest_ratio(fmt.w, fmt.h)}." + (" The key subject must survive a tight centre-band crop." if fmt.ratio >= 2.2 else ""),
             f"Colour palette: {pal['primary']} dominant, {pal['accent']} accents, {pal['bg']} shadows. Cohesive grade.",
             "Photoreal, razor sharp, professional studio-quality lighting from one direction, rich contrast, natural skin tones, fine detail, shallow depth of field."]
    if brief.product_image:
        parts.append("IMPORTANT: do NOT draw the product. Build a styled empty set (podium, surface, backdrop, props kept subtle) with a clear, "
                     "well-lit empty area where a product will be placed afterwards, and a soft light pool and surface reflections that will suit it.")
    elif brief.assets:
        parts.append("The supplied reference photo(s) show the exact product or people: reproduce them faithfully (shape, colour, branding), do not redesign them.")
    if brief.avoid:
        parts.append("Avoid: " + "; ".join(brief.avoid) + ".")
    parts.append("Absolutely no text, no letters, no numbers, no logos, no watermarks, no UI elements, no borders and no frames anywhere in the image.")
    return " ".join(parts)


class ArtInspector:
    """Vision check of the generated art BEFORE typography: stray text or logos, warped products, broken hands or faces,
    and whether the area reserved for copy really is calm. Fails open (returns None) if the brain has no vision."""

    def __init__(self, llm: Any):
        self.llm = llm

    async def check(self, img: Any, spec: DesignSpec, brief: Brief) -> Optional[Dict[str, Any]]:
        im = img.copy()
        if max(im.size) > 1100:
            k = 1100 / max(im.size)
            im = im.resize((int(im.width * k), int(im.height * k)))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=85)
        user = (f"Area reserved for copy: {spec.art_notes or 'not specified'}. Layout recipe: {spec.recipe}. "
                f"Reference photos supplied: {'yes' if brief.assets else 'no'}. Product cut-out will be added later: {'yes' if brief.product_image else 'no'}.")
        try:
            raw = await ask_vision(self.llm, ART_INSPECTOR_SYSTEM, user, buf.getvalue())
        except Exception as e:
            log.warning("art inspector failed: %r", e)
            return None
        return parse_json(raw) if raw else None


@dataclass
class DesignResult:
    files: Dict[str, Path]
    spec: DesignSpec
    issues: List[Issue]
    score: float
    critic: Optional[Dict[str, Any]] = None
    alternates: List["DesignResult"] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    checked: bool = False                      # a critic actually rated it; an unchecked design has score 0 and never passes a benchmark

    def summary(self) -> str:
        bad = [str(i) for i in self.issues if i.severity == "error"]
        return (f"{self.spec.name}: score {self.score:.0f}, {self.spec.recipe}, "
                + ("clean" if not bad else f"{len(bad)} unresolved error(s)") + f", {len(self.alternates)} alternate(s)")


def auto_art(image_client: Any = None) -> ArtBackend:
    """Muse Image when a client is given, with the drawn backdrop as the last resort."""
    backends: List[ArtBackend] = [MuseImageArt(image_client)] if image_client is not None else []
    backends.append(ProceduralArt())
    return ArtRouter(backends) if len(backends) > 1 else backends[0]


class DesignStudio:
    def __init__(self, llm: Any, *, art: Optional[ArtBackend] = None, reports: Optional[ReportStore] = None,
                 retriever: Optional[Retriever] = None, fonts: Optional[FontBook] = None, critic: bool = True,
                 out_dir: Union[str, Path] = OUT_DIR, max_repairs: int = 3):
        self.llm = llm
        self.reports = reports or ReportStore()
        self.art = art or auto_art()
        self.fonts = fonts or FontBook()
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.director = DesignDirector(llm, retriever or self.reports)
        self.critic = Critic(llm) if critic and llm is not None else None
        self.inspector = ArtInspector(llm) if critic and llm is not None else None
        self.min_score = float(_env("DESIGN_MIN_SCORE", "90"))     # the benchmark: nothing below it is treated as finished
        self.rounds = 3
        self.fixed_recipe: Optional[str] = None                   # set when the picture is the owner's photo: it gets its own panel, never text over it
        self.art_retries = 1                                  # each picture is a slow call: one retry, then the layout copes (split panel)
        self.max_repairs = max_repairs
        self._sem = asyncio.Semaphore(2)

    # one direction -> one finished design ------------------------------------
    async def _paint(self, spec: DesignSpec, brief: Brief, fmt: Format, idx: int) -> Tuple[str, Any, List[str], List[str], bool]:
        """Paint the art, inspect it, and retry with the inspector's hint when it has stray text or defects.
        Returns (jpeg base64, image, palette, notes, flagged)."""
        notes: List[str] = []
        pal = complete_palette(spec.palette, brief.brand, [])
        refs = [Path(p).read_bytes() for p in brief.assets if Path(p).exists()][:6]
        prompt = build_art_prompt(spec, brief, fmt, pal)
        best: Optional[Tuple[str, Any, List[str]]] = None
        flagged = False
        attempts = 1 + (self.art_retries if self.inspector else 0)
        for attempt in range(attempts):
            try:
                raw = await asyncio.to_thread(self.art.generate, prompt, width=fmt.w, height=fmt.h, refs=refs, seed=idx + attempt * 7, palette=pal)
            except Exception as e:
                notes.append(f"art backend failed ({e!r}), used the procedural backdrop")
                log.warning(notes[-1])
                raw = ProceduralArt().generate(prompt, width=fmt.w, height=fmt.h, seed=idx, palette=pal)
                best = best or None
                b64, img, cols = await asyncio.to_thread(prepare_art, raw, fmt.w, fmt.h)
                best = (b64, img, cols)
                flagged = False
                break
            b64, img, cols = await asyncio.to_thread(prepare_art, raw, fmt.w, fmt.h)
            best = (b64, img, cols)
            verdict = await self.inspector.check(img, spec, brief) if self.inspector else None
            if verdict is None:
                break
            bad = bool(verdict.get("has_text")) or bool(verdict.get("has_logo_or_watermark")) or verdict.get("pass") is False \
                or verdict.get("calm_zone_ok") is False
            if not bad:
                flagged = False
                break
            flagged = True
            hint = str(verdict.get("retry_hint") or "").strip()
            notes.append(f"art attempt {attempt + 1} rejected: " + ("; ".join(str(x) for x in (verdict.get("defects") or [])) or hint or "stray text or no calm zone"))
            prompt += (" STRICT RETRY: the previous image was rejected. " + hint +
                       " There must be absolutely no text, letters, numbers, signs, logos or watermarks anywhere, and the area reserved for copy must be smooth and empty.")
        assert best is not None
        if flagged:
            notes.append("art still flagged after retries: kept the best attempt")
        return best[0], best[1], best[2], notes, flagged

    async def _build_one(self, brief: Brief, spec: DesignSpec, idx: int) -> DesignResult:
        fmt = FORMATS[brief.format]
        notes: List[str] = []
        # 1. facts lock, proofread, grounded copy: revise once, then strip anything still ungrounded
        spec = enforce_facts(spec, brief)
        if self.fixed_recipe:
            spec.recipe, spec.ornament, spec.align = self.fixed_recipe, "none", "left"
        spec.copy = await self.director.proofread(spec.copy, brief)
        guard = copy_guard(spec.copy, brief)
        if any(i.severity == "error" for i in guard) and self.llm is not None:
            spec = await self.director.revise(spec, brief, guard)
            guard = copy_guard(spec.copy, brief)
        if any(i.severity == "error" for i in guard):
            spec.copy = strip_ungrounded(spec.copy, guard)
            guard = copy_guard(spec.copy, brief)
        spec = enforce_facts(spec, brief)
        # 2. art
        b64, img, cols, n, art_flag = await self._paint(spec, brief, fmt, idx)
        notes += n
        if art_flag and spec.recipe not in ("banner_wide", "story_stack", "menu", "split_panel"):
            # The picture ignored the request for calm space, so the words must not sit on it: a solid panel carries them, the art fills the rest.
            spec.recipe, spec.align, spec.ornament = "split_panel", (spec.align if spec.align in ("left", "right") else "left"), "none"
            notes.append("the picture left no empty space, so the words sit on a colour panel")
            art_flag = False                                      # the words no longer sit on the subject, so the flag no longer costs points
        critic_res: Optional[Dict[str, Any]] = None
        issues: List[Issue] = []
        cv: Optional[Canvas] = None
        for rnd in range(self.rounds):                         # each later round is the critic's notes applied to copy, colour and layout (no new picture)
            for _ in range(self.max_repairs + 1):             # lint + repair loop
                cv = Composer(self.fonts, fmt, spec, brief, b64, cols).build()
                sc = min(1.0, 1400 / max(fmt.w, fmt.h))
                base = await asyncio.to_thread(render_svg, cv.to_svg(layers=("art", "shade", "shape", "fx")),
                                               max(1, int(fmt.w * sc)), max(1, int(fmt.h * sc)))
                issues = await asyncio.to_thread(lint_layout, cv, base, fmt, sc)
                blocking = [i for i in issues if i.severity == "error"]
                if not blocking or not apply_repairs(spec, blocking):
                    break
            png = await asyncio.to_thread(render_svg, cv.to_svg(), fmt.w, fmt.h)
            if self.critic is None:
                break
            critic_res = await self.critic.review(png, brief)               # every round, so the score is of the design that is delivered
            if not critic_res:
                break
            errs_now = [i for i in issues + guard if i.severity == "error"]
            if self._score(critic_res, errs_now, [i for i in issues + guard if i.severity == "warn"], art_flag) >= self.min_score or rnd == self.rounds - 1:
                break
            fixes = [str(x) for x in (critic_res.get("issues") or []) + (critic_res.get("fixes") or [])]
            spec = await self.director.revise(spec, brief, [str(i) for i in issues] + fixes)
            if self.fixed_recipe:                                  # the director may suggest another layout: the owner's photo keeps its panel
                spec.recipe, spec.ornament, spec.align = self.fixed_recipe, "none", "left"
            # a second round of art would add minutes: the revision above (copy, colour, layout) is what the critic's note gets
        # 3. score and files
        errs = [i for i in issues + guard if i.severity == "error"]
        warns = [i for i in issues + guard if i.severity == "warn"]
        score = self._score(critic_res, errs, warns, art_flag)
        files = await asyncio.to_thread(self._save, brief, spec, fmt, idx, png, cv)
        return DesignResult(files, spec, issues + guard, score, critic_res, [], notes, checked=bool(critic_res))

    @staticmethod
    def _score(critic_res: Optional[Dict[str, Any]], errs: Sequence[Any], warns: Sequence[Any], art_flag: bool) -> float:
        """0 to 100: the art director's rating of the finished design (1 to 10, times ten) less a penalty for every unresolved lint error and warning
        and for a picture that kept stray text. With no critic the design cannot be certified, so it scores 0 and `checked` is False."""
        if not critic_res:
            return 0.0
        return max(0.0, min(100.0, float(critic_res.get("overall") or 0) * 10 - 22 * len(errs) - 6 * len(warns) - (15 if art_flag else 0)))

    def _save(self, brief: Brief, spec: DesignSpec, fmt: Format, idx: int, png: bytes, cv: Canvas) -> Dict[str, Path]:
        from PIL import Image
        stem = f"{slug(brief.brand.name)}_{fmt.name}_{slug(spec.name)}_{idx + 1}"
        files: Dict[str, Path] = {}
        files["png"] = self.out / f"{stem}.png"
        files["png"].write_bytes(png)
        im = Image.open(io.BytesIO(png)).convert("RGB")
        files["jpg"] = self.out / f"{stem}.jpg"
        im.save(files["jpg"], "JPEG", quality=92, optimize=True)
        files["svg"] = self.out / f"{stem}.svg"
        files["svg"].write_text(cv.to_svg(), encoding="utf-8")
        if fmt.name.startswith(("flyer", "poster")):
            files["pdf"] = self.out / f"{stem}.pdf"
            im.save(files["pdf"], "PDF", resolution=300.0)
        return files

    async def design(self, brief: Brief) -> DesignResult:
        if brief.format not in FORMATS:
            raise ValueError(f"unknown format '{brief.format}', choose from {sorted(FORMATS)}")
        n = max(1, brief.variants)
        specs = await self.director.directions(brief, n)

        async def one(i: int, sp: DesignSpec) -> Optional[DesignResult]:
            async with self._sem:
                try:
                    return await self._build_one(brief, sp, i)
                except Exception:
                    log.exception("direction %d failed", i)
                    return None

        results = [r for r in await asyncio.gather(*(one(i, s) for i, s in enumerate(specs))) if r]
        if not results:
            raise RuntimeError("no design could be produced")
        results.sort(key=lambda r: r.score, reverse=True)
        best = results[0]
        best.alternates = results[1:]
        return best


# ── SERVICE: the entry point for the sales agent ───────────────────────────────
DESIGN_TOOL_SPEC = {
    "name": "create_design",
    "description": "Create a flyer, banner, poster or social post image for the customer's business.",
    "input_schema": {"type": "object", "properties": {
        "request": {"type": "string", "description": "What the customer asked for, in their own words."},
    }, "required": ["request"]},
}


class DesignService:
    def __init__(self, studio: DesignStudio):
        self.studio = studio

    async def intake(self, user_text: str, brand: BrandKit) -> Tuple[Brief, List[str]]:
        data: Dict[str, Any] = {}
        if self.studio.llm is not None:
            try:
                ctx = (f"Saved brand kit: name={brand.name}; industry={brand.industry}; colours={brand.colors}; "
                       f"phone={brand.phone}; website={brand.website}; instagram={brand.instagram}; address={brand.address}")
                data = parse_json(await ask_llm(self.studio.llm, INTAKE_SYSTEM, f"{ctx}\n\nCUSTOMER REQUEST:\n{user_text}",
                                                strong=False, max_tokens=900, temperature=0.2)) or {}
            except Exception as e:
                log.warning("intake LLM failed: %r", e)
        fmt = data.get("format") if data.get("format") in FORMATS else "ig_post"
        kind = str(data.get("kind") or "social_post")
        brief = Brief(brand=brand, kind=kind, format=fmt, goal=str(data.get("goal") or ""), audience=str(data.get("audience") or ""),
                      headline=str(data.get("headline") or ""), offer=str(data.get("offer") or ""), price=str(data.get("price") or ""),
                      date=str(data.get("date") or ""), venue=str(data.get("venue") or ""), cta=str(data.get("cta") or ""),
                      details=[str(x) for x in data.get("details") or []], tone=str(data.get("tone") or ""),
                      language=str(data.get("language") or "en"), must_include=[str(x) for x in data.get("must_include") or []],
                      avoid=[str(x) for x in data.get("avoid") or []], notes=user_text[:400])
        return brief, [str(q) for q in (data.get("missing") or [])][:3]

    async def handle(self, user_text: str, brand: BrandKit, *, answers_ok: bool = False) -> Dict[str, Any]:
        brief, missing = await self.intake(user_text, brand)
        if missing and not answers_ok:
            return {"status": "needs_info", "questions": missing, "brief": brief}
        r = await self.studio.design(brief)
        return {"status": "done", "type": "image", "files": r.files, "summary": r.summary(), "score": r.score,
                "alternates": [a.files for a in r.alternates], "notes": r.notes, "brief": brief}


