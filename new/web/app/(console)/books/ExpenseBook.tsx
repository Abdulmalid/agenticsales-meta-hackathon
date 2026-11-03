"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Badge, Empty } from "@/components/ui";
import { useToast } from "@/components/toast";
import { call } from "@/lib/client";
import { naira, relTime, toKobo } from "@/lib/format";
import type { Books, Expense } from "@/lib/types";

export function ExpenseBook({ recent, categories, limits, isAdmin }: { recent: Expense[]; categories: Record<string, number>; limits: Books["limits"]; isAdmin: boolean }) {
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [per, setPer] = useState(limits.per_expense_kobo ? String(limits.per_expense_kobo / 100) : "");
  const [daily, setDaily] = useState(limits.daily_kobo ? String(limits.daily_kobo / 100) : "");
  const toast = useToast();
  const router = useRouter();

  async function saveLimits(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const r = await call("books/limits", { method: "PUT", body: { per_expense_kobo: per.trim() ? toKobo(per) : null, daily_kobo: daily.trim() ? toKobo(daily) : null } });
    setBusy(false);
    if (!r.ok) return toast(r.error, "error");
    toast(per.trim() || daily.trim() ? "Limits saved." : "Limits removed.", "ok");
    router.refresh();
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const kobo = toKobo(amount);
    if (!(kobo > 0)) return toast("Enter the amount in naira.", "error");
    setBusy(true);
    let r = await call("expenses", { method: "POST", body: { amount_kobo: kobo, note: note.trim() } });
    if (!r.ok && r.status === 409) {                                           // above the owner's own limit: only a deliberate second step records it
      if (!window.confirm(`${r.error}

Record it anyway?`)) { setBusy(false); return; }
      r = await call("expenses", { method: "POST", body: { amount_kobo: kobo, note: note.trim(), confirm: true } });
    }
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
        {isAdmin && (
          <form className="card stack" onSubmit={saveLimits} aria-labelledby="lim-h">
            <h2 id="lim-h">Spending limits</h2>
            <p className="small muted">A guard against typing errors and runaway spending. Above a limit, your rep will not log an expense from chat, and the console asks you to confirm. Leave a box empty for no limit.</p>
            <label className="field">Most for one expense (₦)<input value={per} onChange={(e) => setPer(e.target.value)} inputMode="decimal" placeholder="200,000" /></label>
            <label className="field">Most per day (₦)<input value={daily} onChange={(e) => setDaily(e.target.value)} inputMode="decimal" placeholder="500,000" /></label>
            <button className="btn" disabled={busy}>Save limits</button>
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
