"use client";
import { useState } from "react";
import { Badge, Empty, Notice } from "@/components/ui";
import { useToast } from "@/components/toast";
import { call } from "@/lib/client";
import { relTime, titleCase } from "@/lib/format";
import type { OutreachProspect, OutreachState } from "@/lib/types";

const TONE: Record<string, "neutral" | "ok" | "warn" | "danger" | "info" | "brand"> = {
  new: "neutral", drafted: "info", approved: "brand", sent: "ok", replied: "ok", unsubscribed: "warn", failed: "danger", not_fit: "warn",
};

/** First line may be a header (email,name,company,note). Commas inside a note are fine: only the first three commas split. */
export function parseList(text: string): { email: string; name: string; company: string; note: string }[] {
  const rows = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (rows.length && /^email\b/i.test(rows[0])) rows.shift();
  return rows.map((line) => {
    const [email = "", name = "", company = "", ...note] = line.split(",");
    return { email: email.trim(), name: name.trim(), company: company.trim(), note: note.join(",").trim() };
  });
}

export function OutreachBoard({ initial }: { initial: OutreachState }) {
  const toast = useToast();
  const [state, setState] = useState(initial);
  const [busy, setBusy] = useState<string | null>(null);
  const [list, setList] = useState("");
  const [basis, setBasis] = useState("business_contact");
  const [attested, setAttested] = useState(false);
  const [offer, setOffer] = useState("");
  const [blocked, setBlocked] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [edit, setEdit] = useState({ subject: "", body: "" });
  const [whoOpen, setWhoOpen] = useState<number | null>(null);
  const [who, setWho] = useState({ name: "", company: "", title: "", note: "" });

  async function reload() {
    const r = await call<OutreachState>("outreach");
    if (r.ok) setState(r.data);
  }
  async function run<T>(key: string, path: string, method: "POST" | "PUT" | "DELETE", body: unknown, done: (d: T) => string) {
    setBusy(key);
    const r = await call<T>(path, { method, body });
    setBusy(null);
    if (!r.ok) return toast(r.error, "error");
    toast(done(r.data), "ok");
    await reload();
    return r.data;
  }

  const counts = state.summary.counts;
  const n = (k: string) => counts[k] ?? 0;
  const importList = async () => {
    const rows = parseList(list);
    const d = await run<{ added: number; duplicates: number; invalid: number; suppressed: number }>("import", "outreach/import", "POST", { rows, basis, attested },
      (d) => `Added ${d.added}. Skipped ${d.duplicates} duplicates, ${d.invalid} invalid and ${d.suppressed} who opted out.`);
    if (d) setList("");
  };
  const send = async () => {
    const d = await run<{ sent: number; failed: number; remaining_today: number; blocked: string }>("send", "outreach/send", "POST", {},
      (d) => (d.blocked ? "Nothing was sent." : `Sent ${d.sent}${d.failed ? `, ${d.failed} failed` : ""}. ${d.remaining_today} left for today.`));
    if (d) setBlocked(d.blocked);
  };
  const saveDetails = (p: OutreachProspect) => run("who" + p.id, `outreach/prospects/${p.id}/details`, "PUT", who, () => "Saved.");
  const keep = (p: OutreachProspect) => run("keep" + p.id, `outreach/prospects/${p.id}/keep`, "POST", {}, () => "Kept. They will be drafted next.");
  const save = (p: OutreachProspect) => run("save" + p.id, `outreach/prospects/${p.id}`, "PUT", edit, () => "Saved. Approve it again to send it.");

  return (
    <div className="stack">
      {!state.summary.ready_to_send && <Notice tone="warn">Add your business address in your business settings before sending. Commercial email must say who sent it and where they are.</Notice>}
      {blocked && <Notice tone="warn">{blocked}</Notice>}

      <section className="card stack" aria-labelledby="imp">
        <h2 id="imp">1. Add people</h2>
        <p className="small muted">One person per line: <span className="mono">email, name, company, note</span>. The note helps your rep write something relevant, for example &quot;runs a phone shop in Yaba&quot;. Up to 500 at a time.</p>
        <textarea rows={5} value={list} onChange={(e) => setList(e.target.value)} placeholder={"ada@example.com, Ada Obi, Obi Stores, runs a phone shop in Yaba"} aria-label="People to email" />
        <div className="row wrap">
          <select value={basis} onChange={(e) => setBasis(e.target.value)} aria-label="Why you may email them">
            {Object.entries(state.summary.lawful_bases).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        <label className="row small"><input type="checkbox" checked={attested} onChange={(e) => setAttested(e.target.checked)} /> I confirm I may lawfully email everyone on this list, and I will not buy or scrape lists.</label>
        <div><button className="btn primary" disabled={!!busy || !attested || !list.trim()} onClick={importList}>{busy === "import" ? "Adding…" : "Add to list"}</button></div>
      </section>

      <section className="card stack" aria-labelledby="dr">
        <h2 id="dr">2. Write the emails</h2>
        <textarea rows={2} value={offer} onChange={(e) => setOffer(e.target.value)} placeholder="What are you offering? For example: We supply brand new phones to retailers, with delivery across Lagos." aria-label="What you are offering" />
        <div className="row wrap">
          <button className="btn primary" disabled={!!busy || !offer.trim() || n("new") === 0} onClick={() => run("draft", "outreach/draft", "POST", { offer, limit: 25 }, (d: { drafted: number; failed: number }) => `Wrote ${d.drafted} emails${d.failed ? `, ${d.failed} need a different offer` : ""}.`)}>
            {busy === "draft" ? "Writing…" : `Write emails for ${Math.min(n("new"), 25)} people`}
          </button>
          <span className="small muted">Drafts never include prices, and every email gets your name, address and a "reply STOP" line automatically. There is no link in the email, which keeps it out of spam.</span>
        </div>
      </section>

      <section className="card stack" aria-labelledby="ap">
        <div className="row spread wrap">
          <h2 id="ap">3. Approve and send</h2>
          <span className="small muted">{n("drafted")} to review, {n("approved")} approved, {n("sent")} sent, {n("replied")} replied · today {state.summary.sent_today}/{state.summary.daily_cap}</span>
        </div>
        <div className="row wrap">
          <button className="btn" disabled={!!busy || n("drafted") === 0} onClick={() => run("approve", "outreach/approve", "POST", {}, (d: { approved: number }) => `Approved ${d.approved} emails.`)}>Approve all {n("drafted")} drafts</button>
          <button className="btn primary" disabled={!!busy || n("approved") === 0} onClick={send}>{busy === "send" ? "Sending…" : `Send ${n("approved")} approved`}</button>
        </div>
        {state.prospects.length === 0 ? <Empty title="No one on your list yet">Add people above and the emails will appear here for you to read.</Empty> : (
          <div className="tablewrap">
            <table className="table">
              <thead><tr><th>Person</th><th>Status</th><th>Email</th><th /></tr></thead>
              <tbody>
                {state.prospects.map((p) => (
                  <tr key={p.id}>
                    <td data-label="Person">
                      {whoOpen === p.id ? (
                        <div className="stack">
                          <input value={who.name} maxLength={80} onChange={(e) => setWho({ ...who, name: e.target.value })} placeholder="Name" aria-label="Name" />
                          <input value={who.title} maxLength={80} onChange={(e) => setWho({ ...who, title: e.target.value })} placeholder="Title or role, e.g. Procurement manager" aria-label="Title or role" />
                          <input value={who.company} maxLength={120} onChange={(e) => setWho({ ...who, company: e.target.value })} placeholder="Company" aria-label="Company" />
                          <input value={who.note} maxLength={400} onChange={(e) => setWho({ ...who, note: e.target.value })} placeholder="Note for your rep" aria-label="Note" />
                          <div className="row"><button className="btn sm primary" disabled={!!busy} onClick={async () => { await saveDetails(p); setWhoOpen(null); }}>Save</button><button className="btn sm" onClick={() => setWhoOpen(null)}>Cancel</button></div>
                        </div>
                      ) : (
                        <>
                          <strong>{p.name || p.email}</strong>
                          <div className="small muted">{p.name ? p.email : ""}{p.title ? ` · ${p.title}` : ""}{p.company ? ` · ${p.company}` : ""}</div>
                          {p.fit != null && <div className="small muted">Fit {p.fit}/100{p.fit_reason ? `: ${p.fit_reason}` : ""}{p.fit_model ? ` (${p.fit_model})` : ""}</div>}
                          {p.status === "not_fit" && <button className="btn sm ghost" disabled={!!busy} onClick={() => keep(p)}>Keep anyway</button>}
                          {!["sent", "replied", "unsubscribed"].includes(p.status) && <button className="btn sm ghost" onClick={() => { setWhoOpen(p.id); setWho({ name: p.name, company: p.company, title: p.title ?? "", note: p.note }); }}>Edit details</button>}
                        </>
                      )}
                    </td>
                    <td data-label="Status"><Badge tone={TONE[p.status] ?? "neutral"}>{titleCase(p.status)}</Badge>{p.error && <div className="small" style={{ color: "var(--warn)" }}>{p.error}</div>}</td>
                    <td data-label="Email">
                      {open === p.id ? (
                        <div className="stack">
                          <input value={edit.subject} onChange={(e) => setEdit({ ...edit, subject: e.target.value })} aria-label="Subject" />
                          <textarea rows={7} value={edit.body} onChange={(e) => setEdit({ ...edit, body: e.target.value })} aria-label="Email body" />
                          <div className="row"><button className="btn sm primary" disabled={!!busy} onClick={async () => { await save(p); setOpen(null); }}>Save</button><button className="btn sm" onClick={() => setOpen(null)}>Cancel</button></div>
                        </div>
                      ) : p.subject ? (
                        <div><strong>{p.subject}</strong><div className="small muted" style={{ whiteSpace: "pre-wrap" }}>{p.body}</div></div>
                      ) : <span className="muted">Not written yet</span>}
                      {p.sent && <div className="small muted">Sent {relTime(p.sent)}</div>}
                    </td>
                    <td>
                      <div className="row">
                        {(p.status === "drafted" || p.status === "approved") && open !== p.id && <button className="btn sm" onClick={() => { setOpen(p.id); setEdit({ subject: p.subject ?? "", body: p.body ?? "" }); }}>Edit</button>}
                        {p.status !== "sent" && p.status !== "replied" && <button className="btn sm" disabled={!!busy} onClick={() => run("rm" + p.id, `outreach/prospects/${p.id}`, "DELETE", undefined, () => "Removed.")}>Remove</button>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
