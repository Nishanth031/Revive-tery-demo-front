// Data contract (port of revive_ml/contract.py and convert.py) and the upload adapter
// (port of bulid X/src/ml_engine_bridge.py). A bundle is { meta, tel, ignored_columns }.
// tel is columnar: { n, columns: [...], t: Float64Array (epoch seconds), asset_id: [], voltage_v: Float64Array, ... }.

import { parseCSV, scalar, toNumber } from "../lib/csv.js";
import { ruleRoute } from "./state.js";

export class ContractError extends Error { constructor(m) { super(m); this.name = "ContractError"; } }
export class AdapterError extends Error { constructor(m) { super(m); this.name = "AdapterError"; } }

export const REQUIRED_COLUMNS = ["asset_id", "timestamp_utc", "voltage_v", "current_a", "temperature_c"];
export const OPTIONAL_COLUMNS = ["soc_pct", "min_temperature_c", "ambient_temperature_c", "power_kw",
  "operating_state", "bms_soh_pct"];
export const FLOAT_COLUMNS = ["voltage_v", "current_a", "temperature_c", "soc_pct", "min_temperature_c",
  "ambient_temperature_c", "power_kw", "bms_soh_pct"];
const KNOWN_FOREIGN_NAMES = { pack_voltage_V: "voltage_v", pack_current_A: "current_a",
  max_cell_temp_C: "temperature_c", soh_pct: "bms_soh_pct", power_kW: "power_kw" };
const CHEMISTRIES = ["LFP", "NMC", "NCA"];
const PROVENANCES = ["measured", "simulated", "synthetic"];
const CONVENTIONS = ["discharge_negative", "discharge_positive", "unknown"];

// ---------------------------------------------------------------- time
const ISO = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d+))?)?)?\s*(Z|z|[+-]\d{2}(?::?\d{2})?)?$/;
/** ISO-8601 text -> epoch seconds (microseconds kept). Naive times are read as UTC, as pandas utc=True does. */
export function parseIso(s) {
  if (s === null || s === undefined) return NaN;
  if (typeof s === "number") return s;
  const m = ISO.exec(String(s).trim());
  if (!m) return NaN;
  const [, Y, Mo, D, h = "0", mi = "0", se = "0", frac = "", tz] = m;
  let t = Date.UTC(+Y, +Mo - 1, +D, +h, +mi, +se) / 1000;
  if (frac) t += Number(`0.${frac}`);
  if (tz && tz.toUpperCase() !== "Z") {
    const sgn = tz[0] === "-" ? -1 : 1, body = tz.slice(1).replace(":", "");
    t -= sgn * (Number(body.slice(0, 2)) * 3600 + Number(body.slice(2, 4) || 0) * 60);
  }
  return t;
}
/** lenient parse for uploads (pandas to_datetime(errors="coerce")) */
export function parseTimeLenient(s) {
  const t = parseIso(s);
  if (!Number.isNaN(t)) return t;
  if (s === null || s === undefined || String(s).trim() === "") return NaN;
  const ms = Date.parse(`${String(s).trim()} UTC`);
  return Number.isNaN(ms) ? (Number.isNaN(Date.parse(s)) ? NaN : Date.parse(s) / 1000) : ms / 1000;
}
export function isoUTC(sec, withFrac = false) {
  if (!Number.isFinite(sec)) return null;
  const d = new Date(Math.round(sec * 1000));
  const s = d.toISOString();
  return withFrac ? s : s.replace(/\.\d{3}Z$/, "Z");
}
const dateOnly = (sec) => new Date(Math.floor(sec) * 1000).toISOString().slice(0, 10);

