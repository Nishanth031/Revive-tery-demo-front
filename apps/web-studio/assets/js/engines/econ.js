// Economics router (port of revive_ml/econ/router.py and sensitivity.py): Second-Life per application vs
// Recycle, with second-life value capped at the cost of buying new storage for the same service.

import { tag, comma0, f } from "../lib/provenance.js";
import * as np from "../lib/np.js";
import { nominalParams, trajectory, yearsTo } from "./physics.js";

export const METALS = ["nickel", "cobalt", "lithium"];
const v = (x) => Number(x.value);

export function metalPricesUsdPerKg(cfg, mult = {}) {
  const p = cfg.recycling.prices_usd_per_tonne;
  const liFrac = v(cfg.recycling.lithium_carbonate_li_fraction);
  return {
    nickel: v(p.nickel) / 1000 * (mult.nickel ?? 1.0),
    cobalt: v(p.cobalt) / 1000 * (mult.cobalt ?? 1.0),
    lithium: v(p.lithium_carbonate) / 1000 / liFrac * (mult.lithium ?? 1.0), // lithium content priced via Li2CO3
  };
}

export function recycleValue(chemistry, packKwh, cfg, mult = {}) {
  const rc = cfg.recycling;
  const comp = rc.composition_kg_per_kwh[chemistry];
  const prices = metalPricesUsdPerKg(cfg, mult);
  const byMetal = Object.fromEntries(METALS.map((m) => [m, comp[m] * packKwh * prices[m] * rc.recovery_rate[m] * rc.payable_fraction[m]]));
  const packKg = rc.pack_kg_per_kwh[chemistry] * packKwh;
  const cost = v(rc.processing_cost_usd_per_kg_pack) * packKg;
  const total = METALS.reduce((s, m) => s + byMetal[m], 0);
  return { ...Object.fromEntries(METALS.map((m) => [`${m}_usd`, byMetal[m]])), processing_cost_usd: cost, net_usd: total - cost, pack_kg: packKg };
}

export function secondLifeValue(packKwh, sohNow, sohByYear, years, w, recycleNet, cfg, valueMult = 1.0) {
  const sl = cfg.second_life, bn = cfg.buy_new_benchmark;
  const r = v(cfg.discount_rate);
  years = Math.min(years, v(sl.max_service_years));
  const price = v(sl.value_per_kwh_delivered) * valueMult;
  const cycPerYear = w.cycles_per_day * 365;
  const mode = w.valuation_mode || "energy_arbitrage";
  let gross = 0.0, energyPv = 0.0;
  const nFull = Math.floor(years);
  for (let y = 0; y <= nFull; y++) {
    const frac = y < nFull ? 1.0 : years - nFull;
    if (frac <= 0) break;
    const soh = sohByYear[Math.min(y, sohByYear.length - 1)];
    const e = packKwh * soh * w.daily_dod * cycPerYear * v(sl.round_trip_efficiency) * frac;
    const disc = (1 + r) ** -(y + 0.5);
    // reuse in a vehicle: each year of service avoids that year's share of a new pack of the same usable energy
    if (mode === "avoided_new_pack") gross += v(bn.new_ev_pack_usd_per_kwh) * packKwh * soh / v(bn.new_ev_pack_life_years) * frac * disc;
    else gross += e * price * disc;
    energyPv += e * disc;
  }
  const avoided = mode === "avoided_new_pack";          // the buy-new storage cap applies to stationary options only
  const cap = avoided ? null : v(bn.installed_system_usd_per_kwh) * packKwh * sohNow * Math.min(1.0, years / v(bn.new_system_life_years));
  const value = avoided ? gross : Math.min(gross, cap);
  const upfront = packKwh * ["testing_usd_per_kwh", "refurbishment_usd_per_kwh", "logistics_usd_per_kwh", "installation_usd_per_kwh"]
    .reduce((s, k) => s + v(sl[k]), 0);
  const later = recycleNet * (1 + r) ** -years;
  return { years_used: years, gross_energy_value_usd: gross, buy_new_cap_usd: cap, capped: avoided ? false : gross > cap, upfront_cost_usd: upfront,
    end_of_life_recycle_pv_usd: later, net_usd: value - upfront + later,
    lcos_usd_per_kwh: energyPv > 0 ? upfront / energyPv : Infinity, valuation_mode: mode };
}

