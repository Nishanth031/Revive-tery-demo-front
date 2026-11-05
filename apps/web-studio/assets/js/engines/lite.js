// Lite analyzer and second-life suggester (port of bulid X/src/ml_analyzer_suggester.py).
// uploaded .zip / .csv / .xlsx -> extractor (explicit header aliases) -> in-browser store (stands in for the
// DuckDB tables ml_telemetry / ml_ingest_log) -> safety gate -> state -> economic suggestion.
// Unknown columns are reported, never guessed. Current is never flipped. SoH only from capacity data.

import { parseCSV, scalar, toNumber } from "../lib/csv.js";
import { parseTimeLenient } from "./contract.js";
import { median, polyfit1, pyRound } from "../lib/np.js";
import { comma0, f } from "../lib/provenance.js";

export const SUPPORTED_SUFFIXES = [".csv", ".xlsx", ".xls"];
export const MAX_ZIP_MEMBERS = 500;
export const MAX_UNCOMPRESSED_BYTES = 2 * 1024 ** 3;

export const COLUMN_ALIASES = {
  battery_id: ["battery_id", "asset_id", "cell_id", "cell", "battery", "barcode", "pack_id"],
  timestamp_utc: ["timestamp_utc", "timestamp", "datetime", "date_time", "time_utc"],
  test_time_s: ["test_time_s", "test_time", "time_s", "time", "elapsed_time_s", "time_sec"],
  cycle_index: ["cycle_index", "cycle", "cycle_number", "cycle_no", "cycle_count", "cycle_id"],
  voltage_v: ["voltage_v", "voltage", "pack_voltage_v", "cell_voltage_v", "voltage_measured", "v", "terminal_voltage", "batt_voltage"],
  current_a: ["current_a", "current", "pack_current_a", "current_measured", "i", "batt_current"],
  temperature_c: ["temperature_c", "temperature", "temp_c", "temp", "max_cell_temp_c", "temperature_measured", "cell_temperature_c"],
  capacity_ah: ["capacity_ah", "capacity", "discharge_capacity_ah", "discharge_capacity", "measured_capacity_ah", "qd", "qdischarge"],
  soc_pct: ["soc_pct", "soc", "state_of_charge"],
};
const REQUIRED_FOR_ANALYSIS = ["voltage_v"];
export const SAFETY_LIMITS = {
  LFP: { cell_v_min: 2.0, cell_v_max: 3.65, temp_max_c: 60.0, temp_spike_c: 5.0 },
  NMC: { cell_v_min: 2.75, cell_v_max: 4.25, temp_max_c: 60.0, temp_spike_c: 5.0 },
  NCA: { cell_v_min: 2.5, cell_v_max: 4.25, temp_max_c: 60.0, temp_spike_c: 5.0 },
};
export const USE_CASES = [
  { name: "Residential solar storage", category: "Second-Life Reuse", min_soh: 80.0, cycles_per_year: 300, dod: 0.8 },
  { name: "Commercial peak shaving", category: "Second-Life Reuse", min_soh: 75.0, cycles_per_year: 450, dod: 0.9 },
  { name: "Telecom / UPS backup", category: "Second-Life Reuse", min_soh: 70.0, cycles_per_year: 50, dod: 0.5 },
  { name: "Low-speed EV / e-rickshaw", category: "Second-Life Reuse", min_soh: 70.0, cycles_per_year: 300, dod: 0.8 },
  { name: "Module-level repurpose (street lights, small backup)", category: "Repurpose", min_soh: 60.0, cycles_per_year: 365, dod: 0.6 },
];
export const END_OF_USE_SOH = 60.0;
export const ECONOMICS = {
  value_per_kwh_delivered_usd: { value: 0.08, status: "PLACEHOLDER" },
  refurbishment_usd_per_kwh: { value: 40.0, status: "PLACEHOLDER" },
  repurpose_extra_usd_per_kwh: { value: 20.0, status: "PLACEHOLDER" },
  new_storage_installed_usd_per_kwh: { value: 236.0, status: "indicative (BNEF US system survey)" },
  new_storage_life_years: { value: 15.0, status: "assumed" },
  recycle_net_usd_per_kwh: { value: 5.0, status: "PLACEHOLDER" },
  discount_rate: { value: 0.08, status: "assumed" },
  max_second_life_years: { value: 10.0, status: "assumed" },
};
export const STANDARD_COLUMNS = ["battery_id", "timestamp_utc", "test_time_s", "cycle_index", "voltage_v", "current_a", "temperature_c", "capacity_ah", "soc_pct"];

