# REVIVE-TERY backend API

One local service in front of everything the front end needs:

```
 React/Dash UI ──HTTP/SSE──▶  revive_api (FastAPI)
                               ├─ db.py            the only door to DuckDB (single writer, shared lock)
                               ├─ services/runs    RunController → virtual replay | simulated ESP32 | real ESP32
                               ├─ services/ingest  .csv/.xlsx/.zip → ml_telemetry
                               └─ services/assess  full ML engine (revive-tery-ml) or the lite analyzer
```

Local only: it binds to 127.0.0.1 and has no login. Hardware access is **monitor-only**: the API reads
from the ESP32 and has no way to write to it.

## Run

Python 3.13 (the ML engine is built on it). One-time setup, outside OneDrive:

```powershell
py -3.13 -m venv "$HOME\venvs\revive-backend"
& "$HOME\venvs\revive-backend\Scripts\python.exe" -m pip install -r requirements.txt -e ..\..\revive-tery-ml
```

Start (from this folder):

```powershell
& "$HOME\venvs\revive-backend\Scripts\python.exe" -m uvicorn revive_api.main:app --host 127.0.0.1 --port 8000
```

Interactive docs: http://127.0.0.1:8000/docs. Use `REVIVE_DB=<path>` to point at a database copy.
Close the Dash app and the ReLife desktop app first if they hold the database open for writing:
DuckDB allows one writer.

## Endpoints

| Method and path | Does |
|---|---|
| `GET /api/health` | Status, database path and tables, ML engine version |
| `GET /api/batteries`, `GET /api/batteries/{id}` | Database batteries and uploaded ones; profile, health history, events, telemetry |
| `GET /api/ports`, `GET /api/faults` | Serial ports; simulator fault list |
| `POST /api/runs` | Start `virtual` replay, `simulated` ESP32 or `hardware` run |
| `POST /api/runs/stop`, `POST /api/runs/fault` | Stop; inject a fault into a simulated run |
| `GET /api/runs/current` | Snapshot with the last N readings |
| `GET /api/runs/stream` | Server-sent events: `snapshot` messages with only the new readings |
| `POST /api/uploads`, `GET /api/uploads` | Store `.csv/.xlsx/.zip` (form field `data_provenance`); ingest log |
| `POST /api/assessments` | Assess a battery: `engine` = `auto` (full, else lite with the reason), `full` or `lite` |
| `POST /api/assessments/bundle` | Full ML engine on a zipped data-contract bundle |
| `GET /api/assessments`, `GET /api/assessments/{id}` | Saved assessments (summary + full report) |

Every assessment returns a normalised `summary` (decision, rationale, readiness, gate, SOH, failed checks,
the old rule's answer, warnings) for cards, plus the complete `report` with a provenance tag on every number.

## Which engine runs

* **full** (revive-tery-ml): 14 data-quality checks, safety gate, ML remaining life with a CV+ interval,
  physics projection, economics. Needs timestamps and a capacity test. The demo pack goes this way.
* **lite** (`src/ml_analyzer_suggester.py`): capacity-based triage for uploads that cannot meet the contract,
  e.g. cycler logs with no time column. `auto` falls back to it and puts the reason in `summary.warnings`.

Nothing is guessed to make an upload fit: no timestamps means no full assessment.

## Tests

```powershell
& "$HOME\venvs\revive-backend\Scripts\python.exe" -m pytest
```

They run against a scratch copy of the database, never the project file.
