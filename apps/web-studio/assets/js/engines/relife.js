// ReLife BMS Studio engine (port of "Hackathon project ev/bms_engine.py" and models.py).
// A rule-based BMS simulator: adapter compatibility, scenario evaluation and a 30 s synthetic virtual pulse
// test. SYNTHETIC VIRTUAL PULSE: not a real measurement or explosion prediction. No physical device I/O.

import { pyRound } from "../lib/np.js";

export const SCENARIOS = ["Normal", "Pulse load", "High load", "Overcurrent", "Cell imbalance", "Cell failure", "Thermal risk"];
export const EVALUATE_SCENARIOS = ["Normal", "Undervoltage", "Overvoltage", "Overcurrent", "High temperature", "Stale sensor"];
export const SOURCE_LABEL = "SYNTHETIC VIRTUAL PULSE — not a real measurement or explosion prediction";
export const PULSE_DURATION_S = 30.0;
export const PULSE_SAMPLE_S = 0.25;

const adapter = (id, name, chemistry_families, min_series, max_series, max_stack_voltage_v, max_temperature_channels = 9, balancing_supported = true) =>
  ({ id, name, chemistry_families, min_series, max_series, max_stack_voltage_v, max_temperature_channels, balancing_supported, simulated_only: true });
export const ADAPTERS = [
  adapter("V-LI-3-16", "Virtual lithium monitor • 3–16S", ["LFP", "Li-ion", "Lithium-ion (cell-specific details in source files)"], 3, 16, 80),
  adapter("V-LI-SINGLE", "Virtual single-cell monitor • 1S", ["Li-ion", "LFP"], 1, 1, 5),
  adapter("V-STACK-12", "Virtual stack monitor • up to 12S", ["LFP", "Li-ion"], 1, 12, 60),
  adapter("V-BLOCK", "Virtual block-voltage monitor", ["Lead-acid", "NiMH", "NiCd"], 1, 24, 120, 0, false),
  adapter("V-HV-PACK", "Virtual HV pack monitor • up to 120S", ["NMC", "NCA", "LFP", "Li-ion"], 3, 120, 500),
];

// ---------------------------------------------------------------- profiles (models.BatteryProfile)
const UNKNOWN_TEXT = ["", "Unknown", "unknown"];
const INT_FIELDS = ["series_cells", "parallel_cells", "cycle_count"];
const FLOAT_FIELDS = ["nominal_voltage_v", "capacity_value", "rated_energy_wh", "charge_limit_a", "discharge_limit_a", "mass_kg",
  "measured_capacity_ah", "measured_voltage_v", "measured_current_a", "measured_temperature_c", "soh_pct", "initial_soc_pct", "internal_resistance_mohm"];
export const PROFILE_DEFAULTS = { id: "", name: "", chemistry: "Unknown", manufacturer: "Unknown", model: "Unknown", category: "Unclassified",
  series_cells: null, parallel_cells: null, nominal_voltage_v: null, capacity_value: null, capacity_unit: "Ah", rated_energy_wh: null,
  charge_limit_a: null, discharge_limit_a: null, mass_kg: null, manufacture_date: "Unknown", condition: "Unknown", cycle_count: null,
  measured_capacity_ah: null, measured_voltage_v: null, measured_current_a: null, measured_temperature_c: null, soh_pct: null,
  initial_soc_pct: null, internal_resistance_mohm: null, source_kind: "user_entered", source_title: "User entry", source_url: "",
  license: "User-provided", measurement_method: "Not specified", notes: "", tags: [] };

