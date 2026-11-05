"""Data-quality detectors. Each returns one or more CheckResult with evidence.

Conventions:
- Integration always uses the row-to-row time step of the time-sorted, de-duplicated rows.
- Current is never flipped in the data. Where a check needs a direction it works in a
  "charge-positive" frame computed from the declared or inferred convention, and says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

from revive_ml.config import load
from revive_ml.contract import Bundle
from revive_ml.provenance import data_provenance_tag, tag

Status = Literal["pass", "warn", "fail", "inconclusive", "not_applicable"]


@dataclass
class CheckResult:
    id: str
    name: str
    status: Status
    severity: Literal["info", "low", "medium", "high"]
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "status": self.status,
                "severity": self.severity, "message": self.message, "evidence": self.evidence}


@dataclass
class Context:
    """Shared, derived views of a bundle used by several detectors."""

    bundle: Bundle
    rules: dict[str, Any]
    df: pd.DataFrame          # time-sorted, duplicate timestamps dropped
    dt_s: np.ndarray          # row-to-row step of df (len n-1)
    prov: str                 # provenance tag for numbers derived from the data
    convention: str | None    # convention used for direction-dependent checks
    convention_source: str
    capacity_ref_ah: float
    capacity_ref_source: str

    @property
    def meta(self):  # noqa: ANN201
        return self.bundle.meta


def seconds(ts: pd.Series) -> np.ndarray:
    """Epoch seconds, independent of the datetime resolution pandas chose."""
    return ts.astype("datetime64[ns, UTC]").astype("int64").to_numpy() / 1e9


def _assumed(v: float, unit: str | None = None) -> dict[str, Any]:
    return tag(v, "assumed", unit)


def build_context(bundle: Bundle, rules: dict[str, Any] | None = None) -> Context:
    rules = rules or load("dq_rules.yaml")
    raw = bundle.telemetry.reset_index(drop=True)
    df = (raw.sort_values("timestamp_utc", kind="stable")
          .drop_duplicates("timestamp_utc").reset_index(drop=True))
    dt = np.diff(seconds(df["timestamp_utc"]))
    meta = bundle.meta
    if meta.capacity_tests:
        latest = max(meta.capacity_tests, key=lambda c: (c.date, c.cycle_count or 0))
        cap, src = latest.measured_capacity_ah, f"latest capacity test ({latest.date})"
    else:
        cap, src = meta.rated_capacity_ah, "rated capacity (no capacity test)"
    ctx = Context(bundle, rules, df, dt, data_provenance_tag(meta.data_provenance), None,
                  "none", cap, src)
    inferred = infer_convention(ctx)["inferred"]
    if meta.current_sign_convention != "unknown":
        ctx.convention, ctx.convention_source = meta.current_sign_convention, "declared in metadata"
    elif inferred in ("discharge_negative", "discharge_positive"):
        ctx.convention, ctx.convention_source = inferred, "inferred from data (not declared)"
    return ctx


def charge_positive(ctx: Context) -> np.ndarray | None:
    i = ctx.df["current_a"].to_numpy(dtype=float)
    if ctx.convention == "discharge_negative":
        return i
    if ctx.convention == "discharge_positive":
        return -i
    return None


def _cum_ah(i: np.ndarray, dt: np.ndarray) -> np.ndarray:
    """Cumulative charge (Ah), trapezoid rule with the actual row-to-row step."""
    inc = 0.5 * (i[1:] + i[:-1]) * dt / 3600.0
    return np.concatenate([[0.0], np.nancumsum(inc)])


# --------------------------------------------------------------------------- 1. sign convention
def infer_convention(ctx: Context) -> dict[str, Any]:
    r = ctx.rules["sign_convention"]
    df = ctx.df
    i = df["current_a"].to_numpy(dtype=float)
    i_mid = 0.5 * (i[1:] + i[:-1])
    thr = r["min_current_a_fraction_of_c"] * ctx.meta.rated_capacity_ah
    votes: dict[str, Any] = {}
    active = np.abs(i_mid) > thr
    if "soc_pct" in df and df["soc_pct"].notna().sum() > 2:
        dsoc = np.diff(df["soc_pct"].to_numpy(dtype=float))
        m = active & np.isfinite(dsoc) & (np.abs(dsoc) > 0)
        if m.sum() >= 2:
            votes["soc"] = float(np.mean(np.sign(i_mid[m]) == np.sign(dsoc[m])))
            votes["soc_n"] = int(m.sum())
    # Voltage: dV = a * (I * dt) [state-of-charge drift] + b * dI [ohmic step].
    # Both a and b are positive when current is charge-positive (discharge negative).
    dv = np.diff(df["voltage_v"].to_numpy(dtype=float))
    di = np.diff(i)
    m = np.isfinite(dv) & np.isfinite(i_mid) & np.isfinite(di)
    if m.sum() >= 4:
        X = np.column_stack([i_mid[m] * ctx.dt_s[m], di[m]])
        X = X / np.maximum(np.abs(X).max(axis=0), 1e-12)
        coef, *_ = np.linalg.lstsq(X, dv[m], rcond=None)
        resid = dv[m] - X @ coef
        dof = max(1, int(m.sum()) - 2)
        cov = np.linalg.pinv(X.T @ X) * float(resid @ resid) / dof
        t = coef / np.sqrt(np.maximum(np.diag(cov), 1e-30))
        k = int(np.argmax(np.abs(t)))
        votes["voltage_t_drift"], votes["voltage_t_ohmic"] = float(t[0]), float(t[1])
        votes["voltage_n"] = int(m.sum())
        if abs(t[k]) >= 3:
            votes["voltage"] = 1.0 if t[k] > 0 else 0.0
    calls = []
    for k in ("soc", "voltage"):
        if k in votes:
            f = votes[k]
            calls.append("discharge_negative" if f >= r["agree_fraction"]
                         else "discharge_positive" if f <= 1 - r["agree_fraction"] else "ambiguous")
    if not calls:
        inferred = "undetermined"
    elif all(c == calls[0] for c in calls):
        inferred = calls[0]
    else:
        inferred = "ambiguous"
    return {"inferred": inferred, "votes": votes, "calls": calls}


def check_sign_convention(ctx: Context) -> CheckResult:
    r = ctx.rules["sign_convention"]
    inf = infer_convention(ctx)
    declared = ctx.meta.current_sign_convention
    ev: dict[str, Any] = {
        "declared": declared,
        "inferred": inf["inferred"],
        "convention_used_downstream": ctx.convention or "none",
        "data_flipped": False,
    }
    if "soc" in inf["votes"]:
        ev["soc_agreement_fraction"] = tag(inf["votes"]["soc"], ctx.prov,
                                           note="share of active intervals where sign(I) == sign(dSOC)",
                                           n=inf["votes"]["soc_n"])
    if "voltage_t_drift" in inf["votes"]:
        ev["voltage_response_t_stats"] = tag(
            None, ctx.prov, note="t-statistics of dV on (I*dt, dI); positive means charge-positive current",
            drift=round(inf["votes"]["voltage_t_drift"], 2), ohmic=round(inf["votes"]["voltage_t_ohmic"], 2),
            n=inf["votes"]["voltage_n"])
    issues: list[str] = []
    status: Status = "pass"
    df = ctx.df
    if "power_kw" in df and df["power_kw"].notna().any():
        vi = df["voltage_v"].to_numpy(float) * df["current_a"].to_numpy(float) / 1000
        p = df["power_kw"].to_numpy(float)
        m = np.isfinite(vi) & np.isfinite(p) & (np.abs(vi) > 1e-3)
        if m.any():
            same = np.mean(np.abs(p[m] - vi[m]) <= r["power_rel_tol"] * np.abs(vi[m]))
            opp = np.mean(np.abs(p[m] + vi[m]) <= r["power_rel_tol"] * np.abs(vi[m]))
            ev["power_equals_v_times_i_fraction"] = tag(float(same), ctx.prov)
            ev["power_equals_minus_v_times_i_fraction"] = tag(float(opp), ctx.prov)
            if opp > 0.8:
                ev["power_column_convention"] = "discharge_positive"
                cur_conv = ctx.convention
                if cur_conv == "discharge_negative":
                    issues.append("power_kw is +V*|I| on discharge (discharge-positive) while current "
                                  "is discharge-negative: two sign conventions in one record")
                    status = "warn"
            elif same > 0.8:
                ev["power_column_convention"] = "same as current"
                if ctx.convention == "discharge_positive":
                    pass
            else:
                issues.append("power_kw matches neither +V*I nor -V*I")
                status = "warn"
    if inf["inferred"] == "ambiguous":
        issues.append("SOC and voltage behaviour disagree about the current sign")
        status = "fail"
    elif inf["inferred"] == "undetermined":
        issues.append("not enough active intervals to infer the current sign")
        status = "inconclusive" if status == "pass" else status
    if declared != "unknown" and inf["inferred"] in ("discharge_negative", "discharge_positive") \
            and declared != inf["inferred"]:
        issues.append(f"metadata declares {declared} but the data behave as {inf['inferred']}")
        status = "fail"
    if declared == "unknown" and inf["inferred"] in ("discharge_negative", "discharge_positive"):
        issues.append(f"convention not declared; inferred {inf['inferred']} from the data "
                      "(used for direction-dependent checks; data not flipped)")
        status = "warn" if status == "pass" else status
    msg = "; ".join(issues) if issues else f"declared {declared} matches the data"
    sev = {"pass": "info", "warn": "medium", "fail": "high", "inconclusive": "medium"}.get(status, "info")
    return CheckResult("sign_convention", "Current sign convention", status, sev, msg, ev)


# --------------------------------------------------------------------------- 2. charge balance
def implied_capacity(ctx: Context) -> dict[str, Any] | None:
    """Least-squares slope of SOC on coulomb-counted charge -> implied capacity (Ah)."""
    i = charge_positive(ctx)
    if i is None or "soc_pct" not in ctx.df:
        return None
    soc = ctx.df["soc_pct"].to_numpy(float)
    ah = _cum_ah(np.nan_to_num(i), ctx.dt_s)
    m = np.isfinite(soc)
    if m.sum() < 3:
        return None
    span = float(np.nanmax(soc[m]) - np.nanmin(soc[m]))
    ah_span = float(ah[m].max() - ah[m].min())
    if ah_span <= 0:
        return {"soc_span_pts": span, "ah_span": ah_span, "capacity_ah": None}
    slope = np.polyfit(ah[m], soc[m], 1)[0]  # SOC points per Ah
    cap = 100.0 / slope if slope > 0 else None
    return {"soc_span_pts": span, "ah_span": ah_span, "slope": float(slope), "capacity_ah": cap,
            "net_ah": float(ah[m][-1] - ah[m][0]), "net_soc_pts": float(soc[m][-1] - soc[m][0])}


def check_charge_balance(ctx: Context) -> CheckResult:
    r = ctx.rules["charge_balance"]
    name = "Charge balance (coulomb count vs recorded SOC)"
    if "soc_pct" not in ctx.df or ctx.df["soc_pct"].notna().sum() < 3:
        return CheckResult("charge_balance", name, "not_applicable", "info", "no SOC channel")
    if ctx.convention is None:
        return CheckResult("charge_balance", name, "inconclusive", "medium",
                           "current sign convention unknown; cannot compare directions")
    ic = implied_capacity(ctx)
    assert ic is not None
    if ic["soc_span_pts"] < r["min_soc_span_pts"]:
        return CheckResult("charge_balance", name, "not_applicable", "info",
                           f"SOC moved only {ic['soc_span_pts']:.1f} points; too little to test")
    ref = ctx.capacity_ref_ah
    expected_pts = ic["ah_span"] / ref * 100
    ev = {
        "coulomb_counted_throughput_ah": tag(ic["ah_span"], ctx.prov, "Ah",
                                             note="trapezoid rule on row-to-row time step"),
        "recorded_soc_span": tag(ic["soc_span_pts"], ctx.prov, "SOC points"),
        "soc_points_explained_by_current": tag(expected_pts, ctx.prov, "SOC points",
                                               note=f"throughput / {ctx.capacity_ref_source}"),
        "reference_capacity": tag(ref, ctx.prov, "Ah", note=ctx.capacity_ref_source),
        "convention_used": ctx.convention,
    }
    if ic["capacity_ah"] is None:
        ev["slope_soc_per_ah"] = tag(ic.get("slope", 0.0), ctx.prov)
        return CheckResult("charge_balance", name, "fail", "high",
                           "SOC moves against the direction of the integrated current", ev)
    rel = ic["capacity_ah"] / ref
    ev["implied_capacity"] = tag(ic["capacity_ah"], ctx.prov, "Ah",
                                 note="least-squares slope of SOC vs cumulative Ah")
    ev["implied_over_reference"] = tag(rel, ctx.prov)
    mismatch_pts = abs(ic["soc_span_pts"] - expected_pts)
    ev["mismatch"] = tag(mismatch_pts, ctx.prov, "SOC points")
    ev["thresholds"] = {"warn_rel": _assumed(r["warn_rel"]), "fail_rel": _assumed(r["fail_rel"])}
    dev = abs(1 / rel - 1)  # relative excess of SOC movement over what current explains
    msg = (f"SOC moved {ic['soc_span_pts']:.1f} points; current explains {expected_pts:.1f} "
           f"on {ref:.1f} Ah (implied capacity {ic['capacity_ah']:.1f} Ah)")
    if dev > r["fail_rel"] and mismatch_pts > r["min_abs_pts"]:
        return CheckResult("charge_balance", name, "fail", "high", msg, ev)
    if dev > r["warn_rel"] and mismatch_pts > r["min_abs_pts"]:
        return CheckResult("charge_balance", name, "warn", "medium", msg, ev)
    return CheckResult("charge_balance", name, "pass", "info", msg, ev)


# --------------------------------------------------------------------------- 3. regen sign
def check_regen_sign(ctx: Context) -> CheckResult:
    r = ctx.rules["regen_sign"]
    name = "Regeneration / charging current direction"
    df = ctx.df
    if "operating_state" not in df or df["operating_state"].isna().all():
        return CheckResult("regen_sign", name, "not_applicable", "info", "no operating_state channel")
    st = df["operating_state"].astype(str).str.upper()
    i = df["current_a"].to_numpy(float)
    regen = st.isin(r["regen_states"]).to_numpy() & np.isfinite(i) & (i != 0)
    drive = st.isin(r["drive_states"]).to_numpy() & np.isfinite(i) & (i != 0)
    if not regen.any():
        return CheckResult("regen_sign", name, "not_applicable", "info", "no regen/charging rows")
    if drive.any():
        drive_sign = float(np.sign(np.median(i[drive])))
        basis = "median sign of driving rows"
    elif ctx.convention:
        drive_sign = -1.0 if ctx.convention == "discharge_negative" else 1.0
        basis = f"convention ({ctx.convention_source})"
    else:
        return CheckResult("regen_sign", name, "inconclusive", "medium",
                           "no driving rows and unknown convention")
    wrong = regen & (np.sign(i) == drive_sign)
    frac = wrong.sum() / regen.sum()
    ev = {"regen_rows": int(regen.sum()), "wrong_sign_rows": int(wrong.sum()),
          "first_rows": [int(k) for k in np.flatnonzero(wrong)[:10]],
          "discharge_sign_basis": basis,
          "wrong_sign_fraction": tag(float(frac), ctx.prov)}
    if wrong.any():
        rows = df.loc[wrong, ["timestamp_utc", "operating_state", "current_a"]].head(3)
        ev["examples"] = [{"timestamp_utc": str(x.timestamp_utc), "operating_state": x.operating_state,
                           "current_a": tag(x.current_a, ctx.prov, "A")} for x in rows.itertuples()]
        status: Status = "fail" if frac >= r["fail_fraction"] else "warn"
        return CheckResult("regen_sign", name, status, "high" if status == "fail" else "medium",
                           f"{wrong.sum()} of {regen.sum()} regen/charging rows have the same current "
                           "sign as driving", ev)
    return CheckResult("regen_sign", name, "pass", "info", "regen/charging rows oppose driving", ev)


# --------------------------------------------------------------------------- 4. resistance
def check_resistance(ctx: Context) -> CheckResult:
    r = ctx.rules["resistance"]
    name = "Internal resistance plausibility"
    meta = ctx.meta
    if not meta.resistance_tests:
        return CheckResult("resistance", name, "not_applicable", "info", "no resistance tests")
    t = max(meta.resistance_tests, key=lambda x: (x.date, x.cycle_count or 0))
    prov = data_provenance_tag(t.provenance)
    if t.level == "cell":
        r_cell = t.resistance_mohm
    elif meta.series_cells and meta.parallel_cells:
        r_cell = t.resistance_mohm * meta.parallel_cells / meta.series_cells
    else:
        return CheckResult("resistance", name, "inconclusive", "medium",
                           "pack resistance given without series/parallel counts")
    cell_cap = meta.rated_capacity_ah / (meta.parallel_cells or 1)
    specific = r_cell * cell_cap
    r_new_cell = r["typical_new_specific_mohm_ah"] / cell_cap
    soh_r_raw = 100 - 20 * (r_cell / r_new_cell - 1) / (r["eol_resistance_factor"] - 1)
    ev = {
        "latest_test_resistance": tag(t.resistance_mohm, prov, "mOhm", note=f"{t.level} level, {t.date}"),
        "per_cell_resistance": tag(r_cell, prov, "mOhm"),
        "specific_resistance": tag(specific, prov, "mOhm*Ah", note="R_cell x C_cell"),
        "plausible_range": {"value": [r["specific_min_mohm_ah"], r["specific_max_mohm_ah"]],
                            "provenance": "assumed", "unit": "mOhm*Ah"},
        "resistance_based_soh_unclipped": tag(soh_r_raw, "modelled", "%",
                                              note="vs an assumed typical new cell; EOL at 2x"),
        "resistance_based_soh_clipped": tag(min(100.0, max(0.0, soh_r_raw)), "modelled", "%"),
    }
    if specific < r["specific_min_mohm_ah"]:
        return CheckResult("resistance", name, "inconclusive", "high",
                           f"{r_cell:.2f} mOhm per cell ({specific:.1f} mOhm*Ah) is implausibly low for "
                           "this cell size; resistance-based SOH hits its 100 % ceiling and is not used",
                           ev)
    if specific > r["specific_max_mohm_ah"]:
        return CheckResult("resistance", name, "warn", "medium",
                           f"{specific:.0f} mOhm*Ah is above the plausible range: degraded cell or bad "
                           "measurement", ev)
    return CheckResult("resistance", name, "pass", "info", "resistance within plausible range", ev)


# --------------------------------------------------------------------------- 5. timestamps
def check_timestamps(ctx: Context) -> CheckResult:
    r = ctx.rules["timestamps"]
    name = "Timestamps (order, duplicates, gaps, regularity)"
    raw = seconds(ctx.bundle.telemetry["timestamp_utc"])
    d_raw = np.diff(raw)
    n_back = int((d_raw < 0).sum())
    n_dup = int(len(raw) - len(np.unique(raw)))
    dt = ctx.dt_s
    prov = ctx.prov
    ev: dict[str, Any] = {"n_rows": len(raw), "duplicates": n_dup, "non_monotonic_steps": n_back}
    if len(dt) == 0:
        return CheckResult("timestamps", name, "fail", "high", "fewer than two distinct timestamps", ev)
    med = float(np.median(dt))
    irregular = np.abs(dt - med) > r["irregular_rel_tol"] * med
    gaps = dt > r["gap_factor"] * med
    span = float(raw.max() - raw.min())
    gap_time = float(dt[gaps].sum())
    ev.update({
        "median_step": tag(med, prov, "s"),
        "min_step": tag(float(dt.min()), prov, "s"),
        "max_step": tag(float(dt.max()), prov, "s"),
        "irregular_step_fraction": tag(float(irregular.mean()), prov),
        "gaps": int(gaps.sum()),
        "gap_time_fraction": tag(gap_time / span if span else 0.0, prov),
        "integration_note": "all integrals use the row-to-row step, never a fixed step",
    })
    issues, status = [], "pass"
    if n_back:
        issues.append(f"{n_back} backwards time step(s)")
        status = "fail"
    if n_dup:
        issues.append(f"{n_dup} duplicate timestamp(s) (dropped for integration)")
        status = "fail"
    if span and gap_time / span > r["gap_fail_fraction"]:
        issues.append(f"gaps cover {100 * gap_time / span:.0f} % of the record")
        status = "fail"
    elif gaps.any():
        issues.append(f"{int(gaps.sum())} gap(s) longer than {r['gap_factor']:.0f}x the median step")
        status = "warn" if status == "pass" else status
    if irregular.mean() > r["irregular_warn_fraction"]:
        issues.append(f"{100 * irregular.mean():.0f} % of steps deviate >"
                      f"{100 * r['irregular_rel_tol']:.0f} % from the median step")
        status = "warn" if status == "pass" else status
    msg = "; ".join(issues) if issues else f"regular {med:.0f} s steps, no duplicates or reversals"
    return CheckResult("timestamps", name, status,  # type: ignore[arg-type]
                       {"pass": "info", "warn": "medium", "fail": "high"}[status], msg, ev)


# --------------------------------------------------------------------------- 6. sensors
CHANNELS = ("voltage_v", "current_a", "temperature_c", "soc_pct")


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """(start, length) of True runs."""
    out, start = [], None
    for k, v in enumerate(mask):
        if v and start is None:
            start = k
        elif not v and start is not None:
            out.append((start, k - start))
            start = None
    if start is not None:
        out.append((start, len(mask) - start))
    return out


def check_sensor_nulls(ctx: Context) -> CheckResult:
    r = ctx.rules["sensor"]
    df = ctx.bundle.telemetry
    fr = {c: float(df[c].isna().mean()) for c in CHANNELS if c in df}
    ev = {f"{c}_null_fraction": tag(v, ctx.prov) for c, v in fr.items()}
    worst = max(fr.values()) if fr else 0.0
    bad = [c for c, v in fr.items() if v > r["null_warn_fraction"]]
    if worst > r["null_fail_fraction"]:
        return CheckResult("sensor_nulls", "Sensor nulls", "fail", "high",
                           f"null fraction above {r['null_fail_fraction']:.0%} in {bad}", ev)
    if bad:
        return CheckResult("sensor_nulls", "Sensor nulls", "warn", "medium", f"nulls in {bad}", ev)
    return CheckResult("sensor_nulls", "Sensor nulls", "pass", "info", "no significant nulls", ev)


def check_sensor_dropouts(ctx: Context) -> CheckResult:
    """Dropout = voltage reads ~0 V (or null) while neighbouring rows are live."""
    r = ctx.rules["sensor"]
    v = ctx.df["voltage_v"].to_numpy(float)
    floor = 0.5 * ctx.meta.min_voltage_v
    drop = ~np.isfinite(v) | (v < floor)
    frac = float(drop.mean())
    ev = {"voltage_dropout_rows": int(drop.sum()), "first_rows": [int(k) for k in np.flatnonzero(drop)[:10]],
          "dropout_fraction": tag(frac, ctx.prov),
          "dropout_floor": tag(floor, "assumed", "V", note="half the minimum pack voltage")}
    if frac > r["dropout_fail_fraction"]:
        return CheckResult("sensor_dropouts", "Sensor dropouts", "fail", "high",
                           f"{drop.sum()} voltage dropout rows", ev)
    if drop.any():
        return CheckResult("sensor_dropouts", "Sensor dropouts", "warn", "medium",
                           f"{drop.sum()} voltage dropout rows", ev)
    return CheckResult("sensor_dropouts", "Sensor dropouts", "pass", "info", "no dropouts", ev)


# Charge throughput (fraction of rated capacity) during a frozen run that makes a frozen
# reading implausible, per channel. A frozen SOC while 2 % of capacity flowed is a fault;
# temperature sensors with coarse resolution legitimately repeat, so they need far more.
STUCK_THROUGHPUT = {"voltage_v": 0.005, "soc_pct": 0.02, "temperature_c": 0.10}


def check_sensor_stuck(ctx: Context) -> CheckResult:
    r = ctx.rules["sensor"]
    df = ctx.df
    i = np.nan_to_num(df["current_a"].to_numpy(float))
    flowing = np.abs(i) > 0.01 * ctx.meta.rated_capacity_ah
    thru = _cum_ah(np.abs(i), ctx.dt_s)  # cumulative |Ah|, row-to-row step
    found: dict[str, int] = {}
    for c, frac in STUCK_THROUGHPUT.items():
        if c not in df:
            continue
        x = df[c].to_numpy(float)
        same = np.concatenate([[False], np.diff(x) == 0]) & flowing
        # Voltage only: a run is also stuck when it is too long to be chance given the channel's
        # own repeat rate (p ** run < 1e-6). This catches short freezes in finely sampled data.
        # SOC and temperature are quantised and slow, so they rely on the throughput rule alone.
        p_repeat = float(same.sum() / max(1, flowing.sum()))
        for start, length in _runs(same):
            moved = thru[start + length - 1] - thru[start - 1]
            rows = length + 1
            log_p_run = length * np.log(max(p_repeat, 1e-12))
            improbable = c == "voltage_v" and p_repeat < 1 and log_p_run < np.log(1e-6)
            enough_charge = moved >= frac * ctx.meta.rated_capacity_ah
            if rows >= r["stuck_min_run"] and (enough_charge or improbable):
                found[c] = max(found.get(c, 0), int(rows))
    ev: dict[str, Any] = {f"{c}_longest_stuck_run": n for c, n in found.items()}
    ev["min_run_rows"] = int(r["stuck_min_run"])
    ev["throughput_needed_fraction_of_capacity"] = {"value": STUCK_THROUGHPUT, "provenance": "assumed"}
    if found:
        return CheckResult("sensor_stuck", "Stuck sensor values", "fail", "high",
                           f"values frozen while current flows: {found}", ev)
    return CheckResult("sensor_stuck", "Stuck sensor values", "pass", "info", "no stuck channels", ev)


def _hampel(x: np.ndarray, w: int, k: float, min_abs: float) -> np.ndarray:
    s = pd.Series(x)
    med = s.rolling(2 * w + 1, center=True, min_periods=3).median()
    mad = (s - med).abs().rolling(2 * w + 1, center=True, min_periods=3).median()
    dev = (s - med).abs()
    return ((dev > k * 1.4826 * mad) & (dev > min_abs)).to_numpy()


def check_sensor_spikes(ctx: Context) -> CheckResult:
    r = ctx.rules["sensor"]
    df = ctx.df
    series = ctx.meta.series_cells or 1
    thr = {"voltage_v": r["spike_min_abs"]["voltage_v_per_cell"] * series,
           "temperature_c": r["spike_min_abs"]["temperature_c"],
           "soc_pct": r["spike_min_abs"]["soc_pct"]}
    found = {}
    for c, m in thr.items():
        if c in df and df[c].notna().sum() > 5:
            sp = _hampel(df[c].to_numpy(float), r["spike_window"], r["spike_k_mad"], m)
            if sp.any():
                found[c] = [int(k) for k in np.flatnonzero(sp)[:10]]
    ev = {f"{c}_spike_rows": rows for c, rows in found.items()}
    ev["min_spike_size"] = {"value": thr, "provenance": "assumed"}
    if found:
        n = sum(len(v) for v in found.values())
        return CheckResult("sensor_spikes", "Sensor spikes", "warn" if n <= 2 else "fail",
                           "medium" if n <= 2 else "high", f"isolated spikes in {list(found)}", ev)
    return CheckResult("sensor_spikes", "Sensor spikes", "pass", "info", "no spikes", ev)


def check_sensor_range(ctx: Context) -> CheckResult:
    rr = ctx.rules["sensor"]["range"]
    df = ctx.df
    meta = ctx.meta
    series = meta.series_cells
    out: dict[str, int] = {}
    v = df["voltage_v"].to_numpy(float)
    if series:
        vc = v / series
        out["voltage_v"] = int(((vc < rr["cell_voltage_min"]) | (vc > rr["cell_voltage_max"])).sum())
    else:
        out["voltage_v"] = int(((v < 0) | (v > 1.5 * meta.max_voltage_v)).sum())
    t = df["temperature_c"].to_numpy(float)
    out["temperature_c"] = int(((t < rr["temperature_min"]) | (t > rr["temperature_max"])).sum())
    if "soc_pct" in df:
        s = df["soc_pct"].to_numpy(float)
        out["soc_pct"] = int(((s < rr["soc_min"]) | (s > rr["soc_max"])).sum())
    i = df["current_a"].to_numpy(float)
    out["current_a"] = int((np.abs(i) > rr["max_abs_c_rate"] * meta.rated_capacity_ah).sum())
    ev = {f"{c}_out_of_range_rows": n for c, n in out.items()}
    ev["sensor_ranges"] = {"value": rr, "provenance": "assumed",
                           "note": "physical sensor plausibility, not operating limits (see gate)"}
    bad = {c: n for c, n in out.items() if n}
    if bad:
        return CheckResult("sensor_range", "Readings beyond sensor range", "fail", "high",
                           f"physically implausible readings: {bad}", ev)
    return CheckResult("sensor_range", "Readings beyond sensor range", "pass", "info",
                       "all readings physically plausible", ev)


def check_temperature_missing(ctx: Context) -> CheckResult:
    df = ctx.bundle.telemetry
    t_null = df["temperature_c"].isna()
    others = df["voltage_v"].notna() & df["current_a"].notna()
    frac = float((t_null & others).sum() / max(1, others.sum()))
    ev = {"temperature_missing_while_live_fraction": tag(frac, ctx.prov)}
    if frac >= 0.5:
        return CheckResult("temperature_missing", "Temperature missing while other channels live",
                           "fail", "high", "temperature absent for most live rows", ev)
    if frac > 0:
        return CheckResult("temperature_missing", "Temperature missing while other channels live",
                           "warn", "medium", f"temperature absent on {frac:.0%} of live rows", ev)
    return CheckResult("temperature_missing", "Temperature missing while other channels live",
                       "pass", "info", "temperature present", ev)


# --------------------------------------------------------------------------- 7. disagreement
def check_estimate_disagreement(ctx: Context, charge_balance: CheckResult | None = None) -> CheckResult:
    r = ctx.rules["estimate_disagreement"]
    name = "Live SOH vs capacity-test SOH"
    meta = ctx.meta
    ic = implied_capacity(ctx) if ctx.convention else None
    live = None
    if ic and ic.get("capacity_ah") and ic["soc_span_pts"] >= ctx.rules["charge_balance"]["min_soc_span_pts"]:
        live = 100 * ic["capacity_ah"] / meta.rated_capacity_ah
    test = None
    if meta.capacity_tests:
        latest = max(meta.capacity_tests, key=lambda c: (c.date, c.cycle_count or 0))
        test = 100 * latest.measured_capacity_ah / meta.rated_capacity_ah
        test_prov = data_provenance_tag(latest.provenance)
    ev: dict[str, Any] = {}
    if live is not None:
        ev["live_soh_from_telemetry"] = tag(live, ctx.prov, "%",
                                            note="implied capacity from SOC vs coulomb count / rated")
    if test is not None:
        ev["soh_from_capacity_test"] = tag(test, test_prov, "%", note=f"latest test {latest.date}")
    if "bms_soh_pct" in ctx.df and ctx.df["bms_soh_pct"].notna().any():
        ev["bms_reported_soh"] = tag(float(ctx.df["bms_soh_pct"].dropna().iloc[-1]), ctx.prov, "%",
                                     note="BMS-reported value; not independently measured")
    if test is None:
        ev["decision_trusts"] = "none: no measured capacity"
        return CheckResult("estimate_disagreement", name, "inconclusive", "high",
                           "no capacity test; SOH cannot be anchored to a measurement", ev)
    ev["decision_trusts"] = "capacity test"
    ev["why"] = ("a full-cycle capacity test is a direct, controlled measurement; the live estimate "
                 "depends on BMS SOC over a partial window" +
                 ("; and the charge-balance check failed for this window"
                  if charge_balance is not None and charge_balance.status == "fail" else ""))
    if live is None:
        return CheckResult("estimate_disagreement", name, "not_applicable", "info",
                           "live SOH not computable from this telemetry window", ev)
    diff = abs(live - test)
    ev["difference"] = tag(diff, ctx.prov, "SOH points")
    msg = f"live SOH {live:.1f} % vs capacity-test SOH {test:.1f} %"
    if diff > r["fail_pts"]:
        return CheckResult("estimate_disagreement", name, "fail", "high", msg, ev)
    if diff > r["warn_pts"]:
        return CheckResult("estimate_disagreement", name, "warn", "medium", msg, ev)
    return CheckResult("estimate_disagreement", name, "pass", "info", msg, ev)


# --------------------------------------------------------------------------- 8. provenance
def check_provenance(ctx: Context) -> CheckResult:
    meta = ctx.meta
    recs = [*meta.capacity_tests, *meta.resistance_tests, *meta.safety_events]
    rec_prov = sorted({r.provenance for r in recs})
    text = " ".join(filter(None, [meta.asset_id, meta.notes or "", meta.source or ""])).upper()
    ev = {"bundle_provenance": meta.data_provenance, "record_provenances": rec_prov,
          "report_tag_for_data_values": ctx.prov}
    if meta.data_provenance == "measured":
        if any(p != "measured" for p in rec_prov):
            return CheckResult("provenance", "Data provenance", "fail", "high",
                               "bundle labelled measured but contains synthetic/simulated records", ev)
        if any(w in text for w in ("SYNTHETIC", "SIMULATED", "DEMO", "ILLUSTRATIVE")):
            return CheckResult("provenance", "Data provenance", "fail", "high",
                               "bundle labelled measured but its description says synthetic/demo", ev)
        return CheckResult("provenance", "Data provenance", "pass", "info", "measured data", ev)
    return CheckResult("provenance", "Data provenance", "warn", "medium",
                       f"{meta.data_provenance} data: every derived number is tagged 'synthetic'; "
                       "results show the pipeline works, not anything about a real battery", ev)


def check_sample_size(ctx: Context) -> CheckResult:
    r = ctx.rules["sample_size"]
    n = len(ctx.df)
    dur = float(ctx.dt_s.sum()) if len(ctx.dt_s) else 0.0
    ev = {"n_rows": n, "duration": tag(dur, ctx.prov, "s"),
          "min_rows": int(r["min_rows"]), "min_duration": _assumed(r["min_duration_s"], "s")}
    if n < r["min_rows"] or dur < r["min_duration_s"]:
        return CheckResult("sample_size", "Enough telemetry", "fail", "high",
                           f"{n} rows over {dur:.0f} s is too little to assess", ev)
    return CheckResult("sample_size", "Enough telemetry", "pass", "info", f"{n} rows over {dur:.0f} s", ev)


def run_all(bundle: Bundle, rules: dict[str, Any] | None = None) -> list[CheckResult]:
    ctx = build_context(bundle, rules)
    cb = check_charge_balance(ctx)
    return [
        check_sample_size(ctx),
        check_provenance(ctx),
        check_timestamps(ctx),
        check_sign_convention(ctx),
        cb,
        check_regen_sign(ctx),
        check_resistance(ctx),
        check_sensor_nulls(ctx),
        check_sensor_dropouts(ctx),
        check_sensor_stuck(ctx),
        check_sensor_spikes(ctx),
        check_sensor_range(ctx),
        check_temperature_missing(ctx),
        check_estimate_disagreement(ctx, cb),
    ]
