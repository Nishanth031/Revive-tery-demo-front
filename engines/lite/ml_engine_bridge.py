"""Bridge from REVIVE-TERY data to the full ML engine (revive-tery-ml), shared by the dashboard and the backend.

Turns the project's data into the engine's data contract (a Bundle), and summarises the engine's report.
It refuses, with a reason, rather than inventing what the contract needs: no timestamps means no full
assessment, and callers fall back to the lite analyzer (ml_analyzer_suggester.py) and say why.

The engine is optional for the dashboard: if revive_ml isn't installed, ENGINE_AVAILABLE is False and
ENGINE_IMPORT_ERROR says why, and the dashboard keeps working with the lite analyzer alone.
"""
from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd

try:
    from revive_ml import __version__ as ENGINE_VERSION
    from revive_ml.config import load as load_cfg
    from revive_ml.contract import Bundle, CapacityTest, ContractError, Metadata, load_bundle, validate_telemetry
    from revive_ml.convert import convert_demo
    from revive_ml.pipeline import assess as full_assess
    from revive_ml.state.rules import rule_route
    ENGINE_AVAILABLE = True
    ENGINE_IMPORT_ERROR = ""
except ImportError as exc:  # The dashboard still runs, with the lite analyzer only.
    ENGINE_AVAILABLE = False
    ENGINE_IMPORT_ERROR = (f"the full ML engine (revive-tery-ml) isn't installed in this Python: {exc}. "
                           "Install it with: pip install -e ../revive-tery-ml")
    ENGINE_VERSION = None

CELL_NOMINAL_V = {"LFP": 3.2, "NMC": 3.65, "NCA": 3.6}
MAX_CAPACITY_TESTS = 50
MIN_TIMESTAMP_COVERAGE = 0.95
CONTRACT_FILES = ("metadata.json", "telemetry.csv", "telemetry.parquet")


class AdapterError(ValueError):
    """The data cannot be turned into a contract bundle. The message says what is missing."""