// ---------------------------------------------------------------- metadata (pydantic model)
function checkKeys(obj, allowed, where) {
  const extra = Object.keys(obj).filter((k) => !allowed.includes(k));
  if (extra.length) throw new ContractError(`${where}: extra field(s) not permitted: ${extra.join(", ")}`);
}
function posFloat(v, name) {
  const x = typeof v === "string" ? Number(v) : v;
  if (typeof x !== "number" || !Number.isFinite(x) || x <= 0) throw new ContractError(`${name} must be a positive number, got ${JSON.stringify(v)}`);
  return x;
}
function optInt(v, name, minExclusive = null, minInclusive = null) {
  if (v === null || v === undefined) return null;
  const x = typeof v === "string" ? Number(v) : v;
  if (!Number.isInteger(x)) throw new ContractError(`${name} must be an integer, got ${JSON.stringify(v)}`);
  if (minExclusive !== null && !(x > minExclusive)) throw new ContractError(`${name} must be > ${minExclusive}`);
  if (minInclusive !== null && !(x >= minInclusive)) throw new ContractError(`${name} must be >= ${minInclusive}`);
  return x;
}
function lit(v, options, name) {
  if (!options.includes(v)) throw new ContractError(`${name} must be one of ${options.join(" | ")}, got ${JSON.stringify(v)}`);
  return v;
}
function dateField(v, name) {
  const s = String(v ?? "");
  const m = /^(\d{4}-\d{2}-\d{2})(?:[T ]00:00(?::00(?:\.0+)?)?(?:Z|\+00:00)?)?$/.exec(s);
  if (!m || Number.isNaN(Date.parse(m[1]))) throw new ContractError(`${name} must be a date (YYYY-MM-DD), got ${JSON.stringify(v)}`);
  return m[1];
}
const optStr = (v) => (v === null || v === undefined ? null : String(v));

export function validateMetadata(raw) {
  if (!raw || typeof raw !== "object") throw new ContractError("metadata.json must hold a JSON object");
  checkKeys(raw, ["asset_id", "chemistry", "rated_capacity_ah", "nominal_voltage_v", "min_voltage_v", "max_voltage_v",
    "series_cells", "parallel_cells", "data_provenance", "current_sign_convention", "cell_model", "cycle_count",
    "capacity_tests", "resistance_tests", "safety_events", "notes", "source"], "metadata");
  for (const k of ["asset_id", "chemistry", "rated_capacity_ah", "nominal_voltage_v", "min_voltage_v", "max_voltage_v", "data_provenance"]) {
    if (raw[k] === undefined || raw[k] === null) throw new ContractError(`metadata: field required: ${k}`);
  }
  const rec = (r, i, kind, keys) => {
    checkKeys(r, keys, `${kind}[${i}]`);
    return { provenance: lit(r.provenance, PROVENANCES, `${kind}[${i}].provenance`) };
  };
  const meta = {
    asset_id: String(raw.asset_id),
    chemistry: lit(raw.chemistry, CHEMISTRIES, "chemistry"),
    rated_capacity_ah: posFloat(raw.rated_capacity_ah, "rated_capacity_ah"),
    nominal_voltage_v: posFloat(raw.nominal_voltage_v, "nominal_voltage_v"),
    min_voltage_v: posFloat(raw.min_voltage_v, "min_voltage_v"),
    max_voltage_v: posFloat(raw.max_voltage_v, "max_voltage_v"),
    series_cells: optInt(raw.series_cells, "series_cells", 0),
    parallel_cells: optInt(raw.parallel_cells, "parallel_cells", 0),
    data_provenance: lit(raw.data_provenance, PROVENANCES, "data_provenance"),
    current_sign_convention: lit(raw.current_sign_convention ?? "unknown", CONVENTIONS, "current_sign_convention"),
    cell_model: optStr(raw.cell_model),
    cycle_count: optInt(raw.cycle_count, "cycle_count", null, 0),
    capacity_tests: (raw.capacity_tests || []).map((r, i) => ({
      ...rec(r, i, "capacity_tests", ["provenance", "date", "cycle_count", "measured_capacity_ah", "method"]),
      date: dateField(r.date, `capacity_tests[${i}].date`),
      cycle_count: optInt(r.cycle_count, `capacity_tests[${i}].cycle_count`, null, 0),
      measured_capacity_ah: posFloat(r.measured_capacity_ah, `capacity_tests[${i}].measured_capacity_ah`),
      method: optStr(r.method),
    })),
    resistance_tests: (raw.resistance_tests || []).map((r, i) => ({
      ...rec(r, i, "resistance_tests", ["provenance", "date", "cycle_count", "resistance_mohm", "level", "method"]),
      date: dateField(r.date, `resistance_tests[${i}].date`),
      cycle_count: optInt(r.cycle_count, `resistance_tests[${i}].cycle_count`, null, 0),
      resistance_mohm: posFloat(r.resistance_mohm, `resistance_tests[${i}].resistance_mohm`),
      level: lit(r.level ?? "pack", ["pack", "cell"], `resistance_tests[${i}].level`),
      method: optStr(r.method),
    })),
    safety_events: (raw.safety_events || []).map((r, i) => {
      const base = rec(r, i, "safety_events", ["provenance", "timestamp_utc", "event_type", "severity", "status", "description"]);
      const t = parseIso(r.timestamp_utc);
      if (Number.isNaN(t)) throw new ContractError(`safety_events[${i}].timestamp_utc is not a datetime`);
      for (const k of ["event_type", "severity"]) if (r[k] === undefined || r[k] === null) throw new ContractError(`safety_events[${i}]: field required: ${k}`);
      return { ...base, timestamp_utc: isoUTC(t), event_type: String(r.event_type), severity: String(r.severity),
        status: optStr(r.status), description: optStr(r.description) };
    }),
    notes: optStr(raw.notes),
    source: optStr(raw.source),
  };
  if (!(meta.min_voltage_v < meta.nominal_voltage_v && meta.nominal_voltage_v < meta.max_voltage_v)) {
    throw new ContractError(`voltages must satisfy min_voltage_v < nominal_voltage_v < max_voltage_v, got ` +
      `${meta.min_voltage_v} / ${meta.nominal_voltage_v} / ${meta.max_voltage_v}`);
  }
  return meta;
}

