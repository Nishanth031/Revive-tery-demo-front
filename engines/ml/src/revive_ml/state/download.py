"""Download public battery datasets listed in configs/datasets.yaml.

Every attempt is logged to reports/download_log.json. A failed download is
logged and skipped; nothing is ever substituted for missing data.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
import yaml

from revive_ml.paths import REPORTS_DIR, cache_dir, config_path

CHECKSUMS = config_path("dataset_checksums.json")
LOG = REPORTS_DIR / "download_log.json"


def load_registry() -> dict[str, dict[str, Any]]:
    with open(config_path("datasets.yaml"), encoding="utf-8") as fh:
        return yaml.safe_load(fh)["datasets"]


def sha256(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _fetch(url: str, dest: Path, expected_size: int | None, retries: int = 4) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, retries + 1):
        try:
            done = tmp.stat().st_size if tmp.exists() else 0
            headers = {"Range": f"bytes={done}-"} if done else {}
            with requests.get(url, stream=True, timeout=60, headers=headers) as r:
                if r.status_code == 200 and done:
                    done = 0  # server ignored the range request; start over
                r.raise_for_status()
                with open(tmp, "ab" if done else "wb") as fh:
                    for block in r.iter_content(chunk_size=1 << 20):
                        fh.write(block)
            if expected_size and tmp.stat().st_size != expected_size:
                raise OSError(f"size {tmp.stat().st_size} != expected {expected_size}")
            tmp.replace(dest)
            return
        except (requests.RequestException, OSError) as exc:
            if attempt == retries:
                raise
            print(f"  retry {attempt}/{retries} after error: {exc}")
            time.sleep(5 * attempt)


def download(names: list[str] | None = None, include_optional: bool = False) -> dict[str, str]:
    """Download datasets; returns {name: status}. Verifies checksums of cached files."""
    registry = load_registry()
    checksums = _read_json(CHECKSUMS)
    log = _read_json(LOG)
    status: dict[str, str] = {}
    root = cache_dir() / "raw"
    root.mkdir(parents=True, exist_ok=True)
    for name, spec in registry.items():
        if names and name not in names:
            continue
        if not names and spec.get("optional") and not include_optional:
            continue
        dest = root / spec["filename"]
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            if not dest.exists():
                print(f"downloading {name} ({spec.get('size_bytes', 0) / 1e6:.0f} MB) ...")
                _fetch(spec["url"], dest, spec.get("size_bytes"))
            digest = sha256(dest)
            known = checksums.get(name, {}).get("sha256")
            if known and known != digest:
                raise OSError(f"checksum mismatch for {name}: {digest} != recorded {known}")
            checksums[name] = {"sha256": digest, "filename": spec["filename"],
                               "size_bytes": dest.stat().st_size, "url": spec["url"]}
            status[name] = "ok"
        except Exception as exc:  # noqa: BLE001 - every failure is logged, then skipped
            status[name] = f"failed: {exc}"
            print(f"  FAILED {name}: {exc}")
        log[name] = {"status": status[name], "time_utc": stamp}
        _write_json(CHECKSUMS, checksums)
        _write_json(LOG, log)
    return status


def local_path(name: str) -> Path | None:
    spec = load_registry()[name]
    p = cache_dir() / "raw" / spec["filename"]
    return p if p.exists() else None
