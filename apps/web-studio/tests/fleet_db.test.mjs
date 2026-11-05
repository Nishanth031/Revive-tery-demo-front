// The fleet in data/demo (refreshed by `just web-db`) is readable by the browser engines: bms.js and contract.js.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { parseCSV } from "../assets/js/lib/csv.js";
import { listBatteryIds, loadBatteryProfile } from "../assets/js/engines/bms.js";
import { convertDemo } from "../assets/js/engines/contract.js";

const read = (t) => parseCSV(readFileSync(new URL(`../data/demo/${t}.csv`, import.meta.url), "utf-8")).rows;
const have = existsSync(new URL("../data/demo/telemetry_dense.csv", import.meta.url));
const tables = () => Object.fromEntries(["battery_asset", "battery_registry", "telemetry", "telemetry_dense", "health_history", "safety_events"]
  .map((t) => [t, read(t)]));

test("fleet: at least 60 packs, registry and key/value battery_asset agree", { skip: !have && "run just web-db" }, () => {
  const t = tables();
  const ids = listBatteryIds(t);
  assert.ok(ids.length >= 60, `${ids.length} packs`);
  for (const r of t.battery_registry) {
    const p = loadBatteryProfile(t, r.asset_id);
    assert.equal(p.chemistry, r.chemistry, r.asset_id);
    assert.equal(p.rated_capacity_ah, Number(r.nominal_capacity_Ah), r.asset_id);
  }
});

test("fleet: an NCA pack converts with dense telemetry (>= 1000 rows) and its original 12 rows", { skip: !have && "run just web-db" }, () => {
  const t = tables();
  const nca = t.battery_registry.find((r) => r.chemistry === "NCA (nickel cobalt aluminium)");
  assert.ok(nca, "an NCA pack exists");
  const dense = convertDemo(t, nca.asset_id, { telemetry: "dense" });
  assert.equal(dense.meta.chemistry, "NCA");
  assert.ok(dense.tel.n >= 1000, `${dense.tel.n} dense rows`);
  const orig = convertDemo(t, nca.asset_id, { telemetry: "original" });
  assert.equal(orig.tel.n, 12);
  assert.throws(() => convertDemo({ ...t, battery_asset: t.battery_asset.map((r) => (r.asset_id === nca.asset_id && r.field === "chemistry" ? { ...r, value: "LCO" } : r)) }, nca.asset_id),
    /no explicit mapping/);                                               // unknown labels still raise
});