// ---------------------------------------------------------------- telemetry (pandera schema)
/** rows: array of objects (strings or numbers). Returns { tel, ignored }. */
export function validateTelemetry(rows, assetId = null) {
  const cols = rows.length ? Object.keys(rows[0]) : [];
  const missing = REQUIRED_COLUMNS.filter((c) => !cols.includes(c));
  if (missing.length) {
    const hints = Object.entries(KNOWN_FOREIGN_NAMES).filter(([k, v]) => cols.includes(k) && missing.includes(v))
      .map(([k, v]) => `'${k}' looks like '${v}'`);
    let msg = `telemetry is missing required column(s): ${missing.join(", ")}.`;
    if (hints.length) msg += ` Found ${hints.join("; ")}. Rename explicitly or use "Convert demo tables".`;
    throw new ContractError(msg);
  }
  const n = rows.length;
  const tel = { n, columns: cols.filter((c) => c !== "timestamp_utc"), t: new Float64Array(n), asset_id: new Array(n) };
  tel.columns.unshift("timestamp_utc");
  const errors = [];
  for (let i = 0; i < n; i++) {
    const t = parseIso(rows[i].timestamp_utc);
    if (Number.isNaN(t)) { errors.push(`timestamp_utc is not parseable as ISO-8601 UTC (row ${i}: ${JSON.stringify(rows[i].timestamp_utc)})`); break; }
    tel.t[i] = t;
    const a = scalar(rows[i].asset_id);
    if (a === null) { errors.push(`asset_id is null on row ${i}`); break; }
    tel.asset_id[i] = String(rows[i].asset_id).trim();
  }
  for (const c of FLOAT_COLUMNS) {
    if (!cols.includes(c)) continue;
    const arr = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      const v = scalar(rows[i][c]);
      if (v !== null && typeof v !== "number") { errors.push(`column ${c}: '${v}' is not a number (row ${i})`); break; }
      arr[i] = v === null ? NaN : v;
    }
    tel[c] = arr;
  }
  if (cols.includes("operating_state")) {
    tel.operating_state = rows.map((r) => { const v = scalar(r.operating_state); return v === null ? null : String(r.operating_state).trim(); });
  }
  if (errors.length) throw new ContractError(`telemetry schema errors: ${errors.join("; ")}`);
  if (assetId !== null) {
    const others = [...new Set(tel.asset_id)].filter((a) => a !== assetId).sort();
    if (others.length) throw new ContractError(`telemetry contains asset_id(s) ${JSON.stringify(others)} not matching metadata '${assetId}'`);
  }
  const known = new Set([...REQUIRED_COLUMNS, ...OPTIONAL_COLUMNS]);
  const ignored = cols.filter((c) => !known.has(c));
  return { tel, ignored };
}