export class IngestionError extends Error { constructor(m) { super(m); this.name = "IngestionError"; } }

/** 'Pack Voltage (V)' -> 'pack_voltage_v'; 'Temp [°C]' -> 'temp_c' */
export function normaliseHeader(name) {
  let s = String(name).trim().toLowerCase().replace(/°/g, "");
  s = s.replace(/[([]\s*([a-z%]+)\s*[)\]]/g, "_$1");
  return s.replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}
const ALIAS = Object.fromEntries(Object.entries(COLUMN_ALIASES).flatMap(([std, as]) => as.map((a) => [a, std])));
const stem = (p) => { const b = p.split("/").pop(); const k = b.lastIndexOf("."); return k > 0 ? b.slice(0, k) : b; };
const suffix = (p) => { const b = p.split("/").pop(); const k = b.lastIndexOf("."); return k > 0 ? b.slice(k).toLowerCase() : ""; };
const pyStr = (v) => (v === null || v === undefined ? "nan" : typeof v === "number" ? (Number.isNaN(v) ? "nan" : String(v)) : String(v));

/** one parsed table -> standardised rows plus how its columns were mapped (null when it has no voltage column) */
export function standardise(header, rows, source) {
  const mapping = {}, unmapped = [];
  const used = new Set();
  for (const col of header) {
    const std = ALIAS[normaliseHeader(col)];
    if (std && !used.has(std)) { mapping[col] = std; used.add(std); } else unmapped.push(String(col));
  }
  if (!REQUIRED_FOR_ANALYSIS.some((s) => used.has(s))) return null;
  const warnings = [];
  const inv = Object.fromEntries(Object.entries(mapping).map(([k, v]) => [v, k]));
  const out = rows.map((r) => Object.fromEntries(Object.entries(mapping).map(([src, std]) => [std, r[src]])));
  for (const c of ["voltage_v", "current_a", "temperature_c", "capacity_ah", "soc_pct", "test_time_s"]) {
    if (!(c in inv)) continue;
    let bad = 0;
    for (const o of out) {
      const before = scalar(o[c]);
      const x = toNumber(o[c]);
      if (before !== null && Number.isNaN(x)) bad++;
      o[c] = x;
    }
    if (bad) warnings.push(`${c}: ${bad} non-numeric values set to null`);
  }
  if ("cycle_index" in inv) for (const o of out) { const x = toNumber(o.cycle_index); o.cycle_index = Number.isInteger(x) ? x : (Number.isFinite(x) ? Math.trunc(x) : NaN); }
  if ("timestamp_utc" in inv) for (const o of out) o.timestamp_utc = o.timestamp_utc instanceof Date ? o.timestamp_utc.getTime() / 1000 : parseTimeLenient(o.timestamp_utc);
  if (!("battery_id" in inv)) {
    const id = stem(source.split("#")[0]);
    for (const o of out) o.battery_id = id;
    warnings.push("no battery id column; file name used as battery_id");
  }
  out.forEach((o, k) => { o.battery_id = pyStr(scalar(o.battery_id)); o.source_file = source; o.row_in_file = k; });
  return { source, data: out, mapping, unmapped, warnings };
}

/** a CSV or Excel table -> extracted tables (Excel: one per sheet). libs: { XLSX } */
export function parseTable(name, bytes, label, libs = {}) {
  try {
    if (suffix(name) === ".csv") {
      const text = typeof bytes === "string" ? bytes : new TextDecoder("utf-8").decode(bytes);
      const { header, rows } = parseCSV(text);
      return [standardise(header, rows, label)];
    }
    if (!libs.XLSX) throw new IngestionError("reading Excel files needs the SheetJS library, which did not load");
    const wb = libs.XLSX.read(bytes, { type: "array", cellDates: true });
    return wb.SheetNames.map((sheet) => {
      const aoa = libs.XLSX.utils.sheet_to_json(wb.Sheets[sheet], { header: 1, defval: null, raw: true });
      if (!aoa.length) return null;
      const header = aoa[0].map((h, k) => (h === null ? `Unnamed: ${k}` : String(h)));
      const rows = aoa.slice(1).filter((r) => r.some((v) => v !== null && v !== "")).map((r) => Object.fromEntries(header.map((h, k) => {
        const v = r[k] === undefined ? null : r[k];
        return [h, v instanceof Date ? v.toISOString() : v];
      })));
      return standardise(header, rows, `${label}#${sheet}`);
    });
  } catch (e) {
    if (e instanceof IngestionError) throw e;
    throw new IngestionError(`could not parse ${label}: ${e.message}`);
  }
}

