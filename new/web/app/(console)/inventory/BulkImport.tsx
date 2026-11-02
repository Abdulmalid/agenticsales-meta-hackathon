"use client";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { Notice } from "@/components/ui";
import { useToast } from "@/components/toast";
import { call } from "@/lib/client";
import { chunkCsv, csvCell, type Chunk } from "@/lib/csv";
import { naira } from "@/lib/format";
import { SHEET_TEMPLATE } from "@/lib/inventory";
import type { ImportPreview, SheetReport } from "@/lib/types";

const MAX_FILE_BYTES = 25 * 1024 * 1024;
const FIELD_LABEL: Record<string, string> = { name: "Name", price: "Price", stock: "Stock", variants: "Sizes/colours", sku: "Code", fee: "Delivery", fee_local: "Lagos delivery", fee_other: "Other states delivery", active: "Listed", description: "Description" };
const n = (x: number) => x.toLocaleString("en-NG");

type Tally = { created: number; updated: number; restored: number; unchanged: number; skipped: string[]; skippedTotal: number; notAdded: string[] };
const blank = (): Tally => ({ created: 0, updated: 0, restored: 0, unchanged: 0, skipped: [], skippedTotal: 0, notAdded: [] });

function download(name: string, text: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob(["﻿" + text], { type: "text/csv" }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

/** Bring in a whole product file (thousands of rows) without drawing any of it: a preview of a few rows, a progress bar, a short summary. */
export function BulkImport() {
  const [file, setFile] = useState<{ name: string; chunks: Chunk[]; rows: number } | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [done, setDone] = useState(0);
  const [tally, setTally] = useState<Tally | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const stop = useRef(false);
  const toast = useToast();
  const router = useRouter();

  function reset() { setFile(null); setPreview(null); setTally(null); setErr(null); setDone(0); }

  async function pick(f: File | null | undefined) {
    if (!f) return;
    reset();
    if (/\.xlsx?$/i.test(f.name)) return setErr("That is an Excel file. In Excel choose File → Save As → CSV (Comma delimited), then upload the .csv.");
    if (f.size > MAX_FILE_BYTES) return setErr("That file is over 25 MB. Split it into two files and upload them one after the other.");
    setBusy("Reading the file…");
    const chunks = chunkCsv(await f.text());
    const rows = chunks.reduce((t, c) => t + c.rows, 0);
    if (!rows) { setBusy(null); return setErr("No products found. The first row needs headings such as Product Name and Price (₦)."); }
    const r = await call<ImportPreview>("inventory/import", { method: "POST", body: { csv: chunks[0].csv, line_offset: chunks[0].offset, dry_run: true } });
    setBusy(null);
    if (!r.ok) return setErr(r.error);
    setFile({ name: f.name, chunks, rows });
    setPreview(r.data);
  }

  async function run() {
    if (!file) return;
    stop.current = false;
    setErr(null); setDone(0);
    const t = blank();
    let used = 0;
    for (const [i, c] of file.chunks.entries()) {
      if (stop.current) break;
      setBusy(`Importing… ${n(used)} of ${n(file.rows)}`);
      const r = await call<SheetReport>("inventory/import", { method: "POST", body: { csv: c.csv, line_offset: c.offset } });
      if (!r.ok) { setErr(`Stopped after ${n(used)} products: ${r.error}. Everything before that is saved; upload the file again to carry on.`); break; }
      const k = r.data.counts;
      t.created += k?.created ?? r.data.created.length; t.updated += k?.updated ?? r.data.updated.length;
      t.restored += k?.restored ?? r.data.restored.length; t.unchanged += r.data.unchanged;
      const lines = r.data.problem_lines ?? r.data.problems;
      const plan = lines.filter((p) => /not added: your plan/.test(p));
      t.notAdded.push(...plan);
      t.skipped.push(...lines.filter((p) => !plan.includes(p)));
      t.skippedTotal += Math.max(0, (k?.problems ?? lines.length) - plan.length);
      used += c.rows;
      setDone((i + 1) / file.chunks.length);
    }
    setBusy(null);
    setTally(t);
    if (t.created || t.updated) toast("Products imported.", "ok");
    router.refresh();
  }

  const sample = preview?.rows ?? [];
  return (
    <section className="card stack" aria-labelledby="bulk-h">
      <div className="cardhead">
        <h2 id="bulk-h">Import a product file</h2>
        <button type="button" className="btn sm ghost" onClick={() => download("inventory-template.csv", SHEET_TEMPLATE)}>Download template</button>
      </div>
      <p className="muted small">For a long list: save your spreadsheet as a CSV and upload it here. Thousands of rows are fine; they go in a few at a time and only a short summary is shown. Products already here are updated by code or name, and nothing is removed.</p>

      {!file && !tally && (
        <div
          className="dropzone" data-over={over}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); void pick(e.dataTransfer.files?.[0]); }}
        >
          <strong>{busy ?? "Drop your CSV file here"}</strong>
          <label className="btn sm" style={{ cursor: "pointer" }}>
            Choose a file
            <input type="file" accept=".csv,text/csv" hidden disabled={!!busy} onChange={(e) => { void pick(e.target.files?.[0]); e.target.value = ""; }} />
          </label>
        </div>
      )}

      {err && <Notice tone="danger">{err}</Notice>}

      {file && preview && !tally && (
        <div className="stack">
          <div className="row spread wrap">
            <div><strong>{file.name}</strong><div className="small muted">{n(file.rows)} product{file.rows === 1 ? "" : "s"} found{preview.problem_count ? ` · ${n(preview.problem_count)} problem${preview.problem_count === 1 ? "" : "s"} in the first part` : ""}</div></div>
            {!busy && <button type="button" className="btn sm ghost" onClick={reset}>Choose another</button>}
          </div>
          <div className="row wrap" style={{ gap: "0.35rem" }} aria-label="Columns understood">
            {Object.entries(preview.columns).map(([f, h]) => <span key={f} className="badge brand">{FIELD_LABEL[f] ?? f}<span className="muted"> ← {h}</span></span>)}
          </div>
          <div className="tablewrap">
            <table className="table">
              <thead><tr><th>First rows</th><th>Price</th><th>Stock</th></tr></thead>
              <tbody>{sample.map((r, i) => <tr key={i}><td data-label="Product">{r.name}</td><td data-label="Price">{naira(r.price_kobo)}</td><td data-label="Stock">{r.stock ?? (Object.keys(r.variants).length ? Object.keys(r.variants).join(", ") : "–")}</td></tr>)}</tbody>
            </table>
          </div>
          {busy ? (
            <div className="stack" style={{ gap: "0.5rem" }}>
              <div className="bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(done * 100)} aria-label="Import progress"><span style={{ width: `${Math.max(done * 100, 3)}%`, animation: "none", transition: "width .3s" }} /></div>
              <div className="row spread"><span className="small muted">{busy}</span><button type="button" className="btn sm" onClick={() => { stop.current = true; }}>Stop after this part</button></div>
            </div>
          ) : (
            <div><button type="button" className="btn primary" onClick={run}>Import {n(file.rows)} product{file.rows === 1 ? "" : "s"}</button></div>
          )}
        </div>
      )}

      {tally && (
        <div className="stack">
          <Notice tone={tally.skippedTotal || tally.notAdded.length ? "warn" : "ok"}>
            <strong>{[tally.created && `${n(tally.created)} added`, tally.updated && `${n(tally.updated)} updated`, tally.restored && `${n(tally.restored)} back on sale`].filter(Boolean).join(", ") || "Nothing needed changing"}</strong>
            {tally.unchanged > 0 && <> · {n(tally.unchanged)} already up to date</>}
            {tally.skippedTotal > 0 && <> · {n(tally.skippedTotal)} row{tally.skippedTotal === 1 ? "" : "s"} skipped</>}
            {tally.notAdded.length > 0 && <div>{tally.notAdded.join(" ")} Ask for a bigger plan to add the rest.</div>}
          </Notice>
          <div className="row wrap">
            {tally.skipped.length > 0 && <button type="button" className="btn sm" onClick={() => download("skipped-rows.csv", "Why\n" + tally.skipped.map(csvCell).join("\n"))}>Download the skipped rows</button>}
            <button type="button" className="btn sm" onClick={reset}>Import another file</button>
          </div>
        </div>
      )}
    </section>
  );
}
