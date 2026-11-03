"""A timer for the jobs an owner would otherwise press a button for.

Off unless SCHEDULER=1 on the server, and every job is off for a business until its admin turns it on. A job does only what its button
does today, with the same plan checks, caps and approvals: outreach emails still go only after the owner approved that exact email, within
the daily cap, and only in business hours in Lagos. One failing job is recorded and never stops the others. The lead steps are chained but
each stops short of sending: import adds people, drafting writes emails, and they wait for the owner's approval.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from .agents.content import ContentError
from .content import viral
from .design import quality, service as design
from .inventory import sheet
from .leads import retention
from .outreach import DEFAULT_MIN_FIT, LAWFUL_BASES, OutreachError
from .server.plans import PlanLimit

log = logging.getLogger("agentic_sales.scheduler")

LAGOS = timezone(timedelta(hours=1))        # no daylight saving, so a fixed offset is exact
SEND_FROM, SEND_UNTIL = 8, 18               # local hours, Monday to Saturday
MIN_EVERY, MAX_EVERY = 5, 1440              # minutes
TICK_SECONDS = 30
MAX_IMPORT_ROWS = 500
CONFIG_KEYS = ("url", "basis", "offer", "attested", "icp", "min_fit", "platforms", "count", "video", "gap_days")
BACKGROUND = {"content_auto"}               # minutes of picture-making: run on their own thread so the quick jobs are never kept waiting
DESIGN_FORMAT = {"instagram": "ig_post", "facebook": "ig_post", "x": "x_post", "threads": "ig_square", "whatsapp_status": "ig_story", "tiktok": "ig_story", "telegram": "ig_post"}


@dataclass(frozen=True)
class Job:
    key: str
    label: str
    about: str
    every: int                                  # default minutes between runs
    needs: tuple[str, ...] = ()                 # settings the owner must give before it can be switched on
    gated: bool = False                         # needs the plan feature that covers follow-ups and cold email
    feature: str = ""                           # a plan feature this job needs (image creation for designs and videos)


JOBS: dict[str, Job] = {j.key: j for j in (
    Job("flush", "Send queued messages", "Sends the replies and follow-ups waiting in the outbox.", 5),
    Job("followups", "Customer follow-ups", "Queues thank-you and check-in messages after sales, and one recovery message for leads that went quiet.", 30, gated=True),
    Job("lead_import", "Import new leads from a sheet", "Reads a Google Sheet you choose and adds the new people as prospects. Nothing is emailed by this step.", 360,
        needs=("url", "basis", "attested"), gated=True),
    Job("lead_qualify", "Score new leads against your ideal customer", "A model reads each new person and scores how well they fit the customer you describe. Poor fits are set aside, not emailed, and you can keep any of them.", 60,
        needs=("icp",), gated=True),
    Job("lead_draft", "Draft emails for new leads", "Writes a short email for each new prospect from your offer. Every email waits for your approval.", 60,
        needs=("offer",), gated=True),
    Job("content_auto", "Make posts, flyers and videos for your products", "Picks a product you have not promoted lately, writes the posts, makes a flyer for each (and a video if you ask), "
        "and checks every picture against the quality benchmark. They wait in your approvals: nothing is posted until you approve it.", 1440, needs=("platforms",), feature="image_generation"),
    Job("outreach_send", "Send approved outreach emails", "Sends the emails you approved, within your daily cap, Monday to Saturday, 8am to 6pm Lagos time.", 60, gated=True),
)}

_COLUMNS = {"email": ("email", "e-mail", "email address", "mail"), "name": ("name", "full name", "contact", "contact name"),
            "company": ("company", "business", "organisation", "organization", "company name"), "title": ("title", "role", "position", "job title"),
            "note": ("note", "notes", "about", "description")}

_SCHEMA = """CREATE TABLE IF NOT EXISTS schedule(
    job TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0, every INTEGER NOT NULL, config TEXT NOT NULL DEFAULT '{}',
    last_run TEXT, last_status TEXT, last_detail TEXT)"""


class ScheduleError(ValueError):
    """Something the owner can fix; the message is shown to them."""


def _iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).isoformat()


def in_sending_hours(now: datetime) -> bool:
    local = now.astimezone(LAGOS)
    return local.weekday() < 6 and SEND_FROM <= local.hour < SEND_UNTIL


class Schedule:
    """One business's job settings and last results, in its own database."""

    def __init__(self, memory):
        self.con = memory.con
        with self.con:
            self.con.execute(_SCHEMA)

    def row(self, key: str) -> dict:
        r = self.con.execute("SELECT * FROM schedule WHERE job=?", (key,)).fetchone()
        if r is None:
            return {"job": key, "enabled": False, "every": JOBS[key].every, "config": {}, "last_run": None, "last_status": None, "last_detail": None}
        d = dict(r)
        d["enabled"], d["config"] = bool(d["enabled"]), json.loads(d["config"] or "{}")
        return d

    def view(self) -> list[dict]:
        out = []
        for job in JOBS.values():
            r = self.row(job.key)
            cfg = {k: v for k, v in r["config"].items() if k in CONFIG_KEYS}
            out.append({"job": job.key, "label": job.label, "about": job.about, "enabled": r["enabled"], "every_minutes": r["every"], "config": cfg,
                        "needs": list(job.needs), "last_run": r["last_run"], "last_status": r["last_status"], "last_detail": r["last_detail"]})
        return out

    def set(self, key: str, enabled: bool | None, every: int | None, config: dict | None) -> None:
        if key not in JOBS:
            raise ScheduleError("Unknown job.")
        cur = self.row(key)
        every = cur["every"] if every is None else every
        if not MIN_EVERY <= every <= MAX_EVERY:
            raise ScheduleError(f"Choose between every {MIN_EVERY} minutes and every {MAX_EVERY // 60} hours.")
        cfg = dict(cur["config"])
        for k, v in (config or {}).items():
            if k not in CONFIG_KEYS:
                raise ScheduleError("Unknown setting.")
            cfg[k] = v
        if "url" in cfg:
            try:
                sheet.export_url(str(cfg["url"]))
            except sheet.SheetError as e:
                raise ScheduleError(str(e)) from None
        if cfg.get("basis") and cfg["basis"] not in LAWFUL_BASES:
            raise ScheduleError("Choose why you may email these people: " + ", ".join(LAWFUL_BASES))
        if "offer" in cfg and not 10 <= len(str(cfg["offer"]).strip()) <= 500:
            raise ScheduleError("Say what you are offering in one or two sentences (10 to 500 characters).")
        if "icp" in cfg and not 10 <= len(str(cfg["icp"]).strip()) <= 500:
            raise ScheduleError("Describe your ideal customer in one or two sentences (10 to 500 characters).")
        if "platforms" in cfg:
            keys = [k.strip().lower().replace(" ", "_") for k in str(cfg["platforms"]).replace(";", ",").split(",") if k.strip()]
            bad = [k for k in keys if k not in viral.PLATFORM_KEYS]
            if bad or not keys or len(keys) > 3:
                raise ScheduleError("Choose one to three platforms from: " + ", ".join(viral.PLATFORM_KEYS) + ".")
            cfg["platforms"] = ", ".join(dict.fromkeys(keys))
        for k, lo, hi, what in (("count", 1, 3, "How many products per run is 1 to 3."), ("gap_days", 1, 60, "Days before a product is promoted again is 1 to 60.")):
            if k in cfg and cfg[k] != "":
                try:
                    cfg[k] = str(int(cfg[k]))
                except ValueError:
                    raise ScheduleError(what) from None
                if not lo <= int(cfg[k]) <= hi:
                    raise ScheduleError(what)
        if "min_fit" in cfg:
            try:
                cfg["min_fit"] = str(int(cfg["min_fit"]))
            except ValueError:
                raise ScheduleError("The minimum score is a number from 1 to 100.") from None
            if not 1 <= int(cfg["min_fit"]) <= 100:
                raise ScheduleError("The minimum score is a number from 1 to 100.")
        want = cur["enabled"] if enabled is None else enabled
        missing = [n for n in JOBS[key].needs if not cfg.get(n)]
        if want and missing:
            raise ScheduleError("Before switching this on, fill in: " + ", ".join(missing) + ".")
        with self.con:
            self.con.execute("INSERT INTO schedule(job,enabled,every,config) VALUES(?,?,?,?) ON CONFLICT(job) DO UPDATE SET enabled=?, every=?, config=?",
                             (key, int(want), every, json.dumps(cfg), int(want), every, json.dumps(cfg)))

    def record(self, key: str, when: datetime, status: str, detail: str, touch: bool = True) -> None:
        """Remember what a run did. With touch=False the run does not count as having happened, so the job is tried again at the next tick."""
        cur = self.row(key)
        if not touch:
            when = datetime.fromisoformat(cur["last_run"]) if cur["last_run"] else None
        if when is None:
            with self.con:
                self.con.execute("INSERT INTO schedule(job,enabled,every,config,last_status,last_detail) VALUES(?,?,?,?,?,?) "
                                 "ON CONFLICT(job) DO UPDATE SET last_status=?, last_detail=?",
                                 (key, int(cur["enabled"]), cur["every"], json.dumps(cur["config"]), status, detail[:300], status, detail[:300]))
            return
        with self.con:
            self.con.execute("INSERT INTO schedule(job,enabled,every,config,last_run,last_status,last_detail) VALUES(?,?,?,?,?,?,?) "
                             "ON CONFLICT(job) DO UPDATE SET last_run=?, last_status=?, last_detail=?",
                             (key, int(cur["enabled"]), cur["every"], json.dumps(cur["config"]), _iso(when), status, detail[:300],
                              _iso(when), status, detail[:300]))

    def due(self, now: datetime) -> list[str]:
        out = []
        for key in JOBS:
            r = self.row(key)
            if not r["enabled"]:
                continue
            last = datetime.fromisoformat(r["last_run"]) if r["last_run"] else None
            if last is None or now - last >= timedelta(minutes=r["every"]):
                out.append(key)
        return out