/** a copy of the economics config whose tariff is the selected region's (null/global_default: unchanged) */
export function withRegion(cfg, region) {
  if (!region) return cfg;
  const regions = cfg.second_life.regions || {};
  if (!(region in regions)) throw new Error(`unknown region '${region}'; choose one of ${Object.keys(regions).sort().join(", ")}`);
  const out = structuredClone(cfg);
  out.second_life.value_per_kwh_delivered = { ...regions[region] };
  return out;
}

export function placeholders(cfg, path = "") {
  const out = [];
  if (cfg && typeof cfg === "object" && !Array.isArray(cfg)) {
    if (cfg.status === "PLACEHOLDER") out.push(path.replace(/^\.+|\.+$/g, ""));
    for (const [k, x] of Object.entries(cfg)) out.push(...placeholders(x, `${path}.${k}`));
  }
  return out;
}
const pySorted = (a) => [...a].sort((x, y) => (x < y ? -1 : x > y ? 1 : 0));

export function route(meta, state, projections, cfg, region = null) {
  cfg = withRegion(cfg, region);
  const packKwh = meta.nominal_voltage_v * meta.rated_capacity_ah / 1000;
  const sohNow = state.soh.value / 100;
  const rec = recycleValue(meta.chemistry, packKwh, cfg);
  const options = {};
  for (const [name, pj] of Object.entries(projections)) {
    const w = pj.workload.values;
    const sohByYear = pj.points.map((p) => p.soh.value / 100);
    const x = secondLifeValue(packKwh, sohNow, sohByYear, pj.conservative_years.value, w, rec.net_usd, cfg);
    options[name] = {
      label: pj.workload.label,
      conservative_years: tag(x.years_used, "modelled", "years", "conservative remaining life, capped at max service years"),
      gross_energy_value: tag(x.gross_energy_value_usd, "modelled", "USD"),
      buy_new_cap: tag(x.buy_new_cap_usd, "modelled", "USD", x.buy_new_cap_usd !== null ? "cost of equivalent new installed storage for the same service years" : "not applied: reuse is valued by the new pack it replaces"),
      valuation_mode: x.valuation_mode,
      capped_by_buy_new: x.capped,
      upfront_costs: tag(x.upfront_cost_usd, "assumed", "USD", "placeholder cost inputs"),
      end_of_life_recycle_pv: tag(x.end_of_life_recycle_pv_usd, "modelled", "USD"),
      net_value: tag(x.net_usd, "modelled", "USD"),
      lcos_for_comparison: tag(x.lcos_usd_per_kwh, "modelled", "USD/kWh", "upfront cost / discounted energy; comparison only"),
    };
  }
  let best = null;
  for (const k of Object.keys(options)) if (best === null || options[k].net_value.value > options[best].net_value.value) best = k;
  const ph = pySorted(placeholders(cfg));
  const out = {
    pack_energy: tag(packKwh, "modelled", "kWh", "nominal voltage x rated capacity"),
    second_life_options: options,
    recycle: { nickel_value: tag(rec.nickel_usd, "modelled", "USD"), cobalt_value: tag(rec.cobalt_usd, "modelled", "USD"),
      lithium_value: tag(rec.lithium_usd, "modelled", "USD"), processing_cost: tag(rec.processing_cost_usd, "assumed", "USD"),
      net_value: tag(rec.net_usd, "modelled", "USD") },
    benchmark: "Buy New: second-life gross value capped at installed new-storage cost (sourced, configs/economics.yaml buy_new_benchmark.installed_system_usd_per_kwh)",
    discount_rate: tag(v(cfg.discount_rate), "assumed", "1/yr", null, { status: cfg.discount_rate.status || "assumed" }),
    placeholder_inputs: ph,
    region: region || "global_default",
    status: "ok",
  };
  if (best !== null && options[best].net_value.value > rec.net_usd && options[best].conservative_years.value >= 1.0) {
    const o = options[best];
    out.decision = `Second-Life: ${o.label}`;
    out.recommendation = { option: "Second-Life", application: best, label: o.label };
    out.rationale = [
      `${o.label}: net ${comma0(o.net_value.value)} USD over a conservative ${f(o.conservative_years.value, 1)} years vs recycling now ${comma0(rec.net_usd)} USD`,
      "values use PLACEHOLDER cost and tariff inputs: " + ph.slice(0, 4).join(", ") + " ...",
    ];
  } else {
    out.decision = "Recycle";
    out.recommendation = { option: "Recycle" };
    const why = best ? `best second-life option (${best}) nets ${comma0(options[best].net_value.value)} USD` : "no second-life projection available";
    out.rationale = [`${why}; recycling now nets ${comma0(rec.net_usd)} USD`];
  }
  return out;
}