/** a zip, csv or xlsx upload -> extracted tables. libs: { JSZip, XLSX } */
export async function extract(name, bytes, libs = {}) {
  const sfx = suffix(name);
  if (sfx === ".zip") {
    if (!libs.JSZip) throw new IngestionError("reading zip files needs the JSZip library, which did not load");
    let zip;
    try { zip = await libs.JSZip.loadAsync(bytes); } catch (e) { throw new IngestionError(`${name} is not a valid zip archive: ${e.message}`); }
    const members = Object.values(zip.files).filter((m) => !m.dir);
    if (members.length > MAX_ZIP_MEMBERS) throw new IngestionError(`zip has ${members.length} files (limit ${MAX_ZIP_MEMBERS})`);
    const total = members.reduce((s, m) => s + ((m._data && m._data.uncompressedSize) || 0), 0);
    if (total > MAX_UNCOMPRESSED_BYTES) throw new IngestionError("zip expands beyond the 2 GB limit");
    const results = [];
    for (const m of members) {
      const base = m.name.split("/").pop();
      if (!SUPPORTED_SUFFIXES.includes(suffix(base)) || base.startsWith("~$")) continue; // READMEs, images, lock files
      const data = await m.async("uint8array");
      results.push(...parseTable(base, data, `${name}/${m.name}`, libs).filter(Boolean));
    }
    if (!results.length) throw new IngestionError(`${name} contains no CSV/Excel table with battery telemetry`);
    return results;
  }
  if (SUPPORTED_SUFFIXES.includes(sfx)) return parseTable(name, bytes, name, libs).filter(Boolean);
  throw new IngestionError(`unsupported file type '${sfx}'; expected .zip, .csv or .xlsx`);
}

// ---------------------------------------------------------------- the store (DuckDBSeeder equivalent)
export class LiteStore {
  constructor(initial = null) { this.telemetry = initial ? initial.telemetry : []; this.log = initial ? initial.log : []; }
  seed(files, dataProvenance = "synthetic") {
    if (!["measured", "simulated", "synthetic"].includes(dataProvenance)) throw new Error("data_provenance must be measured, simulated or synthetic");
    const now = new Date();
    const ingestId = `ING-${now.toISOString().replace(/[-:]/g, "").replace(/\.(\d{3})Z$/, "$1000")}`;
    let total = 0;
    const add = [], logAdd = [];
    for (const f of files) {
      for (const r of f.data) {
        const o = {};
        for (const c of STANDARD_COLUMNS) o[c] = c in r ? r[c] : (c === "battery_id" ? null : NaN);
        if (Number.isFinite(o.timestamp_utc)) o.timestamp_utc = Math.round(o.timestamp_utc * 1000) / 1000; // stored at ms resolution
        o.source_file = r.source_file; o.row_in_file = r.row_in_file; o.ingest_id = ingestId; o.data_provenance = dataProvenance;
        add.push(o);
      }
      logAdd.push({ ingest_id: ingestId, ingested_utc: now.toISOString(), source_file: f.source, rows: f.data.length,
        column_mapping: JSON.stringify(f.mapping), unmapped_columns: JSON.stringify(f.unmapped), warnings: JSON.stringify(f.warnings) });
      total += f.data.length;
    }
    this.telemetry.push(...add); // all-or-nothing: nothing is added until every file is ready
    this.log.push(...logAdd);
    return { ingest_id: ingestId, rows_inserted: total, files: files.map((f) => f.source),
      battery_ids: [...new Set(files.flatMap((f) => f.data.map((r) => r.battery_id)))].sort() };
  }
  loadBattery(id) {
    return this.telemetry.filter((r) => r.battery_id === id)
      .sort((a, b) => (a.source_file < b.source_file ? -1 : a.source_file > b.source_file ? 1 : a.row_in_file - b.row_in_file));
  }
  batteryIds() { return [...new Set(this.telemetry.map((r) => r.battery_id))].sort(); }
  clear() { this.telemetry = []; this.log = []; }
}

