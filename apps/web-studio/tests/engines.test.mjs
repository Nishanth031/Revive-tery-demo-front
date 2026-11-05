// Parity of every other engine with its Python original (golden outputs from tools/make_golden.py and export_assets.py).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { createRequire } from "node:module";
import { ROOT, golden, assets, close, readJSON, readText } from "./helpers.mjs";
import { parseCSV } from "../assets/js/lib/csv.js";
import * as contract from "../assets/js/engines/contract.js";
import { assess } from "../assets/js/engines/pipeline.js";
import * as physics from "../assets/js/engines/physics.js";
import { sweep } from "../assets/js/engines/econ.js";
import * as lite from "../assets/js/engines/lite.js";
import * as bms from "../assets/js/engines/bms.js";
import { SimulatedESP32 } from "../assets/js/engines/esp32sim.js";
import * as relife from "../assets/js/engines/relife.js";
import * as np from "../assets/js/lib/np.js";

const require = createRequire(import.meta.url);
const libs = { JSZip: require("jszip"), XLSX: require("xlsx") };
const demoTables = () => Object.fromEntries(["battery_asset", "telemetry", "health_history", "safety_events", "charge_sessions", "modules"]
  .map((t) => [t, parseCSV(readText(`data/demo/${t}.csv`)).rows]));

// ---------------------------------------------------------------- exported models
test("state model: HGB + CV+ matches scikit-learn + MAPIE on 130 inputs", async () => {
  const A = await assets();
  const g = golden("state_inputs.json");
  g.X.forEach((row, i) => {
    const p = A.stateModel.predictOne(row.map((v) => (v === null ? NaN : v)));
    close(p.point, g.point[i], `point ${i}`, 1e-9, 1e-9);
    close(p.lower, g.lower[i], `lower ${i}`, 1e-9, 1e-9);
    close(p.upper, g.upper[i], `upper ${i}`, 1e-9, 1e-9);
  });
});

for (const fam of ["synthetic_packs", "measured_cells"]) {
  test(`gate model ${fam}: IsolationForest scores match scikit-learn`, async () => {
    const A = await assets();
    const g = golden(`gate_inputs_${fam}.json`);
    g.X.forEach((x, i) => close(A.gates[fam].scoreOne(x), g.score[i], `score ${i}`, 1e-9, 1e-12));
  });
}

// ---------------------------------------------------------------- physics and economics
test("physics: life tables match the Python sanity report", async () => {
  const A = await assets();
  const ph = A.configs.physics, p = physics.nominalParams(ph);
  const years = np.linspace(0, 60, 60 * 365 + 1);
  const life = (w, soh0 = 1.0, rul = 1000.0) => {
    const tr = physics.trajectory(ph, soh0, rul, { ...w, cycles_per_day: 1.0 }, p, years, physics.EOL_REF, false);
    const y = physics.yearsTo(tr, years, physics.EOL_REF);
    return y === null ? Infinity : y * 365.0;
  };
  const g = golden("physics_sanity.json").checks;
  const base = { daily_dod: 1.0, ambient_c: 25.0, c_rate: 1.0 };
  for (const [t, v] of Object.entries(g.temperature.cycles_to_80_by_ambient_c)) assert.equal(np.pyRound(life({ ...base, ambient_c: Number(t) })), v, `T=${t}`);
  for (const [d, v] of Object.entries(g.depth_of_discharge.cycles_to_80_by_dod)) assert.equal(np.pyRound(life({ ...base, daily_dod: Number(d) })), v, `DoD=${d}`);
  for (const [c, v] of Object.entries(g.c_rate.cycles_to_80_by_c_rate)) assert.equal(np.pyRound(life({ ...base, c_rate: Number(c) })), v, `C=${c}`);
  for (const c of g.continuity_at_reference.cases) {
    close(life({ daily_dod: 1.0, ambient_c: 30.0, c_rate: 4.0 }, c.soh0, c.ml_rul_ref), c.physics_cycles_to_80, "continuity", 1e-3);
  }
});

