# PLAN: revive-tery-ml

Standalone ML engine for REVIVE-TERY (EV battery second-life decision support).
Order of work: data quality, then triage gate, state estimation, physics projection, economics routing.

## Phase 0 findings (2026-11-03)

### Environment
- Default `python` is 3.15.2; several ML wheels are uncertain there. The package uses its own
  venv on **Python 3.13.14** (`py -3.13 -m venv .venv`). Everything installed from wheels
  (no compilers on this machine): numpy 2.5, pandas 3.1, scikit-learn 1.9, **MAPIE 1.6**,
  pandera 0.35, pydantic 2.14, h5py 3.16, scipy 1.18, pyarrow 26, typer, ruff, pytest, duckdb (dev only).
- No `make` or `just` on PATH. `just` is installed into the venv from the `rust-just` wheel,
  so `.venv/Scripts/just.exe <target>` works. A `justfile` is the single source of targets.
- torch is NOT installed up front. A GRU/LSTM is only allowed if it beats the baselines;
  decided in phase 4 (see below).
- Windows console is cp1252: commands set `PYTHONIOENCODING=utf-8`, and CLI output stays ASCII.
- git 2.x available, user G Nishanth. Repo is local only; nothing is pushed.

### Network (checked with HEAD requests)
| Source | URL | Result |
|---|---|---|
| PyPI | pypi.org | 200 |
| Severson LFP, 3 batches | data.matr.io/1/api/v1/file/... | 200, 3.03 GB + 2.01 GB + 3.24 GB |
| NASA PCoE Battery (#5) | phm-datasets.s3.amazonaws.com | 200, 210 MB |
| NASA Randomized Usage (#11) | phm-datasets.s3.amazonaws.com | 200, 1.07 GB (optional) |
| NASA Recommissioned | data.nasa.gov | no direct file URL found; **not downloaded** (logged) |
| CALCE CS2 cells | web.calce.umd.edu/batteries/data/CS2_xx.zip | 200, ~40 MB each (optional) |

Raw downloads go to `%LOCALAPPDATA%\revive-tery-ml\cache\raw` (override `REVIVE_ML_CACHE`),
**not** into the repo: the repo is inside a OneDrive-synced Desktop and 8+ GB would sync.
SHA-256 of every downloaded file is recorded in `configs/dataset_checksums.json`; every
attempt (success or failure) in `reports/download_log.json`.

### Demo data, checked against the CSV bundle and a COPY of revive_tery.duckdb
- One synthetic pack `DEMO-EV-PACK-001`, every row tagged `SYNTHETIC`.
- **The demo pack is NMC, not LFP.** The master prompt says "the data is LFP"; only the public
  Severson dataset is LFP. Consequences: the LFP-trained state model is applied to an NMC pack
  only with an explicit chemistry out-of-distribution warning, and the economics use the NMC
  scrap assumption set for the demo pack (still labelled synthetic/assumed).
- Telemetry: 12 rows, **exactly 300 s apart** (checked: 11 diffs, all 300 000 ms; 12 distinct
  timestamps). The master prompt says the demo "mixes 5-minute rows"; that is not true of this
  copy. The timestamp detector is still built and unit-tested on injected irregular gaps,
  duplicates and reversals, and always integrates with the row-to-row step.
- Current is negative on discharge (`power_kW` is +V*|I|, so the power column uses the
  opposite, discharge-positive convention: two conventions inside one record).
- Coulomb count (trapezoid, row-to-row dt) = 33.2 Ah = 16.6 % of 200 Ah (17.1 % of the
  193.6 Ah test capacity) while SOC falls 82 -> 48 (34 points). Ratio about 2.0.
  Implied live capacity 33.2 / 0.34 = 97.5 Ah, i.e. live SOH about 49 % vs 96.8 % from the test.
- The one `REGENERATIVE_BRAKING` row has current -31 A (same sign as driving) and SOC keeps falling.
- Pack internal resistance 2.2 mOhm for 96s40p means 2.2 * 40 / 96 = 0.92 mOhm per cell;
  21700 NMC cells are typically tens of mOhm DC, so the pack value is roughly 20x too low.
  A resistance-based SOH clips at 100 %. Reported as **Inconclusive**, never pass.
- `fetchall()` on TIMESTAMPTZ needs pytz; the engine never reads the DuckDB file. The
  sample-bundle converter reads the CSV bundle (identical content) and DuckDB only appears in
  an optional dev check using `epoch_ms()`.

### Sample bundle converter: explicit column mapping (no guessing)
| Demo column | Contract column | Note |
|---|---|---|
| `timestamp_utc` | `timestamp_utc` | parsed as UTC |
| `asset_id` | `asset_id` | |
| `pack_voltage_V` | `voltage_v` | pack level |
| `pack_current_A` | `current_a` | sign kept as recorded (never flipped) |
| `max_cell_temp_C` | `temperature_c` | hottest cell: the conservative choice for the gate |
| `soc_pct` | `soc_pct` | BMS-reported |
| `min_cell_temp_C` | `min_temperature_c` | optional extra |
| `ambient_temp_C` | `ambient_temperature_c` | optional extra |
| `power_kW` | `power_kw` | optional extra, used by the sign-convention check |
| `operating_state` | `operating_state` | optional extra, used by the regen check |
| `soh_pct` | `bms_soh_pct` | optional extra: BMS-reported, not measured |
| `data_class` | (metadata `data_provenance`) | `SYNTHETIC` -> `synthetic` |
`battery_asset` (key/value) -> metadata; `health_history` -> capacity-test and resistance-test
records; `safety_events` -> safety events. `materials_recycling` is not used (its masses are
"synthetic estimate"; scrap value uses chemistry defaults from economics.yaml).

## Package layout
```
revive-tery-ml/
  pyproject.toml  justfile  README.md  PLAN.md
  configs/  datasets.yaml dataset_checksums.json limits.yaml dq_rules.yaml physics.yaml economics.yaml
  src/revive_ml/
    provenance.py   Tagged numbers (measured | modelled | assumed | synthetic)
    contract.py     pydantic metadata + pandera telemetry schema + bundle loader
    convert.py      demo CSV bundle -> contract bundle
    dq/             detectors.py, readiness.py, inject.py (fault injection)
    gate/           limits.py (datasheet limits), ood.py (IsolationForest)
    state/          download.py, etl_*.py, features.py, train.py, conformal.py, rules.py
    physics/        fade.py (double exponential + stress factors), montecarlo.py
    econ/           router.py, scrap.py, sensitivity.py
    pipeline.py     assess(bundle) -> report dict
    report.py       JSON report schema
    cli.py          revive-ml assess|convert-demo|download|train|validate-dq|...
    api.py          thin FastAPI wrapper (last)
  tests/  examples/  reports/  models/  docs/
```

## Report decision flow
1. Contract validation fails -> hard error (exit 2), no report.
2. Data readiness `NOT_READY` -> verdict "Insufficient or untrustworthy data", no recommendation.
3. Gate `Reject` -> "Recycle (safety limit)"; `Quarantine` -> "Inspection required", no recommendation.
4. Otherwise: state estimate -> projections per workload -> economics -> recommendation.

## Data-readiness rules (explicit, no 0-100 score)
Each check returns pass | warn | fail | inconclusive | not_applicable with evidence.
- any `fail` -> NOT_READY
- otherwise any `warn` or `inconclusive` -> READY_WITH_WARNINGS
- otherwise READY
`inconclusive` never counts as pass; an inconclusive estimate is excluded from the decision.

## State model plan
- Primary training data: Severson LFP (124 cells). NASA PCoE as a secondary set if time allows.
- Two feature sets: `full` (includes Var(dQ(V)) from per-cycle curves, as in Severson) and
  `field` (only what a used-battery bundle can provide: SOH, fade slope over the window,
  resistance ratio to the earliest record, temperature stats). Bundles use `field`.
- Targets: current SOH (from features that exclude capacity, as a cross-check) and remaining
  cycles to 80 % of nominal.
- Baselines: naive mean -> ElasticNet -> HistGradientBoosting. GroupKFold by cell id.
- Intervals: MAPIE CV+ with grouped folds, coverage measured on outer held-out cells.
- ML output passed to physics: fade rate at Severson reference conditions
  (100 % DoD, 30 degC, the protocol's C-rate) = (SOH_now - 0.8) / RUL.

## Risks
| Risk | Mitigation |
|---|---|
| 8.3 GB Severson download slow or fails | background download with resume; log; continue with what exists |
| Severson .mat is MATLAB v7.3 (HDF5 references) | read with h5py only the summary and Qdlin arrays |
| Pack-level data vs cell-level training data | normalise features (SOH fraction, resistance ratio); OOD warning |
| LFP model applied to NMC demo pack | chemistry OOD warning in every report; the report says so |
| Prices for economics not sourceable offline | every price has source + retrieval date or is marked PLACEHOLDER |
| Physics below 80 % SOH is extrapolation | every projected point tagged "Projected (physics model)"; two bands |
| Demo data fails data quality | expected and correct: demo report says "Insufficient or untrustworthy data". A second, clearly synthetic clean bundle shows the full path |

## Status (2026-11-03): phases 0-7 done
| Phase | Commit message prefix | Evidence |
|---|---|---|
| 0 | Phase 0 | env/network survey, this file |
| 1 | Phase 1 | contract, converter, CLI slice |
| 2 | Phase 2 | reports/dq_validation.json |
| 3 | Phase 3 | reports/gate_validation.json |
| 4 | Phase 4 | reports/state_metrics.json, severson_etl_log.json |
| 5 | Phase 5 | reports/physics_sanity.json |
| 6 | Phase 6 | reports/econ_sensitivity.json |
| 7 | Phase 7 | README, docs/model_cards, docs/judge_qa.md, thin FastAPI wrapper |
`just all` (lint, 89 tests, validate-dq, train-gate, physics-check, sweep, demo) reproduces all
reports and models byte-identically (fixed seeds).

## Decisions log
- D1: Python 3.13 venv (3.15 lacks guaranteed wheels).
- D2: raw data cache outside OneDrive.
- D3: NMC demo pack handled as NMC; LFP model flagged out-of-distribution for it.
- D4: telemetry timestamps in the demo are regular; detector tested on injected faults only.
- D5: `temperature_c` <- `max_cell_temp_C` (conservative for limits).
- D6: the engine reads CSV/parquet bundles only; the demo DuckDB is never opened by the engine.
- D7 (phase 2): detector thresholds were developed on seeds 0-39; reported rates use held-out
  seeds 1000-1099. A false-positive source (SOC quantisation in the stuck check) was found
  and fixed on the development seeds.
- D8 (phase 3): one IsolationForest on pooled NASA + synthetic windows gave 25-35 % false
  quarantine on unseen NASA cells and ~0 % spike detection on packs. Replaced by two families:
  `measured_cells` (NASA, measured, leave-cells-out 12-fold) and `synthetic_packs`
  (simulated). Packs use the pack model; the report names the family and its provenance.
- D9 (phase 3): an IsolationForest saturates beyond the training range, so gross spikes can
  score only moderately. Added an explicit training-envelope rule (2+ windows outside
  [q0.1 - 3w, q99.9 + 3w]) next to the forest score. Slow drift is NOT reliably caught by a
  window-level filter (measured 0-10 %); documented as a limitation.
- D10 (phase 3): NASA PCoE cells B0033-B0056 contain zero or constant capacity records;
  only B0005-7, B0018, B0025-32 with capacity >= 1.6 Ah are used as healthy windows.
- D12 (phase 4): Severson cleaning is rule-based and logged (reports/severson_etl_log.json).
  Five batch-2 files with truncated policy strings are continuations of batch-1 cells; they are
  paired by index order within a policy group (barcodes are not readable strings in the files)
  and merged only when capacity is continuous (gaps 0.05-1.1 %). The recorded cycle_life is
  used as the EOL label only when capacity data confirm it (<= 0.89 Ah at that cycle): this
  excludes b1c8, b1c10, b1c12, b1c13, b1c22 (labels not supported by data) and b3c23, b3c32
  (never reach 0.88 Ah). Result: 128 usable cells. The paper reports 124; the 4-cell
  difference is not reconciled here.
- D13 (phase 4): deployed RUL model uses FIELD features only (what a bundle can provide).
  FULL features (with Var dQ(V)) are reported for comparison but cannot be computed from a
  bundle. The ML SOH model (no capacity features) is a reported cross-check; bundle SOH comes
  from the latest capacity test.
- D14 (phase 4): MAPE for RUL is computed on windows with true RUL >= 50 cycles (undefined near 0).
- D15 (phase 4): GRU/LSTM not attempted (torch not installed; optional per the prompt).
- D16 (phase 4): CV+ uses MAPIE's gamma (relative) conformity score because RUL is positive and
  heteroscedastic; coverage is measured with nested grouped CV (outer 5 x inner 5 by cell).
- D11 (phase 3): gate models are committed (6.4 MB joblib, scikit-learn 1.9.1) so `assess`
  works without retraining; `just train-gate` reproduces them (fixed seed 0).
