# Model card: physics projection (not a trained model)

| | |
|---|---|
| Code / config | `physics/fade.py`, `configs/physics.yaml` |
| Form | double-exponential capacity fade (He et al. 2011) in equivalent reference cycles; Arrhenius temperature factor and C-rate term (Wang et al. 2011, Ea 31.7 kJ/mol); DoD factor (DoD)^k, k in [1, 1.5]; square-root-of-time calendar term (Naumann et al. 2018 form) |
| Anchor | starts at the measured SOH; at reference conditions (30 degC, 100 % DoD, 4C) the cycle term reaches 80 % exactly at the ML RUL |
| Parameters | all **assumed**; nominal values and priors in `configs/physics.yaml` |
| Bands | (1) ML band: CV+ RUL bounds with nominal parameters (measured coverage on held-out LFP cells); (2) Monte Carlo band: 5th-95th percentile over 1,000 parameter draws, **assumption-conditional** |
| Knee scenario | optional stronger growing exponential (eps 0.01, kappa 3) |
| Checks (`just physics-check`) | continuity exact; life falls with temperature, C-rate and DoD; 25->45 degC life ratio 2.27 (range 1.70-3.17 over the Ea prior; a 10 degC-doubling rule would give 4.0); 50 % vs 100 % DoD life ratio 2.30 with non-decreasing throughput |

Every projected point carries the label "Projected (physics model)". The temperature and C-rate
trends match Wang et al. 2011 by construction, so the checks verify the implementation; they
are not independent validation. No second-life data was available to validate projections
below 80 % SOH.
