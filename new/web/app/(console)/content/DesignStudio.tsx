"use client";
import { useEffect, useState } from "react";
import { Badge, Notice } from "@/components/ui";
import { useToast } from "@/components/toast";
import { call } from "@/lib/client";
import { naira } from "@/lib/format";
import type { DesignResult, ViralPlatform } from "@/lib/types";

const FORMATS = [["ig_post", "Instagram or Facebook post"], ["ig_story", "Story, Reel or Status"], ["ig_square", "Square post"], ["fb_post", "Facebook link share"],
  ["flyer_a5", "Flyer, A5"], ["poster_a3", "Poster, A3"]] as const;

export function DesignStudio({ products, enabled }: { products: { sku: string; name: string; price_kobo: number }[]; enabled: boolean }) {
  const toast = useToast();
  const [request, setRequest] = useState("");
  const [format, setFormat] = useState<string>("ig_post");
  const [sku, setSku] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<DesignResult | null>(null);
  const [job, setJob] = useState("");
  const [platforms, setPlatforms] = useState<ViralPlatform[]>([]);
  const [chosen, setChosen] = useState<string[]>([]);
  const [caption, setCaption] = useState("");
  const [posting, setPosting] = useState(false);
  const [outcome, setOutcome] = useState<string[]>([]);

  useEffect(() => {
    void call<ViralPlatform[]>("viral/platforms").then((r) => { if (r.ok) setPlatforms(r.data); });
  }, []);

  /** Make posts from the design, then (for "Post now") approve and publish each one. A platform we cannot post to for them says so and keeps the caption to copy. */
  async function post(now: boolean) {
    if (!result || chosen.length === 0) return;
    setPosting(true);
    setOutcome([]);
    const made = await call<{ items: { id: number; platform_key: string; violations: string[] }[] }>(`design/jobs/${job}/items`, { method: "POST", body: { platforms: chosen, caption } });
    if (!made.ok) { setPosting(false); return toast(made.error, "error"); }
    const lines: string[] = [];
    for (const it of made.data.items) {
      const label = platforms.find((p) => p.key === it.platform_key)?.label ?? it.platform_key;
      if (it.violations.length) { lines.push(`${label}: not posted, ${it.violations.join("; ")}`); continue; }
      if (!now) { lines.push(`${label}: waiting in your approvals`); continue; }
      const ok = await call(`content/${it.id}/approve`, { method: "POST" });
      if (!ok.ok) { lines.push(`${label}: ${ok.error}`); continue; }
      const pub = await call<{ ref?: string }>(`content/${it.id}/publish`, { method: "POST" });
      lines.push(pub.ok ? `${label}: posted` : `${label}: approved, but ${pub.error}`);
    }
    setOutcome(lines);
    setPosting(false);
  }

  async function go(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setResult(null);
    const started = await call<{ job: string }>("design", { method: "POST", body: { request, format, sku: sku || null } });
    if (!started.ok) { setBusy(false); return toast(started.error, "error"); }
    setJob(started.data.job);
    setOutcome([]);
    // Muse Image takes a minute or two: the design is made in the background and this asks how it is going.
    for (let i = 0; i < 200; i++) {
      await new Promise((ok) => setTimeout(ok, 3000));
      const j = await call<{ status: string; result?: DesignResult; error?: string }>(`design/jobs/${started.data.job}`);
      if (!j.ok) break;
      if (j.data.status === "done" && j.data.result) { setBusy(false); setCaption(j.data.result.caption); return setResult(j.data.result); }
      if (j.data.status === "error") { setBusy(false); return toast(j.data.error ?? "The design could not be made.", "error"); }
    }
    setBusy(false);
    toast("This is taking too long. Your credit was not used up if it fails; try again in a moment.", "error");
  }

  const product = products.find((p) => p.sku === sku);
  return (
    <form className="card stack" onSubmit={go} aria-labelledby="design-h">
      <div>
        <h2 id="design-h">Design studio</h2>
        <p className="muted">A flyer, banner or post image with your words on it. Muse Image paints the picture, then your rep sets the lettering as sharp vector type, checks it and fixes what a phone screen would get wrong. Prices come from your catalogue.</p>
      </div>
      {!enabled && <Notice tone="warn">Your plan does not include image creation. Ask us to upgrade it.</Notice>}
      <div className="row wrap">
        <select value={sku} onChange={(e) => setSku(e.target.value)} aria-label="Product">
          <option value="">No product (use my description)</option>
          {products.map((p) => <option key={p.sku} value={p.sku}>{p.name} ({naira(p.price_kobo)})</option>)}
        </select>
        <select value={format} onChange={(e) => setFormat(e.target.value)} aria-label="Size">
          {FORMATS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </div>
      <textarea rows={3} maxLength={600} required minLength={8} value={request} onChange={(e) => setRequest(e.target.value)} aria-label="What the design is for"
        placeholder={product ? `Anything to add? For example: weekend sale, free delivery in Lagos.` : "Describe it. For example: a flyer for our weekend phone sale, with free delivery in Lagos, order on WhatsApp."} />
      <div>
        <button className="btn primary" disabled={busy || !enabled || request.trim().length < 8}>{busy ? "Designing… about two minutes, you can stay on this page" : "Create design"}</button>
      </div>
      {result && (
        <div className="stack">
          <img src={result.image} alt={`Design: ${result.headline || "your request"}`} style={{ maxWidth: 420, width: "100%", borderRadius: 8, border: "1px solid var(--line)" }} />
          <div className="row wrap small">
            <Badge tone={result.passed ? "ok" : "danger"}>{result.passed ? `Quality ${result.score}/100: passed` : result.checked ? `Quality ${result.score}/100: below the ${result.min_score} benchmark` : "Not checked by a model"}</Badge>
            <Badge tone="neutral">{result.brain ? "Muse Spark checked it" : "No AI model reachable: template layout"}</Badge>
            <a className="btn sm ghost" href={result.image} download={result.file.replace(/\.png$/, ".jpg")}>Download instead</a>
          </div>
          {result.passed ? (
            <div className="stack">
              <strong>Post it</strong>
              <div className="row wrap">
                {platforms.filter((p) => p.needs_media !== "video").map((p) => (
                  <label key={p.key} className="check">
                    <input type="checkbox" checked={chosen.includes(p.key)} onChange={(e) => setChosen((c) => (e.target.checked ? [...c, p.key] : c.filter((k) => k !== p.key)))} />
                    {p.label} <span className="small muted">{p.publish === "ready" ? "posts automatically" : p.publish === "needs_setup" ? "needs connecting" : "you copy and post"}</span>
                  </label>
                ))}
              </div>
              <textarea rows={3} maxLength={2200} value={caption} onChange={(e) => setCaption(e.target.value)} aria-label="Caption" />
              <div className="row wrap">
                <button className="btn primary" type="button" disabled={posting || chosen.length === 0 || !caption.trim()} onClick={() => void post(true)}>{posting ? "Posting…" : "Post now"}</button>
                <button className="btn" type="button" disabled={posting || chosen.length === 0 || !caption.trim()} onClick={() => void post(false)}>Send for approval instead</button>
              </div>
              {outcome.map((l) => <p key={l} className="small">{l}</p>)}
            </div>
          ) : <Notice tone="warn">This design did not reach the quality benchmark, so it cannot be posted. Press Create design to make it again.</Notice>}
          {result.asked.length > 0 && <Notice tone="info">The rep would like to know: {result.asked.join(" ")}</Notice>}
          {result.notes.length > 0 && <p className="small muted">{result.notes.join(" · ")}</p>}
        </div>
      )}
    </form>
  );
}
