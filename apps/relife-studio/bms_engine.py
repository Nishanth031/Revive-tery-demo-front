"""Rule-based BMS simulator. No physical device connections are implemented."""
from __future__ import annotations

import math

from models import BatteryProfile, HardwareAdapter

ADAPTERS = [
    HardwareAdapter(
        "V-LI-3-16", "Virtual lithium monitor • 3–16S",
        ["LFP", "Li-ion", "Lithium-ion (cell-specific details in source files)"], 3, 16, 80,
    ),
    HardwareAdapter("V-LI-SINGLE", "Virtual single-cell monitor • 1S", ["Li-ion", "LFP"], 1, 1, 5),
    HardwareAdapter("V-STACK-12", "Virtual stack monitor • up to 12S", ["LFP", "Li-ion"], 1, 12, 60),
    HardwareAdapter("V-BLOCK", "Virtual block-voltage monitor", ["Lead-acid", "NiMH", "NiCd"], 1, 24, 120, 0, False),
    # EV traction packs such as 96S NMC are far beyond the small-stack adapters above.
    HardwareAdapter("V-HV-PACK", "Virtual HV pack monitor • up to 120S", ["NMC", "NCA", "LFP", "Li-ion"], 3, 120, 500),
]

SCENARIOS = ["Normal", "Pulse load", "High load", "Overcurrent", "Cell imbalance", "Cell failure", "Thermal risk"]
SOURCE_LABEL = "SYNTHETIC VIRTUAL PULSE — not a real measurement or explosion prediction"
PULSE_DURATION_S = 30.0
PULSE_SAMPLE_S = 0.25


def check_compatibility(profile: BatteryProfile, adapter: HardwareAdapter):
    errors = []
    warnings = []
    if profile.series_cells is None:
        errors.append("Series cell count is unknown")
    elif not adapter.min_series <= profile.series_cells <= adapter.max_series:
        errors.append("Series cell count is outside adapter capability")

    if profile.chemistry == "Unknown":
        errors.append("Chemistry is unknown")
    else:
        chemistry = profile.chemistry.casefold()
        if not any(family.casefold() in chemistry or chemistry in family.casefold() for family in adapter.chemistry_families):
            errors.append("Chemistry/profile is unsupported by this adapter")

    if profile.nominal_voltage_v is None:
        warnings.append("Nominal voltage is unknown")
    elif profile.nominal_voltage_v > adapter.max_stack_voltage_v:
        errors.append("Nominal voltage exceeds adapter stack capability")
    if profile.capacity_value is None:
        warnings.append("Capacity is unknown; SOC/SOH unavailable")
    return not errors, errors, warnings


def evaluate(profile: BatteryProfile, adapter: HardwareAdapter, scenario: str = "Normal") -> dict:
    compatible, errors, warnings = check_compatibility(profile, adapter)
    if not compatible:
        return {
            "state": "PROFILE_REQUIRED", "status": "BLOCKED", "errors": errors, "warnings": warnings, "faults": [],
            "protection": "SIMULATED ONLY — unavailable", "soc_pct": None, "soh_pct": None,
        }

    # A measured zero is a real measurement and must not silently fall back to
    # nominal voltage (which could hide a disconnected or failed sensor).
    voltage = profile.measured_voltage_v if profile.measured_voltage_v is not None else profile.nominal_voltage_v
    faults = []
    injected = {
        "Undervoltage": "Simulated undervoltage input",
        "Overvoltage": "Simulated overvoltage input",
        "Overcurrent": "Simulated overcurrent input",
        "High temperature": "Simulated high temperature input",
    }
    if scenario in injected:
        faults.append(injected[scenario])
    elif scenario == "Stale sensor":
        warnings.append("Sensor data is stale")
    if profile.measured_temperature_c is None:
        warnings.append("Temperature measurement unknown")

    soc = None
    if voltage is not None and profile.nominal_voltage_v:
        soc = max(0, min(100, 100 * voltage / (profile.nominal_voltage_v * 1.2)))
        warnings.append("SOC is a simple illustrative voltage estimate, not chemistry-calibrated")

    return {
        "state": "FAULT_LATCHED" if faults else "READY",
        "status": "FAULT" if faults else ("REVIEW" if warnings else "READY"),
        "errors": errors, "warnings": warnings, "faults": faults,
        "protection": "SIMULATED OPEN" if faults else "SIMULATED MONITORING",
        "soc_pct": round(soc, 1) if soc is not None else None,
        "soh_pct": profile.soh_pct,
        "voltage_v": voltage,
        "current_a": profile.measured_current_a,
        "temperature_c": profile.measured_temperature_c,
    }


