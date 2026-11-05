// Provenance tags (port of revive_ml/provenance.py) and Python-style string formatting helpers.
//   measured  - read or directly derived from measured data
//   synthetic - read or directly derived from synthetic or simulated data
//   modelled  - output of a fitted or physics model
//   assumed   - a literature or configuration constant

export const PROVENANCES = ["measured", "modelled", "assumed", "synthetic"];
export const PROJECTED_LABEL = "Projected (physics model)";

function clean(v) {
  if (typeof v === "boolean") return v ? 1 : 0;
  if (Number.isInteger(v) && Math.abs(v) < 2 ** 53) return v;
  if (!Number.isFinite(v)) return v;
  return Math.abs(v) < 1e9 ? Number(v.toFixed(6)) : v;
}

export function tag(value, provenance, unit = null, note = null, extra = {}) {
  if (!PROVENANCES.includes(provenance)) throw new Error(`unknown provenance ${provenance}`);
  const out = { value: value === null || value === undefined || Number.isNaN(value) ? null : clean(value), provenance };
  if (unit) out.unit = unit;
  if (note) out.note = note;
  return Object.assign(out, extra);
}

export const dataProvenanceTag = (p) => (p === "measured" ? "measured" : "synthetic");

// ---------------------------------------------------------------- Python formatting
/** f"{x:.Nf}" */
export const f = (x, n = 1) => (Number.isFinite(x) ? x.toFixed(n) : String(x));
/** f"{x:.0%}" */
export const pct0 = (x) => `${(100 * x).toFixed(0)}%`;
/** f"{x:,.0f}" */
export function comma0(x) {
  const s = Math.abs(x).toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return (x < 0 && Number(x.toFixed(0)) !== 0 ? "-" : "") + s;
}
/** f"{x:.4g}" */
export function g4(x) {
  if (!Number.isFinite(x)) return String(x);
  if (x === 0) return "0";
  const e = Math.floor(Math.log10(Math.abs(x)));
  if (e < -4 || e >= 4) {
    let [m, ex] = x.toExponential(3).split("e");
    m = m.replace(/\.?0+$/, "");
    const n = Number(ex);
    return `${m}e${n < 0 ? "-" : "+"}${String(Math.abs(n)).padStart(2, "0")}`;
  }
  return String(Number(x.toPrecision(4)));
}
/** repr() of a list of strings / dict of str -> int, as Python prints it */
export function pyRepr(v) {
  if (Array.isArray(v)) return `[${v.map(pyRepr).join(", ")}]`;
  if (typeof v === "string") return `'${v}'`;
  if (v && typeof v === "object") return `{${Object.entries(v).map(([k, x]) => `'${k}': ${pyRepr(x)}`).join(", ")}}`;
  return String(v);
}
