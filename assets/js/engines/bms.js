// REVIVE-TERY BMS engine (port of bulid X/src/bms_engine.py and test_bench.py): SOC/SOH maths,
// the ESP32 line protocol, serial statistics and the end-of-life decision rules.
// MONITOR-ONLY: nothing in this app ever sends data to the ESP32.

export const MIN_DELTA_SOC_PCT = 5.0;
export const DISAGREEMENT_POINTS = 10.0;
export const DS18B20_DISCONNECTED_C = -127.0;
export const FIRMWARE_READY_MESSAGE = "# INA219 ready";
export const FIRMWARE_OVER_VOLTAGE_PREFIX = "# OVER";
export const MAX_FIRMWARE_MESSAGE_LENGTH = 200;

const number = (v) => {
  if (v === null || v === undefined || typeof v === "boolean") return null;
  const x = typeof v === "number" ? v : typeof v === "string" && v.trim() !== "" ? Number(v) : NaN;
  return Number.isFinite(x) ? x : null;
};

/** Coulomb counting: SOC(t) = SOC(t-1) - I * dt / capacity, as a percentage kept within 0-100 (I > 0 discharging) */
export function calculateSoc(previousSocPct, currentA, deltaTimeS, totalCapacityAh) {
  if (totalCapacityAh <= 0) throw new Error("total_capacity_ah must be positive");
  if (deltaTimeS < 0) throw new Error("delta_time_s can't be negative");
  const change = (currentA * (deltaTimeS / 3600.0)) / totalCapacityAh * 100.0;
  return Math.max(0.0, Math.min(100.0, previousSocPct - change));
}
/** Capacity fade: SOH = measured usable capacity / original rated capacity * 100 */
export function calculateSoh(measuredAh, ratedAh) {
  if (ratedAh <= 0) throw new Error("original_rated_capacity_ah must be positive");
  if (measuredAh < 0) throw new Error("measured_usable_capacity_ah can't be negative");
  return (measuredAh / ratedAh) * 100.0;
}

export const BASIS_FULL_DISCHARGE = "Measured: full discharge down to the cutoff voltage";
export const BASIS_PARTIAL = "Estimate: Ah discharged divided by the recorded SOC change";
export const BASIS_LOWER_BOUND = "At least this much: Ah discharged so far, before reaching the cutoff";
export const BASIS_WAITING = "Waiting for enough discharge";

/** sample: { timestamp, voltage_v, current_a, temperature_c, reported_soc_pct, state } */
export function makeSample(o) {
  return { timestamp: o.timestamp, voltage_v: o.voltage_v, current_a: o.current_a, temperature_c: o.temperature_c ?? null,
    reported_soc_pct: o.reported_soc_pct ?? null, state: o.state ?? "" };
}

export class BMSEngine {
  constructor({ rated_capacity_ah = null, initial_soc_pct = null, baseline_measured_ah = null, baseline_date = null,
    cutoff_voltage_v = null, discharge_positive = true, baseline_source = "Capacity test recorded in the database" } = {}) {
    this.rated_capacity_ah = rated_capacity_ah;
    this.baseline_source = baseline_source;
    this.baseline_measured_ah = baseline_measured_ah;
    this.baseline_date = baseline_date;
    this.cutoff_voltage_v = cutoff_voltage_v;
    this.direction = discharge_positive ? 1.0 : -1.0; // the SOC formula needs positive current to mean discharge
    this.start_soc_pct = initial_soc_pct;
    this.soc_pct = initial_soc_pct;
    this.discharged_ah = 0.0;
    this.samples_seen = 0;
    this.soh_live_pct = null;
    this.soh_basis = BASIS_WAITING;
    this.fullDischargeSoh = null;
    this.firstReportedSoc = null;
    this.lastTime = null;
    this.skippedSteps = 0;
    this.regenRowsWithDischargeSign = 0;
    this.largestSocGap = 0.0;
  }