export function loadBundle(metadataJson, telemetryRows) {
  let raw;
  try { raw = typeof metadataJson === "string" ? JSON.parse(metadataJson) : metadataJson; }
  catch (e) { throw new ContractError(`metadata.json invalid: ${e.message}`); }
  const meta = validateMetadata(raw);
  const { tel, ignored } = validateTelemetry(telemetryRows, meta.asset_id);
  return { meta, tel, ignored_columns: ignored };
}

/** bundle back to rows (for tables, CSV export and the database page) */
export function telemetryRows(tel) {
  const out = [];
  for (let i = 0; i < tel.n; i++) {
    const r = {};
    for (const c of tel.columns) {
      if (c === "timestamp_utc") r[c] = isoUTC(tel.t[i], true);
      else if (c === "asset_id" || c === "operating_state") r[c] = tel[c] ? tel[c][i] : null;
      else r[c] = tel[c] ? (Number.isNaN(tel[c][i]) ? null : tel[c][i]) : null;
    }
    out.push(r);
  }
  return out;
}

// ---------------------------------------------------------------- convert the REVIVE-TERY demo tables
export const TELEMETRY_MAP = {
  timestamp_utc: "timestamp_utc", asset_id: "asset_id", pack_voltage_V: "voltage_v", pack_current_A: "current_a",
  max_cell_temp_C: "temperature_c", soc_pct: "soc_pct", min_cell_temp_C: "min_temperature_c",
  ambient_temp_C: "ambient_temperature_c", power_kW: "power_kw", operating_state: "operating_state", soh_pct: "bms_soh_pct",
};
const CHEMISTRY_MAP = { "NMC (nickel manganese cobalt)": "NMC", NMC: "NMC", LFP: "LFP", "LFP (lithium iron phosphate)": "LFP", NCA: "NCA", "NCA (nickel cobalt aluminium)": "NCA" };
const PROVENANCE_MAP = { SYNTHETIC: "synthetic", SIMULATED: "simulated", MEASURED: "measured" };

function provenanceOf(values) {
  const classes = new Set(values.filter((v) => scalar(v) !== null).map((v) => String(v).trim().toUpperCase()));
  const unknown = [...classes].filter((c) => !(c in PROVENANCE_MAP)).sort();
  if (unknown.length) throw new ContractError(`unrecognised data_class value(s) ${JSON.stringify(unknown)}`);
  for (const c of ["SYNTHETIC", "SIMULATED", "MEASURED"]) if (classes.has(c)) return PROVENANCE_MAP[c];
  throw new ContractError("no data_class column values; provenance unknown");
}
const recProv = (v) => {
  const p = PROVENANCE_MAP[String(v).toUpperCase()];
  if (!p) throw new ContractError(`unrecognised data_class value '${v}'`);
  return p;
};

