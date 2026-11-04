// Physics projection sandbox: the ML hand-over (SOH now, remaining reference cycles) projected under a workload.
import { h, clear, card, kpi, banner, field, select, num, prov, table, collapsible } from "../ui/dom.js";
import { project, stressFactor, nominalParams } from "../engines/physics.js";
import { projectionChart } from "../ui/report.js";

export function render(root, app) {
  const ph = app.assets.configs.physics;
  const wls = app.assets.configs.workloads.workloads;
  const st = { soh: 92, point: 600, lower: 420, upper: 820, preset: "residential_storage", w: { ...wls.residential_storage } };
  root.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Physics projection"),
    h("p", {}, "Below the ML training range the engine projects with physics: a double-exponential fade anchored so it reaches 80 % SOH exactly at the ML-predicted remaining cycles under reference conditions (30 °C, 100 % DoD, 4 C), then scaled to your workload with Arrhenius, depth-of-discharge and C-rate stress factors, plus √time calendar ageing."))));
  root.append(banner("warn", "Projected (physics model).", "Parameters are literature-informed assumptions (configs/physics.yaml). The Monte Carlo band is assumption-conditional, not a measured interval."));
  const controls = h("div", { class: "stack", style: { gap: "10px" } });
  const out = h("div", { class: "stack" });
  root.append(h("div", { class: "grid g-side" }, card("Inputs", controls), out));

  const slider = (label, get, set, min, max, step, fmt = (v) => v) => {
    const o = h("output", {}, fmt(get()));
    return field(label, h("div", { class: "range-row" }, h("input", { type: "range", min, max, step, value: get(), oninput: (e) => { set(Number(e.target.value)); o.textContent = fmt(get()); draw(); } }), o));
  };
  function drawControls() {
    clear(controls).append(
      h("h4", {}, "ML hand-over"),
      slider("SOH now (%)", () => st.soh, (v) => { st.soh = v; }, 81, 100, 0.5),
      slider("Remaining reference cycles (point)", () => st.point, (v) => { st.point = v; st.lower = Math.min(st.lower, v); st.upper = Math.max(st.upper, v); }, 50, 3000, 10),
      slider("CV+ lower bound", () => st.lower, (v) => { st.lower = Math.min(v, st.point); }, 10, 3000, 10),
      slider("CV+ upper bound", () => st.upper, (v) => { st.upper = Math.max(v, st.point); }, 50, 4000, 10),
      h("h4", { class: "mt" }, "Workload ", prov("assumed")),
      field("Preset", select(Object.entries(wls).map(([k, w]) => [k, w.label]), st.preset, (v) => { st.preset = v; st.w = { ...wls[v] }; drawControls(); draw(); })),
      slider("Daily depth of discharge", () => st.w.daily_dod, (v) => { st.w.daily_dod = v; }, 0.1, 1, 0.05, (v) => `${Math.round(v * 100)} %`),
      slider("Ambient (°C)", () => st.w.ambient_c, (v) => { st.w.ambient_c = v; }, 0, 50, 1),
      slider("C-rate", () => st.w.c_rate, (v) => { st.w.c_rate = v; }, 0.1, 4, 0.1),
      slider("Cycles per day", () => st.w.cycles_per_day, (v) => { st.w.cycles_per_day = v; }, 0.05, 3, 0.05),
      slider("Application limit (SOH %)", () => st.w.min_soh_pct, (v) => { st.w.min_soh_pct = v; }, 40, 80, 1));
  }
  function draw() {
    clear(out);
    let p;
    try { p = project(ph, app.assets.mcParams, st.soh, { point: st.point, lower: st.lower, upper: st.upper }, st.w, app.assets.stateModel.validation.measured_coverage); } catch (e) {
      console.error(e); out.append(banner("bad", "The physics projection failed.", e.message)); return;
    }
    const life = p.years_to_application_limit;
    const yrs = (t) => (t.value === null ? "> 20 y" : `${num(t.value, 1)} y`);
    out.append(h("div", { class: "grid g4" },
      kpi("Conservative life", yrs(p.conservative_years), "min of ML lower path and MC 5th pct"),
      kpi("Central path", yrs(life.central)), kpi("Knee scenario", yrs(life.knee_scenario), "earlier, sharper knee"),
      kpi("Stress factor", num(p.stress_factor_nominal.value, 3), "reference cycles per real cycle")));
    out.append(card("Projected SOH", projectionChart(p, st.w.min_soh_pct)));
    const p0 = nominalParams(ph);
    const ref = ph.reference;
    const parts = [
      ["Temperature (Arrhenius)", Math.exp(p0.activation_energy_j_mol / 8.314 * (1 / (ref.temperature_c + 273.15 + p0.cell_temperature_rise_c_per_c_rate * ref.c_rate) - 1 / (st.w.ambient_c + 273.15 + p0.cell_temperature_rise_c_per_c_rate * st.w.c_rate)))],
      ["Depth of discharge", (st.w.daily_dod / ref.daily_dod) ** p0.k_dod],
      ["C-rate", Math.exp(p0.c_rate_coefficient_j_mol * (st.w.c_rate - ref.c_rate) / (8.314 * (st.w.ambient_c + 273.15 + p0.cell_temperature_rise_c_per_c_rate * st.w.c_rate)))],
    ];
    out.append(collapsible("Stress factors and years per path", h("div", { class: "grid g2" },
      h("div", {}, h("h3", {}, "Stress factors (nominal parameters)"), table([{ key: 0, label: "Factor" }, { label: "Multiplier", render: (r) => num(r[1], 4), num: true }], parts),
        h("p", { class: "muted mt", style: { fontSize: "12px" } }, `Product = ${num(stressFactor(ph, p0, st.w), 4)}.`)),
      h("div", {}, h("h3", {}, "Years to the application limit"), table([{ key: "k", label: "Path" }, { label: "Years", render: (r) => yrs(r.v), num: true }],
        Object.entries(life).map(([k, v]) => ({ k: k.replace(/_/g, " "), v })))))));
    out.append(collapsible("Parameters and sources", table([{ key: "k", label: "Parameter" }, { key: "n", label: "Nominal", num: true }, { key: "prior", label: "Monte Carlo prior" }, { key: "src", label: "Source" }],
      Object.entries(ph.parameters).map(([k, v]) => ({ k, n: v.nominal, prior: `${v.prior.dist} ${JSON.stringify(Object.fromEntries(Object.entries(v.prior).filter(([q]) => q !== "dist")))}`, src: v.source })))));
  }
  drawControls();
  draw();
}
