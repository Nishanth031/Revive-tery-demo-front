# Judge Q&A

**What data was the ML trained on?**
Public datasets only, downloaded by `revive-ml download` with SHA-256 checksums recorded in
`configs/dataset_checksums.json`:
- *State model*: Severson et al. 2019 (Nature Energy), 128 A123 LFP/graphite 18650 cells (1.1 Ah)
  cycled to 80 % capacity under fast-charge protocols at 30 degC. These are measured lab data.
- *Gate (cells)*: NASA PCoE Battery Data Set, 12 cells with clean records, measured.
- *Gate (packs)*: synthetic packs from our own simulator, labelled synthetic everywhere.

None of the REVIVE-TERY project's own data trained anything. It is all synthetic, including the
demo pack.

**Is any result validated on a real used battery?**
No. All project data is synthetic. Metrics on public data come from held-out lab cells
(grouped CV by cell). Results on the demo bundles show the pipeline works, nothing more.

**Why does the demo pack get no recommendation?**
Its data fail three checks. SOC drops 34 points while the recorded current explains 17.1 (on the
193.6 Ah test capacity). The regenerative-braking row has the same current sign as driving. The
live SOH from telemetry (about 50 %) disagrees with the capacity test (96.8 %). The rule "any fail
-> NOT_READY" then gives "Insufficient or untrustworthy data". We report both SOH values and say
the decision would trust the capacity test (a controlled measurement), but with these failures
no decision is made at all.

**What is extrapolated?**
Everything below 80 % SOH and every workload other than the training protocol. The ML model
predicts remaining cycles to 80 % at Severson conditions. The physics layer scales that to the
user's DoD, temperature, C-rate and cycles per day, and continues below 80 %. Every projected
point is labelled "Projected (physics model)". Applying the LFP-trained model to NMC or NCA is
also extrapolation, and the report says so.

**How much should I trust the intervals?**
The CV+ interval had 91.5 % measured coverage at a nominal 90 % on held-out Severson cells, but
only 80.6 % when more than 700 cycles remained. Second-life batteries are a distribution shift,
so the coverage on them is unknown. The Monte Carlo band reflects only our assumed parameter
ranges; it is not a measured interval.

**Which assumptions matter most?**
- Physics parameters (configs/physics.yaml): activation energy 31.7 kJ/mol (Wang 2011),
  DoD exponent 1-1.5, calendar loss 1-3.5 % per sqrt(year), knee shape.
- Economics (configs/economics.yaml): second-life energy value, refurbishment, testing,
  logistics, installation and payable fractions are **PLACEHOLDERs**. Pack, system and metal
  prices are sourced and dated but indicative.
- Workloads (configs/workloads.yaml) are illustrative defaults; users can supply their own.
- Safety limits (configs/limits.yaml) are commonly published datasheet values that were not
  re-downloaded; the NMC 2.75 V floor is deliberately conservative.

**Why is no safety certification claimed?**
The gate is "UL 1974-style triage": a screening step that rejects obvious limit breaches and
sends unusual data to human inspection. Certification under UL 1974 needs an accredited body,
physical tests, cell-level inspection and documented processes, none of which software on
telemetry can provide. The limits act on the pack-average cell voltage, so a weak cell can be
hidden. The IsolationForest is an out-of-distribution filter, not a fault detector, and it misses
slow sensor drift. A "Pass" means "nothing unusual seen in this data", not "safe".

**Why not just use the existing SOH rule?**
On held-out Severson windows, asked "is at least one year (365 cycles) left?", the rule
(SOH > 80 % -> stationary storage) says yes to every window: 100 % false-go, 52 % accuracy. The
ML lower bound gets 0.6 % false-go and 84 % accuracy. Every report shows the rule's answer next
to the engine's decision.

**What did not work or was left out?**
- A single IsolationForest on pooled NASA and synthetic data: replaced by two families (PLAN.md D8).
- No GRU/LSTM was tried.
- The NASA Recommissioned dataset had no direct download.
- CALCE cells were downloaded but not used.
- 128 Severson cells vs the paper's 124.
- The demo telemetry is regular (300 s), not mixed as the brief said; the timestamp detector is
  tested on injected faults instead.

