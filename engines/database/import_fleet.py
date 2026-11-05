"""Build the platform database with the user's 60-pack fleet (run by `just db`). Deterministic and idempotent.

1. If the user's database (github.com/Nishanth031/revive-tery-DB, file revive_tery.duckdb) is available, refresh
   engines/database/csv_bundle/ from it: every pack's battery_registry row, the platform's key/value battery_asset
   rows generated from it, and its child tables (telemetry, health_history, safety_events, charge_sessions, modules,
   materials_recycling, data_sources), timestamps normalised to UTC. The platform's own packs stay as they are;
   when an asset_id exists in both, the user's registry wins for registry fields (logged as a conflict).
   Six test-case packs (DEMO-FLAW-01..06) are added with one injected data fault each.
   Without the source file the committed CSVs are used as they are.
2. Build data/db/revive_tery.duckdb from the CSVs (build_relational_db.py).
3. telemetry_dense: SYNTHETIC, densified telemetry for every pack (1,020 rows at 10 s), generated from the pack's
   registry spec and its latest capacity test with the engine's documented physics model (revive_ml.synth:
   chemistry OCV curve, drive/regen/charge current profile, coulomb-consistent SOC, IR drop, lumped thermal model).
   The original 12-row `telemetry` is never changed. Every dense row says data_class=SYNTHETIC and where it came from.
4. Views fleet_summary and pack_history; runtime tables assessments, ml_suggestions, fleet_reports (if missing).

Source path: env REVIVE_FLEET_SRC, else ../_import/revive-tery-DB/revive_tery.duckdb, else data/import/revive_tery.duckdb.
"""
from __future__ import annotations

import os
import re
import sys
import zlib
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CSV_DIR = HERE / "csv_bundle"
DB_PATH = Path(os.environ.get("REVIVE_DB") or ROOT / "data" / "db" / "revive_tery.duckdb")
SRC_CANDIDATES = [os.environ.get("REVIVE_FLEET_SRC"), ROOT.parent / "_import" / "revive-tery-DB" / "revive_tery.duckdb",
                  ROOT / "data" / "import" / "revive_tery.duckdb"]

CHILD_TABLES = ("telemetry", "health_history", "safety_events", "charge_sessions", "modules", "materials_recycling")
TIME_COLUMNS = {"telemetry": ["timestamp_utc"], "safety_events": ["timestamp_utc"], "charge_sessions": ["start_utc", "end_utc"]}
ASSET_FIELDS = ("asset_id", "vehicle_id", "battery_type", "chemistry", "cell_format", "series_parallel_configuration",
                "cell_count", "nominal_voltage_V", "max_voltage_V", "min_voltage_V", "nominal_capacity_Ah",
                "nominal_energy_kWh", "pack_mass_kg", "manufacture_date", "commissioning_date", "warranty_end_date",
                "demo_status")
REGISTRY_COLUMNS = ("asset_id", "vehicle_id", "application", "battery_type", "chemistry", "cell_format",
                    "series_parallel_configuration", "cell_count", "nominal_voltage_V", "max_voltage_V", "min_voltage_V",
                    "nominal_capacity_Ah", "nominal_energy_kWh", "pack_mass_kg", "manufacture_date", "commissioning_date",
                    "warranty_end_date", "latest_assessment_date", "cycle_count", "soh_pct", "lifecycle_status",
                    "demo_status", "data_class", "registry_source")
SRC_USER, SRC_PLATFORM, SRC_TEST = "user fleet DB (revive-tery-DB)", "platform demo fleet", "platform test case"
CHEM = {"NMC (nickel manganese cobalt)": "NMC", "NMC": "NMC", "LFP (lithium iron phosphate)": "LFP", "LFP": "LFP",
        "NCA (nickel cobalt aluminium)": "NCA", "NCA": "NCA"}

