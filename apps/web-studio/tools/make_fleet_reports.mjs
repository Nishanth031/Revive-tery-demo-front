// Precompute the fleet for the Command Center: every pack in data/demo through the browser engines (the JS ports),
// with dense telemetry, plus the insight layer. Writes data/fleet_reports.json (compact: no raw telemetry, no per-window
// gate scores). Run from apps/web-studio:  node tools/make_fleet_reports.mjs   (part of `just web-regen`)
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { parseCSV } from "../assets/js/lib/csv.js";
import { listBatteryIds } from "../assets/js/engines/bms.js";
import { convertDemo } from "../assets/js/engines/contract.js";
import { assess, loadAssets } from "../assets/js/engines/pipeline.js";
import { disposition } from "../assets/js/lib/disposition.js";
import { summarizeForFleet, compactInsight } from "../assets/js/lib/fleet.js";
import { insightFor } from "../assets/js/engines/insight.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const readJSON = (p) => JSON.parse(readFileSync(join(ROOT, p), "utf-8"));
const TABLES = ["battery_asset", "battery_registry", "telemetry", "telemetry_dense", "health_history", "safety_events"];

const assets = await loadAssets(async (p) => readJSON(p));
const tables = Object.fromEntries(TABLES.filter((t) => existsSync(join(ROOT, "data/demo", `${t}.csv`)))
  .map((t) => [t, parseCSV(readFileSync(join(ROOT, "data/demo", `${t}.csv`), "utf-8")).rows]));
const decisionMap = readJSON("data/decision_map.json");
const meta = existsSync(join(ROOT, "data/db_meta.json")) ? readJSON("data/db_meta.json") : {};
const registry = Object.fromEntries((tables.battery_registry || []).map((r) => [r.asset_id, r]));
const ids = listBatteryIds(tables);

const t0 = Date.now();
const packs = [];
for (const id of ids) {
  const reg = registry[id] || {};
  try {
    const bundle = convertDemo(tables, id, { telemetry: "dense" });
    const report = assess(bundle, assets);
    const disp = disposition(decisionMap, report.decision, report.recommendation?.application ?? null, assets.configs.workloads);
    const ins = insightFor(report, assets.configs, { nRows: bundle.tel.n });
    packs.push(summarizeForFleet(id, reg, bundle, report, disp, assets, compactInsight(ins)));
  } catch (e) {
    packs.push({ asset_id: id, chemistry: reg.chemistry ?? null, application: reg.application || null,
      registry_status: reg.lifecycle_status || null, registry_source: reg.registry_source || null,
      decision: `ERROR: ${e.message}`, disposition: "NO_DECISION", error: e.message });
  }
}
const out = { generated_utc: new Date().toISOString().replace(/\.\d+Z$/, "Z"), db_generated_utc: meta.generated_utc ?? null,
  engine: "web-studio JS ports", telemetry_source: "dense", n: packs.length, packs };
writeFileSync(join(ROOT, "data/fleet_reports.json"), JSON.stringify(out));
const count = (k) => packs.reduce((a, p) => ((a[p[k]] = (a[p[k]] || 0) + 1), a), {});
console.log(`fleet: ${packs.length} packs in ${((Date.now() - t0) / 1000).toFixed(1)} s`);
console.log("dispositions:", JSON.stringify(count("disposition")));
console.log("decisions:", JSON.stringify(packs.reduce((a, p) => { const k = String(p.decision).split(":")[0]; a[k] = (a[k] || 0) + 1; return a; }, {})));