  process(sample) {
    this.samples_seen += 1;
    let dt = 0.0;
    if (this.lastTime !== null) {
      dt = sample.timestamp - this.lastTime;
      if (dt < 0) { this.skippedSteps += 1; dt = 0.0; } // out-of-order data can't be integrated
    }
    this.lastTime = sample.timestamp;
    if (this.firstReportedSoc === null) this.firstReportedSoc = sample.reported_soc_pct;
    if (this.soc_pct === null && sample.reported_soc_pct !== null) { // never assume a full battery
      this.soc_pct = sample.reported_soc_pct;
      this.start_soc_pct = sample.reported_soc_pct;
    }
    const i = sample.current_a * this.direction;
    if (String(sample.state || "").toUpperCase().startsWith("REGEN") && i > 0) this.regenRowsWithDischargeSign += 1;
    this.discharged_ah += i * dt / 3600.0;
    if (this.soc_pct !== null && this.rated_capacity_ah) this.soc_pct = calculateSoc(this.soc_pct, i, dt, this.rated_capacity_ah);
    if (this.soc_pct !== null && sample.reported_soc_pct !== null) {
      this.largestSocGap = Math.max(this.largestSocGap, Math.abs(this.soc_pct - sample.reported_soc_pct));
    }
    this.updateLiveSoh(sample);
    return { sample, soc_pct: this.soc_pct, soh_live_pct: this.soh_live_pct, soh_basis: this.soh_basis,
      discharged_ah: this.discharged_ah, delta_time_s: dt };
  }

  updateLiveSoh(sample) {
    if (!this.rated_capacity_ah || this.discharged_ah <= 0) return;
    const reachedCutoff = this.cutoff_voltage_v !== null && sample.voltage_v <= this.cutoff_voltage_v && Boolean(this.start_soc_pct);
    if (reachedCutoff && this.fullDischargeSoh === null) {
      this.fullDischargeSoh = calculateSoh(this.discharged_ah / (this.start_soc_pct / 100.0), this.rated_capacity_ah);
    }
    if (this.fullDischargeSoh !== null) { this.soh_live_pct = this.fullDischargeSoh; this.soh_basis = BASIS_FULL_DISCHARGE; return; }
    if (this.firstReportedSoc !== null && sample.reported_soc_pct !== null) {
      const dSoc = this.firstReportedSoc - sample.reported_soc_pct;
      if (dSoc >= MIN_DELTA_SOC_PCT) {
        this.soh_live_pct = calculateSoh(this.discharged_ah / (dSoc / 100.0), this.rated_capacity_ah);
        this.soh_basis = BASIS_PARTIAL;
      }
      return;
    }
    this.soh_live_pct = calculateSoh(this.discharged_ah, this.rated_capacity_ah); // a lower bound
    this.soh_basis = BASIS_LOWER_BOUND;
  }

  baselineSoh() {
    if (this.baseline_measured_ah === null || !this.rated_capacity_ah) return null;
    return calculateSoh(this.baseline_measured_ah, this.rated_capacity_ah);
  }

  /** the SOH to base a decision on, and where it came from; strongest evidence wins */
  finalSoh() {
    if (this.fullDischargeSoh !== null) return [this.fullDischargeSoh, "Full discharge measured in this test"];
    const b = this.baselineSoh();
    if (b !== null) return [b, `${this.baseline_source}${this.baseline_date ? ` on ${this.baseline_date}` : ""}`];
    if (this.soh_basis === BASIS_PARTIAL) return [this.soh_live_pct, "Estimate from this test's recorded SOC change"];
    return [null, "No capacity measurement: discharge to the cutoff voltage to measure one"];
  }