test("economics: price sensitivity sweep matches Python", async () => {
  const A = await assets();
  const got = sweep(A.configs.economics, A.configs.physics, A.configs.workloads.workloads);
  const ref = golden("econ_sensitivity.json");
  assert.equal(got.reference_battery.projected_years, ref.reference_battery.projected_years);
  for (const [chem, r] of Object.entries(ref.chemistries)) {
    assert.deepEqual(got.chemistries[chem].recycle_wins_at_metal_multipliers, r.recycle_wins_at_metal_multipliers, chem);
    r.grid.forEach((cell, i) => {
      const gc = got.chemistries[chem].grid[i];
      assert.equal(gc.decision, cell.decision, `${chem} cell ${i}`);
      assert.ok(Math.abs(gc.recycle_net_usd - cell.recycle_net_usd) <= 1 && Math.abs(gc.second_life_net_usd - cell.second_life_net_usd) <= 1, `${chem} cell ${i} values`);
    });
  }
});

// ---------------------------------------------------------------- data contract
test("convert-demo: the demo database tables become the same bundle and report", async () => {
  const A = await assets();
  const ref = golden("pipeline_cases.json").demo_pack;
  const b = contract.convertDemo(demoTables(), "DEMO-EV-PACK-001", { telemetry: "original" });
  const m = { ...ref.bundle.metadata };
  for (const k of Object.keys(m)) {
    if (k === "safety_events") m[k].forEach((e, i) => { assert.equal(contract.parseIso(b.meta[k][i].timestamp_utc), contract.parseIso(e.timestamp_utc)); });
    else assert.deepEqual(b.meta[k], m[k], `metadata ${k}`);
  }
  assert.equal(b.tel.n, ref.bundle.telemetry.length);
  const r = assess(b, A);
  assert.equal(r.decision, ref.report.decision);
  assert.deepEqual(r.data_quality.checks.map((c) => c.message), ref.report.data_quality.checks.map((c) => c.message));
});

test("contract: bad metadata is refused with a reason", () => {
  assert.throws(() => contract.validateMetadata({ asset_id: "X" }), /field required/);
  const ok = { asset_id: "X", chemistry: "LFP", rated_capacity_ah: 10, nominal_voltage_v: 3.2, min_voltage_v: 2.5, max_voltage_v: 3.65, data_provenance: "synthetic" };
  assert.equal(contract.validateMetadata(ok).current_sign_convention, "unknown");
  assert.throws(() => contract.validateMetadata({ ...ok, min_voltage_v: 4 }), /voltages must satisfy/);
  assert.throws(() => contract.validateMetadata({ ...ok, chemistry: "LCO" }), /chemistry must be one of/);
  assert.throws(() => contract.validateMetadata({ ...ok, extra: 1 }), /extra field/);
  assert.throws(() => contract.validateTelemetry([{ pack_voltage_V: 1, timestamp_utc: "2026-01-01T00:00:00Z" }]), /looks like 'voltage_v'/);
});

test("contract zip: sample 7 loads as a bundle and is assessed", async () => {
  const A = await assets();
  const zip = await libs.JSZip.loadAsync(readFileSync(join(ROOT, "data/samples/7_contract_bundle.zip")));
  const files = {};
  for (const f of Object.values(zip.files)) if (!f.dir) files[f.name.split("/").pop()] = await f.async("string");
  assert.ok(contract.isContractFileSet(Object.keys(files)));
  const b = contract.bundleFromContractFiles(files);
  const r = assess(b, A);
  assert.ok(r.decision.length > 0);
  assert.equal(r.data_provenance, "synthetic");
});

