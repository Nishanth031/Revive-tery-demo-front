// Formatting. A missing value is always "—" (callers add the reason next to it).
export const DASH = "—";
const ok = (v) => v !== null && v !== undefined && Number.isFinite(Number(v));

export function num(v, digits = 0) {
  if (!ok(v)) return DASH;
  return Number(v).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
export function usd(v, digits = 0) {
  if (!ok(v)) return DASH;
  const n = Number(v);
  const s = Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${n < 0 ? "−" : ""}$${s}`;
}
export function signedUsd(v) { if (!ok(v)) return DASH; return `${Number(v) >= 0 ? "+" : ""}${usd(v)}`.replace("+−", "−"); }
export function pct(v, digits = 1) { return ok(v) ? `${num(v, digits)} %` : DASH; }
export function years(v, digits = 1) { return ok(v) ? `${num(v, digits)} yr` : DASH; }
export function date(iso) {
  if (!iso) return DASH;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? DASH : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}
export function datetime(iso) {
  if (!iso) return DASH;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? DASH : d.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}
export const isNum = ok;
export function humanKey(k) { return String(k ?? "").replace(/_/g, " ").replace(/\b\w/, (c) => c.toUpperCase()); }
export const DISP_SHORT = { REUSE: "Reuse", REPURPOSE: "Repurpose", RECYCLE: "Recycle", INSPECT: "Inspect", NO_DECISION: "No decision" };
export function median(arr) {
  const a = arr.filter(ok).map(Number).sort((x, y) => x - y);
  if (!a.length) return null;
  const m = Math.floor(a.length / 2);
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
}