  dataFlags() {
    const flags = [];
    if (this.regenRowsWithDischargeSign) flags.push(`${this.regenRowsWithDischargeSign} regenerative braking row(s) have the same current sign as discharging.`);
    if (this.largestSocGap > DISAGREEMENT_POINTS) {
      flags.push(`Coulomb-counted SOC drifted up to ${this.largestSocGap.toFixed(0)} points from the recorded SOC, ` +
        "so the recorded current doesn't explain the recorded SOC.");
    }
    const b = this.baselineSoh();
    if (b !== null && this.soh_basis === BASIS_PARTIAL && this.soh_live_pct !== null && Math.abs(this.soh_live_pct - b) > DISAGREEMENT_POINTS) {
      flags.push(`The live SOH estimate (${this.soh_live_pct.toFixed(1)}%) disagrees with the recorded capacity test (${b.toFixed(1)}%). The decision uses the capacity test.`);
    }
    if (this.skippedSteps) flags.push(`${this.skippedSteps} out-of-order reading(s) were left out of the charge count.`);
    return flags;
  }
}

// ---------------------------------------------------------------- ESP32 line protocol (read-only)
/** one JSON line -> sample, or null when it isn't valid telemetry (boot text, half lines) */
export function parseTelemetryLine(text, now) {
  let data;
  try { data = JSON.parse(text); } catch { return null; }
  if (!data || typeof data !== "object" || Array.isArray(data) || !("voltage" in data) || !("current" in data)) return null;
  const voltage = number(data.voltage), current = number(data.current);
  if (voltage === null || current === null) return null;
  let temperature = number(data.temperature);
  if (temperature === DS18B20_DISCONNECTED_C) temperature = null;
  return makeSample({ timestamp: now, voltage_v: voltage, current_a: current, temperature_c: temperature });
}

/** info for the known all-clear, critical for over-voltage, warning for anything else */
export function firmwareMessageSeverity(text) {
  if (text === FIRMWARE_READY_MESSAGE) return "info";
  if (text.startsWith(FIRMWARE_OVER_VOLTAGE_PREFIX)) return "critical";
  return "warning";
}

