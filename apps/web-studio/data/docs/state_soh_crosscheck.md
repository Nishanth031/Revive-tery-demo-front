# Model card: SOH cross-check model (no capacity features)

| | |
|---|---|
| Code | `state/train.py` (evaluated, not deployed) |
| Task | Current SOH from resistance ratio, temperatures, cycle count, Var/min of dQ(V) and charge time, with no capacity-derived input |
| Data and validation | as the RUL model: 128 Severson LFP cells, GroupKFold(10) by cell |

| Model | RMSE (SOH fraction) | MAPE |
|---|---|---|
| Naive mean | 0.043 | 3.66 % |
| ElasticNet | 0.024 | 1.90 % |
| Gradient boosting | 0.013 | 1.02 % |

**Why it is not used in assessments.** Its strongest inputs (dQ(V) curve features, charge time)
need per-cycle lab data that a battery bundle does not carry. The report's SOH comes from the
latest capacity test. With no capacity test, the decision is "Insufficient data", which matches
the existing project rule.