# Test cases: one injected data fault each, on the user's DEMO-EV-PACK-001 spec (labelled in the UI as test cases)
FLAW_BASE = "DEMO-EV-PACK-001"
FLAWS = {
    "DEMO-FLAW-01": ("sign_flip", "current sign flips half-way through the record"),
    "DEMO-FLAW-02": ("gap", "60-minute gap in the record"),
    "DEMO-FLAW-03": ("stuck_voltage", "voltage frozen for 20 minutes while current flows"),
    "DEMO-FLAW-04": ("temp_spike", "single-sample temperature spikes of +25 degC"),
    "DEMO-FLAW-05": ("null_voltage", "voltage missing on every 7th row"),
    "DEMO-FLAW-06": ("capacity_disagreement", "latest capacity test disagrees with the telemetry"),
}
DENSE_ROWS, DENSE_DT_S = 1020, 10.0
CV_MARGIN_HIGH, CV_MARGIN_LOW = 0.995, 1.005     # charger CV setpoint / BMS derate point, as a share of the pack's window
# lumped thermal model of revive_ml.synth (60 kJ/K and 25 W/K for a 100 Ah pack); BOTH scale with pack capacity, so a
# large stationary pack is not cooled like a small one
HEAT_CAP_J_PER_K_PER_100AH, COOLING_W_PER_K_PER_100AH = 60_000.0, 25.0
FLIP_FROM_ROW, GAP_FROM_ROW, GAP_MINUTES = 510, 400, 60


def log(msg: str) -> None:
    print(f"[import_fleet] {msg}")


def find_source() -> Path | None:
    for c in SRC_CANDIDATES:
        if c and Path(c).is_file():
            return Path(c)
    return None