// ---------------------------------------------------------------- analyzer and suggester
function ltag(value, provenance, unit = null, note = null) {
  const v = value === null || value === undefined || (typeof value === "number" && !Number.isFinite(value)) ? null : value;
  const out = { value: typeof v === "number" ? pyRound(v, 4) : v, provenance };
  if (unit) out.unit = unit;
  if (note) out.note = note;
  return out;
}
const pyFloat = (x) => (Number.isInteger(x) ? x.toFixed(1) : String(x));
const isna = (v) => v === null || v === undefined || (typeof v === "number" && Number.isNaN(v));
/** groupby(source_file)[col].diff() */
function groupDiff(df, col) {
  const out = new Array(df.length).fill(NaN);
  for (let k = 1; k < df.length; k++) if (df[k].source_file === df[k - 1].source_file) out[k] = df[k][col] - df[k - 1][col];
  // rows of one file are contiguous (the store orders by source_file, row_in_file)
  return out;
}
function sampleVar(a) {
  const x = a.filter((v) => !isna(v));
  if (x.length < 2) return NaN;
  const m = x.reduce((s, v) => s + v, 0) / x.length;
  return x.reduce((s, v) => s + (v - m) * (v - m), 0) / (x.length - 1);
}

export function defaultSpec() { return { chemistry: "LFP", series_cells: 1, rated_capacity_ah: null, nominal_voltage_v: null }; }

export function dataQuality(df, prov) {
  const out = { rows: df.length };
  for (const c of ["voltage_v", "current_a", "temperature_c", "capacity_ah"]) out[`${c}_null_fraction`] = ltag(df.filter((r) => isna(r[c])).length / df.length, prov);
  out.has_capacity_data = df.some((r) => !isna(r.capacity_ah));
  out.has_temperature = df.some((r) => !isna(r.temperature_c));
  return out;
}

export function safetyGate(df, spec, prov) {
  const lim = SAFETY_LIMITS[spec.chemistry];
  const cellV = df.map((r) => r.voltage_v / Math.max(spec.series_cells, 1));
  const reasons = [], quarantine = [];
  const live = cellV.filter((v) => v > 0.1); // exact zeros are sensor dropouts, flagged below
  if (live.some((v) => v < lim.cell_v_min)) reasons.push(`cell voltage ${Math.min(...live).toFixed(3)} V below ${pyFloat(lim.cell_v_min)} V`);
  if (live.some((v) => v > lim.cell_v_max)) reasons.push(`cell voltage ${Math.max(...live).toFixed(3)} V above ${pyFloat(lim.cell_v_max)} V`);
  const t = df.map((r) => r.temperature_c).filter((v) => !isna(v));
  if (t.some((v) => v > lim.temp_max_c)) reasons.push(`temperature ${Math.max(...t).toFixed(1)} degC above ${pyFloat(lim.temp_max_c)} degC`);
  const jumps = groupDiff(df, "temperature_c").map(Math.abs);
  const nSpikes = jumps.filter((j) => j > lim.temp_spike_c).length;
  if (nSpikes) quarantine.push(`${nSpikes} temperature jump(s) > ${pyFloat(lim.temp_spike_c)} degC between rows`);
  const nDrop = cellV.filter((v) => v <= 0.1).length;
  if (nDrop) quarantine.push(`${nDrop} voltage dropout row(s) (~0 V)`);
  if (!t.length) quarantine.push("no temperature data: thermal behaviour cannot be screened");
  const verdict = reasons.length ? "Reject" : quarantine.length ? "Quarantine" : "Pass";
  return { verdict, reasons: [...reasons, ...quarantine],
    wording: "UL 1974-style triage. Screening only, not certification or a safety approval.",
    min_cell_voltage: ltag(live.length ? Math.min(...live) : null, prov, "V"),
    max_temperature: ltag(t.length ? Math.max(...t) : null, prov, "degC"),
    limits: Object.fromEntries(Object.entries(lim).map(([k, v]) => [k, ltag(v, "assumed")])),
    note: "pack voltage / series_cells is the AVERAGE cell; a weak cell can be hidden" };
}

