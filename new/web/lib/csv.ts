// Cutting a product file into pieces small enough to send one at a time. Pure and unit-tested; the import card uses it.

export const CHUNK_CHARS = 180_000;       // the console's proxy accepts 256 KB per request
export const CHUNK_ROWS = 2000;

/** Split CSV text into records (lines), keeping a quoted cell that contains a line break in one piece. */
export function splitRecords(text: string): string[] {
  const out: string[] = [];
  let cur = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '"') quoted = !quoted;
    if (!quoted && (c === "\n" || c === "\r")) {
      if (c === "\r" && text[i + 1] === "\n") i++;
      out.push(cur);
      cur = "";
      continue;
    }
    cur += c;
  }
  if (cur !== "") out.push(cur);
  return out;
}

/** The index of the heading line: the first line near the top that mentions a name and a price. */
export function headerIndex(records: string[]): number {
  for (let i = 0; i < Math.min(records.length, 15); i++) {
    const r = records[i].toLowerCase();
    if (/name|product|item|title/.test(r) && /price|amount|cost|₦|naira|ngn/.test(r)) return i;
  }
  return 0;
}

export type Chunk = { csv: string; offset: number; rows: number };

/** Pieces that each start with the heading line. `offset` is how many lines of the file came before the piece's first product, so a
 *  problem can be reported against the line the owner sees in their spreadsheet. */
export function chunkCsv(text: string, maxChars = CHUNK_CHARS, maxRows = CHUNK_ROWS): Chunk[] {
  const records = splitRecords(text.replace(/^﻿/, ""));
  if (records.length === 0) return [];
  const h = headerIndex(records);
  const head = records[h];
  const chunks: Chunk[] = [];
  let lines: string[] = [];
  let size = head.length;
  let first = h + 1;
  const flush = (next: number) => {
    if (lines.length) chunks.push({ csv: [head, ...lines].join("\n"), offset: first - 1, rows: lines.length });
    lines = [];
    size = head.length;
    first = next;
  };
  for (let i = h + 1; i < records.length; i++) {
    const r = records[i];
    if (!r.trim()) {
      if (!lines.length) first = i + 1;      // blank lines at the start of a piece still count as lines of the file
      else lines.push(r);
      continue;
    }
    if (lines.length >= maxRows || size + r.length + 1 > maxChars) flush(i);
    lines.push(r);
    size += r.length + 1;
  }
  flush(records.length);
  return chunks;
}

/** A small, safe CSV cell for the file of skipped rows. */
export const csvCell = (s: string) => `"${s.replace(/"/g, '""')}"`;
