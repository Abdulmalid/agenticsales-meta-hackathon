"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Notice } from "@/components/ui";
import { useToast } from "@/components/toast";
import { call } from "@/lib/client";
import { csvCell } from "@/lib/csv";
import { photoToBase64 } from "@/lib/photo";
import type { LedgerReading, SheetReport } from "@/lib/types";

type Line = { name: string; price: string; stock: string; sizes: string };
const MAX_LINES = 400;
const HEADINGS = "Product Name,Price (₦),Stock Quantity,Available Sizes/Colors";
const priceOf = (l: Line) => Number(l.price.replace(/[₦,\s]/g, ""));

/** Photograph the store book or price list: the rep reads the page into rows, the owner checks and corrects them, and only then are they imported. */
export function LedgerScan() {
  const [lines, setLines] = useState<Line[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const [result, setResult] = useState<SheetReport | null>(null);
  const toast = useToast();
  const router = useRouter();

  async function read(files: FileList | null) {
    if (!files?.length) return;
    setErr(null); setResult(null);
    const next = [...lines];
    const said: string[] = [];
    for (const [i, f] of Array.from(files).entries()) {
      setBusy(`Reading page ${i + 1} of ${files.length}…`);
      let data: string;
      try { data = await photoToBase64(f, 1800); } catch { setErr("That file is not a photo this browser can open."); break; }
      const r = await call<LedgerReading>("inventory/ledger", { method: "POST", body: { data } });
      if (!r.ok) { setErr(r.error); break; }
      if (!r.data.readable) said.push(r.data.note || `Page ${i + 1} could not be read. Try a closer, brighter photo.`);
      else if (r.data.note) said.push(`Page ${i + 1}: ${r.data.note}`);
      for (const row of r.data.rows) {
        if (next.length >= MAX_LINES || next.some((l) => l.name.trim().toLowerCase() === row.name.toLowerCase())) continue;
        next.push({ name: row.name, price: row.price_kobo ? String(row.price_kobo / 100) : "", stock: row.stock == null ? "" : String(row.stock), sizes: row.sizes });
      }
    }
    setBusy(null);
    setNotes(said);
    setLines(next);
  }

  const set = (i: number, k: keyof Line, v: string) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, [k]: v } : l)));
  const ready = lines.filter((l) => l.name.trim().length >= 2 && priceOf(l) > 0);
  const missing = lines.length - ready.length;

  async function add() {
    if (!ready.length) return;
    setBusy("Adding to your inventory…"); setErr(null);
    const csv = [HEADINGS, ...ready.map((l) => [l.name.trim(), String(priceOf(l)), l.stock.trim(), l.sizes.trim()].map(csvCell).join(","))].join("\n");
    const r = await call<SheetReport>("inventory/import", { method: "POST", body: { csv } });
    setBusy(null);
    if (!r.ok) return setErr(r.error);
    setResult(r.data); setLines([]); setNotes([]);
    toast("Products added.", "ok");
    router.refresh();
  }

  const picker = (label: string, camera = false) => (
    <label className="btn sm" style={{ cursor: "pointer" }}>
      {label}
      <input type="file" accept="image/*" {...(camera ? { capture: "environment" as const } : {})} multiple hidden disabled={!!busy} onChange={(e) => { void read(e.target.files); e.target.value = ""; }} />
    </label>
  );

  return (
    <section className="card stack" aria-labelledby="ledger-h">
      <div className="cardhead"><h2 id="ledger-h">Add products from a photo of your book</h2></div>
      <p className="muted small">Take a clear photo of, or upload an image of, your store book, stock ledger or price list. Your rep reads it into a list for you to check, then adds the products and stock counts. Handwriting is sometimes misread, so nothing is added until you confirm. Products already here are updated by name.</p>

      {!lines.length && (
        <div className="dropzone">
          <strong>{busy ?? "Photograph or upload a page of your book"}</strong>
          {picker("Take a photo", true)}{picker("Upload images")}
          <span className="small muted">You can pick several pages at once.</span>
        </div>
      )}

      {err && <Notice tone="danger">{err}</Notice>}
      {notes.map((t, i) => <Notice key={i} tone="warn">{t}</Notice>)}
      {result && (
        <Notice tone={result.problems.length ? "warn" : "ok"}>
          <strong>{[result.counts?.created && `${result.counts.created} added`, result.counts?.updated && `${result.counts.updated} updated`].filter(Boolean).join(", ") || "Nothing needed changing"}</strong>
          {result.problems.length > 0 && <> · {result.problems.slice(0, 3).join("; ")}</>}
        </Notice>
      )}

      {lines.length > 0 && (
        <div className="stack">
          <div className="small muted">{lines.length} product{lines.length === 1 ? "" : "s"} read. Fix anything that is wrong, and fill in prices that could not be read.</div>
          <div className="tablewrap">
            <table className="table">
              <thead><tr><th>Product</th><th>Price (₦)</th><th>In stock</th><th>Specifications</th><th aria-label="Remove"></th></tr></thead>
              <tbody>
                {lines.map((l, i) => (
                  <tr key={i}>
                    <td data-label="Product"><input value={l.name} maxLength={80} aria-label="Product name" onChange={(e) => set(i, "name", e.target.value)} /></td>
                    <td data-label="Price (₦)"><input inputMode="decimal" value={l.price} aria-label="Price" aria-invalid={!ready.includes(l)} placeholder="needed" onChange={(e) => set(i, "price", e.target.value)} /></td>
                    <td data-label="In stock"><input inputMode="numeric" value={l.stock} aria-label="Stock" onChange={(e) => set(i, "stock", e.target.value)} /></td>
                    <td data-label="Specifications"><input value={l.sizes} maxLength={200} aria-label="Specifications" placeholder="128GB Violet (2), 256GB Black (4)" onChange={(e) => set(i, "sizes", e.target.value)} /></td>
                    <td><button type="button" className="btn sm ghost" aria-label={`Remove ${l.name}`} onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}>Remove</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {missing > 0 && <Notice tone="warn">{missing} row{missing === 1 ? " has" : "s have"} no price, so {missing === 1 ? "it" : "they"} will be left out until you add one.</Notice>}
          <div className="row wrap">
            <button type="button" className="btn primary" disabled={!ready.length || !!busy} onClick={add}>{busy ?? `Add ${ready.length} product${ready.length === 1 ? "" : "s"}`}</button>
            {picker("Add another page")}
            <button type="button" className="btn sm ghost" disabled={!!busy} onClick={() => { setLines([]); setNotes([]); }}>Start over</button>
          </div>
        </div>
      )}
    </section>
  );
}
