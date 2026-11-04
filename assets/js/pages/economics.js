// Economics: what-if for one pack and the illustrative price-sensitivity sweep.
import { h, clear, card, kpi, banner, field, select, num, usd, table, tabs, pill } from "../ui/dom.js";
import { bars } from "../ui/charts.js";
import { recycleValue, secondLifeValue, sweep, referenceProjection, metalPricesUsdPerKg } from "../engines/econ.js";

export function render(root, app) {
  const cfg = app.assets.configs.economics, ph = app.assets.configs.physics, wl = app.assets.configs.workloads.workloads;
  const st = { chem: "NMC", kwh: 60, soh: 85, rul: 400, valueMult: 1, metalMult: 1 };
  root.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Economics"),
    h("p", {}, "Second-life value is the discounted energy a pack delivers, capped at what new storage giving the same service would cost (the Buy-New benchmark), minus testing, refurbishment, logistics and installation, plus recycling it at the end. Recycling now is recovered metal value minus processing."))));
  root.append(banner("warn", "Placeholder inputs.", `Several cost and tariff inputs are placeholders: ${cfg.second_life.value_per_kwh_delivered.status === "PLACEHOLDER" ? "energy value, " : ""}testing, refurbishment, logistics, installation, processing and payable fractions. Metal prices and the new-storage cost are sourced (see below).`));
  const controls = h("div", { class: "stack", style: { gap: "10px" } });
  const out = h("div", { class: "stack" });
  root.append(h("div", { class: "grid g-side" }, card("What-if (residential storage workload)", controls), out));
  const slider = (label, key, min, max, step, fmt = (v) => v) => {
    const o = h("output", {}, fmt(st[key]));
    return field(label, h("div", { class: "range-row" }, h("input", { type: "range", min, max, step, value: st[key], oninput: (e) => { st[key] = Number(e.target.value); o.textContent = fmt(st[key]); draw(); } }), o));
  };
  controls.append(field("Chemistry", select(["LFP", "NMC", "NCA"], st.chem, (v) => { st.chem = v; draw(); })),
    slider("Pack energy (kWh)", "kwh", 5, 120, 1), slider("SOH (%)", "soh", 81, 99, 1), slider("Remaining reference cycles (ML)", "rul", 50, 2000, 10),
    slider("Energy value ×", "valueMult", 0.25, 3, 0.25, (v) => `${v}×`), slider("Metal prices ×", "metalMult", 0.25, 12, 0.25, (v) => `${v}×`));

  function draw() {
    clear(out);
    const ref = referenceProjection(ph, wl, { soh: st.soh / 100, rul: st.rul });
    const m = { nickel: st.metalMult, cobalt: st.metalMult, lithium: st.metalMult };
    const rec = recycleValue(st.chem, st.kwh, cfg, m);
    const sl = secondLifeValue(st.kwh, st.soh / 100, ref.sohByYear, ref.life, ref.w, rec.net_usd, cfg, st.valueMult);
    const win = sl.net_usd > rec.net_usd;
    out.append(h("div", { class: "grid g4" },
      kpi("Second-life net", usd(sl.net_usd), `${num(sl.years_used, 1)} years of service`), kpi("Recycle now", usd(rec.net_usd), `${num(rec.pack_kg, 0)} kg pack`),
      kpi("Decision", pill(win ? "Second-Life" : "Recycle", win ? "good" : "bad"), "illustrative"), kpi("Buy-New cap", usd(sl.buy_new_cap_usd), sl.capped ? "value was capped" : "not binding")));
    out.append(h("div", { class: "grid g2" },
      card("Second-life value", bars([{ label: "Energy value (discounted)", value: sl.gross_energy_value_usd, color: "--c1" }, { label: "Buy-New cap", value: sl.buy_new_cap_usd, color: "--c2" },
        { label: "Upfront costs", value: -sl.upfront_cost_usd, color: "--c3" }, { label: "Recycle at end (PV)", value: sl.end_of_life_recycle_pv_usd, color: "--c4" }, { label: "Net", value: sl.net_usd, color: "--c5" }], usd)),
      card("Recycle now", bars([{ label: "Nickel", value: rec.nickel_usd }, { label: "Cobalt", value: rec.cobalt_usd }, { label: "Lithium", value: rec.lithium_usd },
        { label: "Processing", value: -rec.processing_cost_usd, color: "--c3" }, { label: "Net", value: rec.net_usd, color: "--c5" }], usd))));
  }
  draw();
  const prices = metalPricesUsdPerKg(cfg);
  const p = cfg.recycling.prices_usd_per_tonne;
  root.append(card("Sourced prices", table([{ key: "k", label: "Input" }, { key: "v", label: "Value", num: true }, { key: "s", label: "Source" }], [
    { k: "Nickel", v: `$${num(p.nickel.value, 0)}/t (${num(prices.nickel, 2)} $/kg)`, s: p.nickel.source },
    { k: "Cobalt", v: `$${num(p.cobalt.value, 0)}/t`, s: p.cobalt.source },
    { k: "Lithium carbonate", v: `$${num(p.lithium_carbonate.value, 0)}/t`, s: p.lithium_carbonate.source },
    { k: "New storage, installed", v: `$${cfg.buy_new_benchmark.installed_system_usd_per_kwh.value}/kWh`, s: cfg.buy_new_benchmark.installed_system_usd_per_kwh.source },
    { k: "Stationary pack price", v: `$${cfg.buy_new_benchmark.stationary_pack_usd_per_kwh.value}/kWh`, s: cfg.buy_new_benchmark.stationary_pack_usd_per_kwh.source }]), null, "mt"));

  const sw = sweep(cfg, ph, wl);
  root.append(card("Price sensitivity: where does the decision flip?", [
    banner("info", "Illustrative.", `${sw.label}. Reference: ${sw.reference_battery.pack_kwh} kWh, SOH ${sw.reference_battery.soh_pct} %, residential workload, ${sw.reference_battery.projected_years} projected years.`),
    tabs(Object.entries(sw.chemistries).map(([chem, r]) => ({ id: chem, label: chem, render: () => {
      const vms = [...new Set(r.grid.map((g) => g.energy_value_multiplier))];
      const mms = [...new Set(r.grid.map((g) => g.metal_price_multiplier))];
      return h("div", {}, h("p", { class: "muted" }, `Composition: ${r.composition_status}. Rows: energy value multiplier; columns: metal price multiplier. Cells show second-life minus recycle (USD).`),
        h("div", { class: "table-wrap" }, h("table", { class: "heat" }, h("thead", {}, h("tr", {}, h("th", {}, "value × \\ metal ×"), mms.map((m) => h("th", { class: "num" }, `${m}×`)))),
          h("tbody", {}, vms.map((vm) => h("tr", {}, h("th", {}, `${vm}×`), mms.map((mm) => {
            const g = r.grid.find((x) => x.energy_value_multiplier === vm && x.metal_price_multiplier === mm);
            return h("td", { class: g.decision === "Second-Life" ? "sl" : "rc", title: `${g.decision}: second life ${usd(g.second_life_net_usd)} vs recycle ${usd(g.recycle_net_usd)}` }, usd(g.second_life_net_usd - g.recycle_net_usd));
          })))))),
        h("div", { class: "legend" }, h("span", {}, h("i", { class: "band", style: { background: "var(--good)" } }), "Second-Life wins"), h("span", {}, h("i", { class: "band", style: { background: "var(--warn)" } }), "Recycle wins")));
    } }))),
    h("p", { class: "muted mt", style: { fontSize: "12px" } }, sw.note)], null, "mt"));
}