def read_rows(text: str) -> list[dict]:
    """People from a sheet's CSV, whatever the column headings are called."""
    reader = csv.reader(io.StringIO(text))
    try:
        heads = [h.strip().lower() for h in next(reader)]
    except StopIteration:
        return []
    where = {field: next((i for i, h in enumerate(heads) if h in names), None) for field, names in _COLUMNS.items()}
    if where["email"] is None:
        raise ScheduleError("The sheet needs a column headed Email.")
    rows = []
    for cells in reader:
        row = {f: (cells[i].strip() if i is not None and i < len(cells) else "") for f, i in where.items()}
        if any(row.values()):
            rows.append(row)
    return rows


class Scheduler:
    """Runs due jobs for every business. `allowed(tenant, label)` applies the plan, `fetch(url)` reads a sheet (replaceable in tests)."""

    def __init__(self, runtimes, auth, gate=None, fetch: Callable[[str], str] | None = None):
        self.runtimes, self.auth, self.gate = runtimes, auth, gate
        self.fetch = fetch or (lambda link: sheet.fetch_csv(sheet.export_url(link)[0]))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._busy: set[tuple[str, str]] = set()
        self._busy_lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(TICK_SECONDS):
            try:
                self.tick()
            except Exception:                                      # the timer itself must never die
                log.exception("scheduler tick failed")

    def tick(self, now: datetime | None = None) -> int:
        """Run every due job for every business; the number of jobs run."""
        now = now or datetime.now(timezone.utc)
        ran = 0
        for t in self.auth.list_tenants():
            if t["disabled"]:
                continue
            try:
                rt = self.runtimes.get(t["id"])
                with rt.lock:
                    due = Schedule(rt.memory).due(now)
            except Exception:
                log.exception("scheduler could not open %s", t["id"])
                continue
            for key in due:
                if key in BACKGROUND:
                    with self._busy_lock:
                        if (t["id"], key) in self._busy:
                            continue
                        self._busy.add((t["id"], key))
                    threading.Thread(target=self._background, args=(rt, t["id"], key, now), daemon=True, name=f"job-{key}").start()
                else:
                    self.run(rt, t["id"], key, now)
                ran += 1
        return ran

    def _background(self, rt, tenant_id: str, key: str, now: datetime) -> None:
        try:
            self.run(rt, tenant_id, key, now)
        finally:
            with self._busy_lock:
                self._busy.discard((tenant_id, key))

    def run(self, rt, tenant_id: str, key: str, now: datetime | None = None) -> dict:
        """One job, now. Always records what happened; never raises. Returns {status, detail}."""
        now = now or datetime.now(timezone.utc)
        job = JOBS[key]
        try:
            if job.gated and self.gate is not None:
                self.gate.require(tenant_id, "followups", job.label)
            if job.feature and self.gate is not None:
                self.gate.require(tenant_id, job.feature, job.label)
            with rt.lock:
                cfg = Schedule(rt.memory).row(key)["config"]
                if key not in BACKGROUND:
                    status, detail = getattr(self, "_" + key)(rt, cfg, now)
            if key in BACKGROUND:                                   # without the tenant lock: this takes minutes and replies must not wait for it
                status, detail = getattr(self, "_" + key)(rt, cfg, now)
        except PlanLimit as e:
            status, detail = "blocked", str(e)
        except (ScheduleError, OutreachError, sheet.SheetError) as e:
            status, detail = "needs attention", str(e)
        except Exception as e:                                      # a bug or an outage in one job is recorded, not raised
            log.exception("job %s failed for %s", key, tenant_id)
            status, detail = "error", f"{type(e).__name__}: {str(e)[:150]}"
        with rt.lock:
            Schedule(rt.memory).record(key, now, status, detail, touch=status != "waiting")
        return {"status": status, "detail": detail}

    # ---- the jobs: each returns (status, detail) ---------------------------------------------------------------------------------
    def _flush(self, rt, cfg, now):
        r = rt.flush()
        return "ok", f"sent {r.sent}, waiting for a template {r.needs_template}, failed {r.failed}"

    def _followups(self, rt, cfg, now):
        stale = retention.mark_stale_leads(rt.orchestrator.leads)
        corpus = rt.orchestrator.corpus
        composer = retention.CorpusComposer(retention.TemplateComposer(), corpus) if corpus is not None else None
        rep = retention.run_due(rt.orchestrator.leads, rt.memory, rt.cfg, composer)
        return "ok", f"queued {rep.enqueued} follow-up(s); {stale} quiet lead(s) marked"

    def _lead_import(self, rt, cfg, now):
        rows = read_rows(self.fetch(str(cfg.get("url", ""))))[:MAX_IMPORT_ROWS]
        if not rows:
            return "ok", "the sheet has no people yet"
        out = rt.outreach.import_prospects(rows, str(cfg.get("basis", "")), bool(cfg.get("attested")))
        return "ok", f"added {out['added']}, already known {out['duplicates']}, invalid {out['invalid']}, opted out {out['suppressed']}"

    def _lead_qualify(self, rt, cfg, now):
        out = rt.outreach.qualify(str(cfg.get("icp", "")), int(cfg.get("min_fit") or DEFAULT_MIN_FIT))
        if out["failed"] and not out["scored"]:
            return "needs attention", f"the scoring model gave no usable answer for {out['failed']} lead(s); they stay unscored"
        model = f" on {out['model']} (about {out['avg_ms'] / 1000:.1f}s each)" if out["scored"] else ""
        return "ok", f"scored {out['scored']}{model}: {out['kept']} fit, {out['set_aside']} set aside, {out['left']} still to score"

    def _lead_draft(self, rt, cfg, now):
        q = Schedule(rt.memory).row("lead_qualify")
        min_fit = int(q["config"].get("min_fit") or DEFAULT_MIN_FIT) if q["enabled"] and q["config"].get("icp") else None     # scoring on: draft only the people who fit
        out = rt.outreach.draft(str(cfg.get("offer", "")), 25, min_fit)
        return "ok", f"drafted {out['drafted']} for your approval, {out['failed']} failed, {out['left']} still to draft"

    def _content_auto(self, rt, cfg, now):
        tid = rt.ctx.tenant_id
        platforms = [k.strip() for k in str(cfg.get("platforms", "")).split(",") if k.strip()]
        count, gap = int(cfg.get("count") or 1), timedelta(days=int(cfg.get("gap_days") or 7))
        plan_ = self.gate.plan(tid) if self.gate is not None else None
        if plan_ is not None:
            platforms = platforms[:plan_.platforms_per_post]
        never = datetime.min.replace(tzinfo=timezone.utc)
        last: dict[str, datetime] = {}
        for it in rt.content.store.list(limit=500):
            if it.get("product_sku"):
                when = datetime.fromisoformat(it["created"])
                last[it["product_sku"]] = max(last.get(it["product_sku"], when), when)
        due = sorted((p for p in rt.cfg.products if p.in_stock and now - last.get(p.sku, never) >= gap), key=lambda p: last.get(p.sku, never))
        if not due:
            return "ok", f"every product in stock was promoted in the last {gap.days} days"
        made = met = 0
        problems: list[str] = []
        for product in due[:count]:
            if self.gate is not None:
                self.gate.consume(tid, "content_posts", len(platforms), what="social posts")
            try:
                with rt.lock:
                    res = rt.content.plan_product(product.sku, platforms, "conversion", variants=1, max_platforms=len(platforms), created_by="scheduler")
            except (ValueError, ContentError) as e:
                if self.gate is not None:
                    self.gate.refund(tid, "content_posts", len(platforms))
                problems.append(f"{product.name}: {str(e)[:80]}")
                continue
            for it in res.items:
                made += 1
                ok, note = self._design_for(rt, tid, it, product, bool(cfg.get("video")))
                met += ok
                if note:
                    problems.append(note)
        say = f"made {made} post(s) with flyers; {met} reached the {quality.MIN_SCORE:.0f} benchmark and wait for your approval"
        if made - met:
            say += f", {made - met} did not and are flagged"
        return ("ok" if made else "needs attention"), say + ("." if not problems else ". " + "; ".join(problems[:3]))

    def _design_for(self, rt, tid: str, item: dict, product, with_video: bool) -> tuple[bool, str]:
        """One post's flyer (and video). True when everything made for it reached the benchmark. Failures are noted on the post, never raised."""
        iid, key = item["id"], item["platform_key"]
        flags: list[str] = []
        try:
            if self.gate is not None:
                self.gate.consume(tid, "images", 1, what="designs")
            try:
                out = design.make(rt.orchestrator.router, rt.cfg, rt.content.media_dir / "designs", f"Promotion for {product.name}",
                                  DESIGN_FORMAT.get(key, "ig_post"), product.sku, rt.content.product_image(product.sku))
            except design.DesignError:
                if self.gate is not None:
                    self.gate.refund(tid, "images", 1)
                raise
            rt.content.store.update(iid, media_path=str(rt.content.media_dir / "designs" / out["file"].replace(".png", ".jpg")))
            if not out["passed"]:
                flags.append("quality: the flyer " + (f"rated {out['score']}/100, below the {out['min_score']} benchmark" if out["checked"] else "could not be checked by a model"))
            row = rt.content.store.get(iid)
            if with_video and key in rt.content.REEL_PLATFORMS and row and row.get("video_script"):
                n = rt.content.reel_frames(iid)
                if self.gate is not None:
                    self.gate.consume(tid, "images", n, what="video frames")
                try:
                    rt.content.generate_reel(iid)
                except ContentError:
                    if self.gate is not None:
                        self.gate.refund(tid, "images", n)
                    flags.append("quality: the video could not be made")
        except (design.DesignError, PlanLimit) as e:
            flags.append(f"quality: no flyer was made ({str(e)[:80]})")
        except Exception as e:                                       # noqa: BLE001 - one post failing must not lose the others
            log.exception("design for post %s failed", iid)
            flags.append(f"quality: no flyer was made ({type(e).__name__})")
        row = rt.content.store.get(iid)
        if flags:
            rt.content.store.update(iid, violations=[*(row["violations"] if row else []), *flags], status="draft")
            row = rt.content.store.get(iid)
        return not flags and not (row and row["violations"]), "; ".join(flags)[:120]

    def _outreach_send(self, rt, cfg, now):
        if not in_sending_hours(now):
            return "waiting", "outside sending hours (Monday to Saturday, 8am to 6pm Lagos time)"
        rep = rt.outreach.send_due(now)
        if rep.blocked:
            return "needs attention", rep.blocked
        return "ok", f"sent {rep.sent}, skipped {rep.skipped}, failed {rep.failed}, {rep.remaining_today} left today"