export class SerialStats {
  constructor() {
    this.good_lines = 0; this.bad_lines = 0; this.message_lines = 0;
    this.last_reading_at = null; this.last_reading_wall = null;
    this.last_fault = ""; this.last_fault_severity = ""; this.last_fault_at = null;
    this.fault_counts = {};
  }
  recordMessage(text, now) {
    this.message_lines += 1;
    const t = text.trim().slice(0, MAX_FIRMWARE_MESSAGE_LENGTH);
    const severity = firmwareMessageSeverity(t);
    if (severity === "info") return;
    this.last_fault = t.replace(/^[# ]+/, "");
    this.last_fault_severity = severity;
    this.last_fault_at = now;
    this.fault_counts[this.last_fault] = (this.fault_counts[this.last_fault] || 0) + 1;
  }
  get faultIsActive() {
    if (this.last_fault_at === null) return false;
    return this.last_reading_at === null || this.last_fault_at >= this.last_reading_at;
  }
}

/** feed one raw serial line through the same path as read_esp32_telemetry; returns a sample or null */
export function handleSerialLine(raw, now, stats) {
  if (!raw || !raw.trim()) return null;
  if (raw.trimStart().startsWith("#")) { stats.recordMessage(raw, now); return null; }
  const s = parseTelemetryLine(raw, now);
  if (s === null) { stats.bad_lines += 1; return null; }
  stats.good_lines += 1;
  stats.last_reading_at = now;
  stats.last_reading_wall = Date.now() / 1000;
  return s;
}

// ---------------------------------------------------------------- decision rules (test_bench.py)
export const TIER_STATIONARY = "Stationary Storage";
export const TIER_LOW_SPEED_EV = "Low-speed EVs";
export const TIER_RECYCLING = "Recycling";
export const INSUFFICIENT_DATA = "Insufficient data";
export const SCREENING_NOTE = "This is a screening rule based on capacity alone. Real reuse needs safety, resistance and cell-level testing by a qualified engineer.";

export function getSecondaryUseCase(soh) {
  if (soh === null || soh === undefined || typeof soh === "boolean") return INSUFFICIENT_DATA;
  const x = Number(soh);
  if (!Number.isFinite(x) || x < 0) return INSUFFICIENT_DATA;
  if (x > 80.0) return TIER_STATIONARY;
  if (x >= 60.0) return TIER_LOW_SPEED_EV;
  return TIER_RECYCLING;
}

export function getDecisionForUi(engine) {
  const [soh, basis] = engine.finalSoh();
  return { use_case: getSecondaryUseCase(soh), soh_pct: soh, basis, live_soh_pct: engine.soh_live_pct,
    live_basis: engine.soh_basis, flags: engine.dataFlags(), note: SCREENING_NOTE };
}

export function faultFlags(stats) {
  const entries = Object.entries(stats.fault_counts);
  if (!entries.length) return [];
  const listed = entries.map(([m, c]) => `${m} (${c} time${c !== 1 ? "s" : ""})`).join("; ");
  return [`The firmware reported faults during this test: ${listed}. No readings were sent while these were active, so SOC and SOH across those periods are approximate.`];
}

// ---------------------------------------------------------------- the demo "database" (DuckDB tables as JS rows)
/** what the database states about one battery (load_battery_profile); tables = parsed demo CSVs */
export function loadBatteryProfile(tables, assetId) {
  const pairs = Object.fromEntries((tables.battery_asset || []).map((r) => [String(r.field), String(r.value)]));
  const details = pairs.asset_id === assetId ? pairs : {};
  let rated = number(details.nominal_capacity_Ah);
  let measured = null, testDate = null;
  let synthetic = String(details.demo_status || "").toUpperCase().includes("SYNTHETIC");
  const hist = (tables.health_history || []).filter((r) => r.asset_id === assetId)
    .sort((a, b) => (a.assessment_date < b.assessment_date ? 1 : a.assessment_date > b.assessment_date ? -1 : 0));
  if (hist.length) {
    measured = number(hist[0].measured_capacity_Ah); testDate = String(hist[0].assessment_date);
    if (rated === null) rated = number(hist[0].rated_capacity_Ah);
  }
  const tel = (tables.telemetry || []).filter((r) => r.asset_id === assetId);
  if (!synthetic) synthetic = tel.some((r) => String(r.data_class || "").toUpperCase().includes("SYNTHETIC"));
  return { asset_id: assetId, chemistry: details.chemistry ?? null, nominal_voltage_v: number(details.nominal_voltage_V),
    min_voltage_v: number(details.min_voltage_V), max_voltage_v: number(details.max_voltage_V), rated_capacity_ah: rated,
    measured_capacity_ah: measured, capacity_test_date: testDate, telemetry_rows: tel.length, is_synthetic: synthetic };
}
export function listBatteryIds(tables) {
  const ids = new Set();
  for (const r of tables.battery_asset || []) if (r.field === "asset_id") ids.add(String(r.value));
  for (const r of tables.telemetry || []) if (r.asset_id) ids.add(String(r.asset_id));
  return [...ids].sort();
}
/** VirtualBattery: the recorded rows of one battery as samples, in time order (never invented) */
export function replaySamples(tables, assetId, parseTime) {
  return (tables.telemetry || []).filter((r) => r.asset_id === assetId)
    .map((r) => ({ r, t: parseTime(r.timestamp_utc) }))
    .filter(({ r, t }) => Number.isFinite(t) && number(r.pack_voltage_V) !== null && number(r.pack_current_A) !== null)
    .sort((a, b) => a.t - b.t)
    .map(({ r, t }) => makeSample({ timestamp: t, voltage_v: number(r.pack_voltage_V), current_a: number(r.pack_current_A),
      temperature_c: number(r.max_cell_temp_C), reported_soc_pct: number(r.soc_pct), state: String(r.operating_state || "") }));
}
export const BUNDLE_DISCHARGE_POSITIVE = false; // the demo bundle records discharge as negative current
