// Sample packs in Circuit Studio: each one replays its latest cycle through the BMS engine.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { ROOT } from "./helpers.mjs";
import { samplePackFromCSV, SAMPLE_PACK_FILES } from "../assets/js/engines/samplePacks.js";
import { BMSEngine, getDecisionForUi, BUNDLE_DISCHARGE_POSITIVE, TIER_STATIONARY, TIER_LOW_SPEED_EV, TIER_RECYCLING } from "../assets/js/engines/bms.js";
import { voltageFlags } from "../assets/js/engines/runController.js";

function replay(file) {
  const pack = samplePackFromCSV(readFileSync(join(ROOT, "data", "samples", file), "utf8"), file);
  const p = pack.profile;
  const engine = new BMSEngine({ rated_capacity_ah: p.rated_capacity_ah, baseline_measured_ah: p.measured_capacity_ah,
    baseline_date: p.capacity_test_date, discharge_positive: BUNDLE_DISCHARGE_POSITIVE });
  for (const s of pack.samples) engine.process(s);
  const rows = pack.samples.map((s) => ({ voltage_v: s.voltage_v }));
  return { pack, engine, decision: getDecisionForUi(engine), flags: voltageFlags(p, rows) };
}

test("sample packs: every file loads and replays its latest cycle", () => {
  for (const f of SAMPLE_PACK_FILES) {
    const { pack, engine } = replay(f);
    assert.equal(pack.samples.length, 6, f);
    assert.ok(pack.samples.every((s, k) => k === 0 || s.timestamp > pack.samples[k - 1].timestamp), `${f}: time increases`);
    // time is derived from the logged capacity, so coulomb counting gives back exactly the logged Ah
    assert.ok(Math.abs(engine.discharged_ah - pack.profile.measured_capacity_ah) < 0.01, `${f}: ${engine.discharged_ah} vs ${pack.profile.measured_capacity_ah}`);
  }
});

test("sample packs: tiers follow the logged capacity", () => {
  const tier = (f) => replay(f).decision.use_case;
  assert.equal(tier("1_healthy_pack.csv"), TIER_STATIONARY);
  assert.equal(tier("2_worn_pack.csv"), TIER_LOW_SPEED_EV);
  assert.equal(tier("5_end_of_life_pack.csv"), TIER_RECYCLING);
  assert.equal(tier("6_timestamped_pack.csv"), TIER_STATIONARY);
});

test("sample packs: only the over-discharged pack is flagged for voltage", () => {
  for (const f of SAMPLE_PACK_FILES) {
    const { flags } = replay(f);
    if (f === "3_overdischarged_pack.csv") assert.match(flags[0] || "", /^Over-discharge: the voltage fell to 29\.0 V, below the pack's minimum of 32 V/);
    else assert.deepEqual(flags, [], f);
  }
});
