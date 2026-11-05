// Command Center data layer: the precomputed fleet, filters, summary, robustness, break-even and the fleet plan.
import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { ROOT, readJSON, golden, assets, bundleFromGolden } from "./helpers.mjs";
import { filterPacks, fleetSummary, page, planInput, DISPOSITIONS, summarizeForFleet, compactInsight } from "../assets/js/lib/fleet.js";
import { assign, robustness, breakEven, insightFor, reroute } from "../assets/js/engines/insight.js";
import { assess } from "../assets/js/engines/pipeline.js";

const have = existsSync(join(ROOT, "data/fleet_reports.json"));
const fleet = () => readJSON("data/fleet_reports.json");

test("fleet file: 60+ packs, every record has a disposition and the summary adds up", { skip: !have && "run just web-regen" }, () => {
  const { packs } = fleet();
  assert.ok(packs.length >= 60);
  for (const p of packs) assert.ok(DISPOSITIONS.includes(p.disposition), p.asset_id);
  const s = fleetSummary(packs);
  assert.equal(Object.values(s.by_disposition).reduce((a, b) => a + b, 0), packs.length);
  const f = s.funnel.map(([, n]) => n);
  for (let i = 1; i < f.length - 1; i++) assert.ok(f[i] <= f[i - 1], "funnel narrows");
  assert.equal(s.funnel.at(-1)[1], s.by_disposition.REUSE + s.by_disposition.REPURPOSE);
  assert.ok(s.test_cases >= 6);
});

test("filters, search, sort and paging", { skip: !have && "run just web-regen" }, () => {
  const { packs } = fleet();
  const lfp = filterPacks(packs, { chem: "LFP" });
  assert.ok(lfp.length && lfp.every((p) => p.chemistry === "LFP"));
  assert.ok(filterPacks(packs, { disp: "RECYCLE" }).every((p) => p.disposition === "RECYCLE"));
  assert.deepEqual(filterPacks(packs, { q: "flaw" }).map((p) => p.asset_id).sort(), packs.filter((p) => /FLAW/.test(p.asset_id)).map((p) => p.asset_id).sort());
  assert.ok(filterPacks(packs, { source: "test" }).every((p) => p.test_case));
  const bySoh = filterPacks(packs, { sort: "soh", dir: "desc" }).map((p) => p.soh ?? p.soh_test ?? -Infinity);
  for (let i = 1; i < bySoh.length; i++) assert.ok(bySoh[i] <= bySoh[i - 1]);
  assert.equal(page(packs, 1, 25).length, Math.min(25, packs.length));
  assert.equal(page(packs, 99, 25).length, 0);
});

test("fleet record from a real report (summarizeForFleet + compactInsight)", async () => {
  const A = await assets();
  const g = golden("pipeline_cases.json").clean_lfp;
  const b = await bundleFromGolden(g.bundle);
  const r = assess(b, A);
  const rec = summarizeForFleet("SYNTH-CLEAN-001", {}, b, r, { code: "REPURPOSE", label: "Repurpose" }, A, compactInsight(insightFor(r, A.configs, { nRows: b.tel.n })));
  assert.equal(rec.disposition, "REPURPOSE");
  assert.equal(rec.best_application, "residential_storage");
  assert.ok(rec.net_value > rec.recycle_value);
  assert.ok(rec.insight.confidence.score_0_100 > 0 && rec.insight.reasons.length <= 5);
});

test("robustness for two packs and the tariff break-even flip", async () => {
  const A = await assets();
  for (const name of ["clean_lfp", "clean_nmc"]) {
    const r = assess(await bundleFromGolden(golden("pipeline_cases.json")[name].bundle), A);
    const rob = robustness(r, A.configs);
    assert.ok(rob.share_same_decision > 0 && rob.share_same_decision < 1, `${name} share ${rob.share_same_decision}`);
    const be = breakEven(r, A.configs, "tariff");
    assert.ok(be.value > 0.06 && be.value < 0.08);
    assert.equal(reroute(r, A.configs, { tariff: be.value + 0.01 }).decision.split(":")[0], "Second-Life");
    assert.equal(reroute(r, A.configs, { tariff: be.value - 0.01 }).decision.split(":")[0], "Recycle");
  }
});

test("fleet plan on the real fleet never exceeds the demand limits", { skip: !have && "run just web-regen" }, () => {
  const { packs } = fleet();
  const limits = { residential_storage: { packs: 5 }, commercial_peak_shaving: { packs: 3, kwh: 150 }, telecom_backup: { packs: 2 }, low_speed_ev: { packs: 2 } };
  const res = assign(planInput(packs), limits);
  for (const [a, u] of Object.entries(res.by_application)) {
    assert.ok(u.packs <= limits[a].packs, a);
    if (limits[a].kwh) assert.ok(u.kwh <= limits[a].kwh + 1e-9, a);
  }
  const eligible = new Set(packs.filter((p) => p.disposition === "REUSE" || p.disposition === "REPURPOSE").map((p) => p.asset_id));
  assert.ok(res.plan.every((x) => eligible.has(x.asset_id)));
  assert.ok(res.total_value >= res.greedy_value - 1e-9);
});