function parseNumber(v, integer = false) {
  if (v === null || v === undefined || UNKNOWN_TEXT.includes(v)) return null;
  const x = typeof v === "number" ? v : typeof v === "string" && v.trim() !== "" ? Number(v) : NaN;
  if (!Number.isFinite(x)) return null;
  return integer ? Math.trunc(x) : x;
}
/** build a profile from JSON or a form/CSV row; bad numbers become unknown, not errors */
export function profileFromDict(data) {
  const p = { ...PROFILE_DEFAULTS, tags: [] };
  for (const [k, v] of Object.entries(data)) if (k in PROFILE_DEFAULTS && !(typeof PROFILE_DEFAULTS[k] === "string" && (v === null || v === ""))) p[k] = v;
  for (const k of INT_FIELDS) p[k] = parseNumber(data[k], true);
  for (const k of FLOAT_FIELDS) p[k] = parseNumber(data[k]);
  p.id = String(data.id || "").trim();
  p.name = String(data.name || "").trim() || p.id;
  if (typeof data.tags === "string") p.tags = data.tags.split(",").map((t) => t.trim()).filter(Boolean);
  else if (Array.isArray(data.tags)) p.tags = data.tags;
  return p;
}
export function completeness(p) {
  const missing = [];
  for (const [k, label] of [["chemistry", "chemistry"], ["series_cells", "series cell count"], ["nominal_voltage_v", "nominal voltage"],
    ["capacity_value", "rated capacity"], ["charge_limit_a", "charge current limit"], ["discharge_limit_a", "discharge current limit"]]) {
    const v = p[k];
    if (v === null || v === undefined || (typeof v === "string" && UNKNOWN_TEXT.includes(v))) missing.push(label);
  }
  return [missing.length ? "INCOMPLETE PROFILE" : "READY FOR SIMULATION", missing];
}

// ---------------------------------------------------------------- compatibility and evaluation
export function checkCompatibility(p, a) {
  const errors = [], warnings = [];
  if (p.series_cells === null) errors.push("Series cell count is unknown");
  else if (!(a.min_series <= p.series_cells && p.series_cells <= a.max_series)) errors.push("Series cell count is outside adapter capability");
  if (p.chemistry === "Unknown") errors.push("Chemistry is unknown");
  else {
    const chem = p.chemistry.toLowerCase();
    if (!a.chemistry_families.some((fam) => chem.includes(fam.toLowerCase()) || fam.toLowerCase().includes(chem))) errors.push("Chemistry/profile is unsupported by this adapter");
  }
  if (p.nominal_voltage_v === null) warnings.push("Nominal voltage is unknown");
  else if (p.nominal_voltage_v > a.max_stack_voltage_v) errors.push("Nominal voltage exceeds adapter stack capability");
  if (p.capacity_value === null) warnings.push("Capacity is unknown; SOC/SOH unavailable");
  return [errors.length === 0, errors, warnings];
}

export function evaluate(p, a, scenario = "Normal") {
  const [ok, errors, warnings] = checkCompatibility(p, a);
  if (!ok) return { state: "PROFILE_REQUIRED", status: "BLOCKED", errors, warnings, faults: [], protection: "SIMULATED ONLY — unavailable", soc_pct: null, soh_pct: null };
  // a measured zero is a real measurement and must not silently fall back to nominal voltage
  const voltage = p.measured_voltage_v !== null ? p.measured_voltage_v : p.nominal_voltage_v;
  const faults = [];
  const injected = { Undervoltage: "Simulated undervoltage input", Overvoltage: "Simulated overvoltage input",
    Overcurrent: "Simulated overcurrent input", "High temperature": "Simulated high temperature input" };
  if (scenario in injected) faults.push(injected[scenario]);
  else if (scenario === "Stale sensor") warnings.push("Sensor data is stale");
  if (p.measured_temperature_c === null) warnings.push("Temperature measurement unknown");
  let soc = null;
  if (voltage !== null && p.nominal_voltage_v) {
    soc = Math.max(0, Math.min(100, 100 * voltage / (p.nominal_voltage_v * 1.2)));
    warnings.push("SOC is a simple illustrative voltage estimate, not chemistry-calibrated");
  }
  return { state: faults.length ? "FAULT_LATCHED" : "READY", status: faults.length ? "FAULT" : warnings.length ? "REVIEW" : "READY",
    errors, warnings, faults, protection: faults.length ? "SIMULATED OPEN" : "SIMULATED MONITORING",
    soc_pct: soc !== null ? pyRound(soc, 1) : null, soh_pct: p.soh_pct, voltage_v: voltage, current_a: p.measured_current_a,
    temperature_c: p.measured_temperature_c };
}

