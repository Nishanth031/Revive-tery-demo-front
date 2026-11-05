# Demo script (5 minutes, follows the guided tour)

Start: `just api` (optional) and `just web`, open `http://localhost:8080/#/command?demo=1`. The tour bar runs at the
bottom (arrows / space / Esc). Every number on screen comes from the engine's real reports on a SYNTHETIC fleet.

| Time | Screen | Say |
|---|---|---|
| 0:00-0:40 | Command Center | "70 packs: the user's 60-pack fleet plus four platform packs and six labelled test cases, each run through five stages: data quality, safety gate, state of health with remaining life, physics projection and economics. 25 go to a second life (stationary storage), 24 to recycling, 15 need inspection, 6 have data the engine refuses. The funnel shows where packs leave." |
| 0:40-1:30 | A Repurpose pack | "Why: the top reasons, each citing a field of the report. Confidence is a documented heuristic, not a probability. The projection shows the central line, the ML interval and the Monte Carlo band against the application's SOH limit." |
| 1:30-2:10 | What-if | "The tariff is a PLACEHOLDER input. Drag it below this pack's break-even (about 0.06 USD/kWh) and the decision flips to Recycle. That's the honest headline: the economics sit on an unsourced input, and the app shows where." |
| 2:10-2:30 | No Reuse | "No pack goes to reuse in a vehicle: valued as the new EV pack it replaces, reuse earns 13.5 USD per usable kWh a year versus 15.7 for stationary storage, which also lasts longer." |
| 2:30-2:50 | Safety-rejected pack | "The gate overrules economics: over-temperature or resistance doubling means recycling, no second-use suggestion." |
| 2:50-3:20 | Live: a flaw pack | "A test case with a mid-record sign flip: data quality stops the engine, later stages stay grey with the reason. Nothing is guessed." |
| 3:20-3:40 | Fleet plan | "Packs assigned to applications under demand limits, with the value we give up against greedy routing." |
| 3:40-4:25 | Hardware (45 s segment) | "Monitor-only bench: the ESP32 never reads the serial port and drives nothing on the battery path. Fuse, manual switch, two DS18B20, CRC and sequence numbers on every line. The sketch compiles for both range profiles; it has not been flashed here. Low voltage only, never an EV pack." |
| 4:25-4:45 | Circuit Studio preset | "Simulated ESP32 with an over-voltage fault: readings are withheld and the alert timeline shows the critical message." |
| 4:45-5:00 | Model evidence | Limits slide (below). |

## 60-second version

Command Center (split and funnel) -> one Repurpose pack (top reasons, confidence) -> drag the tariff past the break-even
and watch it flip -> "synthetic data, placeholder prices, LFP-trained model, monitor-only hardware".

## Limits slide

- All 70 packs and their dense telemetry are **SYNTHETIC**; results show the pipeline works, not anything about real batteries.
- Costs and the tariff are **PLACEHOLDER** inputs; the decision flips near 0.06-0.08 USD/kWh.
- The state model is **LFP-trained** (Severson cells); 91.5 % measured coverage vs 90 % nominal on held-out LFP cells; it
  does not transfer to NMC/NCA, and the app says so.
- Hardware is **monitor-only**, low-voltage bench, never an EV pack; the firmware was compiled, not flashed.

## Fallback plan

| If this fails | Do this |
|---|---|
| The browser or the page | Play the backup video (docs/RECORD_BACKUP.md); or open any page from the sidebar: everything runs offline from the snapshot. |
| The API | Nothing to do: the topbar shows "Snapshot" and every page uses `data/fleet_reports.json`. |
| The serial device | Use Circuit Studio's Simulator source or a preset link from Live assessment; say "simulated" out loud. |
| DuckDB-WASM (CDN) | The app falls back to the CSV copy in `data/demo/` automatically. |
