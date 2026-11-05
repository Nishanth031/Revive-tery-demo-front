"""Uploads: .csv / .xlsx / .zip -> standard schema -> DuckDB (ml_telemetry), through the shared database lock."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .. import db, settings
from ml_analyzer_suggester import BatteryFileExtractor, IngestionError

PROVENANCES = ("measured", "simulated", "synthetic")


class UploadTooLarge(ValueError):
    pass


def save_uploads(files: Iterable[tuple[str, Any]], dest: Path) -> list[Path]:
    """Write uploaded streams into dest, with basename-only names and a total size cap."""
    paths: list[Path] = []
    total = 0
    for filename, stream in files:
        name = Path(filename or "upload").name
        if Path(name).suffix.lower() not in settings.ALLOWED_UPLOAD_SUFFIXES:
            raise IngestionError(f"{name}: unsupported file type; use .csv, .xlsx or .zip")
        target = dest / name
        with open(target, "wb") as out:
            while chunk := stream.read(1 << 20):
                total += len(chunk)
                if total > settings.MAX_UPLOAD_BYTES:
                    raise UploadTooLarge(f"upload is larger than {settings.MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
                out.write(chunk)
        paths.append(target)
    if not paths:
        raise IngestionError("no files were uploaded")
    return paths


def ingest(files: Iterable[tuple[str, Any]], data_provenance: str) -> dict[str, Any]:
    """Extract every upload and store the rows in one transaction. Per-file failures are reported, not fatal."""
    if data_provenance not in PROVENANCES:
        raise ValueError(f"data_provenance must be one of {PROVENANCES}")
    tmp = Path(tempfile.mkdtemp(prefix="revive_upload_"))
    try:
        paths = save_uploads(files, tmp)
        extractor = BatteryFileExtractor()
        tables, errors = [], []
        for p in paths:
            try:
                tables.extend(extractor.extract(p))
            except IngestionError as exc:
                errors.append(str(exc))
        if not tables:
            raise IngestionError("; ".join(errors) or "no usable telemetry found in the upload")
        result = db.seeder().seed(tables, data_provenance)
        result["column_mappings"] = {t.source: {"mapped": t.mapping, "unmapped": t.unmapped, "warnings": t.warnings}
                                     for t in tables}
        result["errors"] = errors
        result["data_provenance"] = data_provenance
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def ingest_log(limit: int = 100) -> list[dict[str, Any]]:
    with db.read() as con:
        df = con.execute("SELECT ingest_id, ingested_utc, source_file, rows, column_mapping, unmapped_columns, warnings "
                         "FROM ml_ingest_log ORDER BY ingested_utc DESC LIMIT ?", [limit]).df()
    return db.records(df)