// ---------------------------------------------------------------- the virtual pulse test
function startingVoltage(p) {
  if (p.measured_voltage_v !== null) return [Math.max(0.0, p.measured_voltage_v), "profile measurement"];
  if (p.nominal_voltage_v !== null) return [Math.max(0.0, p.nominal_voltage_v), "profile nominal voltage"];
  const chem = p.chemistry.toLowerCase();
  const cellV = chem.includes("lfp") ? 3.2 : chem.includes("lead") ? 2.0 : chem.includes("nimh") || chem.includes("nicd") ? 1.2 : 3.7;
  return [Math.max(0.0, cellV * (p.series_cells || 1)), `${cellV.toFixed(1)} V/cell synthetic virtual default`];
}
function capacityAh(p, nominal) {
  let cap = p.capacity_unit === "Ah" ? p.capacity_value : null;
  if (cap === null && p.capacity_value !== null && nominal) cap = (p.capacity_unit === "kWh" ? 1000 : 1) * p.capacity_value / nominal;
  return cap || 2.0;
}
function ratedAh(p) {
  if (p.capacity_unit === "Ah") return p.capacity_value;
  if (p.nominal_voltage_v && p.capacity_value) {
    if (p.capacity_unit === "Wh") return p.capacity_value / p.nominal_voltage_v;
    if (p.capacity_unit === "kWh") return 1000 * p.capacity_value / p.nominal_voltage_v;
  }
  return null;
}
function defaultDemand(p, capacity, scenario) {
  let d = Math.max(1.0, Math.min(p.discharge_limit_a || 10.0, capacity * 0.5));
  if (scenario === "High load") d *= 1.5;
  else if (scenario === "Overcurrent") d = (p.discharge_limit_a || d) * 1.25;
  else if (scenario === "Cell imbalance") d *= 0.5;
  return d;
}
/** the 30 s load shape: low baseline, full demand, reduced demand, full demand */
export const pulseFactor = (t) => (t < 3 ? 0.20 : t < 12 ? 1.0 : t < 20 ? 0.55 : 1.0);