/** tables: { battery_asset, telemetry, health_history, safety_events } as arrays of row objects */
export function convertDemo(tables, assetId = null, { telemetry = "original" } = {}) {
  // fleet layout: battery_asset rows carry an asset_id column; pick one pack (the first when none is named)
  const keyed = tables.battery_asset.some((r) => r.asset_id !== undefined);
  const id = assetId ?? (keyed ? String(tables.battery_asset[0].asset_id) : null);
  const only = (rows) => (id === null ? rows : rows.filter((r) => String(r.asset_id) === id));
  // telemetry "dense": the SYNTHETIC densified series (engines/database/import_fleet.py) when this pack has one, as
  // ml_engine_bridge.bundle_from_database(..., telemetry_source="dense"); its `source` note is not a reading
  const dense = telemetry === "dense" && tables.telemetry_dense ? only(tables.telemetry_dense) : [];
  if (dense.length) tables = { ...tables, telemetry: dense.map(({ source, ...row }) => row) };
  const asset = Object.fromEntries((keyed ? only(tables.battery_asset) : tables.battery_asset).map((r) => [r.field, r.value]));
  if (keyed && !Object.keys(asset).length) throw new AdapterError(`${id}: no asset record in battery_asset`);
  const chemRaw = asset.chemistry;
  if (!(chemRaw in CHEMISTRY_MAP)) throw new ContractError(`chemistry '${chemRaw}' has no explicit mapping`);
  const m = /^(\d+)s(\d+)p$/.exec(String(asset.series_parallel_configuration ?? "").trim());
  if (!m) throw new ContractError("series_parallel_configuration is not of the form <n>s<m>p");
  const tel = only(tables.telemetry);
  const provenance = provenanceOf(tel.map((r) => r.data_class));
  const health = only(tables.health_history);
  const meta = {
    asset_id: asset.asset_id, chemistry: CHEMISTRY_MAP[chemRaw],
    rated_capacity_ah: toNumber(asset.nominal_capacity_Ah), nominal_voltage_v: toNumber(asset.nominal_voltage_V),
    min_voltage_v: toNumber(asset.min_voltage_V), max_voltage_v: toNumber(asset.max_voltage_V),
    series_cells: Number(m[1]), parallel_cells: Number(m[2]), data_provenance: provenance,
    current_sign_convention: "unknown", cell_model: asset.cell_format ?? null,
    cycle_count: Math.max(...health.map((r) => Math.trunc(toNumber(r.cycle_count)))),
    capacity_tests: health.map((r) => ({ date: r.assessment_date, cycle_count: Math.trunc(toNumber(r.cycle_count)),
      measured_capacity_ah: toNumber(r.measured_capacity_Ah), method: r.assessment_method, provenance: recProv(r.data_class) })),
    resistance_tests: health.map((r) => ({ date: r.assessment_date, cycle_count: Math.trunc(toNumber(r.cycle_count)),
      resistance_mohm: toNumber(r.internal_resistance_mOhm), level: "pack", method: r.assessment_method,
      provenance: recProv(r.data_class) })),
    safety_events: only(tables.safety_events).map((r) => ({ timestamp_utc: r.timestamp_utc, event_type: r.event_type,
      severity: r.severity, status: r.status, description: `observed ${r.observed_value}; threshold ${r.threshold_value}`,
      provenance: recProv(r.data_class) })),
    notes: String(asset.demo_status ?? ""),
    source: "REVIVE-TERY demo CSV bundle (ev_battery_demo_csv_bundle.zip), converted by revive_ml.convert",
  };
  const cols = tel.length ? Object.keys(tel[0]) : [];
  const unmapped = cols.filter((c) => !(c in TELEMETRY_MAP) && c !== "data_class");
  if (unmapped.length) throw new ContractError(`demo telemetry has unmapped column(s) ${JSON.stringify(unmapped)}`);
  const lacking = Object.keys(TELEMETRY_MAP).filter((c) => !cols.includes(c));
  if (lacking.length) throw new ContractError(`demo telemetry lacks column(s) ${JSON.stringify(lacking)}`);
  const rows = tel.map((r) => Object.fromEntries(Object.entries(TELEMETRY_MAP).map(([src, dst]) => [dst, r[src]])));
  return loadBundle(meta, rows);
}

// ---------------------------------------------------------------- contract bundle from files (zip upload)
export const CONTRACT_FILES = ["metadata.json", "telemetry.csv", "telemetry.parquet"];
export function isContractFileSet(names) {
  const base = new Set(names.map((n) => n.split("/").pop()));
  return base.has("metadata.json") && (base.has("telemetry.csv") || base.has("telemetry.parquet"));
}
export function bundleFromContractFiles(files) {
  if (!files["telemetry.csv"]) {
    if (files["telemetry.parquet"]) throw new AdapterError("telemetry.parquet cannot be read in the browser; zip telemetry.csv instead");
    throw new AdapterError("no telemetry.csv in the bundle");
  }
  try {
    return loadBundle(files["metadata.json"], parseCSV(files["telemetry.csv"], ",").rows);
  } catch (e) {
    if (e instanceof ContractError) throw new AdapterError(`bundle rejected by the data contract: ${e.message}`);
    throw e;
  }
}

// ---------------------------------------------------------------- upload adapter (ml_engine_bridge.bundle_from_rows)
export const CELL_NOMINAL_V = { LFP: 3.2, NMC: 3.65, NCA: 3.6 };
const MAX_CAPACITY_TESTS = 50;
const MIN_TIMESTAMP_COVERAGE = 0.95;