def _starting_voltage(profile: BatteryProfile) -> tuple[float, str]:
    if profile.measured_voltage_v is not None:
        return max(0.0, float(profile.measured_voltage_v)), "profile measurement"
    if profile.nominal_voltage_v is not None:
        return max(0.0, float(profile.nominal_voltage_v)), "profile nominal voltage"
    chemistry = profile.chemistry.casefold()
    if "lfp" in chemistry:
        cell_v = 3.2
    elif "lead" in chemistry:
        cell_v = 2.0
    elif "nimh" in chemistry or "nicd" in chemistry:
        cell_v = 1.2
    else:
        cell_v = 3.7
    return max(0.0, cell_v * (profile.series_cells or 1)), f"{cell_v:.1f} V/cell synthetic virtual default"


def _capacity_ah(profile: BatteryProfile, nominal: float) -> float:
    """Capacity for the model. Wh and kWh are converted using the nominal voltage."""
    capacity = profile.capacity_value if profile.capacity_unit == "Ah" else None
    if capacity is None and profile.capacity_value is not None and nominal:
        scale = 1000 if profile.capacity_unit == "kWh" else 1
        capacity = scale * profile.capacity_value / nominal
    return capacity or 2.0


def _rated_ah(profile: BatteryProfile) -> float | None:
    """Rated capacity from the profile's own figures only, used to work out capacity health."""
    if profile.capacity_unit == "Ah":
        return profile.capacity_value
    if profile.nominal_voltage_v and profile.capacity_value:
        if profile.capacity_unit == "Wh":
            return profile.capacity_value / profile.nominal_voltage_v
        if profile.capacity_unit == "kWh":
            return 1000 * profile.capacity_value / profile.nominal_voltage_v
    return None


def _default_demand(profile: BatteryProfile, capacity: float, scenario: str) -> float:
    demand = max(1.0, min(profile.discharge_limit_a or 10.0, capacity * 0.5))
    if scenario == "High load":
        demand *= 1.5
    elif scenario == "Overcurrent":
        demand = (profile.discharge_limit_a or demand) * 1.25
    elif scenario == "Cell imbalance":
        demand *= 0.5
    return demand


def _pulse_factor(t: float) -> float:
    """The 30 second load shape: low baseline, full demand, reduced demand, full demand."""
    if t < 3:
        return 0.20
    if t < 12:
        return 1.0
    if t < 20:
        return 0.55
    return 1.0


