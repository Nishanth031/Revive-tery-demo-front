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
