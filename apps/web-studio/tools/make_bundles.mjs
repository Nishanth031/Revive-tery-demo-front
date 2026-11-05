// Copy the example bundles (clean synthetic packs, gate cases and every injected data-quality fault) out of the
// golden file into data/bundles.json, so the Data-quality lab can run the browser engine on them.
// Run: node tools/make_bundles.mjs   (after python tools/make_golden.py)
import { readFileSync, writeFileSync } from "node:fs";

const cases = JSON.parse(readFileSync("tests/golden/pipeline_cases.json", "utf-8"));
const DESCRIPTIONS = {
  demo_pack: "The REVIVE-TERY demo pack (database tables converted by convert-demo)",
  clean_lfp: "Clean synthetic LFP pack (examples/clean_synthetic_bundle)",
  clean_nmc: "Clean synthetic NMC pack",
  gate_undervoltage: "One row below the LFP cell-voltage floor",
  gate_resistance_double: "Latest resistance test at 2.1x the first",
  gate_open_event: "An open HIGH-severity thermal safety event",
  gate_spiky: "Four large voltage spikes",
};
const out = {};
for (const [name, c] of Object.entries(cases)) {
  const t = c.bundle.telemetry;
  const cols = Object.keys(t[0]);
  out[name] = {
    description: DESCRIPTIONS[name] || `Clean LFP pack with an injected fault: ${name.replace(/^fault_/, "").replace(/_/g, " ")}`,
    group: name.startsWith("fault_") ? "Injected data-quality faults" : name.startsWith("gate_") ? "Safety-gate cases" : "Reference bundles",
    metadata: c.bundle.metadata,
    columns: cols,
    rows: t.map((r) => cols.map((k) => r[k])),
    ignored_columns: c.bundle.ignored_columns,
    python_decision: c.report.decision,
  };
}
writeFileSync("data/bundles.json", JSON.stringify(out));
console.log(`wrote data/bundles.json: ${Object.keys(out).length} bundles, ${(JSON.stringify(out).length / 1024).toFixed(0)} KB`);
