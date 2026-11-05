"""Economics router: Second-Life (per application) vs Recycle, benchmarked against Buy New.

Second-life value for an application, over Y = conservative remaining years (capped):
    gross = sum_y  usable_kWh(y) * DoD * cycles/yr * RTE * value_per_kWh / (1 + r)^y
    usable_kWh(y) = pack_kWh * SOH(y)        (central projected SOH; fades every year)
    gross is capped at the cost of new storage giving the same service:
        cap = installed_new_usd_per_kWh * pack_kWh * SOH_now * min(1, Y / new_life_years)
    net_second_life = min(gross, cap) - (testing + refurbishment + logistics + installation) * kWh
                      + recycle_value / (1 + r)^Y          (the pack is still recycled afterwards)
Recycle now: sum_metal  kg * price * recovery * payable  - processing_cost * pack_kg.
LCOS is reported for comparison only and is never multiplied by years.
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np

from revive_ml.config import load
from revive_ml.provenance import tag

METALS = ("nickel", "cobalt", "lithium")


def _v(x: dict[str, Any]) -> float:
    return float(x["value"])


def _status_tag(value: float, entry: dict[str, Any], unit: str) -> dict[str, Any]:
    return tag(value, "assumed", unit, status=entry.get("status", "assumed"))


def metal_prices_usd_per_kg(cfg: dict[str, Any], mult: dict[str, float] | None = None) -> dict[str, float]:
    mult = mult or {}
    p = cfg["recycling"]["prices_usd_per_tonne"]
    li_frac = _v(cfg["recycling"]["lithium_carbonate_li_fraction"])
    return {
        "nickel": _v(p["nickel"]) / 1000 * mult.get("nickel", 1.0),
        "cobalt": _v(p["cobalt"]) / 1000 * mult.get("cobalt", 1.0),
        # lithium metal content priced via lithium carbonate
        "lithium": _v(p["lithium_carbonate"]) / 1000 / li_frac * mult.get("lithium", 1.0),
    }


def recycle_value(chemistry: str, pack_kwh: float, cfg: dict[str, Any] | None = None,
                  mult: dict[str, float] | None = None) -> dict[str, float]:
    cfg = cfg or load("economics.yaml")
    rc = cfg["recycling"]
    comp = rc["composition_kg_per_kwh"][chemistry]
    prices = metal_prices_usd_per_kg(cfg, mult)
    by_metal = {m: comp[m] * pack_kwh * prices[m] * rc["recovery_rate"][m] * rc["payable_fraction"][m]
                for m in METALS}
    pack_kg = rc["pack_kg_per_kwh"][chemistry] * pack_kwh
    cost = _v(rc["processing_cost_usd_per_kg_pack"]) * pack_kg
    return {**{f"{m}_usd": v for m, v in by_metal.items()}, "processing_cost_usd": cost,
            "net_usd": sum(by_metal.values()) - cost, "pack_kg": pack_kg}


def second_life_value(pack_kwh: float, soh_now: float, soh_by_year: list[float], years: float,
                      workload: dict[str, Any], recycle_net: float,
                      cfg: dict[str, Any] | None = None, value_mult: float = 1.0) -> dict[str, float]:
    cfg = cfg or load("economics.yaml")
    sl, bn = cfg["second_life"], cfg["buy_new_benchmark"]
    r = _v(cfg["discount_rate"])
    years = float(min(years, _v(sl["max_service_years"])))
    price = _v(sl["value_per_kwh_delivered"]) * value_mult
    cyc_per_year = workload["cycles_per_day"] * 365
    mode = workload.get("valuation_mode", "energy_arbitrage")
    gross, energy_pv = 0.0, 0.0
    n_full = int(np.floor(years))
    for y in range(n_full + 1):
        frac = 1.0 if y < n_full else years - n_full  # partial final year
        if frac <= 0:
            break
        soh = soh_by_year[min(y, len(soh_by_year) - 1)]
        e = pack_kwh * soh * workload["daily_dod"] * cyc_per_year * _v(sl["round_trip_efficiency"]) * frac
        disc = (1 + r) ** -(y + 0.5)
        if mode == "avoided_new_pack":
            # reuse in a vehicle: each year of service avoids that year's share of a new pack of the same usable energy
            gross += _v(bn["new_ev_pack_usd_per_kwh"]) * pack_kwh * soh / _v(bn["new_ev_pack_life_years"]) * frac * disc
        else:
            gross += e * price * disc
        energy_pv += e * disc
    upfront = pack_kwh * sum(_v(sl[k]) for k in ("testing_usd_per_kwh", "refurbishment_usd_per_kwh",
                                                  "logistics_usd_per_kwh", "installation_usd_per_kwh"))
    later_recycle = recycle_net * (1 + r) ** -years
    if mode == "avoided_new_pack":       # the buy-new storage cap applies to stationary options only
        cap, capped, value = None, False, gross
    else:
        new_cost = _v(bn["installed_system_usd_per_kwh"])
        cap = new_cost * pack_kwh * soh_now * min(1.0, years / _v(bn["new_system_life_years"]))
        capped, value = gross > cap, min(gross, cap)
    net = value - upfront + later_recycle
    return {"years_used": years, "gross_energy_value_usd": gross, "buy_new_cap_usd": cap,
            "capped": capped, "upfront_cost_usd": upfront, "end_of_life_recycle_pv_usd": later_recycle,
            "net_usd": net, "lcos_usd_per_kwh": (upfront / energy_pv) if energy_pv > 0 else float("inf"),
            "valuation_mode": mode}


def with_region(cfg: dict[str, Any], region: str | None) -> dict[str, Any]:
    """A copy of the economics config whose tariff is the selected region's (None/global_default: unchanged)."""
    if not region:
        return cfg
    regions = cfg["second_life"].get("regions", {})
    if region not in regions:
        raise ValueError(f"unknown region {region!r}; choose one of {sorted(regions)}")
    out = copy.deepcopy(cfg)
    out["second_life"]["value_per_kwh_delivered"] = dict(regions[region])
    return out