// ---------------------------------------------------------------- lite analyzer + upload adapter
test("lite analyzer and upload adapter: samples 1-6 match Python", async () => {
  const A = await assets();
  const ref = golden("lite_cases.json");
  const store = new lite.LiteStore();
  const files = ["1_healthy_pack.csv", "2_worn_pack.csv", "3_overdischarged_pack.csv", "4_no_capacity_in_zip.zip", "5_end_of_life_pack.csv", "6_timestamped_pack.csv"];
  const spec = { chemistry: "LFP", series_cells: 16, rated_capacity_ah: 100, nominal_voltage_v: null };
  const bspec = { chemistry: "LFP", series_cells: 16, parallel_cells: 1, rated_capacity_ah: 100.0, nominal_voltage_v: null };
  for (const name of files) {
    const ex = await lite.extract(name, new Uint8Array(readFileSync(join(ROOT, "data/samples", name))), libs);
    store.seed(ex, "synthetic");
    for (const bid of [...new Set(ex.flatMap((x) => x.data.map((r) => r.battery_id)))]) {
      const g = ref[bid];
      assert.ok(g, `golden for ${bid}`);
      for (const x of ex) {
        const gm = g.mapping[x.source];
        assert.deepEqual(x.mapping, gm.mapped, `${bid} mapping`);
        assert.deepEqual(x.unmapped, gm.unmapped);
        assert.deepEqual(x.warnings, gm.warnings);
        assert.equal(x.data.length, gm.rows);
      }
      const rep = lite.suggest(store, bid, spec);
      const gr = g.report;
      assert.deepEqual(rep.suggestion, gr.suggestion, `${bid} suggestion`);
      assert.deepEqual(rep.data_quality, gr.data_quality, `${bid} data quality`);
      assert.deepEqual({ ...rep.safety_gate }, gr.safety_gate, `${bid} gate`);
      if (gr.state) for (const [k, v] of Object.entries(gr.state)) assert.deepEqual(rep.state[k], v, `${bid} state ${k}`);
      if (gr.economics) assert.deepEqual(rep.economics.options, gr.economics.options, `${bid} options`);
      try {
        const b = contract.bundleFromRows(store.loadBattery(bid), bid, bspec, "golden", A.configs.limits);
        assert.ok(g.bundle, `${bid}: Python refused (${g.adapter_error}) but JS built a bundle`);
        assert.deepEqual(b.meta, g.bundle.metadata, `${bid} adapter metadata`);
        assert.equal(b.tel.n, g.bundle.telemetry.length);
        assert.equal(assess(b, A).decision, g.full_report.decision, `${bid} full decision`);
      } catch (e) {
        if (!(e instanceof contract.AdapterError)) throw e;
        assert.equal(e.message, g.adapter_error, `${bid} adapter error`);
      }
    }
  }
});

test("lite: header normalisation and unknown columns", () => {
  assert.equal(lite.normaliseHeader("Pack Voltage (V)"), "pack_voltage_v");
  assert.equal(lite.normaliseHeader("Temp [°C]"), "temp_c");
  const s = lite.standardise(["Voltage", "Mystery"], [{ Voltage: "3.7", Mystery: "x" }, { Voltage: "bad", Mystery: "y" }], "f.csv");
  assert.deepEqual(s.unmapped, ["Mystery"]);
  assert.deepEqual(s.warnings, ["voltage_v: 1 non-numeric values set to null", "no battery id column; file name used as battery_id"]);
  assert.equal(s.data[0].battery_id, "f");
  assert.equal(lite.standardise(["foo"], [{ foo: 1 }], "x.csv"), null);
});

test("upload adapter: re-uploading a file keeps only its latest copy", async () => {
  const A = await assets();
  const store = new lite.LiteStore();
  const name = "6_timestamped_pack.csv";
  const bytes = new Uint8Array(readFileSync(join(ROOT, "data/samples", name)));
  store.seed(await lite.extract(name, bytes, libs), "synthetic");
  await new Promise((r) => setTimeout(r, 5));
  store.seed(await lite.extract(name, bytes, libs), "synthetic");
  const rows = store.loadBattery("PACK-TIMESTAMPED");
  const b = contract.bundleFromRows(rows, "PACK-TIMESTAMPED", { chemistry: "LFP", series_cells: 16, parallel_cells: 1, rated_capacity_ah: 100, nominal_voltage_v: null }, "test", A.configs.limits);
  assert.equal(b.tel.n * 2, rows.length);
});

