"use client";
import { useCallback, useEffect, useState } from "react";
import { Badge, Notice } from "@/components/ui";
import { useToast } from "@/components/toast";
import { call } from "@/lib/client";
import { relTime, titleCase } from "@/lib/format";
import type { AutomationJob, AutomationState } from "@/lib/types";

const EVERY = [[5, "5 minutes"], [15, "15 minutes"], [30, "30 minutes"], [60, "hour"], [180, "3 hours"], [360, "6 hours"], [1440, "day"]] as const;
const TONE: Record<string, "ok" | "warn" | "danger" | "neutral"> = { ok: "ok", waiting: "neutral", "needs attention": "warn", blocked: "warn", error: "danger" };
const BASES: Record<string, string> = {
  business_contact: "Business contacts with a published work address, and the offer fits their role",
  existing_relationship: "Past or current customers or enquirers",
  consented: "They asked to hear from us or opted in",
};

export function ScheduleCard() {
  const toast = useToast();
  const [state, setState] = useState<AutomationState | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, Record<string, string | boolean>>>({});

  const load = useCallback(async () => {
    const r = await call<AutomationState>("automation");
    if (r.ok) { setState(r.data); setErr(null); } else setErr(r.error);
  }, []);
  useEffect(() => { load(); }, [load]);

  async function save(job: AutomationJob, body: { enabled?: boolean; every_minutes?: number; config?: Record<string, string | boolean> }, label: string) {
    setBusy(job.job + label);
    const r = await call<AutomationJob>(`automation/${job.job}`, { method: "PUT", body });
    setBusy(null);
    if (!r.ok) return toast(r.error, "error");
    toast(label === "on" ? (body.enabled ? `${job.label}: on` : `${job.label}: off`) : "Saved", "ok");
    setDraft((d) => ({ ...d, [job.job]: {} }));
    load();
  }

  async function runNow(job: AutomationJob) {
    setBusy(job.job + "run");
    const r = await call<{ status: string; detail: string }>(`automation/${job.job}/run`, { method: "POST" });
    setBusy(null);
    if (!r.ok) return toast(r.error, "error");
    toast(`${titleCase(r.data.status)}: ${r.data.detail}`, r.data.status === "ok" ? "ok" : "error");
    load();
  }

  const value = (job: AutomationJob, key: string) => (draft[job.job]?.[key] ?? job.config[key] ?? (key === "attested" ? false : "")) as string | boolean;
  const edit = (job: AutomationJob, key: string, v: string | boolean) => setDraft((d) => ({ ...d, [job.job]: { ...d[job.job], [key]: v } }));
  const dirty = (job: AutomationJob) => Object.keys(draft[job.job] ?? {}).length > 0;

  return (
    <section className="card stack" aria-labelledby="sched">
      <h2 id="sched">Automatic schedule</h2>
      <p className="muted">Switch on what you want your rep to do by itself. Each job does exactly what its button does: nothing is ever emailed to a prospect until you approve that exact email, and outreach goes out only Monday to Saturday, 8am to 6pm Lagos time, within your daily limit.</p>
      {err && <Notice tone="danger">{err}</Notice>}
      {state && (state.timer_on
        ? <Notice tone="ok">The timer is running. Jobs below that are switched on run by themselves.</Notice>
        : <Notice tone="warn">The timer is switched off on this server, so jobs only run when you press Run now.</Notice>)}
      {!state && !err && <p className="muted">Loading…</p>}
      <div className="stack">
        {state?.jobs.map((j) => (
          <div key={j.job} className="stack" style={{ borderTop: "1px solid var(--line)", paddingTop: "0.8rem" }}>
            <div className="row spread wrap">
              <div style={{ maxWidth: 520 }}>
                <strong>{j.label}</strong>
                <div className="small muted">{j.about}</div>
              </div>
              <div className="row wrap">
                <label className="row small"><input type="checkbox" checked={j.enabled} disabled={busy !== null} onChange={(e) => save(j, { enabled: e.target.checked }, "on")} /> On</label>
                <select value={j.every_minutes} disabled={busy !== null} aria-label={`How often: ${j.label}`} onChange={(e) => save(j, { every_minutes: Number(e.target.value) }, "every")}>
                  {EVERY.map(([m, l]) => <option key={m} value={m}>Every {l}</option>)}
                  {!EVERY.some(([m]) => m === j.every_minutes) && <option value={j.every_minutes}>Every {j.every_minutes} min</option>}
                </select>
                <button className="btn sm" disabled={busy !== null} onClick={() => runNow(j)}>{busy === j.job + "run" ? "Running…" : "Run now"}</button>
              </div>
            </div>
            <div className="small row wrap" style={{ gap: "0.5rem" }}>
              {j.last_status ? <><Badge tone={TONE[j.last_status] ?? "neutral"}>{titleCase(j.last_status)}</Badge><span className="muted" suppressHydrationWarning>{j.last_run ? relTime(j.last_run) : "not run yet"}{j.last_detail ? `: ${j.last_detail}` : ""}</span></> : <span className="muted">Not run yet.</span>}
            </div>
            {j.job === "lead_import" && (
              <div className="stack">
                <input type="url" placeholder="https://docs.google.com/spreadsheets/d/..." value={String(value(j, "url"))} onChange={(e) => edit(j, "url", e.target.value)} aria-label="Google Sheet link with your leads" />
                <select value={String(value(j, "basis")) || ""} onChange={(e) => edit(j, "basis", e.target.value)} aria-label="Why you may email them">
                  <option value="">Why may you email these people?</option>
                  {Object.entries(BASES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
                <label className="row small"><input type="checkbox" checked={value(j, "attested") === true} onChange={(e) => edit(j, "attested", e.target.checked)} /> I confirm I may lawfully email everyone on this sheet, and I will not buy or scrape lists.</label>
                <p className="small muted">The sheet needs a column headed Email (Name, Company, Title and Note are used if present). Share it as Anyone with the link, Viewer.</p>
                {dirty(j) && <div><button className="btn sm primary" disabled={busy !== null} onClick={() => save(j, { config: draft[j.job] }, "cfg")}>Save settings</button></div>}
              </div>
            )}
            {j.job === "lead_qualify" && (
              <div className="stack">
                <textarea rows={2} placeholder="Who is your ideal customer? For example: shops and resellers in Lagos that sell phones or accessories." value={String(value(j, "icp"))} onChange={(e) => edit(j, "icp", e.target.value)} aria-label="Your ideal customer" />
                <div className="row small"><label htmlFor="minfit">Only draft emails for people scoring at least</label><input id="minfit" type="number" min={1} max={100} style={{ width: 80 }} value={String(value(j, "min_fit") || "60")} onChange={(e) => edit(j, "min_fit", e.target.value)} /></div>
                <p className="small muted">The score comes from an AI model reading the row you gave. People below it are set aside, not emailed, and you can keep any of them on the Outreach page.</p>
                {dirty(j) && <div><button className="btn sm primary" disabled={busy !== null} onClick={() => save(j, { config: draft[j.job] }, "cfg")}>Save settings</button></div>}
              </div>
            )}
            {j.job === "content_auto" && (
              <div className="stack">
                <input value={String(value(j, "platforms"))} onChange={(e) => edit(j, "platforms", e.target.value)} placeholder="instagram, facebook" aria-label="Platforms to make posts for" />
                <div className="row wrap small">
                  <label htmlFor="cnt">Products per run</label>
                  <select id="cnt" value={String(value(j, "count") || "1")} onChange={(e) => edit(j, "count", e.target.value)}>{["1", "2", "3"].map((n) => <option key={n} value={n}>{n}</option>)}</select>
                  <label htmlFor="gap">Promote the same product again after (days)</label>
                  <input id="gap" type="number" min={1} max={60} style={{ width: 70 }} value={String(value(j, "gap_days") || "7")} onChange={(e) => edit(j, "gap_days", e.target.value)} />
                  <label className="row"><input type="checkbox" checked={value(j, "video") === true} onChange={(e) => edit(j, "video", e.target.checked)} /> Also make a video for Reels, Stories and Status</label>
                </div>
                <p className="small muted">Every flyer, picture and video must score at least 90 out of 100 from an AI art director to reach your approvals unflagged. Anything below is flagged and cannot be approved until you remake it. Nothing is posted until you approve it, and each design uses image credits from your plan.</p>
                {dirty(j) && <div><button className="btn sm primary" disabled={busy !== null} onClick={() => save(j, { config: draft[j.job] }, "cfg")}>Save settings</button></div>}
              </div>
            )}
            {j.job === "lead_draft" && (
              <div className="stack">
                <textarea rows={2} placeholder="What you offer, in a sentence or two. The rep writes each email from this." value={String(value(j, "offer"))} onChange={(e) => edit(j, "offer", e.target.value)} aria-label="Your offer" />
                {dirty(j) && <div><button className="btn sm primary" disabled={busy !== null} onClick={() => save(j, { config: draft[j.job] }, "cfg")}>Save settings</button></div>}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