def route(meta: Any, state: dict[str, Any], projections: dict[str, Any],
          cfg: dict[str, Any] | None = None, region: str | None = None) -> dict[str, Any]:
    cfg = with_region(cfg or load("economics.yaml"), region)
    pack_kwh = meta.nominal_voltage_v * meta.rated_capacity_ah / 1000
    soh_now = state["soh"]["value"] / 100
    rec = recycle_value(meta.chemistry, pack_kwh, cfg)
    options: dict[str, Any] = {}
    for name, pj in projections.items():
        w = pj["workload"]["values"]
        years = pj["conservative_years"]["value"]
        soh_by_year = [p["soh"]["value"] / 100 for p in pj["points"]]
        v = second_life_value(pack_kwh, soh_now, soh_by_year, years, w, rec["net_usd"], cfg)
        options[name] = {
            "label": pj["workload"]["label"],
            "conservative_years": tag(v["years_used"], "modelled", "years",
                                      note="conservative remaining life, capped at max service years"),
            "gross_energy_value": tag(v["gross_energy_value_usd"], "modelled", "USD"),
            "buy_new_cap": tag(v["buy_new_cap_usd"], "modelled", "USD",
                               note="cost of equivalent new installed storage for the same service years"
                               if v["buy_new_cap_usd"] is not None else "not applied: reuse is valued by the new pack it replaces"),
            "valuation_mode": v["valuation_mode"],
            "capped_by_buy_new": v["capped"],
            "upfront_costs": tag(v["upfront_cost_usd"], "assumed", "USD", note="placeholder cost inputs"),
            "end_of_life_recycle_pv": tag(v["end_of_life_recycle_pv_usd"], "modelled", "USD"),
            "net_value": tag(v["net_usd"], "modelled", "USD"),
            "lcos_for_comparison": tag(v["lcos_usd_per_kwh"], "modelled", "USD/kWh",
                                       note="upfront cost / discounted energy; comparison only"),
        }
    best = max(options, key=lambda k: options[k]["net_value"]["value"]) if options else None
    rc = {"nickel_value": tag(rec["nickel_usd"], "modelled", "USD"),
          "cobalt_value": tag(rec["cobalt_usd"], "modelled", "USD"),
          "lithium_value": tag(rec["lithium_usd"], "modelled", "USD"),
          "processing_cost": tag(rec["processing_cost_usd"], "assumed", "USD"),
          "net_value": tag(rec["net_usd"], "modelled", "USD")}
    placeholders = sorted(_placeholders(cfg))
    out: dict[str, Any] = {
        "pack_energy": tag(pack_kwh, "modelled", "kWh", note="nominal voltage x rated capacity"),
        "second_life_options": options,
        "recycle": rc,
        "benchmark": "Buy New: second-life gross value capped at installed new-storage cost (sourced, "
                     "configs/economics.yaml buy_new_benchmark.installed_system_usd_per_kwh)",
        "discount_rate": _status_tag(_v(cfg["discount_rate"]), cfg["discount_rate"], "1/yr"),
        "placeholder_inputs": placeholders,
        "region": region or "global_default",
        "status": "ok",
    }
    if best is not None and options[best]["net_value"]["value"] > rec["net_usd"] \
            and options[best]["conservative_years"]["value"] >= 1.0:
        o = options[best]
        out["decision"] = f"Second-Life: {o['label']}"
        out["recommendation"] = {"option": "Second-Life", "application": best, "label": o["label"]}
        out["rationale"] = [
            f"{o['label']}: net {o['net_value']['value']:,.0f} USD over a conservative "
            f"{o['conservative_years']['value']:.1f} years vs recycling now {rec['net_usd']:,.0f} USD",
            "values use PLACEHOLDER cost and tariff inputs: " + ", ".join(placeholders[:4]) + " ...",
        ]
    else:
        out["decision"] = "Recycle"
        out["recommendation"] = {"option": "Recycle"}
        why = (f"best second-life option ({best}) nets {options[best]['net_value']['value']:,.0f} USD"
               if best else "no second-life projection available")
        out["rationale"] = [f"{why}; recycling now nets {rec['net_usd']:,.0f} USD"]
    return out


def _placeholders(cfg: Any, path: str = "") -> list[str]:
    out = []
    if isinstance(cfg, dict):
        if cfg.get("status") == "PLACEHOLDER":
            out.append(path.strip("."))
        for k, v in cfg.items():
            out += _placeholders(v, f"{path}.{k}")
    return out