// ---------------------------------------------------------------- BMS engine, serial path, simulator
test("BMS engine: demo replay matches Python reading by reading", () => {
  const g = golden("bms_cases.json").demo_replay;
  const s = g.settings;
  const eng = new bms.BMSEngine(s);
  const samples = bms.replaySamples(demoTables(), "DEMO-EV-PACK-001", contract.parseIso);
  assert.equal(samples.length, g.samples.length);
  samples.forEach((smp, i) => {
    assert.equal(smp.timestamp, g.samples[i].timestamp);
    const r = eng.process(smp);
    close(r.soc_pct, g.readings[i].soc_pct, `soc ${i}`, 1e-12);
    close(r.soh_live_pct, g.readings[i].soh_live_pct, `soh ${i}`, 1e-12);
    assert.equal(r.soh_basis, g.readings[i].soh_basis);
  });
  assert.deepEqual(bms.getDecisionForUi(eng), g.decision);
  const prof = bms.loadBatteryProfile(demoTables(), "DEMO-EV-PACK-001");
  assert.equal(prof.rated_capacity_ah, s.rated_capacity_ah);
  assert.equal(prof.measured_capacity_ah, s.baseline_measured_ah);
  assert.equal(prof.capacity_test_date, s.baseline_date);
  assert.ok(prof.is_synthetic);
});

for (const name of ["sim_clean", "sim_faults"]) {
  test(`BMS engine on simulated-ESP32 serial lines (${name}) matches Python`, () => {
    const g = golden("bms_cases.json")[name];
    const eng = new bms.BMSEngine(g.settings);
    const stats = new bms.SerialStats();
    g.lines.forEach((item, i) => {
      const exp = g.results[i];
      if (item.line.startsWith("#")) {
        stats.recordMessage(item.line, item.t);
        assert.equal(bms.firmwareMessageSeverity(item.line), exp.severity);
        return;
      }
      const s = bms.parseTelemetryLine(item.line, item.t);
      if (s === null) { assert.ok(exp.skipped !== undefined); return; }
      const r = eng.process(s);
      close(r.soc_pct, exp.soc_pct, `soc ${i}`, 1e-12);
      close(r.soh_live_pct, exp.soh_live_pct, `soh ${i}`, 1e-12);
      assert.equal(s.temperature_c, exp.temperature_c);
    });
    assert.deepEqual(bms.getDecisionForUi(eng), g.decision);
    assert.deepEqual(stats.fault_counts, g.fault_counts);
  });
}

test("simulated ESP32 (JS) reproduces the Python simulator's line sequence", () => {
  const g = golden("bms_cases.json").sim_faults;
  const faults = { 300: "ds18b20", 330: "none", 600: "overvoltage", 620: "none", 900: "ina219", 930: "none" };
  const sim = new SimulatedESP32({ true_capacity_ah: 1.8, load_current_a: 1.0, speed: 60.0, seed: 7 }, 0.0);
  const lines = sim.open().map((l) => ({ t: sim.clock(), line: l }));
  // the Python harness counts readline() calls; one line per call, silent ticks don't return
  let calls = lines.length, queue = [];        // each boot line costs one readline() call in the Python harness
  while (!sim.complete && calls < 8000) {
    if (calls in faults) sim.setFault(faults[calls]);
    while (!queue.length) queue = sim.tick();
    lines.push({ t: sim.clock(), line: queue.shift() });
    calls++;
  }
  assert.equal(lines.length, g.lines.length);
  lines.forEach((l, i) => {
    const ref = g.lines[i];
    assert.equal(l.t, ref.t, `time ${i}`);
    if (ref.line.startsWith("#")) { assert.equal(l.line, ref.line, `message ${i}`); return; }
    const a = JSON.parse(l.line), b = JSON.parse(ref.line);
    assert.ok(Math.abs(a.voltage - b.voltage) < 0.03 && Math.abs(a.current - b.current) < 0.004, `reading ${i}: ${l.line} vs ${ref.line}`);
    assert.equal(a.temperature === null, b.temperature === null, `temperature presence ${i}`);
  });
});

