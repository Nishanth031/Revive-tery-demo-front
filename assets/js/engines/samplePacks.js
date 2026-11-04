// Sample packs for Circuit Studio replay: the SYNTHETIC cycler logs in data/samples/ (made by src/make_ml_samples.py),
// turned into replayable batteries next to the database battery.
//
// What is taken from the files, and what is not:
// - Each pack replays its LATEST cycle: the battery as it is now, not as it was 100 cycles ago.
// - Most files have no time column. The time between rows is worked out from the logged discharge capacity:
//   dt = ΔAh / |I| × 3600, so coulomb counting reproduces the logged Ah exactly. Nothing else is assumed about time.
//   (6_timestamped_pack's timestamps are 10 min apart, which its own capacity and current don't add up to, so the
//   same rule is used for it and that is said in its note.)
// - The pack spec comes from data/samples/README.txt: LFP, 16 cells in series, rated 100 Ah.
// - The latest cycle's logged discharge capacity is that pack's capacity test.
// - The start SOC is unknown and is never assumed, so live SOH is a lower bound (Ah discharged / rated).
import { parseCSV } from "../lib/csv.js";
import { standardise, SAFETY_LIMITS } from "./lite.js";
import { makeSample } from "./bms.js";

export const SAMPLE_PACK_FILES = ["1_healthy_pack.csv", "2_worn_pack.csv", "3_overdischarged_pack.csv", "5_end_of_life_pack.csv", "6_timestamped_pack.csv"];
export const SAMPLE_PACK_SPEC = { chemistry: "LFP", series_cells: 16, rated_capacity_ah: 100, source: "data/samples/README.txt" };

/** one sample CSV -> { profile, samples, note } for its latest cycle; throws when the file can't be replayed */
export function samplePackFromCSV(text, file) {
  const { header, rows } = parseCSV(text);
  const std = standardise(header, rows, file);
  if (!std) throw new Error(`${file}: no voltage column`);
  for (const c of ["current_a", "capacity_ah", "cycle_index"]) {
    if (!std.data.length || !(c in std.data[0])) throw new Error(`${file}: needs a ${c} column to be replayed`);
  }
  const id = std.data[0].battery_id;
  const lastCycle = Math.max(...std.data.map((r) => r.cycle_index).filter(Number.isFinite));
  const cyc = std.data.filter((r) => r.battery_id === id && r.cycle_index === lastCycle);
  if (cyc.length < 2) throw new Error(`${file}: cycle ${lastCycle} has fewer than 2 rows`);

  const samples = [];
  let t = 0, skipped = 0;
  cyc.forEach((r, k) => {
    if (k > 0) {
      const dAh = r.capacity_ah - cyc[k - 1].capacity_ah;
      const amps = Math.abs(r.current_a);
      if (!(dAh >= 0) || !(amps > 0)) { skipped++; return; }
      t += (dAh / amps) * 3600;
    }
    samples.push(makeSample({ timestamp: t, voltage_v: r.voltage_v, current_a: r.current_a, temperature_c: r.temperature_c, state: "DISCHARGE" }));
  });
  const measured = Math.max(...cyc.map((r) => r.capacity_ah).filter(Number.isFinite));
  const lim = SAFETY_LIMITS[SAMPLE_PACK_SPEC.chemistry];
  const n = SAMPLE_PACK_SPEC.series_cells;
  const profile = {
    asset_id: id, chemistry: SAMPLE_PACK_SPEC.chemistry, nominal_voltage_v: null,
    min_voltage_v: round(lim.cell_v_min * n), max_voltage_v: round(lim.cell_v_max * n),
    rated_capacity_ah: SAMPLE_PACK_SPEC.rated_capacity_ah, measured_capacity_ah: round(measured, 2),
    capacity_test_date: `cycle ${lastCycle} of the log`, telemetry_rows: samples.length, is_synthetic: true,
    source: "sample", file, cycle: lastCycle, cycles_in_file: new Set(std.data.map((r) => r.cycle_index)).size,
    voltage_limits_basis: `${SAMPLE_PACK_SPEC.chemistry} ${lim.cell_v_min}–${lim.cell_v_max} V per cell × ${n} in series`,
  };
  const note = `Latest cycle (${lastCycle} of ${profile.cycles_in_file}) of data/samples/${file}. Time between rows is worked out from the logged discharge capacity ÷ current` +
    `${"timestamp_utc" in cyc[0] ? " (the file's own timestamps don't match its capacity and current, so they aren't used)" : " (the file has no time column)"}.` +
    `${skipped ? ` ${skipped} row(s) left out: capacity went down or current was zero.` : ""}`;
  return { profile, samples, note };
}

/** fetch and convert every sample pack; packs that fail are reported, not hidden */
export async function loadSamplePacks(fetchText) {
  const packs = {}, errors = [];
  await Promise.all(SAMPLE_PACK_FILES.map(async (f) => {
    try { const p = samplePackFromCSV(await fetchText(`data/samples/${f}`), f); packs[p.profile.asset_id] = p; }
    catch (e) { errors.push(`${f}: ${e.message}`); }
  }));
  return { packs, errors };
}

function round(x, d = 1) { const k = 10 ** d; return Math.round(x * k) / k; }
