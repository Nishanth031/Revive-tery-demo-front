"""Write SYNTHETIC sample uploads for the ML panel to data/ml_samples/.

Each file exercises a different path through the analyzer. None of it is real battery data.
Run: python src/make_ml_samples.py
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parents[2] / "engines" / "database" / "ml_samples"
RNG = np.random.default_rng(0)


def cycling_log(battery_id: str, cycles: int, cap0_ah: float, fade_per_cycle: float, series: int,
                cell_v_min: float = 2.8, temp_base: float = 27.0, rows_per_cycle: int = 6) -> pd.DataFrame:
    """One summary-ish row block per cycle: discharge from full to empty with measured capacity."""
    rows = []
    for c in range(1, cycles + 1):
        cap = cap0_ah * (1 - fade_per_cycle * c) * (1 + RNG.normal(0, 0.002))
        for k in range(rows_per_cycle):
            frac = k / (rows_per_cycle - 1)
            cell_v = 3.35 - (3.35 - cell_v_min) * frac ** 3   # flat LFP-like plateau, then a drop
            rows.append({"battery_id": battery_id, "cycle": c,
                         "Voltage (V)": round(series * cell_v + RNG.normal(0, 0.01 * series), 3),
                         "Current (A)": round(-0.5 * cap0_ah * (1 + 0.1 * (k % 2)), 3),
                         "Temperature (°C)": round(temp_base + 3 * frac + RNG.normal(0, 0.2), 2),
                         "Discharge Capacity (Ah)": round(cap * frac, 4)})
    return pd.DataFrame(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # All packs: 16 LFP cells in series, rated 100 Ah. Logs start mid-life, like used EV packs.
    # 1. ~94 % SoH, slow fade: expect a second-life reuse suggestion.
    cycling_log("PACK-HEALTHY", 120, 95.0, 0.000126, series=16).to_csv(OUT / "1_healthy_pack.csv", index=False)
    # 2. ~70 % SoH, slow fade: expect module-level repurpose.
    cycling_log("PACK-WORN", 150, 70.0, 0.00006, series=16).to_csv(OUT / "2_worn_pack.csv", index=False)
    # 3. Over-discharged pack (cells reach 1.8 V): expect a safety Reject -> Recycle.
    cycling_log("PACK-OVERDISCHARGED", 60, 90.0, 0.0001, series=16, cell_v_min=1.8).to_csv(
        OUT / "3_overdischarged_pack.csv", index=False)
    # 5. ~55 % SoH: below every reuse threshold, expect Recycle.
    cycling_log("PACK-END-OF-LIFE", 100, 56.0, 0.0001, series=16).to_csv(
        OUT / "5_end_of_life_pack.csv", index=False)
    # 4. Excel inside a zip with different header names and no capacity column: expect Insufficient data.
    df = cycling_log("PACK-NOCAP", 30, 90.0, 0.0001, series=16).drop(columns="Discharge Capacity (Ah)")
    df = df.rename(columns={"battery_id": "Asset ID", "cycle": "Cycle Number", "Voltage (V)": "Pack Voltage [V]",
                            "Current (A)": "Current [A]", "Temperature (°C)": "Temp (C)"})
    df["Operator note"] = "bench log"   # an unrelated column: reported as not used
    xlsx = OUT / "4_no_capacity.xlsx"
    df.to_excel(xlsx, index=False)
    with zipfile.ZipFile(OUT / "4_no_capacity_in_zip.zip", "w") as z:
        z.write(xlsx, "logs/4_no_capacity.xlsx")
        z.writestr("README.txt", "Synthetic sample for the REVIVE-TERY ML panel.")
    xlsx.unlink()
    # 6. The healthy log again, with real timestamps (10 minutes apart): enough for the full ML engine,
    #    which counts charge over real time steps. Samples 1 to 5 have no timestamps, so they use the lite analyzer.
    df = cycling_log("PACK-TIMESTAMPED", 120, 95.0, 0.000126, series=16)
    df.insert(1, "timestamp_utc", pd.date_range("2026-01-01", periods=len(df), freq="10min", tz="UTC")
              .strftime("%Y-%m-%dT%H:%M:%SZ"))
    df.to_csv(OUT / "6_timestamped_pack.csv", index=False)
    # 7. A zipped data-contract bundle (metadata.json + telemetry.csv), made by the ML engine's own generator.
    #    Skipped when revive-tery-ml isn't installed in this Python.
    try:
        from revive_ml.contract import write_bundle
        from revive_ml.synth import make_clean_bundle
    except ImportError:
        print("revive-tery-ml not installed: skipped 7_contract_bundle.zip")
    else:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_clean_bundle()
            write_bundle(tmp, bundle.meta, bundle.telemetry)
            with zipfile.ZipFile(OUT / "7_contract_bundle.zip", "w") as z:
                for f in Path(tmp).iterdir():
                    z.write(f, f.name)
    (OUT / "README.txt").write_text(
        "SYNTHETIC sample uploads for the ML analyzer panel (made by src/make_ml_samples.py).\n"
        "In the panel use: chemistry LFP, cells in series 16, rated capacity 100 Ah.\n"
        "Not real battery data.\n", encoding="utf-8")
    print(f"wrote samples to {OUT}")


if __name__ == "__main__":
    main()