def stress_test(profile: BatteryProfile, scenario: str = "Pulse load", *, mode: str = "Discharge",
                target_voltage_v: float | None = None, demand_current_a: float | None = None,
                duration_s: float = PULSE_DURATION_S, sample_s: float = PULSE_SAMPLE_S) -> dict:
    """Simulate a battery under requested load/charge and estimate SOC/SOH from its trace.

    Profile SOH or measured capacity may seed the synthetic plant aging model;
    reported SOH is calculated separately from simulated voltage/current pulse telemetry.
    """
    if mode not in ("Discharge", "Charge"):
        raise ValueError("mode must be 'Discharge' or 'Charge'")
    if duration_s <= 0 or sample_s <= 0:
        raise ValueError("duration_s and sample_s must be positive")
    if demand_current_a is not None and demand_current_a <= 0:
        raise ValueError("demand_current_a must be positive")

    voltage, voltage_source = _starting_voltage(profile)
    nominal = max(float(profile.nominal_voltage_v or voltage or 1.0), 0.1)
    capacity = _capacity_ah(profile, nominal)
    rated_ah = _rated_ah(profile)
    base_temp = profile.measured_temperature_c if profile.measured_temperature_c is not None else 25.0
    if demand_current_a is None:
        demand_current_a = _default_demand(profile, capacity, scenario)
    target_voltage_v = float(target_voltage_v if target_voltage_v is not None else voltage)

    # Simulated internal resistance is profile-specific rather than a shared
    # 25 mΩ fallback. It scales with pack voltage/capacity and profile health.
    ref_r_mohm = max(1.0, 18.0 * (nominal / 48.0) * (50.0 / max(capacity, 0.1)) ** 0.5)
    capacity_soh = (
        100.0 * profile.measured_capacity_ah / rated_ah
        if profile.measured_capacity_ah is not None and rated_ah else None
    )
    latent_soh = profile.soh_pct if profile.soh_pct is not None else capacity_soh
    profile_seed = sum(ord(ch) for ch in profile.id) % 31
    if latent_soh is None:
        latent_soh = 68.0 + profile_seed
    latent_soh = max(10.0, min(110.0, float(latent_soh)))
    if profile.internal_resistance_mohm is not None and profile.internal_resistance_mohm > 0:
        resistance_used = profile.internal_resistance_mohm / 1000.0
        resistance_source = "profile input"
    else:
        resistance_used = (ref_r_mohm / 1000.0) * (1.0 + (100.0 - latent_soh) / 65.0 + profile_seed * 0.003)
        resistance_source = "profile-specific synthetic virtual plant estimate"

    rated_current = profile.discharge_limit_a if mode == "Discharge" else profile.charge_limit_a
    has_rating = rated_current is not None and rated_current > 0
    current_limit = max(0.0, float(rated_current if has_rating else capacity * (1.0 if mode == "Discharge" else 0.5)))
    health_factor = max(0.0, min(1.0, (latent_soh - 20.0) / 80.0))
    voltage_factor = max(0.0, min(1.0, voltage / max(target_voltage_v, nominal * 0.75, 0.1)))
    thermal_factor = max(0.0, min(1.0, (65.0 - max(0.0, base_temp)) / 40.0))
    available_current = current_limit * min(health_factor, voltage_factor, thermal_factor)
    requested_peak = float(demand_current_a)
    sign = 1.0 if mode == "Charge" else -1.0

    initial_soc = profile.initial_soc_pct
    if initial_soc is None and voltage > 0:
        initial_soc = max(0.0, min(100.0, 100.0 * voltage / (nominal * 1.08)))
        soc_source = "voltage-based starting estimate, then coulomb count"
    elif initial_soc is not None:
        initial_soc = max(0.0, min(100.0, float(initial_soc)))
        soc_source = "profile initial SOC, then coulomb count"
    else:
        soc_source = "unavailable: no usable voltage or initial SOC"

    r_min = ref_r_mohm / 1000 * 0.1
    r_max = ref_r_mohm / 1000 * 5
    points = []
    baseline = None
    estimated_r = None
    estimated_soh = None
    resistance_clamped = False
    charged_ah = 0.0
    last_current = 0.0
    for n in range(int(round(duration_s / sample_s)) + 1):
        t = n * sample_s
        pulse = _pulse_factor(t)
        if scenario == "Cell failure":
            pulse *= 0.5
        requested = requested_peak * pulse
        current = min(requested, available_current) if voltage > 0 else 0.0
        if n:
            charged_ah += last_current * sample_s / 3600.0
        soc = max(0.0, min(100.0, initial_soc + sign * 100.0 * charged_ah / capacity)) if initial_soc is not None else None
        soc_change = (soc - initial_soc) if soc is not None else 0.0
        open_circuit = voltage + soc_change * nominal * 0.0012
        temp = base_temp + (current * current * resistance_used) * (1 - math.exp(-t / 18.0)) * 0.12
        effective_r = resistance_used * (
            1 + max(0.0, 25.0 - temp) * 0.004 + max(0.0, 50.0 - (soc if soc is not None else 50.0)) * 0.002
        )
        terminal = max(0.0, open_circuit + sign * current * effective_r)
        signed_current = sign * current

        if t < 3 and current > 0:
            baseline = (terminal, signed_current)
        if t >= 3 and baseline is not None and current > 0:
            current_step = abs(signed_current - baseline[1])
            voltage_step = abs(terminal - baseline[0])
            if current_step > 1e-6:
                raw_r = voltage_step / current_step
                estimated_r = max(r_min, min(r_max, raw_r))
                resistance_clamped = estimated_r != raw_r
                estimated_soh = max(0.0, min(100.0, 100.0 * (ref_r_mohm / 1000) / estimated_r))

        points.append({
            "time_s": round(t, 2),
            "voltage_v": round(terminal, 4),
            "current_a": round(current, 4),
            "battery_current_a": round(signed_current, 4),
            "demand_current_a": round(requested, 4),
            "target_voltage_v": round(target_voltage_v, 4),
            "temperature_c": round(temp, 3),
            "power_w": round(terminal * current, 3),
            "soc_pct": round(soc, 3) if soc is not None else None,
            "soh_pct": round(estimated_soh, 3) if estimated_soh is not None else None,
            "soh_state": "ESTIMATED FROM LIVE PULSE" if estimated_soh is not None else "WAITING FOR LOAD PULSE",
            "resistance_mohm": round(estimated_r * 1000, 3) if estimated_r is not None else None,
            "dod_pct": round(100 - soc, 3) if soc is not None else None,
        })
        last_current = current

    peak_temp = max(p["temperature_c"] for p in points)
    min_stress_voltage = min(p["voltage_v"] for p in points)
    faults = []
    if requested_peak > available_current:
        faults.append("Requested current not fully delivered by virtual capability")
    if scenario == "Cell imbalance":
        faults.append("Synthetic imbalance injected")
    if scenario == "Overcurrent":
        faults.append("Synthetic overcurrent threshold crossed")
    if scenario == "Cell failure":
        faults.append("Synthetic cell failure injected")
    if points[-1]["voltage_v"] < target_voltage_v * 0.98:
        faults.append("Requested voltage not met by direct-source model")
    if peak_temp >= 55 or scenario == "Thermal risk":
        faults.append("Thermal risk indicator — requires qualified assessment")

    voltage_drop = voltage - min_stress_voltage
    drop_pct = (100 * voltage_drop / voltage) if voltage else None
    effective_soh = points[-1]["soh_pct"]
    if voltage <= 0:
        condition = "DEAD / NO OUTPUT"
        use = "No use — no valid voltage output. Qualified assessment/recycling review."
    elif peak_temp >= 55 or scenario == "Thermal risk":
        condition = "CRITICAL HEAT"
        use = "No reuse recommendation — thermal indicator requires qualified assessment."
    elif scenario in ("Overcurrent", "Cell failure", "Cell imbalance") or (drop_pct is not None and drop_pct >= 15):
        condition = "FAIL / LARGE VOLTAGE SAG"
        use = "No use recommendation — investigate modeled fault or voltage sag."
    elif effective_soh is None:
        condition = "INCOMPLETE HEALTH DATA"
        use = "No pulse-derived SOH available; collect more voltage/current/capacity data."
    elif effective_soh >= 80:
        condition = "VIRTUAL PASS — SCREENING ONLY"
        use = "Candidate for stationary storage screening after independent engineering qualification."
    elif effective_soh >= 60:
        condition = "LIMITED — SCREENING ONLY"
        use = "Consider low-demand backup screening only after independent testing."
    else:
        condition = "END-OF-LIFE SCREEN"
        use = "Further qualified assessment or recycling review."

    return {
        "points": points, "mode": mode, "target_voltage_v": target_voltage_v, "demand_current_a": requested_peak,
        "delivered_current_a": sign * min(requested_peak, available_current),
        "current_capability_a": available_current, "c_rate_limit_a": current_limit,
        "peak_current_a": max(p["current_a"] for p in points),
        "peak_voltage_v": max(p["voltage_v"] for p in points),
        "min_voltage_v": min_stress_voltage, "peak_temperature_c": peak_temp,
        "energy_wh": sum(p["power_w"] for p in points) * sample_s / 3600,
        "failed_cells": 1 if scenario == "Cell failure" and profile.series_cells else 0,
        "faults": faults,
        "risk": "HIGH — modeled fault present" if faults else "No modeled fault in this scenario",
        "soc_source": soc_source,
        "soh_source": (
            "estimated from simulated voltage sag / current step"
            if effective_soh is not None else "unavailable: no measurable current pulse"
        ),
        "voltage_source": voltage_source,
        "resistance_mohm": estimated_r * 1000 if estimated_r is not None else resistance_used * 1000,
        "resistance_source": resistance_source, "reference_resistance_mohm": ref_r_mohm,
        "soh_proxy_clamped": resistance_clamped,
        "loaded_voltage_drop_v": voltage_drop, "loaded_voltage_drop_pct": drop_pct,
        "condition": condition, "use_recommendation": use,
        "source": SOURCE_LABEL,
    }


