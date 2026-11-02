"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Badge, Empty } from "@/components/ui";
import { useToast } from "@/components/toast";
import { call } from "@/lib/client";
import { naira, relTime, toKobo } from "@/lib/format";
import type { Expense } from "@/lib/types";

export function ExpenseBook({ recent, categories, isAdmin }: { recent: Expense[]; categories: Record<string, number>; isAdmin: boolean }) {
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const router = useRouter();

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const kobo = toKobo(amount);
    if (!(kobo > 0)) return toast("Enter the amount in naira.", "error");
    setBusy(true);
    const r = await call("expenses", { method: "POST", body: { amount_kobo: kobo, note: note.trim() } });
    setBusy(false);
    if (!r.ok) return toast(r.error, "error");
    setAmount(""); setNote("");
    toast("Expense saved.", "ok");
    router.refresh();
  }
  async function remove(id: number) {
    const r = await call(`expenses/${id}`, { method: "DELETE" });
    if (!r.ok) return toast(r.error, "error");
    router.refresh();
  }

  const cats = Object.entries(categories);
  return (
    <div className="grid gmain">
      <section className="card flush" aria-labelledby="exp-h">
        <div className="cardhead" style={{ padding: "1rem 1.1rem 0" }}><h2 id="exp-h">Recent spending</h2></div>
        {recent.length === 0 ? (
          <Empty title="No spending logged yet">Tell your rep on Telegram, for example “spent 12k on generator fuel”, or add it here.</Empty>
        ) : (
          <div className="tablewrap">
            <table className="table">
              <thead><tr><th>When</th><th>What</th><th>Amount</th>{isAdmin && <th aria-label="Remove"></th>}</tr></thead>
              <tbody>
                {recent.map((x) => (
                  <tr key={x.id}>
                    <td className="small muted">{relTime(x.ts)}</td>
                    <td>{x.note || <span className="muted">No note</span>} <Badge>{x.category}</Badge></td>
                    <td><strong>{naira(x.amount_kobo)}</strong></td>
                    {isAdmin && <td><button className="btn sm ghost" onClick={() => remove(x.id)} aria-label={`Remove ${naira(x.amount_kobo)}`}>Remove</button></td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="stack">
        {isAdmin && (
          <form className="card stack" onSubmit={add} aria-labelledby="add-h">
            <h2 id="add-h">Add spending</h2>
            <label className="field">Amount (₦)<input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" placeholder="5,000" required /></label>
            <label className="field">What for<input value={note} onChange={(e) => setNote(e.target.value)} maxLength={120} placeholder="transport to the supplier" /></label>
            <button className="btn primary" disabled={busy}>{busy ? "Saving…" : "Save"}</button>
          </form>
        )}
        {cats.length > 0 && (
          <section className="card" aria-labelledby="cat-h">
            <h2 id="cat-h">This month by type</h2>
            {cats.map(([k, v]) => (
              <div className="listrow" key={k}><div className="grow">{k}</div><strong>{naira(v)}</strong></div>
            ))}
          </section>
        )}
      </div>
    </div>
  );
}
