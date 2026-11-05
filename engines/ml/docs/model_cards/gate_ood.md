# Model card: gate OOD / sensor-noise filter (two families)

| | `measured_cells` | `synthetic_packs` |
|---|---|---|
| File | `models/gate_ood_measured_cells.joblib` | `models/gate_ood_synthetic_packs.joblib` |
| Used for | single-cell bundles | packs (series or parallel > 1) |
| Training data | NASA PCoE B0005-7, B0018, B0025-32 (24 and 43 degC), cycles with capacity >= 1.6 Ah; **measured** | 150 clean packs from `revive_ml.synth` (LFP/NMC, 1-30 s sampling); **synthetic** |
| Training windows | 28,921 | 54,998 |
| Validation | 12-fold, one cell held out per fold | 5-fold by seed |
| Clean quarantine rate (segments) | 0.2 % | 0.0 % |
| Clean window flag rate | 1.1 % | 1.0 % |
| Detection: 3 voltage spikes 0.15-0.4 V/cell | 1.9 % | 100 % |
| Detection: 1-3 row dropout to 0 V | 59.7 % | 97.3 % |
| Detection: voltage ramp 50-150 mV/cell | 0.2 % | 10.0 % |
| Detection: temperature ramp 5-15 degC | 0.4 % | 0.0 % |

**Algorithm.** IsolationForest (300 trees, seed 0) on 8 window features (20 rows, stride 10):
normalised voltage level, RMS C-rate, residual noise and largest residual of dV after removing
charge and ohmic effects, residual drift t-statistic, temperature slope and largest temperature
deviation, repeated-voltage share. Quarantine if more than 10 % of windows score below the 1st
percentile of training scores, or if 2 or more windows fall outside the training envelope. The
envelope is there because an IsolationForest saturates beyond the training range.

**What it is.** An out-of-distribution and sensor-noise screen that sends batteries to
inspection. **What it is not.** A fault detector, a diagnosis, or a safety certification. It is
blind to slow drift. NASA's natural measurement tails hide moderate spikes. The pack model only
knows the simulator, so on real pack data it would measure "unlike the simulator". Expect high
quarantine rates on real packs until it is retrained on measured healthy pack windows.