/** rows: standardised upload rows (lite store). spec: { chemistry, series_cells, parallel_cells, rated_capacity_ah, nominal_voltage_v } */
export function bundleFromRows(rowsIn, batteryId, spec, source, limitsCfg) {
  if (!rowsIn.length) throw new AdapterError(`${batteryId}: no uploaded rows`);
  let rows = rowsIn;
  const has = (c) => rows.length && c in rows[0];
  if (has("source_file") && has("row_in_file") && has("ingest_id")) {
    // the same file uploaded again is appended under a new ingest_id: keep only its latest copy
    const byIngest = rows.map((r, i) => [r, i]).sort((a, b) => (a[0].ingest_id < b[0].ingest_id ? -1 : a[0].ingest_id > b[0].ingest_id ? 1 : a[1] - b[1]));
    const last = new Map();
    for (const [r] of byIngest) last.set(`${r.source_file}\u0000${r.row_in_file}`, r);
    rows = [...last.values()].sort((a, b) => (a.source_file < b.source_file ? -1 : a.source_file > b.source_file ? 1 : a.row_in_file - b.row_in_file));
  }
  const problems = [];
  const ts = has("timestamp_utc") ? rows.map((r) => (typeof r.timestamp_utc === "number" ? r.timestamp_utc : parseTimeLenient(r.timestamp_utc))) : null;
  const frac = (arr) => arr.filter((v) => Number.isFinite(v)).length / arr.length;
  if (ts === null || frac(ts) < MIN_TIMESTAMP_COVERAGE) problems.push("no usable timestamp_utc column (the full engine integrates over real time steps)");
  for (const col of ["voltage_v", "current_a"]) {
    if (!has(col) || frac(rows.map((r) => toNumber(r[col]))) < 0.95) problems.push(`${col} is missing for more than 5 % of rows`);
  }
  const chem = spec.chemistry;
  let rated = spec.rated_capacity_ah ?? null;
  const cap = has("capacity_ah") && has("cycle_index")
    ? rows.map((r, i) => ({ r, i, c: toNumber(r.capacity_ah), k: toNumber(r.cycle_index) })).filter((x) => !Number.isNaN(x.c) && !Number.isNaN(x.k))
    : [];
  const perCycleMax = () => {
    const m = new Map();
    for (const x of cap) m.set(x.k, Math.max(m.has(x.k) ? m.get(x.k) : -Infinity, x.c));
    return [...m.entries()].sort((a, b) => a[0] - b[0]);
  };
  if (rated === null && cap.length) rated = Math.max(...perCycleMax().slice(0, 5).map((e) => e[1]));
  if (rated === null) problems.push("rated capacity unknown: enter it, or upload per-cycle capacity");
  if (problems.length) throw new AdapterError(problems.join("; "));

  const provs = rows.map((r) => r.data_provenance);
  const prov = provs.every((p) => p === "measured") ? "measured"
    : provs.some((p) => p === "simulated") && !provs.some((p) => p === "synthetic") ? "simulated" : "synthetic";
  const series = spec.series_cells;
  const lim = limitsCfg.chemistries[chem];
  const nominal = spec.nominal_voltage_v || CELL_NOMINAL_V[chem] * series;
  const hasSoc = has("soc_pct") && rows.some((r) => !Number.isNaN(toNumber(r.soc_pct)));
  const telRows = [];
  rows.forEach((r, i) => {
    if (!Number.isFinite(ts[i])) return;
    const o = { asset_id: batteryId, timestamp_utc: ts[i], voltage_v: toNumber(r.voltage_v), current_a: toNumber(r.current_a),
      temperature_c: has("temperature_c") ? toNumber(r.temperature_c) : NaN };
    if (hasSoc) o.soc_pct = toNumber(r.soc_pct);
    telRows.push(o);
  });
  let tests = [];
  if (cap.length) {
    const m = new Map();
    for (const x of cap) {
      const t = ts ? ts[x.i] : NaN;
      const e = m.get(x.k) || { capacity: -Infinity, ts: NaN };
      e.capacity = Math.max(e.capacity, x.c);
      if (Number.isFinite(t) && (Number.isNaN(e.ts) || t < e.ts)) e.ts = t;
      m.set(x.k, e);
    }
    let perCycle = [...m.entries()].sort((a, b) => a[0] - b[0]).filter(([, e]) => e.capacity > 0 && Number.isFinite(e.ts));
    if (perCycle.length > MAX_CAPACITY_TESTS) {
      const step = (perCycle.length - 1) / (MAX_CAPACITY_TESTS - 1); // numpy linspace: j * step, last point exact
      const idx = [...new Set(Array.from({ length: MAX_CAPACITY_TESTS }, (_, j) => (j === MAX_CAPACITY_TESTS - 1 ? perCycle.length - 1 : Math.trunc(j * step))))];
      perCycle = idx.map((j) => perCycle[j]);
    }
    tests = perCycle.map(([k, e]) => ({ date: dateOnly(e.ts), cycle_count: Math.trunc(k), measured_capacity_ah: e.capacity,
      method: "uploaded cycler log (max discharge capacity in the cycle)", provenance: prov }));
  }
  const cyc = has("cycle_index") ? rows.map((r) => toNumber(r.cycle_index)).filter((v) => !Number.isNaN(v)) : [];
  try {
    const meta = validateMetadata({
      asset_id: batteryId, chemistry: chem, rated_capacity_ah: rated, nominal_voltage_v: nominal,
      min_voltage_v: lim.cell_v_min.value * series, max_voltage_v: lim.cell_v_max.value * series,
      series_cells: series, parallel_cells: spec.parallel_cells, data_provenance: prov, current_sign_convention: "unknown",
      cycle_count: cyc.length ? Math.trunc(Math.max(...cyc)) : null, capacity_tests: tests,
      notes: `Built from an upload by ${source}; rated capacity ` + (spec.rated_capacity_ah ? "entered by the user" : "taken from the first cycles (assumed)"),
      source: `${source} upload adapter`,
    });
    const { tel, ignored } = validateTelemetry(telRows, batteryId);
    return { meta, tel, ignored_columns: ignored };
  } catch (e) {
    if (e instanceof ContractError) throw new AdapterError(`upload does not fit the data contract: ${e.message}`);
    throw e;
  }
}