export function estimateState(df, spec, prov) {
  const out = { status: "ok" };
  const dv = groupDiff(df, "voltage_v"), di = groupDiff(df, "current_a");
  const xs = [], ys = [];
  for (let k = 0; k < df.length; k++) if (!isna(dv[k]) && !isna(di[k]) && Math.abs(di[k]) > 1e-3) { xs.push(di[k]); ys.push(dv[k]); }
  if (xs.length >= 5) {
    const slope = polyfit1(xs, ys)[0];
    out.resistance_proxy = ltag(Math.abs(slope) * 1000 / Math.max(spec.series_cells, 1), "modelled", "mOhm per cell", "|dV/dI| between rows; rough proxy");
  }
  out.voltage_variance = ltag(sampleVar(df.map((r) => r.voltage_v)), prov, "V^2");
  const temps = df.map((r) => r.temperature_c).filter((v) => !isna(v));
  if (temps.length) out.temperature_mean = ltag(temps.reduce((s, v) => s + v, 0) / temps.length, prov, "degC");
  const cap = df.filter((r) => !isna(r.capacity_ah));
  if (!cap.length) return { ...out, status: "insufficient", reason: "no capacity data: SoH cannot be measured (voltage alone is not enough)" };
  let perCycle; // [label, capacity] pairs, like a pandas Series index
  if (cap.some((r) => !isna(r.cycle_index))) {
    const m = new Map();
    for (const r of cap) if (!isna(r.cycle_index)) m.set(r.cycle_index, Math.max(m.has(r.cycle_index) ? m.get(r.cycle_index) : -Infinity, r.capacity_ah));
    perCycle = [...m.entries()].sort((a, b) => a[0] - b[0]);
  } else perCycle = cap.map((r, k) => [k, r.capacity_ah]);
  perCycle = perCycle.filter(([, c]) => c > 0);
  if (!perCycle.length) return { ...out, status: "insufficient", reason: "capacity values are all zero" };
  const rated = spec.rated_capacity_ah || Math.max(...perCycle.slice(0, 5).map((e) => e[1]));
  const ratedSrc = spec.rated_capacity_ah ? "user-supplied rated capacity" : "max of the first 5 cycles (no rated capacity given)";
  const latest = median(perCycle.slice(-5).map((e) => e[1]));
  const soh = 100.0 * latest / rated;
  out.rated_capacity = ltag(rated, !spec.rated_capacity_ah ? "assumed" : "measured", "Ah", ratedSrc);
  out.current_capacity = ltag(latest, prov, "Ah", "median of the last 5 cycles");
  out.soh = ltag(soh, "modelled", "%", "current capacity / rated capacity");
  out.cycles_observed = perCycle.length;
  const recent = perCycle.slice(-50);
  if (recent.length >= 5) {
    const fade = -polyfit1(recent.map((e) => e[0]), recent.map((e) => 100.0 * e[1] / rated))[0];
    out.fade_rate = ltag(fade, "modelled", "SoH points per cycle", "linear fit over up to the last 50 cycles");
    if (fade > 1e-6) {
      out.cycles_to_end_of_use = ltag(Math.max(0.0, (soh - END_OF_USE_SOH) / fade), "modelled", "cycles",
        `linear, to ${END_OF_USE_SOH.toFixed(0)} % SoH; real fade often accelerates (knee), so treat as optimistic`);
    }
  } else out.fade_rate = ltag(null, "modelled", null, "fewer than 5 cycles: fade not estimated");
  out.capacity_by_cycle = perCycle.map(([k, c]) => [k, c]);
  return out;
}

