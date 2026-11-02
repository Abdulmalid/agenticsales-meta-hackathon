"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Badge, Notice } from "@/components/ui";
import { useToast } from "@/components/toast";
import { call } from "@/lib/client";
import { relTime } from "@/lib/format";
import type { TeamMember } from "@/lib/types";

const EXPIRY = [["90", "90 days (recommended)"], ["30", "30 days"], ["365", "1 year"], ["0", "Never expires (avoid)"]] as const;

export function TeamBoard({ members }: { members: TeamMember[] }) {
  const [label, setLabel] = useState("");
  const [expiry, setExpiry] = useState("90");
  const [busy, setBusy] = useState(false);
  const [made, setMade] = useState<{ key: string; label: string } | null>(null);
  const toast = useToast();
  const router = useRouter();

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const days = Number(expiry);
    const r = await call<{ key: string }>("team", { method: "POST", body: { label: label.trim(), expires_days: days || null } });
    setBusy(false);
    if (!r.ok) return toast(r.error, "error");
    setMade({ key: r.data.key, label: label.trim() });
    setLabel("");
    router.refresh();
  }
  async function remove(m: TeamMember) {
    if (!window.confirm(`Remove ${m.label || "this person"}? They are signed out immediately.`)) return;
    const r = await call(`team/${m.id}`, { method: "DELETE" });
    if (!r.ok) return toast(r.error, "error");
    toast("Removed.", "ok");
    router.refresh();
  }
  const state = (m: TeamMember) => (m.revoked ? <Badge tone="danger">Removed</Badge> : m.expires && new Date(m.expires) < new Date() ? <Badge tone="warn">Expired</Badge> : <Badge tone="ok">Active</Badge>);

  return (
    <div className="stack">
      <section className="card stack" aria-labelledby="t-add">
        <h2 id="t-add">Add a team member</h2>
        {made && (
          <div className="notice ok stack" role="status">
            <strong>Give this token to {made.label} privately. It is shown only once.</strong>
            <code className="mono" style={{ wordBreak: "break-all", userSelect: "all" }}>{made.key}</code>
            <div className="row">
              <button className="btn sm" onClick={() => navigator.clipboard.writeText(made.key).then(() => toast("Copied.", "ok"), () => toast("Couldn't copy; select and copy it.", "error"))}>Copy</button>
              <button className="btn sm ghost" onClick={() => setMade(null)}>I&apos;ve sent it</button>
            </div>
          </div>
        )}
        <form className="row wrap" onSubmit={add}>
          <label className="field" style={{ flex: "1 1 14rem" }}>Name and role<input value={label} onChange={(e) => setLabel(e.target.value)} required minLength={2} maxLength={80} placeholder="e.g. Bola (sales)" /></label>
          <label className="field">Expires
            <select value={expiry} onChange={(e) => setExpiry(e.target.value)}>{EXPIRY.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
          </label>
          <button className="btn primary" disabled={busy} style={{ alignSelf: "end" }}>{busy ? "Adding…" : "Add staff member"}</button>
        </form>
        <Notice tone="info">New people are always <strong>staff</strong>: they handle customers and approvals, but they can&apos;t change settings, prices, delivery fees, connections or your team, they can&apos;t decide anything that involves money (discounts, orders, payment checks, refunds), and they can never confirm a payment (only the payment gateway does), and they only see the books or publish posts if you allow it in Settings. Only the AgenticSales team can create another admin.</Notice>
      </section>

      <section className="card flush" aria-labelledby="t-list">
        <h2 id="t-list" style={{ padding: "1rem 1.1rem 0" }}>People with access</h2>
        <div className="tablewrap">
          <table className="table">
            <thead><tr><th>Name</th><th>Access</th><th>Added</th><th>Last signed in</th><th>Expires</th><th>Status</th><th /></tr></thead>
            <tbody>
              {members.map((m) => (
                <tr key={m.id}>
                  <td data-label="Name">{m.label || <span className="muted">#{m.id}</span>}{m.you && <> <Badge tone="brand">You</Badge></>}</td>
                  <td data-label="Access">{m.role === "admin" ? "Admin" : "Staff"}</td>
                  <td data-label="Added" className="muted" suppressHydrationWarning>{relTime(m.created)}</td>
                  <td data-label="Last signed in" className="muted" suppressHydrationWarning>{relTime(m.last_used)}</td>
                  <td data-label="Expires" className="muted" suppressHydrationWarning>{m.expires ? new Date(m.expires).toLocaleDateString("en-GB") : "Never"}</td>
                  <td data-label="Status">{state(m)}</td>
                  <td>{m.role === "staff" && !m.revoked && <button className="btn sm" onClick={() => remove(m)}>Remove</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