def _utc_text(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_csv(name: str) -> pd.DataFrame:
    p = CSV_DIR / f"{name}.csv"
    return pd.read_csv(p, dtype=str, keep_default_na=False) if p.is_file() else pd.DataFrame()


def _write_csv(name: str, df: pd.DataFrame) -> None:
    df.to_csv(CSV_DIR / f"{name}.csv", index=False, lineterminator="\n")


def _asset_rows(reg: pd.Series) -> list[list[str]]:
    rid = str(reg["asset_id"])
    return [[rid, f, "" if pd.isna(reg.get(f)) else str(reg.get(f))] for f in ASSET_FIELDS]


def _platform_registry(asset: pd.DataFrame, health: pd.DataFrame, pid: str) -> dict:
    """A registry row for a platform pack, from its own battery_asset record. Nothing is invented: fields the
    platform never recorded (application, lifecycle_status) stay empty."""
    pairs = dict(zip(asset.loc[asset.asset_id == pid, "field"], asset.loc[asset.asset_id == pid, "value"]))
    h = health[health.asset_id == pid].sort_values("assessment_date")
    last = h.iloc[-1] if len(h) else None
    row = {c: "" for c in REGISTRY_COLUMNS}
    row.update({f: pairs.get(f, "") for f in ASSET_FIELDS})
    row.update({"latest_assessment_date": last["assessment_date"] if last is not None else "",
                "cycle_count": last["cycle_count"] if last is not None else "",
                "soh_pct": last["soh_pct"] if last is not None else "", "data_class": "SYNTHETIC",
                "registry_source": SRC_PLATFORM})
    return row


def refresh_csvs(src: Path) -> list[str]:
    """Merge the user's fleet into the CSV bundle. Returns notes for the upgrade log."""
    notes: list[str] = []
    s = duckdb.connect(str(src), read_only=True)
    try:
        sreg = s.execute("SELECT * FROM battery_registry ORDER BY asset_id").df()
        schild = {t: s.execute(f'SELECT * FROM "{t}"').df() for t in CHILD_TABLES}
        ssrc = s.execute("SELECT * FROM data_sources").df()
    finally:
        s.close()
    for t, cols in TIME_COLUMNS.items():
        for c in cols:
            schild[t][c] = _utc_text(schild[t][c])
    for t in schild:
        schild[t] = schild[t].astype(str).replace({"nan": "", "None": "", "NaT": "", "<NA>": ""})

    asset, reg_old = _read_csv("battery_asset"), _read_csv("battery_registry")
    health_old = _read_csv("health_history")
    if not reg_old.empty and "registry_source" in reg_old:
        platform_ids = sorted(reg_old.loc[reg_old.registry_source == SRC_PLATFORM, "asset_id"])
    else:
        platform_ids = sorted(asset.loc[asset.field == "asset_id", "value"]) if "field" in asset else []
    repo_ids = list(sreg.asset_id)
    conflicts = sorted(set(platform_ids) & set(repo_ids))
    for c in conflicts:
        notes.append(f"asset_id {c} exists in both: the user's database wins (registry, battery_asset AND its "
                     "capacity history/telemetry/events), because the platform's pack under that id is a different "
                     "synthetic battery and the user's capacity histories must not be replaced")
    keep_platform = set(platform_ids) - set(repo_ids)       # platform-only packs stay exactly as they are
    test_ids = set(FLAWS)

    # child tables: platform-only packs as they are + every pack of the user's database
    for t in CHILD_TABLES:
        old = _read_csv(t)
        old = old[old.asset_id.isin(keep_platform)] if not old.empty else old
        new = schild[t]
        merged = pd.concat([old, new[old.columns] if not old.empty else new], ignore_index=True)
        _write_csv(t, merged)
    ds_old = _read_csv("data_sources")
    ds = pd.concat([ds_old, ssrc.astype(str)[~ssrc.source_id.isin(ds_old.get("source_id", []))]], ignore_index=True)
    _write_csv("data_sources", ds)

    # registry: the user's 60 + platform-only packs + test cases
    reg = sreg.copy()
    reg["registry_source"] = SRC_USER
    for c in ("manufacture_date", "commissioning_date", "warranty_end_date", "latest_assessment_date"):
        reg[c] = pd.to_datetime(reg[c]).dt.strftime("%Y-%m-%d")
    rows = [r for _, r in reg.iterrows()]
    health = _read_csv("health_history")
    for pid in platform_ids:
        if pid not in repo_ids:
            rows.append(pd.Series(_platform_registry(asset, health_old, pid)))
    base = reg[reg.asset_id == FLAW_BASE].iloc[0]
    for fid, (_, label) in FLAWS.items():
        r = base.copy()
        r["asset_id"], r["vehicle_id"] = fid, f"TEST-{fid[-2:]}"
        r["lifecycle_status"], r["application"] = "", base["application"]
        r["demo_status"] = f"SYNTHETIC TEST CASE - injected data fault: {label}"
        r["registry_source"] = SRC_TEST
        rows.append(r)
    regdf = pd.DataFrame(rows)[list(REGISTRY_COLUMNS)].astype(str).replace({"nan": "", "None": "", "NaT": ""})
    _write_csv("battery_registry", regdf)

    # battery_asset: generated from the registry for every pack except platform-only ones (their record is the source)
    out = [r for r in asset.itertuples(index=False) if r.asset_id in keep_platform and r.asset_id not in repo_ids]
    out = [[r.asset_id, r.field, r.value] for r in out]
    for _, r in regdf.iterrows():
        if r.registry_source != SRC_PLATFORM:
            out += _asset_rows(r)
    _write_csv("battery_asset", pd.DataFrame(out, columns=["asset_id", "field", "value"]))

    # test cases: health history (and modules/materials for the pack page) cloned from the base pack
    health = _read_csv("health_history")
    health = health[~health.asset_id.isin(test_ids)]
    bh = health[health.asset_id == FLAW_BASE].sort_values("assessment_date")
    add = []
    for fid, (fault, _) in FLAWS.items():
        h = bh.copy()
        h["asset_id"] = fid
        if fault == "capacity_disagreement":     # the newest capacity test says 70 % while the telemetry shows the base pack
            i = h.index[-1]
            rated = float(h.at[i, "rated_capacity_Ah"])
            h.at[i, "measured_capacity_Ah"] = f"{0.70 * rated:.1f}"
            h.at[i, "soh_pct"] = "70.0"
        add.append(h)
    _write_csv("health_history", pd.concat([health, *add], ignore_index=True))
    for t in ("modules", "materials_recycling"):
        d = _read_csv(t)
        d = d[~d.asset_id.isin(test_ids)]
        b = d[d.asset_id == FLAW_BASE]
        _write_csv(t, pd.concat([d, *[b.assign(asset_id=fid) for fid in FLAWS]], ignore_index=True))
    notes.append(f"imported {len(repo_ids)} packs from {src.name}; platform packs kept: {len(platform_ids)}; "
                 f"test cases: {len(FLAWS)}; conflicts: {conflicts or 'none'}")
    return notes


# ---------------------------------------------------------------------------------------------------------------
# telemetry_dense
# ---------------------------------------------------------------------------------------------------------------

def _seed(asset_id: str) -> int:
    return zlib.crc32(asset_id.encode()) & 0x7FFFFFFF


def _num(v, default=None):
    try:
        x = float(v)
        return x if np.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def densify(con: duckdb.DuckDBPyConnection) -> tuple[pd.DataFrame, list[str]]:
    from revive_ml.synth import current_profile, ocv_cell     # the engine's documented synthetic physics

    reg = con.execute("SELECT * FROM battery_registry ORDER BY asset_id").df()
    health = con.execute("SELECT * FROM health_history").df()
    events = con.execute("SELECT asset_id, event_type, observed_value FROM safety_events").df()
    orig = con.execute("SELECT asset_id, min(timestamp_utc) AS t0, avg(ambient_temp_C) AS amb FROM telemetry GROUP BY 1").df()
    orig = orig.set_index("asset_id")
    notes, frames = [], []
    for _, r in reg.iterrows():
        aid = r.asset_id
        chem = CHEM.get(str(r.chemistry))
        m = re.fullmatch(r"\s*(\d+)s(\d+)p\s*", str(r.series_parallel_configuration))
        if chem is None or m is None:
            notes.append(f"{aid}: not densified (chemistry {r.chemistry!r} or configuration unmapped)")
            continue
        series = int(m.group(1))
        rated = _num(r.nominal_capacity_Ah)
        hid = FLAW_BASE if FLAWS.get(aid, ("",))[0] == "capacity_disagreement" else aid
        h = health[health.asset_id == hid].sort_values("assessment_date")
        if rated is None or h.empty:
            notes.append(f"{aid}: not densified (no rated capacity or no capacity test)")
            continue
        last = h.iloc[-1]
        true_cap = float(last.measured_capacity_Ah)
        r_pack = (_num(last.internal_resistance_mOhm, 2.0)) / 1000.0
        rng = np.random.default_rng(_seed(aid))
        n, dt = DENSE_ROWS, DENSE_DT_S
        i = current_profile(n, dt, rated, rng)
        vmin, vmax = _num(r.min_voltage_V), _num(r.max_voltage_V)
        # CC-CV charging and BMS power derating, as a real charger/BMS would: the terminal voltage is held inside the
        # pack's registry window instead of being clipped afterwards (the limits are the pack's own, not tuned values)
        v_hi = (vmax if vmax else series * 4.2) * CV_MARGIN_HIGH
        v_lo = (vmin if vmin else 0.0) * CV_MARGIN_LOW
        soc = np.empty(n)
        soc[0] = 0.8
        for k in range(1, n):
            if soc[k - 1] >= 0.95 and i[k] > 0:
                i[k] = 0.0
            ocv = series * float(ocv_cell(np.array([soc[k - 1]]), chem)[0])
            if i[k] > 0 and ocv + i[k] * r_pack > v_hi:
                i[k] = max(0.0, (v_hi - ocv) / r_pack)
            elif i[k] < 0 and ocv + i[k] * r_pack < v_lo:
                i[k] = min(0.0, (v_lo - ocv) / r_pack)
            soc[k] = soc[k - 1] + 0.5 * (i[k] + i[k - 1]) * dt / 3600 / true_cap
        v = series * ocv_cell(soc, chem) + i * r_pack + rng.normal(0, 0.02 * series / 96, n)
        if vmin is not None and vmax is not None and (v.min() < vmin or v.max() > vmax):
            notes.append(f"{aid}: dense voltage {v.min():.1f}-{v.max():.1f} V leaves the registry window "
                         f"{vmin}-{vmax} V (kept, not clipped)")
        amb = _num(orig.amb.get(aid) if aid in orig.index else None, 25.0)
        temp = np.empty(n)
        temp[0] = amb + 1.0
        heat_cap = HEAT_CAP_J_PER_K_PER_100AH * (rated / 100)
        hcoef = COOLING_W_PER_K_PER_100AH * (rated / 100)
        for k in range(1, n):
            q = i[k] ** 2 * r_pack - hcoef * (temp[k - 1] - amb)
            temp[k] = temp[k - 1] + q * dt / heat_cap
        temp += rng.normal(0, 0.05, n)
        ev = events[(events.asset_id == aid) & (events.event_type == "CELL_TEMPERATURE_WARNING")]
        for obs in ev.observed_value:                      # a matching recorded excursion, shaped as a smooth bump
            peak = _num(re.sub(r"[^0-9.\-]", "", str(obs)))
            if peak is not None and peak > temp.max():
                centre = int(n * 0.30)
                temp += (peak - temp.max()) * np.exp(-0.5 * ((np.arange(n) - centre) / 25.0) ** 2)
        t0 = orig.t0.get(aid) if aid in orig.index else None
        start = pd.Timestamp(t0).tz_convert("UTC").floor("min") if t0 is not None and pd.notna(t0) \
            else pd.Timestamp("2026-10-20T08:00:00Z")
        ts = start + pd.to_timedelta(np.arange(n) * dt, unit="s")
        drive = (np.arange(n) * dt >= 600) & (np.arange(n) * dt < 4200)
        state = np.where(i < -1e-9, "DRIVING", np.where(i > 1e-9, "CHARGING", "IDLE"))
        state = np.where(drive & (i > 0), "REGENERATIVE_BRAKING", state)
        df = pd.DataFrame({
            "timestamp_utc": ts, "asset_id": aid, "soc_pct": (soc * 100).round(2), "soh_pct": float(last.soh_pct),
            "pack_voltage_V": v.round(3), "pack_current_A": i.round(3), "max_cell_temp_C": temp.round(2),
            "min_cell_temp_C": (temp - 1.2 - 0.6 * np.abs(i) / rated + rng.normal(0, 0.05, n)).round(2),
            "ambient_temp_C": (amb + 0.002 * np.arange(n)).round(3), "power_kW": (v * i / 1000).round(4),
            "operating_state": state, "data_class": "SYNTHETIC",
            "source": "densified from battery_registry + health_history (revive_ml.synth physics)",
        })
        fault = FLAWS.get(aid, (None,))[0]
        if fault == "sign_flip":            # a consistent convention is not a fault; a flip mid-record is
            df.loc[FLIP_FROM_ROW:, "pack_current_A"] *= -1
            df.loc[FLIP_FROM_ROW:, "power_kW"] *= -1
        elif fault == "gap":                # the logger stops for an hour; no reading is removed or invented
            df.loc[GAP_FROM_ROW:, "timestamp_utc"] += pd.Timedelta(minutes=GAP_MINUTES)
        elif fault == "stuck_voltage":
            df.loc[300:419, "pack_voltage_V"] = df.at[300, "pack_voltage_V"]
        elif fault == "temp_spike":
            for k in (250, 520, 760):
                df.at[k, "max_cell_temp_C"] += 25.0
        elif fault == "null_voltage":
            df.loc[df.index % 7 == 3, "pack_voltage_V"] = np.nan
        if fault:
            df["source"] = f"densified test case with injected fault: {FLAWS[aid][1]}"
        frames.append(df)
    return pd.concat(frames, ignore_index=True), notes


VIEWS = {
    "fleet_summary": """
        CREATE OR REPLACE VIEW fleet_summary AS
        SELECT r.asset_id, r.chemistry, r.application, r.lifecycle_status, r.registry_source,
               h.soh_pct AS latest_test_soh_pct, h.cycle_count,
               (SELECT count(*) FROM safety_events e WHERE e.asset_id = r.asset_id AND upper(e.status) = 'OPEN') AS open_safety_events,
               (SELECT count(*) FROM telemetry t WHERE t.asset_id = r.asset_id) AS telemetry_rows,
               (SELECT count(*) FROM telemetry_dense d WHERE d.asset_id = r.asset_id) AS telemetry_dense_rows
        FROM battery_registry r
        LEFT JOIN (SELECT * FROM health_history QUALIFY row_number() OVER (PARTITION BY asset_id ORDER BY assessment_date DESC) = 1) h
          ON h.asset_id = r.asset_id""",
    "pack_history": """
        CREATE OR REPLACE VIEW pack_history AS
        SELECT asset_id, assessment_date, cycle_count, soh_pct, internal_resistance_mOhm AS resistance_mohm
        FROM health_history ORDER BY asset_id, assessment_date""",
}
RUNTIME_DDL = [
    """CREATE TABLE IF NOT EXISTS assessments (id VARCHAR PRIMARY KEY, created_utc TIMESTAMPTZ, battery_id VARCHAR,
       engine VARCHAR, decision VARCHAR, readiness VARCHAR, gate VARCHAR, soh_pct DOUBLE, summary_json VARCHAR,
       report_json VARCHAR)""",
    """CREATE TABLE IF NOT EXISTS ml_suggestions (id VARCHAR PRIMARY KEY, created_utc TIMESTAMPTZ, battery_id VARCHAR,
       assessment_id VARCHAR, engine VARCHAR, status VARCHAR, top_application VARCHAR, advice_json VARCHAR)""",
    """CREATE TABLE IF NOT EXISTS fleet_reports (asset_id VARCHAR, generated_utc TIMESTAMPTZ, engine VARCHAR,
       telemetry_source VARCHAR, decision VARCHAR, disposition VARCHAR, soh_pct DOUBLE, rul_cycles DOUBLE,
       net_value_usd DOUBLE, confidence VARCHAR, registry_status VARCHAR, rule_agrees BOOLEAN, rule_reason VARCHAR,
       report_json VARCHAR)""",
]


def finish_db(con: duckdb.DuckDBPyConnection) -> list[str]:
    dense, notes = densify(con)
    con.execute("DROP TABLE IF EXISTS telemetry_dense")
    con.register("dense_in", dense)
    con.execute("CREATE TABLE telemetry_dense AS SELECT * FROM dense_in")
    con.unregister("dense_in")
    con.execute('CREATE INDEX "idx_telemetry_dense_asset_id" ON telemetry_dense (asset_id, timestamp_utc)')
    for sql in VIEWS.values():
        con.execute(sql)
    for sql in RUNTIME_DDL:
        con.execute(sql)
    n = con.execute("SELECT count(DISTINCT asset_id), count(*) FROM telemetry_dense").fetchone()
    notes.append(f"telemetry_dense: {n[1]:,} rows for {n[0]} packs")
    return notes


def main() -> int:
    sys.path.insert(0, str(HERE))
    import build_relational_db as build

    notes: list[str] = []
    src = find_source()
    if src:
        notes += refresh_csvs(src)
    else:
        notes.append("user's fleet DB not found (set REVIVE_FLEET_SRC); the committed CSV bundle is used as it is")
    build.DB_PATH = DB_PATH
    rc = build.main()
    if rc:
        return rc
    with duckdb.connect(str(DB_PATH)) as con:
        notes += finish_db(con)
        n_assets = con.execute("SELECT count(*) FROM battery_registry").fetchone()[0]
    for line in notes:
        log(line)
    log(f"done: {n_assets} packs in {DB_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