export function economics(state, spec) {
  const e = Object.fromEntries(Object.entries(ECONOMICS).map(([k, v]) => [k, v.value]));
  const cellV = { LFP: 3.2, NMC: 3.7, NCA: 3.6 }[spec.chemistry];
  const packV = spec.nominal_voltage_v || cellV * Math.max(spec.series_cells, 1);
  const soh = state.soh.value;
  const kwhNow = packV * state.current_capacity.value / 1000.0;
  const fade = (state.fade_rate || {}).value || 0.0;
  const r = e.discount_rate;
  const recycle = e.recycle_net_usd_per_kwh * kwhNow;
  const options = [];
  for (const uc of USE_CASES) {
    if (soh < uc.min_soh) continue;
    let years = fade > 0 ? (soh - uc.min_soh) / (fade * uc.cycles_per_year) : e.max_second_life_years;
    years = Math.min(years, e.max_second_life_years);
    let pv = 0.0;
    for (let y = 0; y < Math.ceil(years); y++) {
      const share = Math.min(1.0, years - y);
      const sohY = Math.max(uc.min_soh, soh - fade * uc.cycles_per_year * y);
      pv += kwhNow * sohY / soh * uc.dod * uc.cycles_per_year * share / (1 + r) ** (y + 0.5);
    }
    const value = pv * e.value_per_kwh_delivered_usd;
    const cap = e.new_storage_installed_usd_per_kwh * kwhNow * Math.min(1.0, years / e.new_storage_life_years);
    const cost = kwhNow * (e.refurbishment_usd_per_kwh + (uc.category === "Repurpose" ? e.repurpose_extra_usd_per_kwh : 0));
    const net = Math.min(value, cap) - cost + recycle / (1 + r) ** years;
    options.push({ use_case: uc.name, category: uc.category, service_years: ltag(years, "modelled", "years"),
      energy_value: ltag(value, "modelled", "USD"), buy_new_cap: ltag(cap, "modelled", "USD"), refurbishment_cost: ltag(cost, "assumed", "USD"),
      net_value: ltag(net, "modelled", "USD"), cost_per_kwh_delivered: ltag(pv ? cost / pv : null, "modelled", "USD/kWh") });
  }
  const newCost = e.new_storage_installed_usd_per_kwh / (e.new_storage_life_years * 300 * 0.8);
  let best = null;
  for (const o of options) if (best === null || o.net_value.value > best.net_value.value) best = o;
  let decision;
  if (best && best.net_value.value > recycle && best.service_years.value >= 1) {
    const cpk = best.cost_per_kwh_delivered.value;
    if (cpk !== null && cpk > newCost) {
      decision = { decision: "Buy New", category: "Buy New", reason: `reuse costs ${cpk.toFixed(3)} USD/kWh delivered vs about ${newCost.toFixed(3)} for new storage; recycle this pack` };
    } else {
      decision = { decision: `${best.category}: ${best.use_case}`, category: best.category, use_case: best.use_case,
        reason: `net ${comma0(best.net_value.value)} USD over ${f(best.service_years.value, 1)} years vs recycling now ${comma0(recycle)} USD` };
    }
  } else decision = { decision: "Recycle", category: "Recycle", reason: !options.length ? "SoH below every use-case threshold" : "no reuse option beats recycling now" };
  decision.placeholder_inputs = Object.entries(ECONOMICS).filter(([, v]) => v.status === "PLACEHOLDER").map(([k]) => k);
  return { pack_energy_now: ltag(kwhNow, "modelled", "kWh"), recycle_now: ltag(recycle, "assumed", "USD"),
    new_storage_cost_per_kwh_delivered: ltag(newCost, "assumed", "USD/kWh"), options, inputs: ECONOMICS, suggestion: decision };
}

export function suggest(store, batteryId, spec = defaultSpec()) {
  const df = store.loadBattery(batteryId);
  const report = { battery_id: batteryId, generated_utc: new Date().toISOString().replace(/\.\d{3}Z$/, "+00:00"),
    spec: { chemistry: spec.chemistry, series_cells: spec.series_cells, rated_capacity_ah: spec.rated_capacity_ah ?? null, nominal_voltage_v: spec.nominal_voltage_v ?? null },
    data_quality: {}, safety_gate: null, state: null, economics: null, suggestion: null, warnings: [] };
  if (!df.length) { report.suggestion = { decision: "Insufficient data", reason: "no rows for this battery" }; return report; }
  const prov = df.every((r) => r.data_provenance === "measured") ? "measured" : "synthetic";
  report.data_provenance = prov;
  if (prov !== "measured") report.warnings.push("Data is synthetic/simulated: the suggestion demonstrates the pipeline, not the condition of a real battery.");
  if (!(spec.chemistry in SAFETY_LIMITS)) throw new Error(`chemistry must be one of ${Object.keys(SAFETY_LIMITS).sort().join(", ")}`);
  report.data_quality = dataQuality(df, prov);
  const gate = safetyGate(df, spec, prov);
  report.safety_gate = gate;
  if (gate.verdict === "Reject") { report.suggestion = { decision: "Recycle", category: "Recycle", reason: "hard safety limit breached: " + gate.reasons.join("; ") }; return report; }
  const state = estimateState(df, spec, prov);
  report.state = state;
  if (state.status !== "ok") { report.suggestion = { decision: "Insufficient data", reason: state.reason }; return report; }
  if (gate.verdict === "Quarantine") { report.suggestion = { decision: "Inspection required", category: null, reason: gate.reasons.join("; ") }; return report; }
  const econ = economics(state, spec);
  report.economics = econ;
  report.suggestion = econ.suggestion;
  return report;
}
