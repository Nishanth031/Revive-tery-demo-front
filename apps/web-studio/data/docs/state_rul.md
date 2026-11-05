# Model card: remaining-cycles (RUL) model, field features

| | |
|---|---|
| File | `models/state_rul_field.joblib` (`state/train.py`, `just train`) |
| Task | Remaining cycles to 80 % of nominal capacity, at the training protocol's conditions |
| Algorithm | HistGradientBoostingRegressor on log1p(RUL) (selected over ElasticNet and a naive mean by grouped-CV RMSE); MAPIE CV+ (`CrossConformalRegressor`, method `plus`, gamma score, 90 %) |
| Training data | Severson et al. 2019, measured: 128 A123 APR18650M1A LFP/graphite cells (1.1 Ah) after documented cleaning; 9,625 windows of 50 cycles every 10 cycles |
| Features (field) | latest SOH, fade slope and fade acceleration over the window, resistance ratio to the earliest record, mean and max temperature, cycles so far |
| Validation | GroupKFold(10) by cell for point metrics; nested GroupKFold (5 outer x 5 inner) for interval coverage |

## Metrics (cycles; held-out cells)

| Model | RMSE | MAE | MAPE (true RUL >= 50) |
|---|---|---|---|
| Naive mean | 385 | 295 | 107 % |
| Linear extrapolation of fade slope | 2308 | 1760 | 353 % |
| ElasticNet | 276 | 167 | 34 % |
| **Gradient boosting (deployed)** | **169** | **92** | **16.6 %** |
| Gradient boosting, full features with Var dQ(V) (not deployable from a bundle) | 133 | 74 | 14.3 % |

CV+ at a nominal 90 %: measured coverage 91.5 % overall (by true RUL: 0-100 95.7 %, 100-300 97.3 %,
300-700 92.4 %, > 700 80.6 %); median width 306 cycles.

## Intended use and hand-over

Diagnostic for a used battery that has capacity-test records. The output is turned into a fade
rate at reference conditions, `(SOH - 0.80) / RUL`, which the physics layer scales to a workload.
The CV+ lower bound gives the conservative path.

## Not intended for / caveats

- Not for chemistries other than LFP without retraining. NMC/NCA inputs get an explicit
  out-of-distribution warning, and the coverage figure does not apply to them.
- Pack-level, sparse capacity tests differ from per-cycle lab data. Fade slope over a few tests
  is coarser than over 50 consecutive cycles.
- Coverage is an empirical measurement on held-out Severson cells. Second-life use is a
  distribution shift.
- Says nothing below 80 % SOH; that region is physics projection.

## Known limits (added 2026-11-05, upgrade P2.10)

- **LFP-trained.** The state/RUL model is trained on Severson LFP cells. The platform applies it to NMC and NCA packs too (31 NMC and 8 NCA packs in the user's fleet). For those packs the remaining-life numbers are indicative only, and the engine's insight layer shows a `warn` reason ("State model trained on LFP, pack is NMC/NCA") and halves the in-distribution confidence factor.
- **Interval coverage does not transfer.** The CV+ interval's coverage was measured on held-out LFP cells: 91.47 % against a 90 % nominal level. That figure does not apply to other chemistries, to packs (the model sees cells) or to second-life duty.
- **Wide intervals.** On the clean LFP example pack the RUL interval is 277-590 cycles around a 390-cycle median, about 80 % of the median. The insight layer reports this width and suggests "add a recent full capacity test", which is expected to narrow it.
- **Non-LFP validation not done.** NASA PCoE cell data (`configs/datasets.yaml`, `state/etl_nasa.py`) was not downloaded or used in this build (time box). No model was retrained.
- **Synthetic fleet.** Every fleet pack and its dense telemetry is SYNTHETIC; fleet results show the pipeline works, not anything about real batteries.