// ---------------------------------------------------------------- illustrative price sensitivity
export const REF_PACK_KWH = 60.0, REF_SOH = 0.85, REF_RUL_REF = 400.0;

export function referenceProjection(physics, workloads, overrides = {}) {
  const w = workloads.residential_storage;
  const years = np.linspace(0, 20, 241);
  const soh = overrides.soh ?? REF_SOH, rul = overrides.rul ?? REF_RUL_REF;
  const tr = trajectory(physics, soh, rul, w, nominalParams(physics), years);
  const life = yearsTo(tr, years, w.min_soh_pct / 100) || 20.0;
  const sohByYear = [];
  for (let i = 0; i < 241; i += 12) sohByYear.push(tr[i]);
  return { w, sohByYear, life };
}

export function sweep(cfg, physics, workloads, opts = {}) {
  const mults = opts.priceMultipliers || cfg.sensitivity.price_multipliers;
  const vmults = opts.valueMultipliers || cfg.sensitivity.value_per_kwh_multipliers;
  const packKwh = opts.packKwh ?? REF_PACK_KWH, soh = opts.soh ?? REF_SOH;
  const { w, sohByYear, life } = referenceProjection(physics, workloads, opts);
  const out = {
    label: "ILLUSTRATIVE SENSITIVITY on a synthetic reference battery; not a result about any real pack",
    reference_battery: { pack_kwh: packKwh, soh_pct: 100 * soh, workload: "residential_storage", projected_years: np.pyRound(life, 2), provenance: "synthetic" },
    chemistries: {},
  };
  for (const chem of opts.chemistries || ["LFP", "NMC", "NCA"]) {
    const res = { composition_status: cfg.recycling.composition_kg_per_kwh[chem].status, grid: [] };
    for (const vm of vmults) {
      for (const m of mults) {
        const rec = recycleValue(chem, packKwh, cfg, { nickel: m, cobalt: m, lithium: m }).net_usd;
        const sl = secondLifeValue(packKwh, soh, sohByYear, life, w, rec, cfg, vm).net_usd;
        res.grid.push({ metal_price_multiplier: m, energy_value_multiplier: vm, recycle_net_usd: np.pyRound(rec, 0),
          second_life_net_usd: np.pyRound(sl, 0), decision: sl > rec ? "Second-Life" : "Recycle" });
      }
    }
    res.recycle_wins_at_metal_multipliers = Object.fromEntries(vmults.map((vm) => [Number.isInteger(vm) ? vm.toFixed(1) : String(vm), // Python str(float)
      res.grid.filter((g) => g.energy_value_multiplier === vm && g.decision === "Recycle").map((g) => g.metal_price_multiplier)]));
    res.provenance = "assumed";
    out.chemistries[chem] = res;
  }
  out.note = "All metal prices are scaled together (x current sourced prices). An empty list means Second-Life wins across the whole swept " +
    "range at that energy value. At very low metal prices recycling has negative value, so Recycle can 'win' only because second life " +
    "also loses money (both options are then uneconomic). Cost inputs include PLACEHOLDERS.";
  return out;
}
