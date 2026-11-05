"""The ML workflow around the engine: understand an upload, then (separately) assess and advise.

    analyze_upload(paths, hints)  files -> mapped, unit-checked, standardised telemetry + the battery's identity
                                  and spec, plus a plain list of what it still needs from the user
    assess_with_advice(bundle)    the unchanged engine assessment + second-use advice (a new "advice" key on a
                                  copy of the report; the report itself is not modified)

This module reads files and returns data. It does not touch any database: the backend takes the standardised
tables and stores them, so this package keeps its independence rule (it imports nothing outside revive_ml).
"""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from revive_ml.intelligence.advisor import AdvisorInput, advise, from_report
from revive_ml.intelligence.identity import (Identity, SpecInference, detect_identity, infer_spec,
                                             parse_spec_table, spec_from_table)
from revive_ml.intelligence.mapper import MappingResult, _num, map_columns, standardise

SUPPORTED = {".csv", ".xlsx", ".xls"}
MAX_ZIP_MEMBERS = 500
MAX_UNCOMPRESSED_BYTES = 2 * 1024 ** 3


class UploadError(RuntimeError):
    """The upload cannot be read at all."""


def read_tables(path: str | Path) -> list[tuple[str, pd.DataFrame]]:
    """Every table in a .csv / .xlsx / .zip, as (label, DataFrame)."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".zip":
        out: list[tuple[str, pd.DataFrame]] = []
        try:
            with zipfile.ZipFile(path) as z:
                members = [i for i in z.infolist() if not i.is_dir() and "__MACOSX" not in i.filename
                           and Path(i.filename).suffix.lower() in SUPPORTED]
                if len(z.infolist()) > MAX_ZIP_MEMBERS:
                    raise UploadError(f"{path.name}: more than {MAX_ZIP_MEMBERS} files in the zip")
                if sum(i.file_size for i in members) > MAX_UNCOMPRESSED_BYTES:
                    raise UploadError(f"{path.name}: unzips to more than 2 GB")
                for info in members:
                    out += _read_bytes(z.read(info), Path(info.filename).suffix.lower(), f"{path.name}/{info.filename}")
        except zipfile.BadZipFile as exc:
            raise UploadError(f"{path.name}: not a valid zip file") from exc
        return out
    if ext not in SUPPORTED:
        raise UploadError(f"{path.name}: unsupported file type; use .csv, .xlsx or .zip")
    return _read_bytes(path.read_bytes(), ext, path.name)


def _read_bytes(data: bytes, ext: str, label: str) -> list[tuple[str, pd.DataFrame]]:
    try:
        if ext == ".csv":
            return [(label, pd.read_csv(io.BytesIO(data), sep=None, engine="python"))]
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None)
        return [(f"{label}#{name}", df) for name, df in sheets.items()]
    except ImportError as exc:
        raise UploadError(f"reading {ext} needs an extra package: {exc}") from exc
    except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError, OSError) as exc:
        raise UploadError(f"could not parse {label}: {exc}") from exc


@dataclass
class TableAnalysis:
    source: str
    role: str                                  # telemetry | metadata | skipped
    mapping: MappingResult | None = None
    data: pd.DataFrame | None = None           # standardised, telemetry only
    metadata: dict[str, Any] = field(default_factory=dict)
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "role": self.role, "note": self.note,
                "rows": int(len(self.data)) if self.data is not None else None,
                "mapping": self.mapping.to_dict() if self.mapping else None, "metadata": self.metadata}


@dataclass
class BatteryAnalysis:
    battery_id: str
    rows: int
    spec: SpecInference

    def to_dict(self) -> dict[str, Any]:
        return {"battery_id": self.battery_id, "rows": self.rows, "spec": self.spec.to_dict()}


@dataclass
class UploadAnalysis:
    tables: list[TableAnalysis]
    identity: Identity
    batteries: list[BatteryAnalysis]
    warnings: list[str] = field(default_factory=list)

    @property
    def telemetry(self) -> list[TableAnalysis]:
        return [t for t in self.tables if t.role == "telemetry"]

    def to_dict(self) -> dict[str, Any]:
        return {"tables": [t.to_dict() for t in self.tables], "identity": self.identity.to_dict(),
                "batteries": [b.to_dict() for b in self.batteries], "warnings": self.warnings,
                "ready_to_assess": [b.battery_id for b in self.batteries if b.spec.complete],
                "needs_from_user": {b.battery_id: b.spec.needs for b in self.batteries if not b.spec.complete}}


def _texts_for_identity(label: str, df: pd.DataFrame, std: pd.DataFrame | None, meta: dict[str, Any]) -> list[str]:
    texts = [label, *[str(c) for c in df.columns[:60]], *[str(v) for v in meta.values()]]
    if std is not None and "battery_id" in std:
        texts += [str(x) for x in std["battery_id"].unique()[:50]]
    for c in df.columns[:40]:                                  # text cells such as 'cell_model', 'manufacturer'
        if _num(df[c]).notna().mean() < 0.5:
            texts += [str(x) for x in df[c].dropna().astype(str).unique()[:30]]
    return texts


def analyze_upload(paths: list[str | Path], hints: dict[str, Any] | None = None) -> UploadAnalysis:
    hints = {k: v for k, v in (hints or {}).items() if v not in (None, "")}
    tables: list[TableAnalysis] = []
    texts: list[str] = []
    table_spec: dict[str, Any] = {}
    warnings: list[str] = []
    if not paths:
        raise UploadError("no files were uploaded")
    for p in paths:
        for label, df in read_tables(p):
            if df.empty or df.shape[1] == 0:
                tables.append(TableAnalysis(label, "skipped", note="empty table"))
                continue
            if sum(pd.notna(pd.to_numeric(pd.Series([str(c) for c in df.columns]), errors="coerce"))) >= max(2, df.shape[1] // 2):
                tables.append(TableAnalysis(label, "skipped", note="no header row (the column names are numbers); "
                                                                  "add a header row so columns can be identified"))
                continue
            mapping = map_columns(df, label)
            if mapping.is_telemetry:
                std = standardise(df, mapping, label)
                tables.append(TableAnalysis(label, "telemetry", mapping, std))
                texts += _texts_for_identity(label, df, std, {})
                continue
            raw = parse_spec_table(df)
            if raw:
                meta = spec_from_table(raw)
                table_spec.update({k: v for k, v in meta.items() if k not in table_spec})
                tables.append(TableAnalysis(label, "metadata", mapping, None, meta,
                                            note="key/value table read as battery metadata"))
                texts += _texts_for_identity(label, df, None, raw)
            else:
                tables.append(TableAnalysis(label, "skipped", mapping, None,
                                            note="no voltage column was recognised and it is not a key/value metadata table"))
    if not any(t.role == "telemetry" for t in tables):
        notes = "; ".join(f"{t.source}: {t.note}" for t in tables if t.note)
        raise UploadError("no telemetry table was found" + (f" ({notes})" if notes else ""))

    identity = detect_identity(texts + ([str(hints["brand"])] if "brand" in hints else [])
                               + ([str(hints["chemistry"])] if "chemistry" in hints else []))
    if hints.get("brand"):
        identity.evidence.append("maker given by the user")
    if table_spec.get("brand") and not identity.brand:
        identity = detect_identity(texts + [table_spec["brand"]])
    frames = pd.concat([t.data for t in tables if t.role == "telemetry"], ignore_index=True)
    batteries = []
    for bid, g in frames.groupby("battery_id", sort=True):
        batteries.append(BatteryAnalysis(str(bid), int(len(g)), infer_spec(g, identity, table_spec, hints)))
    for t in tables:
        if t.mapping:
            warnings += [f"{t.source}: {w}" for w in t.mapping.warnings]
    return UploadAnalysis(tables, identity, batteries, warnings)


# ---------------------------------------------------------------------------------------------
# engine + advice
# ---------------------------------------------------------------------------------------------

def _resistance_ratio(bundle: Any) -> float | None:
    tests = sorted(getattr(bundle.meta, "resistance_tests", None) or [], key=lambda t: str(t.date))
    if len(tests) >= 2 and tests[0].resistance_mohm > 0:
        return float(tests[-1].resistance_mohm / tests[0].resistance_mohm)
    return None


def assess_with_advice(bundle: Any, workloads: dict[str, Any] | None = None, brand: str | None = None,
                       chemistry_basis: str = "engine") -> dict[str, Any]:
    """The engine's report (unchanged) plus second-use advice for this battery, as a new 'advice' key."""
    from revive_ml.pipeline import assess

    report = assess(bundle, workloads)
    inp: AdvisorInput = from_report(report, brand=brand, chemistry_basis=chemistry_basis,
                                    resistance_ratio=_resistance_ratio(bundle))
    wl = workloads.get("workloads") if isinstance(workloads, dict) and "workloads" in workloads else workloads
    out = dict(report)
    out["advice"] = advise(inp, wl)
    return out
