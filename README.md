# REVIVE-TERY Platform

**Problem:** Give used EV batteries a second life. Quickly assess the health of a used EV battery and decide whether it should be **reused, repurposed or recycled** (AI/ML · battery analytics · EV technology · predictive analytics).

This folder is the single, organised home for everything built so far in the five legacy folders, arranged so that **edits stay local** and **changes tell you what else to re-run**.

> All data is synthetic or simulated. Results show the pipeline works, not anything about a real battery. Hardware is monitor-only and low-voltage only.

## Layout

```
REVIVE-TERY-Platform/
├─ README.md  MASTER_PROMPT.md  registry.json  justfile
├─ docs/            PROJECT_INVENTORY.md  FOLDER_WORKFLOWS.md  ARCHITECTURE.md  CHANGE_GUIDE.md  legacy/
├─ contracts/       the interfaces between parts (JSON schemas) + CHANGELOG.md
├─ config/          platform settings + decision_map.json (engine tunables stay in engines/ml/configs)
├─ engines/
│   ├─ firmware/    ESP32 sketch
│   ├─ bms/         BMS engine, ESP32 simulator, run controller
│   ├─ lite/        lite analyzer + upload bridge
│   ├─ ml/          full ML engine (revive-tery-ml, own layout)
│   └─ database/    DuckDB build scripts, demo CSV bundle, sample uploads
├─ services/api/    FastAPI backend
├─ apps/
│   ├─ circuit-studio/   Dash dashboard
│   ├─ relife-studio/    PySide6 prototype
│   └─ web-studio/       static browser app (JS ports of every engine)
├─ data/            db/ (DuckDB), samples/
├─ scripts/         migrate_from_legacy.py  impact.py  check_contracts.py  migration_manifest.json
└─ tests/           contract guard tests
```

Every module has a `MODULE.md` (purpose, public interface, rules, origin, how to run/test).

## Start here

1. Read [docs/PROJECT_INVENTORY.md](docs/PROJECT_INVENTORY.md) (what exists) and [docs/FOLDER_WORKFLOWS.md](docs/FOLDER_WORKFLOWS.md) (how each part runs).
2. Bring the code in (read-only on the old folders, merge-copy, safe to re-run):
   ```
   pip install rust-just
   just migrate-dry      # shows the plan
   just migrate          # copies
   just check            # contracts + registry guard
   ```
3. Hand the rest to Claude Code with [MASTER_PROMPT.md](MASTER_PROMPT.md) (fixes paths, runs every test suite, reports).

## Working day to day

| I want to... | Do this |
|---|---|
| Know what my edit affects | `just impact` (uses git) or `just impact <files>` |
| Tune the ML engine | edit `engines/ml/configs/*.yaml`, then `just test-ml`, `just web-regen` |
| Change an interface | edit `contracts/`, bump `contracts/CHANGELOG.md`, update every consumer listed in `registry.json` |
| Add an engine / app | add a folder, add one entry in `registry.json`, add a `MODULE.md` |
| Run everything's tests | `just test-all` |
| Start things | `just studio` · `just api` · `just web` · `just relife` |

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/CHANGE_GUIDE.md](docs/CHANGE_GUIDE.md).
