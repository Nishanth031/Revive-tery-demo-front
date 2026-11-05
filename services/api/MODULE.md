# services/api: backend API (FastAPI)

**Purpose:** one local service in front of the DB, BMS runs, uploads and assessments. 127.0.0.1 only, no login, hardware read-only.
**Layout:** `revive_api/main.py` (routes) · `db.py` (only door to DuckDB) · `schemas.py` · `settings.py` (paths, limits, CORS) · `services/{assess,batteries,ingest,runs}.py`.
**Public interface:** the endpoint list in `README.md` (`/api/health`, `/api/batteries`, `/api/runs*`, `/api/uploads`, `/api/assessments*`). The browser app calls only read-only GETs.
**Path rule:** `settings.py` must resolve the platform root from `REVIVE_PLATFORM_ROOT` (fallback: three folders up from `services/api/revive_api`), DB from `REVIVE_DB` or `data/db/revive_tery.duckdb`, and put `engines/bms`, `engines/lite`, `engines/database` on `sys.path`.
**Origin:** `bulid X/backend/`. **Run:** `just api`. **Test:** `just test-api` (runs on a scratch copy of the DB).

**ML-led workflow (`/api/intelligence/*`, additive):** `POST /map` (dry run: how the ML reads the files), `POST /analyze` (map, store in `ml_telemetry`, record identity in `ml_battery_profile`, assess, advise; anything the ML cannot know comes back under `needs_from_user`), `POST /advise` (assess a stored battery and rank second uses; saved in `ml_suggestions`), `GET /suggestions`, `GET /profiles`. Code: `routes_intelligence.py`, `services/intelligence.py`; `main.py` only mounts the router. Test: `tests/test_intelligence_api.py`.

**Fleet (`routes_fleet.py`, `services/fleet.py`, upgrade P6):** `GET /api/fleet` (paging `offset/limit`, `q`, `decision`, `disposition`, `chemistry`, `source=user|platform|test`, `sort=net_value|soh|confidence|asset_id`, `desc`; records in the same compact shape as the web app's `lib/fleet.js`), `GET /api/fleet/summary` (dispositions, value vs recycle-all, kWh redeployed, funnel), `POST /api/fleet/plan` (demand limits -> greedy + 2-opt plan), `POST /api/fleet/refresh` (the single writer of `fleet_reports`: one connection, one transaction), `GET /api/battery/{id}` (registry + latest report + insight), `/history` (`pack_history`), `/passport` (informational), `POST /api/whatif` (overrides + region; economics only), `GET /api/meta`, `GET /api/history/assessments|suggestions|runs`. `AssessIn.telemetry_source` (`dense` default | `original`) for database packs. Test: `tests/test_fleet_api.py`.