export function stressTest(p, scenario = "Pulse load", { mode = "Discharge", target_voltage_v = null, demand_current_a = null,
  duration_s = PULSE_DURATION_S, sample_s = PULSE_SAMPLE_S } = {}) {
  if (!["Discharge", "Charge"].includes(mode)) throw new Error("mode must be 'Discharge' or 'Charge'");
  if (duration_s <= 0 || sample_s <= 0) throw new Error("duration_s and sample_s must be positive");
  if (demand_current_a !== null && demand_current_a <= 0) throw new Error("demand_current_a must be positive");
  const [voltage, voltageSource] = startingVoltage(p);
  const nominal = Math.max(Number(p.nominal_voltage_v || voltage || 1.0), 0.1);
  const capacity = capacityAh(p, nominal);
  const rated = ratedAh(p);
  const baseTemp = p.measured_temperature_c !== null ? p.measured_temperature_c : 25.0;
  if (demand_current_a === null) demand_current_a = defaultDemand(p, capacity, scenario);
  const target = Number(target_voltage_v !== null ? target_voltage_v : voltage);
  const refR = Math.max(1.0, 18.0 * (nominal / 48.0) * (50.0 / Math.max(capacity, 0.1)) ** 0.5);
  const capacitySoh = p.measured_capacity_ah !== null && rated ? 100.0 * p.measured_capacity_ah / rated : null;
  let latent = p.soh_pct !== null ? p.soh_pct : capacitySoh;
  const seed = [...p.id].reduce((s, ch) => s + ch.codePointAt(0), 0) % 31;
  if (latent === null) latent = 68.0 + seed;
  latent = Math.max(10.0, Math.min(110.0, Number(latent)));
  let rUsed, rSource;
  if (p.internal_resistance_mohm !== null && p.internal_resistance_mohm > 0) { rUsed = p.internal_resistance_mohm / 1000.0; rSource = "profile input"; }
  else { rUsed = (refR / 1000.0) * (1.0 + (100.0 - latent) / 65.0 + seed * 0.003); rSource = "profile-specific synthetic virtual plant estimate"; }
  const ratedCurrent = mode === "Discharge" ? p.discharge_limit_a : p.charge_limit_a;
  const hasRating = ratedCurrent !== null && ratedCurrent > 0;
  const currentLimit = Math.max(0.0, Number(hasRating ? ratedCurrent : capacity * (mode === "Discharge" ? 1.0 : 0.5)));
  const health = Math.max(0.0, Math.min(1.0, (latent - 20.0) / 80.0));
  const vFactor = Math.max(0.0, Math.min(1.0, voltage / Math.max(target, nominal * 0.75, 0.1)));
  const thermal = Math.max(0.0, Math.min(1.0, (65.0 - Math.max(0.0, baseTemp)) / 40.0));
  const available = currentLimit * Math.min(health, vFactor, thermal);
  const requestedPeak = Number(demand_current_a);
  const sign = mode === "Charge" ? 1.0 : -1.0;
  let initialSoc = p.initial_soc_pct, socSource;
  if (initialSoc === null && voltage > 0) { initialSoc = Math.max(0.0, Math.min(100.0, 100.0 * voltage / (nominal * 1.08))); socSource = "voltage-based starting estimate, then coulomb count"; }
  else if (initialSoc !== null) { initialSoc = Math.max(0.0, Math.min(100.0, Number(initialSoc))); socSource = "profile initial SOC, then coulomb count"; }
  else socSource = "unavailable: no usable voltage or initial SOC";
  const rMin = refR / 1000 * 0.1, rMax = refR / 1000 * 5;
  const points = [];
  let baseline = null, estR = null, estSoh = null, clamped = false, charged = 0.0, lastI = 0.0;
  const nSteps = pyRound(duration_s / sample_s);
  for (let n = 0; n <= nSteps; n++) {
    const t = n * sample_s;
    let pulse = pulseFactor(t);
    if (scenario === "Cell failure") pulse *= 0.5;
    const requested = requestedPeak * pulse;
    const current = voltage > 0 ? Math.min(requested, available) : 0.0;
    if (n) charged += lastI * sample_s / 3600.0;
    const soc = initialSoc !== null ? Math.max(0.0, Math.min(100.0, initialSoc + sign * 100.0 * charged / capacity)) : null;
    const socChange = soc !== null ? soc - initialSoc : 0.0;
    const ocv = voltage + socChange * nominal * 0.0012;
    const temp = baseTemp + (current * current * rUsed) * (1 - Math.exp(-t / 18.0)) * 0.12;
    const effR = rUsed * (1 + Math.max(0.0, 25.0 - temp) * 0.004 + Math.max(0.0, 50.0 - (soc !== null ? soc : 50.0)) * 0.002);
    const terminal = Math.max(0.0, ocv + sign * current * effR);
    const signed = sign * current;
    if (t < 3 && current > 0) baseline = [terminal, signed];
    if (t >= 3 && baseline !== null && current > 0) {
      const dI = Math.abs(signed - baseline[1]), dV = Math.abs(terminal - baseline[0]);
      if (dI > 1e-6) {
        const raw = dV / dI;
        estR = Math.max(rMin, Math.min(rMax, raw));
        clamped = estR !== raw;
        estSoh = Math.max(0.0, Math.min(100.0, 100.0 * (refR / 1000) / estR));
      }
    }
    points.push({ time_s: pyRound(t, 2), voltage_v: pyRound(terminal, 4), current_a: pyRound(current, 4), battery_current_a: pyRound(signed, 4),
      demand_current_a: pyRound(requested, 4), target_voltage_v: pyRound(target, 4), temperature_c: pyRound(temp, 3),
      power_w: pyRound(terminal * current, 3), soc_pct: soc !== null ? pyRound(soc, 3) : null, soh_pct: estSoh !== null ? pyRound(estSoh, 3) : null,
      soh_state: estSoh !== null ? "ESTIMATED FROM LIVE PULSE" : "WAITING FOR LOAD PULSE",
      resistance_mohm: estR !== null ? pyRound(estR * 1000, 3) : null, dod_pct: soc !== null ? pyRound(100 - soc, 3) : null });
    lastI = current;
  }
  const peakTemp = Math.max(...points.map((q) => q.temperature_c));
  const minV = Math.min(...points.map((q) => q.voltage_v));
  const faults = [];
  if (requestedPeak > available) faults.push("Requested current not fully delivered by virtual capability");
  if (scenario === "Cell imbalance") faults.push("Synthetic imbalance injected");
  if (scenario === "Overcurrent") faults.push("Synthetic overcurrent threshold crossed");
  if (scenario === "Cell failure") faults.push("Synthetic cell failure injected");
  if (points[points.length - 1].voltage_v < target * 0.98) faults.push("Requested voltage not met by direct-source model");
  if (peakTemp >= 55 || scenario === "Thermal risk") faults.push("Thermal risk indicator — requires qualified assessment");
  const drop = voltage - minV;
  const dropPct = voltage ? 100 * drop / voltage : null;
  const effSoh = points[points.length - 1].soh_pct;
  let condition, use;
  if (voltage <= 0) { condition = "DEAD / NO OUTPUT"; use = "No use — no valid voltage output. Qualified assessment/recycling review."; }
  else if (peakTemp >= 55 || scenario === "Thermal risk") { condition = "CRITICAL HEAT"; use = "No reuse recommendation — thermal indicator requires qualified assessment."; }
  else if (["Overcurrent", "Cell failure", "Cell imbalance"].includes(scenario) || (dropPct !== null && dropPct >= 15)) { condition = "FAIL / LARGE VOLTAGE SAG"; use = "No use recommendation — investigate modeled fault or voltage sag."; }
  else if (effSoh === null) { condition = "INCOMPLETE HEALTH DATA"; use = "No pulse-derived SOH available; collect more voltage/current/capacity data."; }
  else if (effSoh >= 80) { condition = "VIRTUAL PASS — SCREENING ONLY"; use = "Candidate for stationary storage screening after independent engineering qualification."; }
  else if (effSoh >= 60) { condition = "LIMITED — SCREENING ONLY"; use = "Consider low-demand backup screening only after independent testing."; }
  else { condition = "END-OF-LIFE SCREEN"; use = "Further qualified assessment or recycling review."; }
  return {
    points, mode, target_voltage_v: target, demand_current_a: requestedPeak, delivered_current_a: sign * Math.min(requestedPeak, available),
    current_capability_a: available, c_rate_limit_a: currentLimit, peak_current_a: Math.max(...points.map((q) => q.current_a)),
    peak_voltage_v: Math.max(...points.map((q) => q.voltage_v)), min_voltage_v: minV, peak_temperature_c: peakTemp,
    energy_wh: points.reduce((s, q) => s + q.power_w, 0) * sample_s / 3600, failed_cells: scenario === "Cell failure" && p.series_cells ? 1 : 0,
    faults, risk: faults.length ? "HIGH — modeled fault present" : "No modeled fault in this scenario", soc_source: socSource,
    soh_source: effSoh !== null ? "estimated from simulated voltage sag / current step" : "unavailable: no measurable current pulse",
    voltage_source: voltageSource, resistance_mohm: estR !== null ? estR * 1000 : rUsed * 1000, resistance_source: rSource,
    reference_resistance_mohm: refR, soh_proxy_clamped: clamped, loaded_voltage_drop_v: drop, loaded_voltage_drop_pct: dropPct,
    condition, use_recommendation: use, source: SOURCE_LABEL,
  };
}

