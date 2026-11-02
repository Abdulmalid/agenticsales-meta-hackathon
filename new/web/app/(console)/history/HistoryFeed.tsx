"use client";
import { useState } from "react";
import { Badge, Empty } from "@/components/ui";
import { useToast } from "@/components/toast";
import { call } from "@/lib/client";
import { stamp } from "@/lib/format";
import type { HistoryPage } from "@/lib/types";

const KINDS: [string, string][] = [["", "Everything"], ["sales", "Sales"], ["stock", "Stock"], ["delivery", "Deliveries"], ["approvals", "Decisions"], ["agent", "What the rep did"]];
const TONE: Record<string, "ok" | "info" | "brand" | "warn" | "neutral"> = { sales: "ok", stock: "info", delivery: "brand", approvals: "warn", agent: "neutral" };
const LABEL: Record<string, string> = { sales: "Sale", stock: "Stock", delivery: "Delivery", approvals: "Decision", agent: "Rep" };

export function HistoryFeed({ initial }: { initial: HistoryPage }) {
  const toast = useToast();
  const [kind, setKind] = useState("");
  const [page, setPage] = useState(initial);
  const [busy, setBusy] = useState(false);

  async function load(k: string, before?: string | null) {
    setBusy(true);
    const r = await call<HistoryPage>(`history?limit=100${k ? `&kind=${k}` : ""}${before ? `&before=${encodeURIComponent(before)}` : ""}`);
    setBusy(false);
    if (!r.ok) return toast(r.error, "error");
    setPage(before ? { items: [...page.items, ...r.data.items], next_before: r.data.next_before } : r.data);
  }

  return (
    <>
      <div className="tabs" role="tablist">
        {KINDS.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={kind === k} onClick={() => { setKind(k); load(k); }}>{label}</button>
        ))}
      </div>
      {page.items.length === 0 ? (
        <div className="card"><Empty title="Nothing here yet">Sales, stock changes and deliveries show up here as they happen.</Empty></div>
      ) : (
        <div className="card flush tablewrap">
          <table className="table">
            <thead><tr><th>When</th><th>What happened</th><th>By</th></tr></thead>
            <tbody>
              {page.items.map((e, i) => (
                <tr key={`${e.ts}-${i}`}>
                  <td className="small mono" style={{ whiteSpace: "nowrap" }}>{stamp(e.ts)}</td>
                  <td><Badge tone={TONE[e.kind] ?? "neutral"}>{LABEL[e.kind] ?? e.kind}</Badge> {e.text}{e.ref && <span className="small muted mono" style={{ display: "block" }}>{e.ref}</span>}</td>
                  <td className="small muted">{e.actor || "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {page.next_before && <div style={{ marginTop: "1rem" }}><button className="btn" disabled={busy} onClick={() => load(kind, page.next_before)}>{busy ? "Loading…" : "Show older"}</button></div>}
    </>
  );
}
