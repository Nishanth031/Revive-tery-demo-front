"""Link to the REVIVE-TERY DuckDB database, and upload the CSV bundle into it.

Uses the same tables and indexes as bulid X/src/build_relational_db.py, so the database
stays usable by backend_connector.py. Reads open the file read-only for as short a time as
possible, so other tools can use it too. This module has no Qt code.
"""
from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

from models import BatteryProfile

ROOT = Path(__file__).resolve().parent
DB_FILE_NAME = "revive_tery.duckdb"
KEY_COLUMN = "asset_id"
TIME_COLUMN = "timestamp_utc"
MAX_BACKUPS = 3
MAX_UNZIPPED_BYTES = 2 * 1024**3
SEARCH_LEVELS = 3

# table: columns it must have, in lower case. Other columns are kept as they are.
BUNDLE_SCHEMA = {
    "battery_asset": ("field", "value"),
    "modules": ("module_id", KEY_COLUMN),
    "charge_sessions": ("session_id", KEY_COLUMN, "start_utc"),
    "telemetry": (TIME_COLUMN, KEY_COLUMN, "soc_pct", "pack_voltage_v", "pack_current_a"),
    "health_history": ("assessment_date", KEY_COLUMN, "soh_pct"),
    "safety_events": ("event_id", KEY_COLUMN, TIME_COLUMN, "event_type", "severity"),
    "materials_recycling": (KEY_COLUMN, "material"),
    "data_sources": ("source_id",),
}


class DatabaseError(Exception):
    """A database or upload problem, with a message fit to show the user."""


@dataclass
class DatabaseStatus:
    path: Path | None
    connected: bool
    message: str
    tables: dict[str, int] = field(default_factory=dict)
    pack_ids: list[str] = field(default_factory=list)


@dataclass
class PackData:
    asset_id: str
    asset: dict[str, str] = field(default_factory=dict)
    telemetry: list[dict] = field(default_factory=list)
    health: list[dict] = field(default_factory=list)
    safety: list[dict] = field(default_factory=list)
    charges: list[dict] = field(default_factory=list)
    modules: list[dict] = field(default_factory=list)
    materials: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)

    @property
    def is_synthetic(self) -> bool:
        """True when the data itself says it is synthetic, in any table."""
        if "SYNTHETIC" in self.asset.get("demo_status", "").upper():
            return True
        rows = (*self.telemetry, *self.health, *self.safety, *self.charges, *self.materials)
        return any("SYNTHETIC" in str(row.get("data_class", "")).upper() for row in rows)


# ---------------------------------------------------------------- finding files


def _search_roots(start: Path) -> list[Path]:
    start = start.resolve()
    return [start, *list(start.parents)[:SEARCH_LEVELS]]


def discover_database(start: Path = ROOT) -> Path | None:
    """Find the built database near this app. Empty files, which DuckDB rejects, are skipped."""
    for root in _search_roots(start):
        for candidate in (
            root / "bulid X" / "data" / "database" / DB_FILE_NAME,
            root / "data" / "database" / DB_FILE_NAME,
            root / "data" / "db" / DB_FILE_NAME,
            root / DB_FILE_NAME,
        ):
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
    return None


def discover_bundles(start: Path = ROOT) -> list[Path]:
    """Find zips and folders near this app that hold the CSV bundle."""
    found: list[Path] = []
    for root in _search_roots(start):
        for folder in (root / "bulid X" / "data" / "csv_bundle", root / "data" / "csv_bundle"):
            if (folder / "battery_asset.csv").is_file() and folder not in found:
                found.append(folder)
        try:
            archives = sorted(root.glob("*.zip"))
        except OSError:
            continue
        for archive in archives:
            try:
                with zipfile.ZipFile(archive) as bundle:
                    names = {Path(name).name.lower() for name in bundle.namelist()}
            except (zipfile.BadZipFile, OSError):
                continue
            if "battery_asset.csv" in names and archive not in found:
                found.append(archive)
    return found


# ---------------------------------------------------------------- reading


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _connect_read_only(path: Path) -> duckdb.DuckDBPyConnection:
    if not path.is_file():
        raise DatabaseError(f"Database file not found: {path}")
    if path.stat().st_size == 0:
        raise DatabaseError(f"This database file is empty (0 bytes), so it was never built: {path}")
    try:
        return duckdb.connect(str(path), read_only=True)
    except duckdb.Error as exc:
        raise DatabaseError(f"Could not open {path.name}: {exc}") from exc