## Upgrade Q&A (2026-11-05, fleet of 70 SYNTHETIC packs)

**Why is an 85 % SOH pack recycled?** On the clean NMC reference pack, SOH 0.90 or higher goes to Second-Life and 0.85 or lower to Recycle. The engine compares the discounted value of the energy a pack can still deliver until it reaches the application's limit (minus testing, refurbishment, logistics and installation) with recycling it now. At 85 % the conservative remaining years are short, so the second-life value no longer beats the metal value. The simple rule ("SOH > 80 % -> stationary storage") ignores remaining years, costs and metal prices; the pack page shows both side by side ("Simple SOH rule says").

**Why is reuse rare, and what changed?** Before the upgrade, reuse in a low-speed EV was valued with the stationary energy tariff and always capped by the buy-new benchmark, so it never won. It is now valued as the new EV pack it replaces (BNEF 2025 average $108/kWh, pack level; 8-year assumed pack life, no storage cap). Result, reported honestly: still 0 Reuse in the fleet. Per usable kWh a year, reuse earns 108/8 = 13.5 USD while stationary storage is capped at 236/15 = 15.7 USD and lasts longer (SOH floor 60 % vs 65 %). We did not tune numbers to force it.

**How sensitive is the decision to the tariff and metal prices?** Very, by design of the inputs. The tariff (a PLACEHOLDER, 0.08 USD/kWh) flips the clean packs from Recycle to Second-Life at 0.070 (NMC) and 0.074 (LFP) USD/kWh. The clean NMC pack flips to Recycle at about 2.7x metal prices. Refurbishment costs, even at zero, do not flip it. In the full robustness grid (420 scenarios) the clean packs keep their decision in about 36-37 % of scenarios. Every pack page shows its own break-even and robustness share.

**Why is the RUL interval wide?** It is a conformal (CV+) interval with 90 % nominal coverage, measured at 91.47 % on held-out LFP cells. On the clean LFP pack it spans 277-590 cycles around a 390-cycle median (about 80 % of the median). Few capacity tests and pack-level duty unlike the training cells make it wide; "add a recent full capacity test" is the first next action, which is expected to narrow it.

**What happens for NMC when the model is LFP-trained?** The engine runs, but the remaining-life numbers are indicative only: the insight layer shows a warning reason, the in-distribution confidence factor is halved, and the model card's "Known limits" says the coverage does not transfer. NASA non-LFP cell data was not used in this build.

**What is real and what is synthetic?** Everything in the fleet is synthetic: the user's 60-pack database (labelled SYNTHETIC in its own `data_class`), the four platform packs, the six test cases, and the dense telemetry generated from each pack's registry and capacity tests. Real are the sourced prices (BNEF pack and system prices, LME metals, EIA residential price for one region), the algorithms and the firmware (compiled, not flashed).

**What is a placeholder?** Any cost, tariff or payable fraction we could not source: the tariff (0.08), testing, refurbishment, logistics, installation, recycling processing cost and payable fractions. They are marked `status: PLACEHOLDER` in `configs/economics.yaml`, listed on every report and on the pack page.

**How does the engine beat the simple SOH rule?** It refuses untrustworthy data instead of approving it (the original 12-row fleet samples: 50 of 70 refused), applies a safety gate before economics (resistance doubling, over-temperature, open high-severity events), projects remaining years per application, and prices the options. On the dense fleet the registry's SOH-threshold status agrees with the engine for 1 pack; the reasons for each disagreement are stored (`fleet_reports.rule_reason`) and shown.

**How would you validate on real batteries?** Measured capacity and resistance tests on second-life packs with known outcomes; check the CV+ coverage on them per chemistry; replace every PLACEHOLDER with quotes and the site's tariff; compare decisions against follow-up capacity tests a year later; then retrain or recalibrate the confidence weights.