def screening_summary(profile: BatteryProfile, result: dict) -> dict:
    """Turn a finished test into one verdict, with its reason and the data still missing.

    tone is one of good, warning, serious or critical. The verdict is a screening flag from
    a synthetic pulse: it can't establish remaining capacity or physical safety.
    """
    soh = result["points"][-1]["soh_pct"]
    if result["faults"] or profile.condition == "Damaged - do not test":
        verdict = ("No reuse recommendation", "critical", "No reuse recommendation from this virtual test.",
                   "The requested operating point was not met, or a modeled fault or blocked condition occurred.")
    elif soh is None:
        verdict = ("Unknown health", "warning", "No use case suggested yet, because SOH is unknown.",
                   "A virtual pulse cannot establish remaining capacity or battery safety.")
    elif result.get("soh_proxy_clamped"):
        verdict = ("Inconclusive", "warning", "No use case suggested from this pulse.",
                   "The pulse resistance fell outside the model's reference range, so the SOH proxy hit its "
                   "limit and doesn't describe this battery. Rely on measured capacity instead.")
    elif soh >= 80:
        verdict = ("Screening pass", "good", "Candidate for stationary-storage screening after independent qualification.",
                   "The pulse-derived SOH proxy is at least 80%. It is not copied from the profile SOH field.")
    elif soh >= 60:
        verdict = ("Limited use", "warning", "Candidate for low-demand backup screening after independent testing.",
                   "The pulse-derived SOH proxy is 60–79%. Verify capacity, resistance, cell balance and power capability.")
    else:
        verdict = ("End of life screen", "serious", "Further qualified assessment or recycling review.",
                   "The pulse-derived SOH proxy is below 60%.")

    gaps = [
        label for value, label in (
            (profile.measured_capacity_ah, "measured capacity test"),
            (profile.internal_resistance_mohm, "internal resistance measurement"),
            (profile.series_cells, "series/cell count and cell-level health"),
            (profile.initial_soc_pct, "initial SOC or valid rest-voltage data"),
            (profile.measured_temperature_c, "measured temperature"),
        ) if value is None
    ]
    return {"label": verdict[0], "tone": verdict[1], "use": verdict[2], "reason": verdict[3], "gaps": gaps}