def _table_names(con: duckdb.DuckDBPyConnection) -> set[str]:
    return {row[0] for row in con.execute("SHOW TABLES").fetchall()}


def _read_table(con: duckdb.DuckDBPyConnection, table: str, where_key: str | None = None) -> list[dict]:
    """Read a table as dictionaries with lower-case keys. Times come back as UTC datetimes.

    Time zone-aware columns are read as epoch milliseconds, because fetching them directly
    needs the optional pytz package.
    """
    columns = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = ? ORDER BY ordinal_position",
        [table],
    ).fetchall()
    if not columns:
        return []
    names = [name for name, _ in columns]
    is_time = [data_type.upper().startswith("TIMESTAMP") for _, data_type in columns]
    select = ", ".join(
        f'epoch_ms("{name}")' if timed else f'"{name}"' for name, timed in zip(names, is_time)
    )
    sql = f'SELECT {select} FROM "{table}"'
    params: list = []
    lower_names = [name.lower() for name in names]
    if where_key is not None:
        if KEY_COLUMN not in lower_names:
            return []
        sql += f' WHERE "{KEY_COLUMN}" = ?'
        params.append(where_key)
    rows = []
    for raw in con.execute(sql, params).fetchall():
        row = {}
        for name, timed, value in zip(lower_names, is_time, raw):
            if timed and value is not None:
                value = datetime.fromtimestamp(value / 1000, timezone.utc)
            row[name] = value
        rows.append(row)
    return rows


def _pack_ids(con: duckdb.DuckDBPyConnection, tables: set[str]) -> list[str]:
    ids: set[str] = set()
    if "battery_asset" in tables:
        ids |= {str(row["value"]) for row in _read_table(con, "battery_asset") if row.get("field") == KEY_COLUMN}
    if "telemetry" in tables:
        ids |= {str(row[0]) for row in con.execute(f'SELECT DISTINCT "{KEY_COLUMN}" FROM telemetry').fetchall()}
    return sorted(ids)


def check_database(path: Path | None) -> DatabaseStatus:
    if path is None:
        return DatabaseStatus(None, False, "No database linked")
    try:
        with _connect_read_only(path) as con:
            names = _table_names(con)
            tables = {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in BUNDLE_SCHEMA if t in names}
            if not tables:
                return DatabaseStatus(path, False, "This file has none of the expected battery tables", {})
            return DatabaseStatus(path, True, "Connected", tables, _pack_ids(con, names))
    except DatabaseError as exc:
        return DatabaseStatus(path, False, str(exc))
    except duckdb.Error as exc:
        return DatabaseStatus(path, False, f"Could not read this database: {exc}")


def _sort_by(rows: list[dict], key: str) -> list[dict]:
    """Sort oldest first. Rows with no usable value go last rather than raising an error."""
    def sort_key(row: dict):
        value = row.get(key)
        if isinstance(value, (datetime, date)):
            return (0, str(value.isoformat()))
        return (0 if value is not None else 1, str(value))
    return sorted(rows, key=sort_key)


def load_pack(path: Path, asset_id: str) -> PackData:
    """Read everything stored for one pack."""
    try:
        with _connect_read_only(path) as con:
            tables = _table_names(con)

            def read(table: str, keyed: bool = True) -> list[dict]:
                if table not in tables:
                    return []
                return _read_table(con, table, asset_id if keyed else None)

            pairs = read("battery_asset", keyed=False)
            if any(KEY_COLUMN in row for row in pairs):   # fleet layout: (asset_id, field, value)
                pairs = [row for row in pairs if str(row.get(KEY_COLUMN)) == asset_id]
            asset = {str(row.get("field")): str(row.get("value")) for row in pairs}
            if asset.get(KEY_COLUMN) != asset_id:
                asset = {}  # battery_asset describes one pack, and it is a different one.
            return PackData(
                asset_id=asset_id,
                asset=asset,
                telemetry=_sort_by(read("telemetry"), TIME_COLUMN),
                health=_sort_by(read("health_history"), "assessment_date"),
                safety=_sort_by(read("safety_events"), TIME_COLUMN),
                charges=_sort_by(read("charge_sessions"), "start_utc"),
                modules=read("modules"),
                materials=read("materials_recycling"),
                sources=read("data_sources", keyed=False),
            )
    except duckdb.Error as exc:
        raise DatabaseError(f"Could not read this pack: {exc}") from exc


