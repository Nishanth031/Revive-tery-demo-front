# HANDOFF: apps/revive-front

## Run it

```
cd apps/revive-front
npm run sync          # refresh data/ from apps/web-studio/data (read-only copy)
npm run serve         # http://localhost:8090
```

- LIVE mode: run `just api` from the platform root first. The status chip turns to `LIVE · API v… · ML engine v…`;
  it re-probes every 10 s and on window focus.
- SNAPSHOT mode: no API needed. The chip reads `SNAPSHOT · generated <date>`; live-only panels say so.
- Demo: `http://localhost:8090/?demo=1` or press `D` (60 s, `Esc` stops). `?` shows shortcuts.
- Screenshots + checks: serve the site, then `node tools/shoot.mjs` (Edge/Chrome over DevTools, no npm install).

## What was verified (and how)

| Check | Result |
|---|---|
| Boot in SNAPSHOT mode, all 7 routes | `tools/shoot.mjs`: 21 shots (7 routes × 1440/1024/390 px), no console errors, no page exceptions, no horizontal overflow, no `NaN`/`undefined`/`[object` in the visible text. Report: `docs/shots/report.txt` |
| All 70 packs open | each `#/pack/<id>` mounted in the browser, including the 6 `NO_DECISION` and 6 test-case packs: 0 errors, 0 bad text |
| Bench | driven against `tools/mock_sse.mjs`: start, SSE scopes, fault injection, "readings withheld" panel, alert timeline |
| Frame rate | adaptive-quality sampler logged `quality: high (70 fps over the first 90 frames)` on the home hero in the in-app browser |
| Contrast | body pairs 5.55:1 to 16.85:1 (lowest: paper-100 on green-600 chips, 5.55:1); muted text on paper 7.48:1 |
| Guards | `python scripts/check_contracts.py`: 0 errors, 0 warnings. `git status --porcelain`: only `?? apps/revive-front/` plus the pre-existing ` M data/db/revive_tery.duckdb` (modified before this work started; not touched here) |
| Offline | fonts, GSAP, Lenis and Three.js are vendored; the only network requests are `data/*` and the local API |

## Not verified / known gaps

- **LIVE mode was not exercised against the real API.** The API was down during the build and the brief forbids starting it.
  Live code paths (projection chart, what-if, plan, passport, history, analyze) follow the documented response shapes and
  guard every field, but have only been run against the mock (bench) or not at all (analyze, plan, projection, passport).
  Analyze and the history chart render the response generically for that reason.
- **impeccable detector not run**: `npx impeccable detect` was blocked by the session's permission policy (it downloads
  external code). A manual audit replaced it: palette-only colours (one stray warm hex was replaced), contrast table above,
  focus rings, 44 px targets, skip link, `aria-live` on the status chip, loader and bench timeline.
- **Layers MCP** needed sign-in in this session: skipped; nothing was sent to it.
- **Funnel waves**: `summary.funnel` has five counts, so it yields **four** real drops (data quality, gate, state,
  projection + economics). The 3D pack peels in four data-sized waves across the five stage panels rather than inventing a fifth.
- **Projection sketch on the home page** is an illustration of shape; its numbers (median central years and band) are fleet
  medians computed from `insight.years_range`, and the panel says so.
- In a background tab, or a hidden browser pane, browsers stop animation frames: the loader then removes itself after
  4 s and route changes skip the curtain, so the site never hangs.
- Headless Chrome/Edge renders WebGL through SwiftShader for the shots; real GPUs look smoother.

## Decisions taken (brief left them open)

- `configs.json` is also copied by the sync script: it supplies the placeholder tariff (0.08 USD/kWh) and the workload
  labels, so the what-if track and the REUSE = 0 note read real config values instead of hard-coding them.
- REUSE = 0 is explained from data: the low-speed EV option's valuation mode (`avoided_new_pack`) and how many packs have a
  low-speed EV net value above recycling now (computed at runtime).
- The fleet "source" filter follows `services/api/revive_api/services/fleet.py` (user = `user fleet` in `registry_source`).
- Provenance choices on Analyze come from `services/ingest.py::PROVENANCES` (`measured, simulated, synthetic`), default `synthetic`.
- Extra files beyond the listed tree: `assets/js/core/demo.js` (demo tour + shortcuts card), `tools/shoot.mjs` report
  `docs/shots/report.txt`.
- Lenis 1.1.20 and GSAP 3.13.0 (ScrollTrigger, SplitText, Flip, ScrollToPlugin) and Three r160.1 are vendored.

## Database-writing calls (all behind a click and a written warning)

`POST /api/intelligence/analyze` (Analyze step 2: warning line, provenance select, and a required "I understand" checkbox),
`POST /api/runs`, `/api/runs/stop`, `/api/runs/fault` (Bench: warning line above the controls; `source: "simulated"` only).
None of them was called against the real API during the build.

## registry.json entry (paste into `components`; not edited here)

```json
{
  "id": "revive-front",
  "name": "REVIVE-TERY luxury front end (static, animated, snapshot + live)",
  "kind": "app",
  "paths": ["apps/revive-front/"],
  "consumers": ["api", "web-studio"],
  "on_change": ["cd apps/revive-front && npm run sync && npm run serve  # then open http://localhost:8090"],
  "regenerate_when_upstream_changes": ["cd apps/revive-front && npm run sync"]
}
```

Note: elsewhere in this registry `consumers` lists who *uses* a component. If you keep that meaning, also add
`"revive-front"` to the `consumers` of `api` and `web-studio` and set this entry's `consumers` to `[]`.
