// Module worker: builds the fleet in the background when data/fleet_reports.json is not available.
import { parseCSV } from "../lib/csv.js";
import { listBatteryIds } from "../engines/bms.js";
import { convertDemo } from "../engines/contract.js";
import { assess, loadAssets } from "../engines/pipeline.js";
import { insightFor } from "../engines/insight.js";
import { disposition } from "../lib/disposition.js";
import { summarizeForFleet, compactInsight } from "../lib/fleet.js";

const url = (p) => new URL(`../../../${p}`, import.meta.url);
const json = async (p) => (await fetch(url(p))).json();
const csv = async (t) => parseCSV(await (await fetch(url(`data/demo/${t}.csv`))).text()).rows;

(async () => {
  try {
    const assets = await loadAssets(json);
    const names = ["battery_asset", "battery_registry", "telemetry", "telemetry_dense", "health_history", "safety_events"];
    const tables = Object.fromEntries(await Promise.all(names.map(async (t) => [t, await csv(t)])));
    const dmap = await json("data/decision_map.json");
    const reg = Object.fromEntries(tables.battery_registry.map((r) => [r.asset_id, r]));
    const ids = listBatteryIds(tables);
    const packs = [];
    for (const [i, id] of ids.entries()) {
      try {
        const b = convertDemo(tables, id, { telemetry: "dense" });
        const r = assess(b, assets);
        const d = disposition(dmap, r.decision, r.recommendation?.application ?? null, assets.configs.workloads);
        packs.push(summarizeForFleet(id, reg[id] || {}, b, r, d, assets, compactInsight(insightFor(r, assets.configs, { nRows: b.tel.n }))));
      } catch (e) {
        packs.push({ asset_id: id, decision: `ERROR: ${e.message}`, disposition: "NO_DECISION", error: e.message });
      }
      postMessage({ type: "progress", done: i + 1, total: ids.length });
    }
    postMessage({ type: "done", result: { generated_utc: new Date().toISOString(), engine: "web-studio JS ports (worker)", telemetry_source: "dense", n: packs.length, packs } });
  } catch (e) {
    postMessage({ type: "error", message: String(e?.message || e) });
  }
})();
