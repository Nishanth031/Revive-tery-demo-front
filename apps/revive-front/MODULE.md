# MODULE: apps/revive-front

## Purpose

The presentation front end of REVIVE-TERY: a scroll-driven, animated site that explains how the engine decides
reuse / repurpose / recycle and lets a visitor explore the fleet, a single pack, the fleet plan, an upload dry run and the
simulated bench. It shows only numbers that come from the API or the snapshot files; it never computes a decision itself.

## Public interface

- **Consumes the API** (`http://127.0.0.1:8000`, override with `localStorage["revive.api.base"]`):
  `GET /api/health, /api/meta, /api/fleet, /api/fleet/summary, /api/battery/{id}, /api/battery/{id}/history,
  /api/battery/{id}/passport, /api/faults, /api/runs/stream`; `POST /api/whatif, /api/fleet/plan, /api/intelligence/map`.
  Behind an explicit click plus a written warning: `POST /api/intelligence/analyze, /api/runs, /api/runs/stop, /api/runs/fault`.
- **Consumes snapshot files** copied from `apps/web-studio/data/` by `tools/sync_snapshot.mjs`:
  `fleet_reports.json, db_meta.json, history.json, decision_map.json, configs.json, docs/*.md`.
- **Produces** nothing that other modules read. It writes no files and opens no database.

## Rules

1. Snapshot first: every page renders from `data/` when the API is down, and marks live-only features as locked
   ("Start the API (`just api`) to unlock this"). Nothing is faked.
2. Honesty marks are permanent: the SYNTHETIC DATA · SCREENING ONLY ribbon, provenance per pack, test-case badges,
   "modelled · placeholder inputs" wherever money appears, "heuristic, not a probability" next to confidence,
   "UL 1974-style triage: screening, not certification" at the gate, the LFP-trained caveat for non-LFP packs.
3. Monitor-only: no hardware controls; the bench sends `source: "simulated"` only and never calls `/api/ports`.
4. Palette is maroon / half-white paper / dark green only (tokens in `assets/css/tokens.css`).
5. No build step, no framework, no CDN at runtime; libraries live in `assets/vendor/`.

## How to run

`npm run sync && npm run serve`, open http://localhost:8090. `just api` in the platform root enables LIVE mode.
