# REVIVE·TERY front end

A luxury, heavily animated, multi-layer front end for the REVIVE-TERY platform: assess a used EV battery and decide
**reuse, repurpose or recycle**, with the reasons attached. Static ES modules, vendored libraries, no build step, runs offline.

## Run

```
cd apps/revive-front
npm run sync      # copy the studio's snapshot files into data/ (read-only on the source)
npm run serve     # python -m http.server 8090
```

Open http://localhost:8090. Start the API from the platform root (`just api`) for **LIVE** mode; without it the site runs
in **SNAPSHOT** mode from `data/` and says so in the status chip.

- `?demo=1` or the `D` key: a 60-second scripted tour. `Esc` stops it.
- `?`: keyboard shortcuts. `1`–`6`: Home, Command Center, Plan, Analyze, Bench, Evidence.

## Routes

| Route | What |
|---|---|
| `#/` | Scroll film in 8 beats: hero, the question, five stages (pinned), the verdict, trust, what-if, honesty, closing |
| `#/fleet` | Command Center: filters, sort, 70 pack cards with Flip transitions |
| `#/pack/<id>` | Verdict, reasons, confidence, RUL and years ranges, projection (live), economics, what-if, next actions, evidence, passport (live) |
| `#/plan` | Fleet assignment under per-application pack limits (live) |
| `#/analyze` | Upload: dry-run column mapping, then an explicit "Store and assess" (live) |
| `#/bench` | Simulated ESP32 bench over SSE (live; test with `tools/mock_sse.mjs`) |
| `#/evidence` | Model cards and judge Q&A |

## Tools

- `tools/sync_snapshot.mjs`: copies `apps/web-studio/data/{fleet_reports,db_meta,history,decision_map,configs}.json` and `docs/*.md`.
- `tools/mock_sse.mjs`: a local mock of the bench endpoints (no database). `node tools/mock_sse.mjs 8765`, then set
  `localStorage["revive.api.base"] = "http://127.0.0.1:8765"` and reload; remove the key afterwards.
- `tools/shoot.mjs`: screenshots of every route at 1440/1024/390 px into `docs/shots/` with a console/overflow/NaN report,
  using a locally installed Edge or Chrome over the DevTools protocol.