def run_full(bundle: Bundle, workloads: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the full engine on a bundle (raises if the engine isn't installed)."""
    if not ENGINE_AVAILABLE:
        raise AdapterError(ENGINE_IMPORT_ERROR)
    return full_assess(bundle, workloads)


class Spec(Protocol):
    """What an upload cannot say about the battery. The backend's SpecIn and the dashboard's form both fit."""
    chemistry: str
    series_cells: int
    parallel_cells: int
    rated_capacity_ah: float | None
    nominal_voltage_v: float | None


def _require_engine() -> None:
    if not ENGINE_AVAILABLE:
        raise AdapterError(ENGINE_IMPORT_ERROR)


def _iso(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------------------
# Adapters: REVIVE-TERY data -> revive-tery-ml bundle
# --------------------------------------------------------------------------------------

TELEMETRY_SOURCES = ("dense", "original")


def _telemetry_table(con: Any, battery_id: str, telemetry_source: str) -> str:
    """'dense' reads telemetry_dense (SYNTHETIC, densified by engines/database/import_fleet.py) when the pack has rows
    there; 'original' (or a database without that table) reads the pack's original telemetry rows."""
    if telemetry_source not in TELEMETRY_SOURCES:
        raise AdapterError(f"telemetry_source must be one of {TELEMETRY_SOURCES}")
    if telemetry_source == "dense":
        has = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'telemetry_dense'").fetchone()[0]
        if has and con.execute("SELECT count(*) FROM telemetry_dense WHERE asset_id = ?", [battery_id]).fetchone()[0]:
            return "telemetry_dense"
    return "telemetry"


def bundle_from_database(con: Any, battery_id: str, telemetry_source: str = "dense") -> Bundle:
    """A battery with asset records (the demo pack), read through an open DuckDB connection.

    The tables are dumped as they are and converted by revive_ml's own explicit column mapping.
    telemetry_source: 'dense' (default; the densified SYNTHETIC series when the pack has one) or 'original'.
    """
    _require_engine()
    cols = {r[0].lower() for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'battery_asset'").fetchall()}
    asset = (con.execute("SELECT field, value FROM battery_asset WHERE asset_id = ?", [battery_id]).df()
             if "asset_id" in cols else con.execute("SELECT field, value FROM battery_asset").df())
    if dict(zip(asset["field"], asset["value"])).get("asset_id") != battery_id:
        raise AdapterError(f"{battery_id}: no asset record in battery_asset")
    table = _telemetry_table(con, battery_id, telemetry_source)
    telemetry = con.execute(f"SELECT * FROM {table} WHERE asset_id = ? ORDER BY timestamp_utc", [battery_id]).df()
    telemetry = telemetry.drop(columns=["source"], errors="ignore")    # provenance note of telemetry_dense, not a reading
    health = con.execute("SELECT * FROM health_history WHERE asset_id = ? ORDER BY assessment_date",
                         [battery_id]).df()
    events = con.execute("SELECT * FROM safety_events WHERE asset_id = ? ORDER BY timestamp_utc", [battery_id]).df()
    if telemetry.empty:
        raise AdapterError(f"{battery_id}: no telemetry rows")
    telemetry["timestamp_utc"] = _iso(telemetry["timestamp_utc"])
    if not events.empty:
        events["timestamp_utc"] = _iso(events["timestamp_utc"])
    health["assessment_date"] = health["assessment_date"].astype(str)
    with tempfile.TemporaryDirectory(prefix="revive_bundle_") as tmp:
        src, out = Path(tmp) / "src", Path(tmp) / "bundle"
        src.mkdir()
        asset.to_csv(src / "battery_asset.csv", index=False)
        telemetry.to_csv(src / "telemetry.csv", index=False)
        health.to_csv(src / "health_history.csv", index=False)
        events.to_csv(src / "safety_events.csv", index=False)
        try:
            return load_bundle(convert_demo(src, out))
        except (ContractError, KeyError, ValueError) as exc:
            raise AdapterError(f"{battery_id}: could not convert the database tables: {exc}") from exc


def bundle_from_rows(df: pd.DataFrame, battery_id: str, spec: Spec, source: str) -> Bundle:
    """Uploaded telemetry rows (the ml_telemetry table) -> bundle.

    Refuses, with reasons, rather than inventing what is missing. `source` names the caller in the
    bundle's metadata, so a report says where its bundle was built.
    """
    _require_engine()
    if df.empty:
        raise AdapterError(f"{battery_id}: no uploaded rows")
    if {"source_file", "row_in_file", "ingest_id"} <= set(df.columns):
        # The same file uploaded again is appended under a new ingest_id. Keep only its latest copy;
        # otherwise every timestamp appears twice and the engine rightly rejects the data.
        df = (df.sort_values("ingest_id", kind="stable")
                .drop_duplicates(["source_file", "row_in_file"], keep="last")
                .sort_values(["source_file", "row_in_file"], kind="stable")
                .reset_index(drop=True))
    problems: list[str] = []
    ts = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce") if "timestamp_utc" in df else None
    if ts is None or ts.notna().mean() < MIN_TIMESTAMP_COVERAGE:
        problems.append("no usable timestamp_utc column (the full engine integrates over real time steps)")
    for col in ("voltage_v", "current_a"):
        if col not in df or df[col].notna().mean() < 0.95:
            problems.append(f"{col} is missing for more than 5 % of rows")
    chem = spec.chemistry
    rated = spec.rated_capacity_ah
    cap = df.dropna(subset=["capacity_ah", "cycle_index"]) if {"capacity_ah", "cycle_index"} <= set(df.columns) \
        else df.iloc[0:0]
    if rated is None and not cap.empty:
        first = cap.groupby("cycle_index")["capacity_ah"].max().sort_index().iloc[:5]
        rated = float(first.max())
    if rated is None:
        problems.append("rated capacity unknown: enter it, or upload per-cycle capacity")
    if problems:
        raise AdapterError("; ".join(problems))

    prov = "measured" if (df["data_provenance"] == "measured").all() else \
        "simulated" if (df["data_provenance"] == "simulated").any() and not (df["data_provenance"] == "synthetic").any() \
        else "synthetic"
    series = spec.series_cells
    lim = load_cfg("limits.yaml")["chemistries"][chem]
    nominal = spec.nominal_voltage_v or CELL_NOMINAL_V[chem] * series
    tel = pd.DataFrame({
        "asset_id": battery_id, "timestamp_utc": ts, "voltage_v": df["voltage_v"].astype(float),
        "current_a": df["current_a"].astype(float),
        "temperature_c": df["temperature_c"].astype(float) if "temperature_c" in df else np.nan,
    })
    if "soc_pct" in df and df["soc_pct"].notna().any():
        tel["soc_pct"] = df["soc_pct"].astype(float)
    # firmware v1.1 "ambient" (second DS18B20): passed through when the rows carry it, never invented
    amb = next((c for c in ("ambient_temperature_c", "ambient_c", "ambient") if c in df), None)
    if amb is not None and df[amb].notna().any():
        tel["ambient_temperature_c"] = pd.to_numeric(df[amb], errors="coerce")
    tel = tel.dropna(subset=["timestamp_utc"])

    tests: list[CapacityTest] = []
    if not cap.empty:
        per_cycle = cap.assign(ts=pd.to_datetime(cap["timestamp_utc"], utc=True, errors="coerce")) \
            .groupby("cycle_index").agg(capacity=("capacity_ah", "max"), ts=("ts", "min")).sort_index()
        per_cycle = per_cycle[per_cycle["capacity"] > 0].dropna(subset=["ts"])
        if len(per_cycle) > MAX_CAPACITY_TESTS:
            per_cycle = per_cycle.iloc[np.unique(np.linspace(0, len(per_cycle) - 1, MAX_CAPACITY_TESTS).astype(int))]
        tests = [CapacityTest(date=row.ts.date(), cycle_count=int(idx), measured_capacity_ah=float(row.capacity),
                              method="uploaded cycler log (max discharge capacity in the cycle)", provenance=prov)
                 for idx, row in per_cycle.iterrows()]
    try:
        meta = Metadata(
            asset_id=battery_id, chemistry=chem, rated_capacity_ah=rated, nominal_voltage_v=nominal,
            min_voltage_v=lim["cell_v_min"]["value"] * series, max_voltage_v=lim["cell_v_max"]["value"] * series,
            series_cells=series, parallel_cells=spec.parallel_cells, data_provenance=prov,
            current_sign_convention="unknown",
            cycle_count=int(df["cycle_index"].max()) if "cycle_index" in df and df["cycle_index"].notna().any() else None,
            capacity_tests=tests,
            notes=f"Built from an upload by {source}; rated capacity "
                  + ("entered by the user" if spec.rated_capacity_ah else "taken from the first cycles (assumed)"),
            source=f"{source} upload adapter",
        )
        tel, ignored = validate_telemetry(tel.reset_index(drop=True), battery_id)
    except (ContractError, ValueError) as exc:
        raise AdapterError(f"upload does not fit the data contract: {exc}") from exc
    return Bundle(meta=meta, telemetry=tel, ignored_columns=ignored)


def is_contract_zip(zip_path: Path) -> bool:
    """True for a zip that holds a data-contract bundle (metadata.json plus telemetry)."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = {Path(m.filename).name for m in zf.infolist() if not m.is_dir()}
    except (zipfile.BadZipFile, OSError):
        return False
    return "metadata.json" in names and bool(names & {"telemetry.csv", "telemetry.parquet"})


def bundle_from_zip(zip_path: Path, max_bytes: int) -> Bundle:
    """A contract bundle zipped as-is: metadata.json plus telemetry.csv or telemetry.parquet."""
    _require_engine()
    with tempfile.TemporaryDirectory(prefix="revive_zip_") as tmp:
        root = Path(tmp).resolve()
        try:
            with zipfile.ZipFile(zip_path) as zf:
                members = [m for m in zf.infolist() if not m.is_dir()]
                if sum(m.file_size for m in members) > max_bytes:
                    raise AdapterError("zip expands beyond the size limit")
                for m in members:
                    name = Path(m.filename).name
                    if name in CONTRACT_FILES:
                        target = (root / name).resolve()
                        if target.parent == root:   # basename only: no path tricks from inside the zip
                            target.write_bytes(zf.read(m))
        except zipfile.BadZipFile as exc:
            raise AdapterError(f"not a valid zip: {exc}") from exc
        try:
            return load_bundle(root)
        except ContractError as exc:
            raise AdapterError(f"bundle rejected by the data contract: {exc}") from exc


# --------------------------------------------------------------------------------------
# Summaries, so both engines can be shown and compared the same way
# --------------------------------------------------------------------------------------

def capacity_test_soh(bundle: Bundle | None) -> float | None:
    """SOH from the newest capacity test, whether or not the engine trusted the data enough to use it."""
    if bundle is None or not bundle.meta.capacity_tests:
        return None
    latest = max(bundle.meta.capacity_tests, key=lambda c: (c.date, c.cycle_count or 0))
    return round(100 * latest.measured_capacity_ah / bundle.meta.rated_capacity_ah, 2)


def _legacy_rule(soh: float | None) -> str | None:
    return rule_route(soh) if ENGINE_AVAILABLE else None


def summarize_full(report: dict[str, Any], bundle: Bundle | None = None) -> dict[str, Any]:
    state = report.get("state") or {}
    soh = (state.get("soh") or {}).get("value")          # only set when the data passed the checks and the gate
    test_soh = capacity_test_soh(bundle)
    rec = report.get("recommendation") or {}
    checks = report["data_quality"]["checks"]
    return {
        "engine": "full", "decision": report["decision"], "rationale": report.get("rationale") or [],
        "application": rec.get("label"), "readiness": report["data_quality"]["readiness"]["verdict"],
        "gate": (report.get("gate") or {}).get("verdict"), "soh_pct": soh,
        "capacity_test_soh_pct": test_soh,
        # what the old fixed-threshold rule would have said from the capacity test alone
        "legacy_rule": _legacy_rule(soh if soh is not None else test_soh), "data_provenance": report["data_provenance"],
        "failed_checks": [{"id": c["id"], "message": c["message"]} for c in checks if c["status"] == "fail"],
        "inconclusive_checks": [{"id": c["id"], "message": c["message"]} for c in checks if c["status"] == "inconclusive"],
        "warnings": report["warnings"],
        "placeholder_inputs": (report.get("economics") or {}).get("placeholder_inputs", []),
    }


def summarize_lite(report: dict[str, Any], notes: list[str]) -> dict[str, Any]:
    sug = report.get("suggestion") or {}
    soh = ((report.get("state") or {}).get("soh") or {}).get("value")
    return {
        "engine": "lite", "decision": sug.get("decision"), "rationale": [sug.get("reason", "")],
        "application": sug.get("use_case"), "readiness": "NOT_ASSESSED (lite engine has no readiness rules)",
        "gate": (report.get("safety_gate") or {}).get("verdict"), "soh_pct": soh, "legacy_rule": _legacy_rule(soh),
        "data_provenance": report.get("data_provenance"), "failed_checks": [], "inconclusive_checks": [],
        "warnings": [*notes, *report.get("warnings", [])], "placeholder_inputs": sug.get("placeholder_inputs", []),
    }