test("BMS maths and decision tiers", () => {
  assert.equal(bms.calculateSoc(50, 1, 3600, 2), 0);
  assert.equal(bms.calculateSoh(1.8, 2), 90);
  assert.equal(bms.getSecondaryUseCase(80.0001), "Stationary Storage");
  assert.equal(bms.getSecondaryUseCase(80), "Low-speed EVs");
  assert.equal(bms.getSecondaryUseCase(60), "Low-speed EVs");
  assert.equal(bms.getSecondaryUseCase(59.9), "Recycling");
  assert.equal(bms.getSecondaryUseCase(null), "Insufficient data");
  assert.equal(bms.getSecondaryUseCase(-1), "Insufficient data");
  assert.equal(bms.parseTelemetryLine("garbage", 0), null);
  assert.equal(bms.parseTelemetryLine('{"voltage":3.7,"current":0.5,"temperature":-127}', 0).temperature_c, null);
  assert.equal(bms.firmwareMessageSeverity("# OVER 26 V"), "critical");
  assert.equal(bms.firmwareMessageSeverity("# INA219 ready"), "info");
  assert.equal(bms.firmwareMessageSeverity("# something new"), "warning");
});

test("firmware messages in the simulator match the .ino sketch", () => {
  const ino = readText("data/firmware/revive_tery_esp32.ino");
  for (const m of ["INA219 ready", "INA219 not found: check SDA, SCL, VCC and GND", "INA219 read failed: check the wiring",
    "OVER 26 V: disconnect now, this exceeds the INA219's rating", "Current above the 3.2 A range: reading withheld"]) {
    assert.ok(ino.includes(m), `sketch has "${m}"`);
  }
});

// ---------------------------------------------------------------- ReLife BMS Studio
test("ReLife: compatibility, evaluation, pulse test and screening match Python", () => {
  const cat = readJSON("data/relife.json").catalog.map(relife.profileFromDict);
  const byId = Object.fromEntries(cat.map((p) => [p.id, p]));
  const ad = Object.fromEntries(relife.ADAPTERS.map((a) => [a.id, a]));
  const g = golden("relife_cases.json");
  for (const c of g.compat) {
    const [ok, errors, warnings] = relife.checkCompatibility(byId[c.profile], ad[c.adapter]);
    assert.deepEqual({ ok, errors, warnings }, { ok: c.ok, errors: c.errors, warnings: c.warnings }, `${c.profile} ${c.adapter}`);
  }
  for (const c of g.evaluate) assert.deepEqual(relife.evaluate(byId[c.profile], ad[c.adapter], c.scenario), c.result, `${c.profile} ${c.scenario}`);
  for (const c of g.stress) {
    const r = relife.stressTest(byId[c.profile], c.scenario, { mode: c.mode });
    const ref = c.result;
    assert.equal(r.points.length, ref.points.length);
    r.points.forEach((p, i) => {
      for (const k of Object.keys(ref.points[i])) {
        if (typeof ref.points[i][k] === "number") close(p[k], ref.points[i][k], `${c.profile} ${c.scenario} ${c.mode} t${i} ${k}`, 1e-9, 2e-3);
        else assert.equal(p[k], ref.points[i][k]);
      }
    });
    for (const k of ["faults", "risk", "condition", "use_recommendation", "soc_source", "soh_source", "voltage_source", "resistance_source", "soh_proxy_clamped", "failed_cells"]) {
      assert.deepEqual(r[k], ref[k], `${c.profile} ${c.scenario} ${c.mode} ${k}`);
    }
    for (const k of ["energy_wh", "resistance_mohm", "reference_resistance_mohm", "current_capability_a", "min_voltage_v"]) close(r[k], ref[k], k, 1e-6, 1e-6);
    assert.deepEqual(relife.screeningSummary(byId[c.profile], r), c.summary);
  }
});
