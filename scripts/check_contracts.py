#!/usr/bin/env python3
"""Cheap guard rails; run after any edit (`python scripts/check_contracts.py`). Standard library only.

Checks:
  1. every contracts/*.json and config/*.json and registry.json parses;
  2. every path in registry.json that is a folder/file exists (warns if the migration has not run yet);
  3. every example bundle metadata.json under engines/ml/examples and apps/web-studio/data validates
     against contracts/bundle_metadata.schema.json (a small subset validator: type, required, enum, items);
  4. every example telemetry.csv has the required columns from contracts/telemetry.schema.json.
Exit code 1 on any error. Warnings (missing optional pieces) do not fail.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []
warnings: list[str] = []


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        errors.append(f"{path.relative_to(ROOT)}: cannot parse ({exc})")
        return None


TYPES = {"string": str, "number": (int, float), "integer": int, "object": dict, "array": list, "null": type(None),
         "boolean": bool}


def validate(value, schema: dict, where: str) -> None:
    t = schema.get("type")
    if t:
        allowed = t if isinstance(t, list) else [t]
        ok = any(isinstance(value, TYPES[x]) and not (x in ("number", "integer") and isinstance(value, bool))
                 for x in allowed)
        if not ok:
            errors.append(f"{where}: expected {allowed}, got {type(value).__name__}")
            return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{where}: {value!r} not in {schema['enum']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{where}: missing required '{key}'")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                validate(value[key], sub, f"{where}.{key}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            validate(item, schema["items"], f"{where}[{i}]")


def main() -> int:
    for pattern in ("contracts/*.json", "config/*.json", "registry.json"):
        for p in sorted(ROOT.glob(pattern)):
            load(p)

    reg = load(ROOT / "registry.json") or {"components": []}
    for comp in reg["components"]:
        for rel in comp["paths"]:
            if not (ROOT / rel).exists():
                warnings.append(f"registry '{comp['id']}': path not found yet: {rel}")

    schema = load(ROOT / "contracts" / "bundle_metadata.schema.json")
    tele = load(ROOT / "contracts" / "telemetry.schema.json")
    metas = sorted({*ROOT.glob("engines/ml/examples/*/metadata.json"), *ROOT.glob("apps/web-studio/data/**/metadata.json")})
    if not metas:
        warnings.append("no example bundles found yet (run the migration first)")
    for meta in metas:
        data = load(meta)
        if schema and data is not None:
            validate(data, schema, str(meta.relative_to(ROOT)))
        csv_path = meta.with_name("telemetry.csv")
        if tele and csv_path.exists():
            with csv_path.open(encoding="utf-8", newline="") as fh:
                header = next(csv.reader(fh), [])
            for col in tele["required_columns"]:
                if col not in header:
                    errors.append(f"{csv_path.relative_to(ROOT)}: missing required column '{col}'")

    for w in warnings:
        print("WARN ", w)
    for e in errors:
        print("ERROR", e)
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
