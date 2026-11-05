// Live assessment: run one bundle or fleet pack through the engine and light up the five stages in order, each with
// its real output. Reference bundles show a parity badge against the Python engine's decision.
import { h, clear, card, banner, pill, icon, attempt } from "../ui/dom.js";
import { loadBundle, convertDemo } from "../engines/contract.js";
import { assess } from "../engines/pipeline.js";
import { insightFor, val } from "../engines/insight.js";
import { FAULTS } from "../engines/esp32sim.js";

const STAGES = [["data_quality", "1 · Data quality"], ["gate", "2 · Safety gate"], ["state", "3 · State & RUL"], ["projection", "4 · Projection"], ["economics", "5 · Economics"]];
const param = (k) => new URLSearchParams(location.hash.split("?")[1] || "").get(k);

function stageOut(report, key) {
  const dq = report.data_quality, g = report.gate, st = report.state, pj = report.projections, e = report.economics;
  const why = (report.rationale || [])[0] || "";
  if (key === "data_quality") {
    const r = dq.readiness, fails = dq.checks.filter((c) => c.status === "fail").map((c) => c.id);
    return { ran: true, tone: r.verdict === "NOT_READY" ? "bad" : r.verdict === "READY" ? "good" : "warn", out: r.verdict,
      detail: `${r.n_pass} pass · ${r.n_warn} warn · ${r.n_fail} fail${fails.length ? ` (${fails.join(", ")})` : ""}` };
  }
  if (key === "gate") return g ? { ran: true, tone: g.verdict === "Pass" ? "good" : g.verdict === "Reject" ? "bad" : "warn", out: g.verdict, detail: (g.reasons || []).join("; ") || "no breach, in distribution" }
    : { ran: false, detail: `not run: ${why}` };
  if (key === "state") return st && st.status === "ok" ? { ran: true, tone: "good", out: `SOH ${val(st.soh).toFixed(1)} %`, detail: st.rul_cycles_reference ? `RUL ${st.rul_cycles_reference.value.toFixed(0)} cycles (${(st.rul_cycles_reference.lower ?? 0).toFixed(0)}-${(st.rul_cycles_reference.upper ?? 0).toFixed(0)})` : "trend-based fade" }
    : { ran: false, detail: `not run: ${st?.reason || why}` };
  if (key === "projection") {
    const k = report.recommendation?.application || Object.keys(pj || {})[0];
    return pj && k ? { ran: true, tone: "good", out: `${val(pj[k].conservative_years)?.toFixed(1) ?? "beyond horizon"} years`, detail: `to the ${pj[k].workload.label} limit (conservative)` } : { ran: false, detail: `not run: ${why}` };
  }
  return e ? { ran: true, tone: report.decision.startsWith("Second-Life") ? "good" : "warn", out: report.decision, detail: why } : { ran: false, detail: `not run: ${why}` };
}

export async function render(root, app) {
  root.append(h("div", { class: "page-head" }, h("h1", {}, "Live assessment"),
    h("p", { class: "muted" }, "Pick a reference bundle or a fleet pack. The five stages light up in order with their real output; stages the engine did not reach stay grey with the reason.")));
  const bundles = await app.fetchJSON("data/bundles.json");
  const groups = {};
  for (const [k, b] of Object.entries(bundles)) (groups[b.group] = groups[b.group] || []).push([k, b]);
  const sel = h("select", { "aria-label": "Scenario" });
  for (const [g, items] of Object.entries(groups)) sel.append(h("optgroup", { label: g }, items.map(([k, b]) => h("option", { value: `b:${k}` }, `${k} - ${b.description.slice(0, 60)}`))));
  const fleetGroup = h("optgroup", { label: "Fleet packs (loading…)" });
  sel.append(fleetGroup);
  app.ensureDemo().then(() => {
    fleetGroup.label = "Fleet packs (dense SYNTHETIC telemetry)";
    for (const r of app.demo.battery_registry || []) fleetGroup.append(h("option", { value: `p:${r.asset_id}` }, r.asset_id));
    const want = param("pack");
    if (want) { sel.value = `p:${want}`; run(); }
  });
  const want = param("bundle");
  if (want && bundles[want]) sel.value = `b:${want}`;
  const stageEls = Object.fromEntries(STAGES.map(([k, l]) => [k, h("div", { class: "stage" }, h("h3", {}, l), h("div", { class: "out" }, "—"), h("small", { class: "muted" }, ""))]));
  const badge = h("div", { class: "row" });
  const after = h("div", { class: "mt" });
  let skip = false;
  const skipBtn = h("button", { class: "btn small", type: "button", onclick: () => { skip = true; } }, "Skip animation");
  root.append(card("Scenario", [h("div", { class: "row" }, sel, h("button", { class: "btn primary", type: "button", onclick: run }, icon("play", 15), "Run"), skipBtn,
    h("a", { class: "btn", href: "#/analyze" }, icon("upload", 15), "Upload a file instead")), badge]),
  h("div", { class: "stages mt" }, Object.values(stageEls)), after,
  card("BMS fault presets (Circuit Studio)", [h("p", { class: "muted" }, "Open the bench with the simulated ESP32 and a fault injected a few seconds in; the alert timeline appears on that page."),
    h("div", { class: "row" }, Object.entries(FAULTS).filter(([k]) => k !== "none").map(([k, l]) => h("a", { class: "btn small", href: `#/bench?preset=${k}` }, l)))], null, "mt"));

  async function run() {
    skip = false;
    const [kind, key] = sel.value.split(/:(.*)/s);
    let report, python = null;
    clear(badge); clear(after);
    for (const el of Object.values(stageEls)) { el.className = "stage"; el.children[1].textContent = "…"; el.children[2].textContent = ""; }
    const res = attempt("Assessment", () => {
      if (kind === "b") {
        const b = bundles[key];
        python = b.python_decision;
        const rows = b.rows.map((r) => Object.fromEntries(b.columns.map((c, i) => [c, r[i]])));
        return assess(loadBundle(b.metadata, rows), app.assets);
      }
      return assess(convertDemo(app.demo, key, { telemetry: "dense" }), app.assets);
    });
    if (res instanceof Node) { after.append(res); return; }
    report = res;
    const t0 = performance.now();
    for (const [k] of STAGES) {
      const o = stageOut(report, k);
      const el = stageEls[k];
      el.className = `stage ${o.ran ? `lit ${o.tone}` : "skipped"}`;
      el.children[1].textContent = o.ran ? o.out : "not run";
      el.children[2].textContent = o.detail;
      if (!skip && performance.now() - t0 < 3500) await new Promise((r) => setTimeout(r, 650));
    }
    badge.append(pill(`Decision: ${report.decision}`, report.decision.startsWith("Second-Life") ? "good" : "warn"));
    if (python) badge.append(pill(`Python reference: ${python} - ${python === report.decision ? "match" : "MISMATCH"}`, python === report.decision ? "good" : "bad"));
    const ins = insightFor(report, app.assets.configs, { withRobustness: false });
    after.append(card("Top reasons", h("ul", {}, ins.reasons.top.map((r) => h("li", {}, h("b", {}, r.title), ": ", r.text)))));
    if (kind === "p") after.append(h("p", {}, h("a", { href: `#/pack?id=${encodeURIComponent(key)}` }, `Open ${key} in detail →`)));
  }
  if (want && bundles[want]) run();
  if (!want && !param("pack")) sel.selectedIndex = 0;
  if (!want && !param("pack")) { /* waits for the user */ }
  void banner;
}
