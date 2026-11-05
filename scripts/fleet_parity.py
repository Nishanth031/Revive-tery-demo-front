"""Per-pack parity: Python fleet_reports (dense) vs the web app's data/fleet_reports.json (JS ports).

    python scripts/fleet_parity.py      -> prints mismatches; exit code 1 if any
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB = Path(os.environ.get("REVIVE_DB") or ROOT / "data" / "db" / "revive_tery.duckdb")


def main() -> int:
    js = {p["asset_id"]: p for p in json.loads((ROOT / "apps/web-studio/data/fleet_reports.json").read_text("utf-8"))["packs"]}
    with duckdb.connect(str(DB), read_only=True) as con:
        py = {a: (d, disp) for a, d, disp in con.execute(
            "SELECT asset_id, decision, disposition FROM fleet_reports WHERE telemetry_source = 'dense'").fetchall()}
    bad = [(a, py[a], (js[a]["decision"], js[a]["disposition"])) for a in sorted(py)
           if a not in js or (js[a]["decision"], js[a]["disposition"]) != py[a]]
    missing = sorted(set(js) - set(py))
    print(f"python {len(py)} packs, js {len(js)} packs, mismatches {len(bad)}, js-only {len(missing)}")
    for b in bad:
        print("  MISMATCH", *b)
    return 1 if bad or missing else 0


if __name__ == "__main__":
    sys.exit(main())