def _number(value) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def profile_from_pack(pack: PackData, db_name: str = DB_FILE_NAME) -> BatteryProfile:
    """Make a test bench profile from a pack, using only what the data actually states."""
    asset = pack.asset
    latest = pack.telemetry[-1] if pack.telemetry else {}
    health = pack.health[-1] if pack.health else {}
    match = re.fullmatch(r"(\d+)s(\d+)p", asset.get("series_parallel_configuration", "").strip().lower())
    energy_kwh = _number(asset.get("nominal_energy_kWh"))
    return BatteryProfile.from_dict({
        "id": pack.asset_id,
        "name": asset.get("vehicle_id") or pack.asset_id,
        "chemistry": asset.get("chemistry"),
        "category": "EV traction",
        "model": asset.get("battery_type"),
        "series_cells": match.group(1) if match else None,
        "parallel_cells": match.group(2) if match else None,
        "nominal_voltage_v": asset.get("nominal_voltage_V"),
        "capacity_value": asset.get("nominal_capacity_Ah"),
        "capacity_unit": "Ah",
        "rated_energy_wh": energy_kwh * 1000 if energy_kwh is not None else None,
        "mass_kg": asset.get("pack_mass_kg"),
        "manufacture_date": asset.get("manufacture_date"),
        "cycle_count": health.get("cycle_count"),
        "measured_capacity_ah": health.get("measured_capacity_ah"),
        "measured_voltage_v": latest.get("pack_voltage_v"),
        "measured_current_a": latest.get("pack_current_a"),
        "measured_temperature_c": latest.get("max_cell_temp_c"),
        "soh_pct": health.get("soh_pct"),
        "initial_soc_pct": latest.get("soc_pct"),
        "internal_resistance_mohm": health.get("internal_resistance_mohm"),
        "source_kind": "database",
        "source_title": db_name,
        "measurement_method": health.get("assessment_method") or "Not specified",
        "notes": asset.get("demo_status", ""),
    })


def data_checks(pack: PackData) -> list[str]:
    """Plain checks of whether the pack's telemetry agrees with itself."""
    notes = []
    rows = [r for r in pack.telemetry if isinstance(r.get(TIME_COLUMN), datetime)]
    voltage_gaps = [r for r in pack.telemetry if _number(r.get("pack_voltage_v")) is None]
    if voltage_gaps:
        notes.append(f"{len(voltage_gaps)} telemetry rows have no pack voltage.")

    # Regenerative braking pushes current into the pack, so its sign should oppose driving.
    regen = [_number(r.get("pack_current_a")) for r in rows if str(r.get("operating_state", "")).upper().startswith("REGEN")]
    driving = [_number(r.get("pack_current_a")) for r in rows if str(r.get("operating_state", "")).upper() == "DRIVING"]
    regen = [v for v in regen if v is not None]
    driving = [v for v in driving if v is not None]
    if regen and driving and sum(driving) / len(driving) < 0 and all(v < 0 for v in regen):
        rows_text = "1 regenerative braking row shows" if len(regen) == 1 else f"{len(regen)} regenerative braking rows show"
        notes.append(f"{rows_text} the same current sign as driving. Charging current should have the opposite sign.")

    # Coulomb count: does the current explain the change in SOC?
    capacity = _number(pack.asset.get("nominal_capacity_Ah"))
    socs = [_number(r.get("soc_pct")) for r in rows]
    currents = [_number(r.get("pack_current_a")) for r in rows]
    if capacity and len(rows) >= 2 and None not in socs and None not in currents:
        amp_hours = sum(
            (currents[i] + currents[i + 1]) / 2 * (rows[i + 1][TIME_COLUMN] - rows[i][TIME_COLUMN]).total_seconds() / 3600
            for i in range(len(rows) - 1)
        )
        from_current = 100 * amp_hours / capacity
        recorded = socs[-1] - socs[0]
        if abs(recorded - from_current) > max(3.0, abs(from_current) * 0.25):
            notes.append(
                f"SOC changed by {recorded:+.0f} points, but the recorded current only explains {from_current:+.0f} "
                f"on a {capacity:g} Ah pack."
            )
    return notes


