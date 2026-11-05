"""
ml_analyzer_suggester.py - REVIVE-TERY batch ingestion, DuckDB seeding and second-life suggester.

Architecture (batch only, no live hardware):
    uploaded .zip / .csv / .xlsx
        -> BatteryFileExtractor   (extract, parse, map headers to a standard schema)
        -> DuckDBSeeder           (append into data/database/revive_tery.duckdb)
        -> SecondLifeSuggester    (safety gate -> state estimation -> economic suggestion)
        -> JSON-serialisable dict (or a flat DataFrame) for the Streamlit frontend

Design rules this module follows:
  * Header mapping uses an EXPLICIT alias table. Unknown columns are reported, never guessed.
  * Current sign is never flipped; voltage/current/temperature values are stored as received.
  * Seeding only creates/appends its OWN tables (ml_telemetry, ml_ingest_log). Existing demo
    tables (telemetry, battery_asset, ...) are never altered or dropped.
  * SoH is computed only from capacity data. Without capacity data the suggester returns
    "Insufficient data" instead of inventing a health value from voltage alone.
  * Every economic input is a PLACEHOLDER in ECONOMICS below and is reported as such.
  * The safety gate is triage, not certification ("UL 1974-style triage").
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

# --------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------

DEFAULT_DB_PATH = Path(os.environ.get("REVIVE_DB") or Path(__file__).resolve().parents[2] / "data" / "db" / "revive_tery.duckdb")
TELEMETRY_TABLE = "ml_telemetry"   # owned by this module; never the demo "telemetry" table
LOG_TABLE = "ml_ingest_log"

SUPPORTED_SUFFIXES = {".csv", ".xlsx", ".xls"}
MAX_ZIP_MEMBERS = 500                     # zip-bomb guards
MAX_UNCOMPRESSED_BYTES = 2 * 1024 ** 3    # 2 GB

# Standard schema -> accepted header aliases (after normalisation, see _normalise_header).
# Add aliases here; the extractor never maps a column that is not listed.
COLUMN_ALIASES: dict[str, list[str]] = {
    "battery_id": ["battery_id", "asset_id", "cell_id", "cell", "battery", "barcode", "pack_id"],
    "timestamp_utc": ["timestamp_utc", "timestamp", "datetime", "date_time", "time_utc"],
    "test_time_s": ["test_time_s", "test_time", "time_s", "time", "elapsed_time_s", "time_sec"],
    "cycle_index": ["cycle_index", "cycle", "cycle_number", "cycle_no", "cycle_count", "cycle_id"],
    "voltage_v": ["voltage_v", "voltage", "pack_voltage_v", "cell_voltage_v", "voltage_measured",
                  "v", "terminal_voltage", "batt_voltage"],
    "current_a": ["current_a", "current", "pack_current_a", "current_measured", "i", "batt_current"],
    "temperature_c": ["temperature_c", "temperature", "temp_c", "temp", "max_cell_temp_c",
                      "temperature_measured", "cell_temperature_c"],
    "capacity_ah": ["capacity_ah", "capacity", "discharge_capacity_ah", "discharge_capacity",
                    "measured_capacity_ah", "qd", "qdischarge"],
    "soc_pct": ["soc_pct", "soc", "state_of_charge"],
}
REQUIRED_FOR_ANALYSIS = ("voltage_v",)   # minimum to store a file; analysis checks more later

# Chemistry-specific triage limits per CELL (datasheet-style values; verify for your cells).
SAFETY_LIMITS: dict[str, dict[str, float]] = {
    "LFP": {"cell_v_min": 2.0, "cell_v_max": 3.65, "temp_max_c": 60.0, "temp_spike_c": 5.0},
    "NMC": {"cell_v_min": 2.75, "cell_v_max": 4.25, "temp_max_c": 60.0, "temp_spike_c": 5.0},
    "NCA": {"cell_v_min": 2.5, "cell_v_max": 4.25, "temp_max_c": 60.0, "temp_spike_c": 5.0},
}

# Second-life use cases: minimum SoH and illustrative duty (all ASSUMED).
USE_CASES: list[dict[str, Any]] = [
    {"name": "Residential solar storage", "category": "Second-Life Reuse", "min_soh": 80.0,
     "cycles_per_year": 300, "dod": 0.8},
    {"name": "Commercial peak shaving", "category": "Second-Life Reuse", "min_soh": 75.0,
     "cycles_per_year": 450, "dod": 0.9},
    {"name": "Telecom / UPS backup", "category": "Second-Life Reuse", "min_soh": 70.0,
     "cycles_per_year": 50, "dod": 0.5},
    {"name": "Low-speed EV / e-rickshaw", "category": "Second-Life Reuse", "min_soh": 70.0,
     "cycles_per_year": 300, "dod": 0.8},
    {"name": "Module-level repurpose (street lights, small backup)", "category": "Repurpose",
     "min_soh": 60.0, "cycles_per_year": 365, "dod": 0.6},
]
END_OF_USE_SOH = 60.0   # below this the pack is recycled (assumed)

# Economic inputs. PLACEHOLDERS: replace with your own tariffs and quotes before real use.
ECONOMICS: dict[str, dict[str, Any]] = {
    "value_per_kwh_delivered_usd": {"value": 0.08, "status": "PLACEHOLDER"},
    "refurbishment_usd_per_kwh": {"value": 40.0, "status": "PLACEHOLDER"},
    "repurpose_extra_usd_per_kwh": {"value": 20.0, "status": "PLACEHOLDER"},
    "new_storage_installed_usd_per_kwh": {"value": 236.0, "status": "indicative (BNEF US system survey)"},
    "new_storage_life_years": {"value": 15.0, "status": "assumed"},
    "recycle_net_usd_per_kwh": {"value": 5.0, "status": "PLACEHOLDER"},
    "discount_rate": {"value": 0.08, "status": "assumed"},
    "max_second_life_years": {"value": 10.0, "status": "assumed"},
}


# --------------------------------------------------------------------------------------
# 1. Extractor
# --------------------------------------------------------------------------------------

class IngestionError(RuntimeError):
    """Raised when an uploaded file cannot be extracted or parsed."""


def _normalise_header(name: Any) -> str:
    """'Pack Voltage (V)' -> 'pack_voltage_v'; 'Temp [°C]' -> 'temp_c'."""
    s = str(name).strip().lower().replace("°", "")
    s = re.sub(r"[\(\[]\s*([a-z%]+)\s*[\)\]]", r"_\1", s)   # units in brackets become a suffix
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s


_ALIAS_LOOKUP = {alias: std for std, aliases in COLUMN_ALIASES.items() for alias in aliases}


@dataclass
class ExtractedFile:
    """One parsed table plus a record of how its columns were mapped."""

    source: str
    data: pd.DataFrame
    mapping: dict[str, str] = field(default_factory=dict)   # original header -> standard name
    unmapped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class BatteryFileExtractor:
    """Accepts .zip, .csv, .xlsx paths and returns standardised telemetry DataFrames."""

    def extract(self, path: str | Path) -> list[ExtractedFile]:
        path = Path(path)
        if not path.exists():
            raise IngestionError(f"file not found: {path}")
        suffix = path.suffix.lower()
        if suffix == ".zip":
            return self._extract_zip(path)
        if suffix in SUPPORTED_SUFFIXES:
            return [x for x in self._parse_table(path, path.name) if x is not None]
        raise IngestionError(f"unsupported file type {suffix!r}; expected .zip, .csv or .xlsx")

    # -- zip -------------------------------------------------------------------------------
    def _extract_zip(self, path: Path) -> list[ExtractedFile]:
        results: list[ExtractedFile] = []
        try:
            with zipfile.ZipFile(path) as zf, tempfile.TemporaryDirectory(prefix="revive_upload_") as tmp:
                members = [m for m in zf.infolist() if not m.is_dir()]
                if len(members) > MAX_ZIP_MEMBERS:
                    raise IngestionError(f"zip has {len(members)} files (limit {MAX_ZIP_MEMBERS})")
                if sum(m.file_size for m in members) > MAX_UNCOMPRESSED_BYTES:
                    raise IngestionError("zip expands beyond the 2 GB limit")
                root = Path(tmp).resolve()
                for m in members:
                    name = Path(m.filename).name
                    if Path(name).suffix.lower() not in SUPPORTED_SUFFIXES or name.startswith("~$"):
                        continue   # skip READMEs, images, Office lock files
                    target = (root / name).resolve()
                    if target.parent != root:   # zip-slip guard: no paths outside tmp
                        continue
                    target.write_bytes(zf.read(m))
                    results.extend(x for x in self._parse_table(target, f"{path.name}/{m.filename}") if x)
        except zipfile.BadZipFile as exc:
            raise IngestionError(f"{path.name} is not a valid zip archive: {exc}") from exc
        if not results:
            raise IngestionError(f"{path.name} contains no CSV/Excel table with battery telemetry")
        return results

    # -- csv / excel -----------------------------------------------------------------------
    def _parse_table(self, path: Path, label: str) -> list[ExtractedFile | None]:
        try:
            if path.suffix.lower() == ".csv":
                frames = {label: pd.read_csv(path, sep=None, engine="python")}   # sniff delimiter
            else:
                sheets = pd.read_excel(path, sheet_name=None)   # every sheet (needs openpyxl)
                frames = {f"{label}#{name}": df for name, df in sheets.items()}
        except ImportError as exc:
            raise IngestionError(f"reading {path.suffix} needs an extra package: {exc}") from exc
        except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError, OSError) as exc:
            raise IngestionError(f"could not parse {label}: {exc}") from exc
        return [self._standardise(df, src) for src, df in frames.items()]

    def _standardise(self, df: pd.DataFrame, source: str) -> ExtractedFile | None:
        mapping: dict[str, str] = {}
        unmapped: list[str] = []
        for col in df.columns:
            std = _ALIAS_LOOKUP.get(_normalise_header(col))
            if std and std not in mapping.values():
                mapping[col] = std
            else:
                unmapped.append(str(col))
        if not any(std in mapping.values() for std in REQUIRED_FOR_ANALYSIS):
            return None   # not a telemetry table (e.g. a metadata sheet); skipped, not guessed
        out = df[list(mapping)].rename(columns=mapping).copy()
        warnings: list[str] = []
        for c in ("voltage_v", "current_a", "temperature_c", "capacity_ah", "soc_pct", "test_time_s"):
            if c in out:
                before = out[c].isna().sum()
                out[c] = pd.to_numeric(out[c], errors="coerce")
                bad = int(out[c].isna().sum() - before)
                if bad:
                    warnings.append(f"{c}: {bad} non-numeric values set to null")
        if "cycle_index" in out:
            out["cycle_index"] = pd.to_numeric(out["cycle_index"], errors="coerce").astype("Int64")
        if "timestamp_utc" in out:
            out["timestamp_utc"] = pd.to_datetime(out["timestamp_utc"], utc=True, errors="coerce")
        if "battery_id" not in out:
            out["battery_id"] = Path(source.split("#")[0]).stem   # file name identifies the battery
            warnings.append("no battery id column; file name used as battery_id")
        out["battery_id"] = out["battery_id"].astype(str)
        out["source_file"] = source
        out["row_in_file"] = np.arange(len(out))   # preserves recorded order for later analysis
        return ExtractedFile(source, out, {str(k): v for k, v in mapping.items()}, unmapped, warnings)


# --------------------------------------------------------------------------------------
# 2. Database seeding
# --------------------------------------------------------------------------------------

STANDARD_COLUMNS = ["battery_id", "timestamp_utc", "test_time_s", "cycle_index", "voltage_v",
                    "current_a", "temperature_c", "capacity_ah", "soc_pct"]


class DuckDBSeeder:
    """Appends standardised telemetry into this module's own DuckDB tables."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)

    def _connect(self, read_only: bool = False) -> duckdb.DuckDBPyConnection:
        if not read_only:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return duckdb.connect(str(self.db_path), read_only=read_only)

    def ensure_tables(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute(f"""
            CREATE TABLE IF NOT EXISTS {TELEMETRY_TABLE} (
                battery_id VARCHAR, timestamp_utc TIMESTAMPTZ, test_time_s DOUBLE, cycle_index BIGINT,
                voltage_v DOUBLE, current_a DOUBLE, temperature_c DOUBLE, capacity_ah DOUBLE,
                soc_pct DOUBLE, source_file VARCHAR, row_in_file BIGINT, ingest_id VARCHAR,
                data_provenance VARCHAR)""")
        con.execute(f"""
            CREATE TABLE IF NOT EXISTS {LOG_TABLE} (
                ingest_id VARCHAR, ingested_utc TIMESTAMPTZ, source_file VARCHAR, rows BIGINT,
                column_mapping VARCHAR, unmapped_columns VARCHAR, warnings VARCHAR)""")

    def seed(self, files: list[ExtractedFile], data_provenance: str = "synthetic") -> dict[str, Any]:
        """Insert every extracted table. data_provenance: measured | simulated | synthetic."""
        if data_provenance not in ("measured", "simulated", "synthetic"):
            raise ValueError("data_provenance must be measured, simulated or synthetic")
        ingest_id = datetime.now(UTC).strftime("ING-%Y%m%dT%H%M%S%f")
        total = 0
        con = self._connect()
        try:
            self.ensure_tables(con)
            con.execute("BEGIN TRANSACTION")
            for f in files:
                df = f.data.reindex(columns=[*STANDARD_COLUMNS, "source_file", "row_in_file"])
                df["ingest_id"] = ingest_id
                df["data_provenance"] = data_provenance
                con.register("incoming", df)
                con.execute(f"INSERT INTO {TELEMETRY_TABLE} BY NAME SELECT * FROM incoming")
                con.unregister("incoming")
                con.execute(f"INSERT INTO {LOG_TABLE} VALUES (?, ?, ?, ?, ?, ?, ?)",
                            [ingest_id, datetime.now(UTC), f.source, len(df), json.dumps(f.mapping),
                             json.dumps(f.unmapped), json.dumps(f.warnings)])
                total += len(df)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")   # all-or-nothing: a failed upload leaves the DB unchanged
            raise
        finally:
            con.close()
        return {"ingest_id": ingest_id, "rows_inserted": total, "files": [f.source for f in files],
                "battery_ids": sorted({b for f in files for b in f.data["battery_id"].unique()})}

    def load_battery(self, battery_id: str) -> pd.DataFrame:
        con = self._connect(read_only=True)
        try:
            # epoch_ms avoids the pytz dependency DuckDB needs for TIMESTAMPTZ fetches
            df = con.execute(
                f"""SELECT * EXCLUDE (timestamp_utc), epoch_ms(timestamp_utc) AS ts_ms
                    FROM {TELEMETRY_TABLE} WHERE battery_id = ?
                    ORDER BY source_file, row_in_file""", [battery_id]).df()
        except duckdb.CatalogException:
            df = pd.DataFrame()
        finally:
            con.close()
        if "ts_ms" in df:
            df["timestamp_utc"] = pd.to_datetime(df.pop("ts_ms"), unit="ms", utc=True)
        return df


# --------------------------------------------------------------------------------------
# 3. Analyzer & suggester
# --------------------------------------------------------------------------------------

def _tag(value: Any, provenance: str, unit: str | None = None, note: str | None = None) -> dict[str, Any]:
    """Every reported number carries its provenance: measured | synthetic | modelled | assumed."""
    v = None if value is None or (isinstance(value, float) and not np.isfinite(value)) else value
    out: dict[str, Any] = {"value": round(float(v), 4) if isinstance(v, int | float) else v,
                           "provenance": provenance}
    if unit:
        out["unit"] = unit
    if note:
        out["note"] = note
    return out


@dataclass
class BatterySpec:
    """What the data cannot tell us and the user must supply (defaults are illustrative)."""

    chemistry: str = "LFP"
    series_cells: int = 1          # pack voltage / series_cells = average cell voltage
    rated_capacity_ah: float | None = None   # if None, the max of the first 5 cycles is used
    nominal_voltage_v: float | None = None   # pack nominal voltage for kWh; else chemistry default


class SecondLifeSuggester:
    def __init__(self, seeder: DuckDBSeeder | None = None):
        self.seeder = seeder or DuckDBSeeder()

    # -- public API ------------------------------------------------------------------------
    def generate_second_life_suggestion(self, battery_id: str,
                                        spec: BatterySpec | None = None) -> dict[str, Any]:
        spec = spec or BatterySpec()
        df = self.seeder.load_battery(battery_id)
        report: dict[str, Any] = {
            "battery_id": battery_id,
            "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "spec": spec.__dict__,
            "data_quality": {}, "safety_gate": None, "state": None, "economics": None,
            "suggestion": None, "warnings": [],
        }
        if df.empty:
            report["suggestion"] = {"decision": "Insufficient data", "reason": "no rows for this battery"}
            return report
        prov = "measured" if (df["data_provenance"] == "measured").all() else "synthetic"
        report["data_provenance"] = prov
        if prov != "measured":
            report["warnings"].append("Data is synthetic/simulated: the suggestion demonstrates the "
                                      "pipeline, not the condition of a real battery.")
        if spec.chemistry not in SAFETY_LIMITS:
            raise ValueError(f"chemistry must be one of {sorted(SAFETY_LIMITS)}")

        report["data_quality"] = self._data_quality(df, prov)
        gate = self._safety_gate(df, spec, prov)
        report["safety_gate"] = gate
        if gate["verdict"] == "Reject":
            report["suggestion"] = {"decision": "Recycle", "category": "Recycle",
                                    "reason": "hard safety limit breached: " + "; ".join(gate["reasons"])}
            return report
        state = self._estimate_state(df, spec, prov)
        report["state"] = state
        if state["status"] != "ok":
            report["suggestion"] = {"decision": "Insufficient data", "reason": state["reason"]}
            return report
        if gate["verdict"] == "Quarantine":
            report["suggestion"] = {"decision": "Inspection required", "category": None,
                                    "reason": "; ".join(gate["reasons"])}
            return report
        econ = self._economics(state, spec)
        report["economics"] = econ
        report["suggestion"] = econ["suggestion"]
        return report

    @staticmethod
    def to_dataframe(report: dict[str, Any]) -> pd.DataFrame:
        """Flatten a report into (section, item, value, unit, provenance) rows for st.dataframe."""
        rows: list[dict[str, Any]] = []

        def walk(obj: Any, section: str, prefix: str = "") -> None:
            if isinstance(obj, dict) and "provenance" in obj and "value" in obj:
                rows.append({"section": section, "item": prefix, "value": obj["value"],
                             "unit": obj.get("unit", ""), "provenance": obj["provenance"]})
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    walk(v, section, f"{prefix}.{k}" if prefix else k)
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    walk(v, section, f"{prefix}[{i}]")
            else:
                rows.append({"section": section, "item": prefix, "value": obj, "unit": "",
                             "provenance": ""})

        for sec in ("data_quality", "safety_gate", "state", "economics", "suggestion"):
            if report.get(sec) is not None:
                walk(report[sec], sec)
        return pd.DataFrame(rows)

    # -- data quality (minimal; the full engine lives in revive-tery-ml) ----------------------
    @staticmethod
    def _data_quality(df: pd.DataFrame, prov: str) -> dict[str, Any]:
        out: dict[str, Any] = {"rows": int(len(df))}
        for c in ("voltage_v", "current_a", "temperature_c", "capacity_ah"):
            out[f"{c}_null_fraction"] = _tag(float(df[c].isna().mean()) if c in df else 1.0, prov)
        out["has_capacity_data"] = bool(df["capacity_ah"].notna().any())
        out["has_temperature"] = bool(df["temperature_c"].notna().any())
        return out

    # -- 3a. safety gate -------------------------------------------------------------------
    @staticmethod
    def _safety_gate(df: pd.DataFrame, spec: BatterySpec, prov: str) -> dict[str, Any]:
        lim = SAFETY_LIMITS[spec.chemistry]
        cell_v = df["voltage_v"] / max(spec.series_cells, 1)
        reasons, quarantine = [], []
        # ignore exact zeros: those are sensor dropouts, flagged separately below
        live = cell_v[cell_v > 0.1]
        if (live < lim["cell_v_min"]).any():
            reasons.append(f"cell voltage {live.min():.3f} V below {lim['cell_v_min']} V")
        if (live > lim["cell_v_max"]).any():
            reasons.append(f"cell voltage {live.max():.3f} V above {lim['cell_v_max']} V")
        t = df["temperature_c"].dropna()
        if (t > lim["temp_max_c"]).any():
            reasons.append(f"temperature {t.max():.1f} degC above {lim['temp_max_c']} degC")
        jumps = df.groupby("source_file")["temperature_c"].diff().abs()
        n_spikes = int((jumps > lim["temp_spike_c"]).sum())
        if n_spikes:
            quarantine.append(f"{n_spikes} temperature jump(s) > {lim['temp_spike_c']} degC between rows")
        n_drop = int((cell_v <= 0.1).sum())
        if n_drop:
            quarantine.append(f"{n_drop} voltage dropout row(s) (~0 V)")
        if not len(t):
            quarantine.append("no temperature data: thermal behaviour cannot be screened")
        verdict = "Reject" if reasons else "Quarantine" if quarantine else "Pass"
        return {"verdict": verdict, "reasons": reasons + quarantine,
                "wording": "UL 1974-style triage. Screening only, not certification or a safety approval.",
                "min_cell_voltage": _tag(float(live.min()) if len(live) else None, prov, "V"),
                "max_temperature": _tag(float(t.max()) if len(t) else None, prov, "degC"),
                "limits": {k: _tag(v, "assumed") for k, v in lim.items()},
                "note": "pack voltage / series_cells is the AVERAGE cell; a weak cell can be hidden"}

    # -- 3b. state estimation --------------------------------------------------------------
    @staticmethod
    def _estimate_state(df: pd.DataFrame, spec: BatterySpec, prov: str) -> dict[str, Any]:
        out: dict[str, Any] = {"status": "ok"}
        # Internal resistance proxy: slope of dV against dI between consecutive rows (ohmic step).
        dv = df.groupby("source_file")["voltage_v"].diff()
        di = df.groupby("source_file")["current_a"].diff()
        m = dv.notna() & di.notna() & (di.abs() > 1e-3)
        if m.sum() >= 5:
            slope = np.polyfit(di[m], dv[m], 1)[0]   # V per A; sign depends on the current convention
            out["resistance_proxy"] = _tag(abs(slope) * 1000 / max(spec.series_cells, 1), "modelled",
                                           "mOhm per cell", note="|dV/dI| between rows; rough proxy")
        out["voltage_variance"] = _tag(float(df["voltage_v"].var()), prov, "V^2")
        if "temperature_c" in df and df["temperature_c"].notna().any():
            out["temperature_mean"] = _tag(float(df["temperature_c"].mean()), prov, "degC")

        # SoH needs capacity. Use one value per cycle (the max recorded within the cycle).
        cap = df.dropna(subset=["capacity_ah"])
        if cap.empty:
            return {**out, "status": "insufficient",
                    "reason": "no capacity data: SoH cannot be measured (voltage alone is not enough)"}
        if "cycle_index" in cap and cap["cycle_index"].notna().any():
            per_cycle = cap.groupby("cycle_index")["capacity_ah"].max().sort_index()
        else:
            per_cycle = cap["capacity_ah"].reset_index(drop=True)
        per_cycle = per_cycle[per_cycle > 0]
        if per_cycle.empty:
            return {**out, "status": "insufficient", "reason": "capacity values are all zero"}
        rated = spec.rated_capacity_ah or float(per_cycle.iloc[:5].max())
        rated_src = "user-supplied rated capacity" if spec.rated_capacity_ah else \
            "max of the first 5 cycles (no rated capacity given)"
        latest = float(per_cycle.iloc[-5:].median())   # median of recent cycles damps noise
        soh = 100.0 * latest / rated
        out["rated_capacity"] = _tag(rated, "assumed" if not spec.rated_capacity_ah else "measured",
                                     "Ah", note=rated_src)
        out["current_capacity"] = _tag(latest, prov, "Ah", note="median of the last 5 cycles")
        out["soh"] = _tag(soh, "modelled", "%", note="current capacity / rated capacity")
        out["cycles_observed"] = int(len(per_cycle))

        # Capacity fade: linear slope over the most recent 50 cycles, in SoH points per cycle.
        recent = per_cycle.iloc[-50:]
        if len(recent) >= 5:
            x = np.asarray(recent.index if "cycle_index" in cap else np.arange(len(recent)), float)
            fade = -np.polyfit(x, 100.0 * recent.to_numpy() / rated, 1)[0]
            out["fade_rate"] = _tag(fade, "modelled", "SoH points per cycle",
                                    note="linear fit over up to the last 50 cycles")
            if fade > 1e-6:
                out["cycles_to_end_of_use"] = _tag(max(0.0, (soh - END_OF_USE_SOH) / fade), "modelled",
                                                   "cycles", note=f"linear, to {END_OF_USE_SOH:.0f} % SoH; "
                                                   "real fade often accelerates (knee), so treat as optimistic")
        else:
            out["fade_rate"] = _tag(None, "modelled", note="fewer than 5 cycles: fade not estimated")
        return out

    # -- 3c. economic suggester ------------------------------------------------------------
    @staticmethod
    def _economics(state: dict[str, Any], spec: BatterySpec) -> dict[str, Any]:
        e = {k: v["value"] for k, v in ECONOMICS.items()}
        nominal_cell_v = {"LFP": 3.2, "NMC": 3.7, "NCA": 3.6}[spec.chemistry]
        pack_v = spec.nominal_voltage_v or nominal_cell_v * max(spec.series_cells, 1)
        soh = state["soh"]["value"]
        kwh_now = pack_v * state["current_capacity"]["value"] / 1000.0
        fade = (state.get("fade_rate") or {}).get("value") or 0.0
        r = e["discount_rate"]
        recycle_value = e["recycle_net_usd_per_kwh"] * kwh_now

        options = []
        for uc in USE_CASES:
            if soh < uc["min_soh"]:
                continue
            # years until SoH falls below the use case's limit at its cycling rate (linear fade)
            years = ((soh - uc["min_soh"]) / (fade * uc["cycles_per_year"])) if fade > 0 else \
                e["max_second_life_years"]
            years = float(min(years, e["max_second_life_years"]))
            pv_energy = 0.0
            for y in range(int(np.ceil(years))):
                share = min(1.0, years - y)
                soh_y = max(uc["min_soh"], soh - fade * uc["cycles_per_year"] * y)
                kwh_y = kwh_now * soh_y / soh * uc["dod"] * uc["cycles_per_year"] * share
                pv_energy += kwh_y / (1 + r) ** (y + 0.5)
            value = pv_energy * e["value_per_kwh_delivered_usd"]
            # Buy-New cap: never worth more than new storage giving the same service years.
            cap = e["new_storage_installed_usd_per_kwh"] * kwh_now * min(1.0, years / e["new_storage_life_years"])
            cost = kwh_now * (e["refurbishment_usd_per_kwh"]
                              + (e["repurpose_extra_usd_per_kwh"] if uc["category"] == "Repurpose" else 0))
            net = min(value, cap) - cost + recycle_value / (1 + r) ** years   # recycled afterwards
            options.append({
                "use_case": uc["name"], "category": uc["category"],
                "service_years": _tag(years, "modelled", "years"),
                "energy_value": _tag(value, "modelled", "USD"),
                "buy_new_cap": _tag(cap, "modelled", "USD"),
                "refurbishment_cost": _tag(cost, "assumed", "USD"),
                "net_value": _tag(net, "modelled", "USD"),
                # cost per kWh actually delivered, compared with buying new (comparison only)
                "cost_per_kwh_delivered": _tag(cost / pv_energy if pv_energy else None, "modelled", "USD/kWh"),
            })
        new_cost_per_kwh_delivered = e["new_storage_installed_usd_per_kwh"] / (
            e["new_storage_life_years"] * 300 * 0.8)   # residential-like duty for the benchmark

        best = max(options, key=lambda o: o["net_value"]["value"]) if options else None
        if best and best["net_value"]["value"] > recycle_value and best["service_years"]["value"] >= 1:
            cpk = best["cost_per_kwh_delivered"]["value"]
            if cpk is not None and cpk > new_cost_per_kwh_delivered:
                decision = {"decision": "Buy New", "category": "Buy New",
                            "reason": f"reuse costs {cpk:.3f} USD/kWh delivered vs about "
                                      f"{new_cost_per_kwh_delivered:.3f} for new storage; recycle this pack"}
            else:
                decision = {"decision": f"{best['category']}: {best['use_case']}", "category": best["category"],
                            "use_case": best["use_case"],
                            "reason": f"net {best['net_value']['value']:,.0f} USD over "
                                      f"{best['service_years']['value']:.1f} years vs recycling now "
                                      f"{recycle_value:,.0f} USD"}
        else:
            why = "SoH below every use-case threshold" if not options else \
                "no reuse option beats recycling now"
            decision = {"decision": "Recycle", "category": "Recycle", "reason": why}
        decision["placeholder_inputs"] = [k for k, v in ECONOMICS.items() if v["status"] == "PLACEHOLDER"]
        return {"pack_energy_now": _tag(kwh_now, "modelled", "kWh"),
                "recycle_now": _tag(recycle_value, "assumed", "USD"),
                "new_storage_cost_per_kwh_delivered": _tag(new_cost_per_kwh_delivered, "assumed", "USD/kWh"),
                "options": options, "inputs": ECONOMICS, "suggestion": decision}


# --------------------------------------------------------------------------------------
# Convenience: one call for the Streamlit upload handler
# --------------------------------------------------------------------------------------

def ingest_and_suggest(paths: list[str | Path], spec: BatterySpec | None = None,
                       db_path: str | Path = DEFAULT_DB_PATH,
                       data_provenance: str = "synthetic") -> dict[str, Any]:
    """Extract every upload, seed DuckDB in one transaction, then suggest per battery.

    Returns {"ingest": {...}, "errors": [...], "reports": {battery_id: report}}.
    Extraction errors for one file are collected and reported; the other files still load.
    """
    extractor = BatteryFileExtractor()
    files: list[ExtractedFile] = []
    errors: list[str] = []
    for p in paths:
        try:
            files.extend(extractor.extract(p))
        except IngestionError as exc:
            errors.append(str(exc))
    if not files:
        return {"ingest": None, "errors": errors or ["no usable telemetry found"], "reports": {}}
    seeder = DuckDBSeeder(db_path)
    ingest = seeder.seed(files, data_provenance)
    ingest["column_mappings"] = {f.source: {"mapped": f.mapping, "unmapped": f.unmapped,
                                            "warnings": f.warnings} for f in files}
    suggester = SecondLifeSuggester(seeder)
    reports = {b: suggester.generate_second_life_suggestion(b, spec) for b in ingest["battery_ids"]}
    return {"ingest": ingest, "errors": errors, "reports": reports}


if __name__ == "__main__":   # python src/ml_analyzer_suggester.py <file> [<file> ...]
    import sys

    result = ingest_and_suggest(sys.argv[1:])
    print(json.dumps(result, indent=2, default=str))
