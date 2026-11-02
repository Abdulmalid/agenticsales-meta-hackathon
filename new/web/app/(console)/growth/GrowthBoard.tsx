"use client";
import { useState } from "react";
import { Badge, Empty, Notice } from "@/components/ui";
import { useToast } from "@/components/toast";
import { call } from "@/lib/client";
import { relTime } from "@/lib/format";
import type { Segment, Segments } from "@/lib/types";

const PLACES: [string, string][] = [
  ["instagram_bio", "Instagram bio"], ["whatsapp_status", "WhatsApp status"], ["facebook_post", "Facebook post"],
  ["x_post", "X post"], ["flyer", "Flyer or QR code"],
];

function Copy({ text, label }: { text: string; label: string }) {
  const toast = useToast();
  return (
    <button type="button" className="btn sm" onClick={async () => {
      try { await navigator.clipboard.writeText(text); toast("Copied.", "ok"); } catch { toast("Couldn't copy. Select the text and copy it.", "error"); }
    }}>{label}</button>
  );
}

function Fit({ n }: { n: number }) {
  return <div className="bar" style={{ width: 120 }} role="img" aria-label={`Fit ${n} out of 100`}><span style={{ width: `${n}%` }} /></div>;
}

function Card({ s }: { s: Segment }) {
  return (
    <section className="card stack" aria-label={s.name}>
      <div className="row spread wrap">
        <h3 style={{ fontSize: "1.1rem" }}>{s.name}</h3>
        <div className="row"><span className="small muted">Fit {s.fit}</span><Fit n={s.fit} /></div>
      </div>
      <p>{s.who}</p>
      <p className="muted small">Why they buy: {s.why}</p>
      {s.skus.length > 0 && <div className="row wrap">{s.skus.map((k) => <Badge key={k} tone="brand">{k}</Badge>)}</div>}
      {s.hook && <div><div className="small muted">Hook</div><strong>{s.hook}</strong></div>}
      {s.post && <div className="stack" style={{ gap: "0.4rem" }}><div className="small muted">Sample post</div><p>{s.post}</p><div><Copy text={s.post} label="Copy post" /></div></div>}
      {s.reply && <div className="stack" style={{ gap: "0.4rem" }}><div className="small muted">When they ask the price</div><p>{s.reply}</p></div>}
      {s.needs_edit.length > 0 && <Notice tone="warn">Part of this was left out because it quoted a figure that isn&apos;t one of your prices.</Notice>}
    </section>
  );
}

export function GrowthBoard({ initial, chatUrl, isAdmin }: { initial: Segments; chatUrl: string; isAdmin: boolean }) {
  const [data, setData] = useState(initial);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  async function suggest() {
    setBusy(true);
    const r = await call<Segments>("growth/segments", { method: "POST" });
    setBusy(false);
    if (!r.ok) return toast(r.error, "error");
    setData(r.data);
  }

  return (
    <div className="stack">
      <section className="card stack" aria-labelledby="g-h">
        <div className="cardhead">
          <h2 id="g-h">Your ideal customers</h2>
          {isAdmin && <button className="btn primary" onClick={suggest} disabled={busy}>{busy ? "Thinking…" : data.segments.length ? "Suggest again" : "Suggest ideal customers"}</button>}
        </div>
        <p className="muted small">Your rep reads your products and describes the groups most likely to buy them, with a hook, a post and a reply for each. The fit score is an <strong>estimate from your catalogue</strong>, not measured demand. Check the Analytics page to see who actually buys.{data.made && <> Last made {relTime(data.made)}.</>}</p>
      </section>

      {data.segments.length === 0 ? (
        <div className="card"><Empty title="No suggestions yet">Press the button and your rep will work out who to aim at first.</Empty></div>
      ) : (
        <div className="grid g2">{data.segments.map((s) => <Card key={s.name} s={s} />)}</div>
      )}

      <section className="card stack" aria-labelledby="l-h">
        <h2 id="l-h">Tracked chat links</h2>
        <p className="muted small">Put a different link in each place you post. Every customer who starts a chat from one is counted under it in Analytics, so you can see which place brings buyers.</p>
        {PLACES.map(([key, label]) => {
          const url = `${chatUrl}?src=${key}`;
          return (
            <div className="listrow" key={key}>
              <div className="grow"><div className="title">{label}</div><div className="small muted mono" style={{ overflowWrap: "anywhere" }}>{url}</div></div>
              <Copy text={url} label="Copy link" />
            </div>
          );
        })}
      </section>
    </div>
  );
}