# ---------------------------------------------------------------- uploading


@dataclass
class FileCheck:
    table: str
    path: Path
    rows: int = 0
    columns: list[str] = field(default_factory=list)
    problem: str = ""

    @property
    def ok(self) -> bool:
        return not self.problem


@dataclass
class BundlePreview:
    """What an upload contains, checked before anything in the database changes."""
    label: str
    files: list[FileCheck] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    _temp: tempfile.TemporaryDirectory | None = None

    @property
    def can_import(self) -> bool:
        return bool(self.files) and all(f.ok for f in self.files)

    def close(self) -> None:
        if self._temp is not None:
            self._temp.cleanup()
            self._temp = None


def _collect_from_zip(archive: Path) -> tuple[dict[str, Path], list[str], tempfile.TemporaryDirectory]:
    """Extract only the expected CSVs, by name, so a crafted path can't write elsewhere."""
    temp = tempfile.TemporaryDirectory(prefix="relife_upload_")
    found: dict[str, Path] = {}
    ignored: list[str] = []
    try:
        with zipfile.ZipFile(archive) as bundle:
            members = [m for m in bundle.infolist() if not m.is_dir()]
            if sum(m.file_size for m in members) > MAX_UNZIPPED_BYTES:
                raise DatabaseError("This zip is over 2 GB when extracted, which is too large to import.")
            for member in members:
                name = Path(member.filename.replace("\\", "/")).name
                table = name.lower().removesuffix(".csv")
                if table not in BUNDLE_SCHEMA or not name.lower().endswith(".csv"):
                    ignored.append(name)
                    continue
                if table in found:
                    raise DatabaseError(f"This zip holds more than one {name}.")
                target = Path(temp.name) / f"{table}.csv"
                target.write_bytes(bundle.read(member))
                found[table] = target
    except zipfile.BadZipFile as exc:
        temp.cleanup()
        raise DatabaseError(f"{archive.name} isn't a valid zip file.") from exc
    except Exception:
        temp.cleanup()
        raise
    return found, ignored, temp


def _collect_from_files(paths: list[Path]) -> tuple[dict[str, Path], list[str]]:
    found: dict[str, Path] = {}
    ignored: list[str] = []
    for path in paths:
        table = path.name.lower().removesuffix(".csv")
        if path.name.lower().endswith(".csv") and table in BUNDLE_SCHEMA:
            found[table] = path
        else:
            ignored.append(path.name)
    return found, ignored


def _check_file(con: duckdb.DuckDBPyConnection, table: str, path: Path) -> FileCheck:
    check = FileCheck(table, path)
    source = f"read_csv_auto({_sql_string(path.as_posix())}, sample_size=-1)"
    try:
        check.columns = [row[0] for row in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()]
        check.rows = con.execute(f"SELECT COUNT(*) FROM {source}").fetchone()[0]
    except duckdb.Error as exc:
        check.problem = f"Could not read this CSV: {str(exc).splitlines()[0]}"
        return check
    lower = {column.lower() for column in check.columns}
    missing = [column for column in BUNDLE_SCHEMA[table] if column not in lower]
    if missing:
        check.problem = "Missing columns: " + ", ".join(missing)
    elif check.rows == 0:
        check.problem = "This file has no data rows"
    return check


def _bundle_warnings(con: duckdb.DuckDBPyConnection, files: list[FileCheck], target: Path | None) -> list[str]:
    """Warn when an upload would leave rows that don't belong to the pack battery_asset describes."""
    good = [f for f in files if f.ok]
    if not good:
        return []
    pack_id = None
    asset_file = next((f for f in good if f.table == "battery_asset"), None)
    if asset_file is not None:
        rows = con.execute(
            f"SELECT value FROM read_csv_auto({_sql_string(asset_file.path.as_posix())}, sample_size=-1, all_varchar=true) "
            f"WHERE field = '{KEY_COLUMN}'"
        ).fetchall()
        if not rows:
            return ["battery_asset.csv has no asset_id row, so its pack can't be matched to the other tables."]
        pack_id = rows[0][0]
    elif target is not None:
        status = check_database(target)
        if status.connected and len(status.pack_ids) == 1:
            pack_id = status.pack_ids[0]

    warnings = []
    if pack_id is not None:
        for check in good:
            if KEY_COLUMN not in BUNDLE_SCHEMA[check.table]:
                continue
            source = f"read_csv_auto({_sql_string(check.path.as_posix())}, sample_size=-1, all_varchar=true)"
            others = [r[0] for r in con.execute(f'SELECT DISTINCT "{KEY_COLUMN}" FROM {source}').fetchall() if r[0] != pack_id]
            if others:
                warnings.append(
                    f"{check.table} has rows for {', '.join(map(str, others[:3]))}, not the database's pack {pack_id}."
                )
    return warnings


