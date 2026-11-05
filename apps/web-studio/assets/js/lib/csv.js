// CSV reading with delimiter sniffing (like pandas read_csv(sep=None, engine="python")).

const CANDIDATES = [",", ";", "\t", "|"];

/** pick the delimiter that splits the first lines into the most consistent, widest rows */
export function sniffDelimiter(text) {
  const lines = text.split(/\r?\n/).filter((l) => l.trim()).slice(0, 20);
  let best = ",", bestScore = -1;
  for (const d of CANDIDATES) {
    const counts = lines.map((l) => splitLine(l, d).length);
    if (!counts.length || counts[0] < 2) continue;
    const consistent = counts.filter((c) => c === counts[0]).length / counts.length;
    const score = consistent * 1000 + counts[0];
    if (score > bestScore) { bestScore = score; best = d; }
  }
  return best;
}

function splitLine(line, d) {
  const out = [];
  let cur = "", q = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (q) {
      if (ch === '"') { if (line[i + 1] === '"') { cur += '"'; i++; } else q = false; }
      else cur += ch;
    } else if (ch === '"') q = true;
    else if (ch === d) { out.push(cur); cur = ""; }
    else cur += ch;
  }
  out.push(cur);
  return out;
}

/** full RFC-4180 parse (quoted fields may hold the delimiter and newlines) */
export function parseCSV(text, delimiter = null) {
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  const d = delimiter || sniffDelimiter(text);
  const rows = [];
  let row = [], cur = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (q) {
      if (ch === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else q = false; }
      else cur += ch;
    } else if (ch === '"') q = true;
    else if (ch === d) { row.push(cur); cur = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cur); cur = "";
      if (row.length > 1 || row[0] !== "") rows.push(row);
      row = [];
    } else cur += ch;
  }
  if (cur !== "" || row.length) { row.push(cur); if (row.length > 1 || row[0] !== "") rows.push(row); }
  if (!rows.length) throw new Error("empty file: no header row");
  const header = rows[0].map((h) => h.trim());
  const body = rows.slice(1).map((r) => {
    const o = {};
    header.forEach((h, k) => { o[h] = r[k] === undefined ? "" : r[k]; });
    return o;
  });
  return { header, rows: body, delimiter: d };
}

/** pandas-like scalar coercion: "" / NA tokens -> null, numbers -> Number, else the string */
const NA = new Set(["", "NA", "N/A", "NaN", "nan", "null", "NULL", "None", "#N/A", "-nan", "n/a", "<NA>"]);
export function scalar(v) {
  if (v === null || v === undefined) return null;
  if (typeof v === "number") return Number.isNaN(v) ? null : v;
  const s = String(v).trim();
  if (NA.has(s)) return null;
  if (/^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(s)) return Number(s);
  return s;
}
export function toNumber(v) {
  const s = scalar(v);
  return typeof s === "number" ? s : NaN;
}

/** rows (objects) -> CSV text */
export function toCSV(header, rows) {
  const esc = (v) => {
    if (v === null || v === undefined || (typeof v === "number" && Number.isNaN(v))) return "";
    const s = String(v);
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [header.join(","), ...rows.map((r) => header.map((h) => esc(r[h])).join(","))].join("\n");
}
