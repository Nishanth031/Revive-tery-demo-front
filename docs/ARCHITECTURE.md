# Architecture

## Layers

```
 firmware ─▶ bms ─▶ database ─▶ api ─▶ web-studio (read-only GETs)
 uploads ──▶ lite ─▶ database ─▶ api
                  └─▶ ml (full engine) ─▶ api, web-studio (ports)
 relife-studio (self-contained)  ─ ported to ─▶ web-studio
 circuit-studio ─ uses ─▶ bms, lite, database (flat imports)
```

Dependencies point one way: `contracts` → engines → services → apps. An app never reaches into an engine's internals, only its public interface (listed in each `MODULE.md`).

## Why edits stay local

| Mechanism | What it does |
|---|---|
| **Contracts** (`contracts/`) | The only agreed shapes between parts: bundle metadata, telemetry columns, ESP32 line, report. Parts can change freely behind them. `check_contracts.py` guards the examples. |
| **Config in files** | ML tunables live in `engines/ml/configs/*.yaml`; platform settings in `config/`. No magic numbers to hunt for. |
| **Registry** (`registry.json`) | One list of components, their paths, who consumes them and what to run after a change. `impact.py` turns your diff into a checklist. |
| **Parity tests** | Browser engines are ports of Python ones; `npm test` compares them to golden outputs generated from Python. A drift fails a test instead of reaching a demo. |
| **Independence rule** | `engines/ml` imports nothing else. The lite bridge is the only adapter between app data and the contract. |
| **Env overrides** | `REVIVE_DB`, `REVIVE_PLATFORM_ROOT`, `REVIVE_ML_CACHE`: no hard-coded absolute paths. |

## Deliberate non-changes

- Flat imports in `engines/bms`, `engines/lite`, `engines/database` stay flat (the platform sets `PYTHONPATH`).
- `engines/ml` keeps the `revive-tery-ml` layout (paths resolve relative to it).
- Two different `bms_engine.py` files remain separate (Circuit Studio vs ReLife).
- The decision vocabulary (reuse/repurpose/recycle) is a mapping layer in `config/decision_map.json`; engine logic is untouched.

## Upgrade (2026-11-05): fleet, insight layer, snapshot/live data flow

```
 user's fleet DB ─▶ engines/database/import_fleet.py ─▶ data/db (battery_registry, battery_asset, telemetry (original),
 (revive-tery-DB)                                         telemetry_dense (SYNTHETIC), views, runtime tables)
                                     │
             engines/database/fleet_reports.py ─▶ fleet_reports (engine + insight per pack)
                                     │
 engines/ml: pipeline.assess ─▶ revive_ml.insight (explain, confidence, what-if, robustness, next actions,
                                                    fleet plan, impact, passport)  ── ported to insight.js
                                     │
 services/api: /api/fleet, /api/battery/{id}, /api/whatif, /api/meta, /api/history/*   (live)
 apps/web-studio: data/fleet_reports.json, db_meta.json, history.json (snapshot, `just web-db` + `just web-regen`)
                  Command Center prefers the live API when it answers, else the snapshot, else a Web Worker
 firmware v1.1 ─▶ ESP32 line (seq, t_ms, ambient, crc) ─▶ bms_engine / bms.js (crc_errors, dropped_lines)
 engines/firmware/wokwi/diagram.json ─▶ tools/wokwi_to_circuit.mjs ─▶ data/circuit.json ─▶ ui/circuitView.js
```

- The insight layer only reads reports; new report content is the additive `insight` key (contract v1.1).
- `telemetry_dense` is SYNTHETIC and generated; the original rows are kept unchanged and selectable (`telemetry_source`).
- Python stays the source of truth: `scripts/fleet_parity.py` checks Python and JS give the same decision per pack.