def preview_upload(paths: list[Path], target: Path | None = None) -> BundlePreview:
    """Check a zip, a folder or a list of CSVs, without changing the database.

    Call close() on the result when finished with it.
    """
    if not paths:
        raise DatabaseError("Nothing was selected.")
    temp = None
    if len(paths) == 1 and paths[0].suffix.lower() == ".zip":
        found, ignored, temp = _collect_from_zip(paths[0])
        label = paths[0].name
    elif len(paths) == 1 and paths[0].is_dir():
        found, ignored = _collect_from_files(sorted(p for p in paths[0].iterdir() if p.is_file()))
        label = paths[0].name
    else:
        found, ignored = _collect_from_files(paths)
        label = f"{len(paths)} selected files"

    preview = BundlePreview(label=label, ignored=ignored, _temp=temp)
    with duckdb.connect() as con:
        preview.files = [_check_file(con, table, found[table]) for table in BUNDLE_SCHEMA if table in found]
        preview.warnings = _bundle_warnings(con, preview.files, target)
    if not preview.files:
        preview.close()
        raise DatabaseError("None of the selected files is part of the battery data bundle.")
    return preview


def _backup(path: Path) -> Path | None:
    """Copy the database before changing it, keeping the newest few copies."""
    if not path.is_file() or path.stat().st_size == 0:
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.stem}.backup-{stamp}{path.suffix}")
    shutil.copy2(path, backup)
    copies = sorted(path.parent.glob(f"{path.stem}.backup-*{path.suffix}"), key=lambda p: p.name, reverse=True)
    for old in copies[MAX_BACKUPS:]:
        old.unlink(missing_ok=True)
    return backup


def import_bundle(preview: BundlePreview, db_path: Path) -> dict:
    """Replace the previewed tables in the database, in one transaction.

    If any CSV fails to load, every table keeps its old contents. Rows are replaced, not
    merged, because battery_asset describes a single pack.
    """
    if not preview.can_import:
        raise DatabaseError("Fix the problems shown in the preview before importing.")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.is_file() and db_path.stat().st_size == 0:
        raise DatabaseError(f"{db_path.name} is an empty file DuckDB can't open. Choose a different database.")

    try:
        backup = _backup(db_path)
        with duckdb.connect(str(db_path)) as con:
            con.execute("BEGIN TRANSACTION")
            try:
                for check in preview.files:
                    con.execute(f'DROP TABLE IF EXISTS "{check.table}"')
                    con.execute(
                        f'CREATE TABLE "{check.table}" AS SELECT * FROM '
                        f"read_csv_auto({_sql_string(check.path.as_posix())}, sample_size=-1)"
                    )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            # Built after the commit, with the same names the build script uses.
            for check in preview.files:
                lower = {column.lower() for column in check.columns}
                if KEY_COLUMN in lower:
                    con.execute(
                        f'CREATE INDEX "idx_{check.table}_{KEY_COLUMN}" ON "{check.table}" ("{KEY_COLUMN}")'
                    )
                if check.table == "telemetry":
                    con.execute(
                        f'CREATE INDEX "idx_telemetry_{KEY_COLUMN}_{TIME_COLUMN}" '
                        f'ON "telemetry" ("{KEY_COLUMN}", "{TIME_COLUMN}")'
                    )
    except duckdb.IOException as exc:
        raise DatabaseError(
            f"Couldn't open {db_path.name} for writing. Close any other program using it, then try again. ({exc})"
        ) from exc
    except duckdb.Error as exc:
        raise DatabaseError(f"The import failed and the old data was kept: {exc}") from exc
    return {
        "tables": {check.table: check.rows for check in preview.files},
        "backup": backup,
    }
