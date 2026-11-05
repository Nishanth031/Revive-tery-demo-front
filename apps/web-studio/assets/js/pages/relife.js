// ReLife BMS Studio (the PySide6 prototype's engine): catalog, adapters, scenario evaluation and the virtual pulse test.
import { h, clear, card, kpi, banner, field, select, numberInput, num, table, pill, decisionCard, kv, icon, download, collapsible } from "../ui/dom.js";
import { lineChart } from "../ui/charts.js";
import * as R from "../engines/relife.js";
import { storage } from "../app.js";

const EDIT_FIELDS = [["name", "Name", "text"], ["chemistry", "Chemistry", "text"], ["series_cells", "Series cells"], ["parallel_cells", "Parallel cells"],
  ["nominal_voltage_v", "Nominal voltage (V)"], ["capacity_value", "Capacity"], ["capacity_unit", "Unit", ["Ah", "Wh", "kWh"]],
  ["charge_limit_a", "Charge limit (A)"], ["discharge_limit_a", "Discharge limit (A)"], ["measured_capacity_ah", "Measured capacity (Ah)"],
  ["measured_voltage_v", "Measured voltage (V)"], ["measured_temperature_c", "Measured temperature (°C)"], ["soh_pct", "Profile SOH (%)"],
  ["initial_soc_pct", "Initial SOC (%)"], ["internal_resistance_mohm", "Internal resistance (mΩ)"],
  ["condition", "Condition", ["Unknown", "Good", "Used", "Damaged - do not test"]]];