// ---------------------------------------------------------------- summaries (both engines shown the same way)
export function capacityTestSoh(bundle) {
  if (!bundle || !bundle.meta.capacity_tests.length) return null;
  const latest = latestBy(bundle.meta.capacity_tests);
  return Number((100 * latest.measured_capacity_ah / bundle.meta.rated_capacity_ah).toFixed(2));
}
/** max by (date, cycle_count or 0), first wins on ties (Python max) */
export function latestBy(records) {
  let best = null;
  for (const r of records) {
    if (best === null || r.date > best.date || (r.date === best.date && (r.cycle_count || 0) > (best.cycle_count || 0))) best = r;
  }
  return best;
}
/** stable sort by (date, cycle_count or 0) */
export const sortByDate = (records) => [...records].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : (a.cycle_count || 0) - (b.cycle_count || 0)));

export function summarizeFull(report, bundle = null) {
  const state = report.state || {};
  const soh = (state.soh || {}).value ?? null;
  const testSoh = capacityTestSoh(bundle);
  const rec = report.recommendation || {};
  const checks = report.data_quality.checks;
  return {
    engine: "full", decision: report.decision, rationale: report.rationale || [], application: rec.label ?? null,
    readiness: report.data_quality.readiness.verdict, gate: (report.gate || {}).verdict ?? null, soh_pct: soh,
    capacity_test_soh_pct: testSoh, legacy_rule: ruleRoute(soh !== null ? soh : testSoh),
    data_provenance: report.data_provenance,
    failed_checks: checks.filter((c) => c.status === "fail").map((c) => ({ id: c.id, message: c.message })),
    inconclusive_checks: checks.filter((c) => c.status === "inconclusive").map((c) => ({ id: c.id, message: c.message })),
    warnings: report.warnings, placeholder_inputs: (report.economics || {}).placeholder_inputs || [],
  };
}
export function summarizeLite(report, notes = []) {
  const sug = report.suggestion || {};
  const soh = ((report.state || {}).soh || {}).value ?? null;
  return {
    engine: "lite", decision: sug.decision ?? null, rationale: [sug.reason || ""], application: sug.use_case ?? null,
    readiness: "NOT_ASSESSED (lite engine has no readiness rules)", gate: (report.safety_gate || {}).verdict ?? null,
    soh_pct: soh, legacy_rule: ruleRoute(soh), data_provenance: report.data_provenance ?? null, failed_checks: [],
    inconclusive_checks: [], warnings: [...notes, ...(report.warnings || [])], placeholder_inputs: sug.placeholder_inputs || [],
  };
}