/** one verdict for a finished test, with its reason and the data still missing */
export function screeningSummary(p, result) {
  const soh = result.points[result.points.length - 1].soh_pct;
  let v;
  if (result.faults.length || p.condition === "Damaged - do not test") v = ["No reuse recommendation", "critical", "No reuse recommendation from this virtual test.", "The requested operating point was not met, or a modeled fault or blocked condition occurred."];
  else if (soh === null) v = ["Unknown health", "warning", "No use case suggested yet, because SOH is unknown.", "A virtual pulse cannot establish remaining capacity or battery safety."];
  else if (result.soh_proxy_clamped) v = ["Inconclusive", "warning", "No use case suggested from this pulse.", "The pulse resistance fell outside the model's reference range, so the SOH proxy hit its limit and doesn't describe this battery. Rely on measured capacity instead."];
  else if (soh >= 80) v = ["Screening pass", "good", "Candidate for stationary-storage screening after independent qualification.", "The pulse-derived SOH proxy is at least 80%. It is not copied from the profile SOH field."];
  else if (soh >= 60) v = ["Limited use", "warning", "Candidate for low-demand backup screening after independent testing.", "The pulse-derived SOH proxy is 60–79%. Verify capacity, resistance, cell balance and power capability."];
  else v = ["End of life screen", "serious", "Further qualified assessment or recycling review.", "The pulse-derived SOH proxy is below 60%."];
  const gaps = [[p.measured_capacity_ah, "measured capacity test"], [p.internal_resistance_mohm, "internal resistance measurement"],
    [p.series_cells, "series/cell count and cell-level health"], [p.initial_soc_pct, "initial SOC or valid rest-voltage data"],
    [p.measured_temperature_c, "measured temperature"]].filter(([val]) => val === null || val === undefined).map(([, l]) => l);
  return { label: v[0], tone: v[1], use: v[2], reason: v[3], gaps };
}