export function render(root, app) {
  const catalog = app.relife.catalog.map(R.profileFromDict);
  const custom = (storage.get("relife-custom", []) || []).map(R.profileFromDict);
  const all = () => [...custom, ...catalog];
  let profile = { ...all()[0] };
  let adapterId = "V-LI-3-16", scenario = "Pulse load", mode = "Discharge", evalScenario = "Normal";
  root.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "ReLife BMS Studio"),
    h("p", {}, "The ReLife prototype's rule-based BMS simulator: check a battery profile against a virtual monitoring adapter, evaluate a scenario, and run a 30-second synthetic pulse test that estimates SOH from the voltage sag."))));
  root.append(banner("warn", "Synthetic virtual pulse.", R.SOURCE_LABEL + ". No physical device is connected. Verdicts are screening flags only."));
  const left = h("div", { class: "stack" });
  const right = h("div", { class: "stack" });
  root.append(left, h("div", { class: "mt" }, right));

  function drawLeft() {
    clear(left);
    left.append(card("Profile", [
      field("Catalog", select(all().map((p) => [p.id, `${p.name}${p.source_kind === "user_entered" ? " (yours)" : ""}`]), profile.id, (v) => { profile = { ...all().find((p) => p.id === v) }; drawLeft(); drawRight(); })),
      h("p", { class: "muted mt", style: { fontSize: "12px" } }, `${profile.source_title}${profile.license ? ` · ${profile.license}` : ""}`, profile.source_url ? [" · ", h("a", { href: profile.source_url, target: "_blank", rel: "noopener" }, "source")] : null),
      h("div", { class: "form-grid mt" }, EDIT_FIELDS.map(([k, l, t]) => field(l, Array.isArray(t) ? select(t, profile[k], (v) => { profile[k] = v; drawRight(); })
        : t === "text" ? h("input", { type: "text", value: profile[k] ?? "", onchange: (e) => { profile[k] = e.target.value || (k === "chemistry" ? "Unknown" : ""); drawRight(); } })
          : numberInput(profile[k], (v) => { profile[k] = v; drawRight(); })))),
      h("div", { class: "row mt" },
        h("button", { class: "btn", onclick: () => {
          const id = profile.source_kind === "user_entered" && custom.some((c) => c.id === profile.id) ? profile.id : `USER-${Date.now().toString(36).toUpperCase()}`;
          const saved = R.profileFromDict({ ...profile, id, source_kind: "user_entered", source_title: "User entry", license: "User-provided" });
          const i = custom.findIndex((c) => c.id === id);
          if (i >= 0) custom[i] = saved; else custom.unshift(saved);
          storage.set("relife-custom", custom);
          profile = { ...saved }; drawLeft(); drawRight();
        } }, "Save as my profile"),
        h("button", { class: "btn", onclick: () => download(`${profile.id}.json`, JSON.stringify(profile, null, 2)) }, icon("download", 14), "JSON"))]));
  }

  function drawRight() {
    clear(right);
    const p = R.profileFromDict(profile);
    const [status, missing] = R.completeness(p);
    right.append(h("div", { class: "row" }, pill(status, missing.length ? "warn" : "good"), missing.length ? h("span", { class: "muted" }, `missing: ${missing.join(", ")}`) : null));
    // adapters
    right.append(card("Virtual adapters", table([{ key: "name", label: "Adapter" }, { label: "Series", render: (a) => `${a.min_series}–${a.max_series}S` }, { label: "Max V", render: (a) => a.max_stack_voltage_v, num: true },
      { label: "Fits this profile", render: (a) => { const [ok, err, warn] = R.checkCompatibility(p, a); return h("span", {}, pill(ok ? "compatible" : "blocked", ok ? "good" : "bad"), " ", h("small", { class: "muted" }, [...err, ...warn].join("; "))); } },
      { label: "", render: (a) => h("button", { class: `btn small ${a.id === adapterId ? "primary" : ""}`, onclick: () => { adapterId = a.id; drawRight(); } }, a.id === adapterId ? "Selected" : "Use") }], R.ADAPTERS)));
    const ad = R.ADAPTERS.find((a) => a.id === adapterId);
    let ev;
    try { ev = R.evaluate(p, ad, evalScenario); } catch (e) { console.error(e); right.append(banner("bad", "Monitor evaluation failed.", e.message)); return; }
    right.append(card("Monitor evaluation", [h("div", { class: "row mb" }, field("Scenario", select(R.EVALUATE_SCENARIOS, evalScenario, (v) => { evalScenario = v; drawRight(); })),
      pill(ev.status, { READY: "good", REVIEW: "warn", FAULT: "bad", BLOCKED: "bad" }[ev.status]), pill(ev.state, "neutral"), pill(ev.protection, "neutral")),
      kv([["SOC (illustrative)", ev.soc_pct === null ? "—" : `${ev.soc_pct} %`], ["Profile SOH", ev.soh_pct === null ? "—" : `${ev.soh_pct} %`],
        ["Errors", ev.errors.join("; ") || "none"], ["Faults", ev.faults.join("; ") || "none"], ["Warnings", ev.warnings.join("; ") || "none"]])]));
    // pulse test
    const ctl = h("div", { class: "row mb" }, field("Pulse scenario", select(R.SCENARIOS, scenario, (v) => { scenario = v; drawRight(); })),
      field("Mode", select(["Discharge", "Charge"], mode, (v) => { mode = v; drawRight(); })));
    let res;
    try { res = R.stressTest(p, scenario, { mode }); } catch (e) { right.append(card("Pulse test", [ctl, banner("bad", "", e.message)])); return; }
    const sum = R.screeningSummary(p, res);
    const t = res.points.map((q) => q.time_s);
    right.append(card("30 s virtual pulse test", [ctl,
      decisionCard("Screening verdict", sum.label, [sum.use, sum.reason], { good: "good", warning: "warn", serious: "bad", critical: "bad" }[sum.tone]),
      h("div", { class: "grid g4 mt" }, kpi("Condition", res.condition), kpi("Pulse SOH proxy", res.points.at(-1).soh_pct === null ? "—" : `${num(res.points.at(-1).soh_pct, 1)} %`, res.soh_source),
        kpi("Resistance", `${num(res.resistance_mohm, 2)} mΩ`, res.resistance_source), kpi("Voltage sag", res.loaded_voltage_drop_pct === null ? "—" : `${num(res.loaded_voltage_drop_pct, 2)} %`, `${num(res.loaded_voltage_drop_v, 3)} V`)),
      h("div", { class: "grid g2 mt" },
        lineChart({ series: [{ name: "terminal voltage", x: t, y: res.points.map((q) => q.voltage_v) }], xLabel: "s", yLabel: "V", height: 190 }),
        lineChart({ series: [{ name: "current", x: t, y: res.points.map((q) => q.current_a), color: "--c2" }, { name: "demand", x: t, y: res.points.map((q) => q.demand_current_a), color: "--c3", dash: "5 4" }], xLabel: "s", yLabel: "A", height: 190 })),
      res.faults.length ? banner("bad", "Modeled faults:", res.faults.join("; ")) : banner("good", "", res.risk),
      h("p", { class: "muted", style: { fontSize: "12px" } }, `Use recommendation: ${res.use_recommendation}. Data still missing: ${sum.gaps.join(", ") || "none"}. ${res.voltage_source}; ${res.soc_source}.`)]));
  }
  drawLeft();
  drawRight();
  if (app.relife.research_note) root.append(collapsible("About the catalog", h("p", { class: "muted", style: { margin: 0 } }, app.relife.research_note), false, "mt"));
}
