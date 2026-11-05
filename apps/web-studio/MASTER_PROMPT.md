# REVIVE-TERY Studio — Master Prompt for Claude Code Opus 5.5

> **Purpose:** Debug, fix, and rebuild the frontend of the REVIVE-TERY Studio web app so that every page opens correctly, all 4 backend engines connect and display properly, and the UI is a clean minimalistic dashboard for demoing engine functionality. This is a demo frontend — the only goal is to verify that the engines work.

---

## 🔒 ABSOLUTE CONSTRAINTS — READ FIRST

1. **DO NOT modify any backend engine source code.** The following are READ-ONLY:
   - `data/firmware/revive_tery_esp32.ino` — ESP32 hardware firmware (C / Arduino)
   - `assets/js/engines/bms.js` — BMS engine (ported from Python `bms_engine.py`)
   - `assets/js/engines/esp32sim.js` — Simulated ESP32 (ported from Python `esp32_sim.py`)
   - `assets/js/engines/runController.js` — Run controller
   - `assets/js/engines/pipeline.js` — Full ML pipeline orchestrator
   - `assets/js/engines/dq.js` — 14 data-quality detectors
   - `assets/js/engines/gate.js` — Safety gate (IsolationForest OOD)
   - `assets/js/engines/state.js` — State/RUL (HistGradientBoosting + MAPIE CV+)
   - `assets/js/engines/physics.js` — Physics projection (double-exponential fade + Monte Carlo)
   - `assets/js/engines/econ.js` — Economics router
   - `assets/js/engines/lite.js` — Lite analyzer
   - `assets/js/engines/contract.js` — Data contract & upload adapter
   - `assets/js/engines/relife.js` — ReLife BMS engine
   - `assets/js/lib/np.js`, `assets/js/lib/csv.js`, `assets/js/lib/provenance.js`, `assets/js/lib/md.js` — Supporting math/parsing libraries

2. **DO NOT modify any data files** under `data/` — configs, models, demo CSVs, samples, reports, docs, firmware, bundles, relife.json, circuit.json.

3. **DO NOT modify tests/** or **tools/** directories.

4. **DO NOT change the source code language.** The frontend is plain HTML + CSS + vanilla JavaScript ES modules. No frameworks, no bundlers, no TypeScript, no React/Vue/Angular.

5. **DO NOT change the project workflow.** Hash routing (`#/page`), static file serving, `localStorage` persistence, lazy page loading via dynamic `import()`, `boot()` → `Promise.all` asset loading — all stay as-is.

6. **DO NOT change vendor libraries** (`assets/vendor/jszip.min.js`, `assets/vendor/xlsx.full.min.js`).

---

## 📂 PROJECT STRUCTURE (reference)

```
index.html                       ← App shell (sidebar + topbar + #content)
assets/css/app.css               ← All styles, light/dark themes via CSS vars
assets/js/app.js                 ← Router, shared state (app object), boot()
assets/js/engines/*.js           ← 12 ported engines (READ-ONLY)
assets/js/lib/*.js               ← Math, CSV, provenance, markdown (READ-ONLY)
assets/js/pages/*.js             ← 11 page modules (EDITABLE — this is the frontend)
assets/js/ui/dom.js              ← DOM toolkit: h(), card(), kpi(), table(), etc. (EDITABLE)
assets/js/ui/charts.js           ← SVG line charts, gauge, bar list (EDITABLE)
assets/js/ui/report.js           ← Full & lite report renderers (EDITABLE)
assets/vendor/                   ← JSZip 3.10.1 + SheetJS 0.18.5 (READ-ONLY)
data/                            ← All data files (READ-ONLY)
```

### The 4 Backend Engines/Software (untouchable):
| # | Engine | Language | Source files |
|---|--------|----------|-------------|
| 1 | **ESP32 Hardware** | C (Arduino `.ino`) | `data/firmware/revive_tery_esp32.ino` |
| 2 | **BMS Engine** | Python (JS port) | `engines/bms.js`, `engines/runController.js`, `engines/esp32sim.js` |
| 3 | **ML Engine** | JSON models | `engines/pipeline.js`, `engines/dq.js`, `engines/gate.js`, `engines/state.js`, `engines/physics.js`, `engines/econ.js`, `engines/lite.js`, `engines/contract.js` |
| 4 | **Database** | DuckDB (demo CSVs) | `data/demo/*.csv` (8 tables), `localStorage` stores |

### The 11 Pages (hash routes):
| Route | Page module | Engine(s) used |
|-------|-------------|---------------|
| `#/overview` | `pages/overview.js` | — |
| `#/bench` | `pages/bench.js` | BMS, ESP32sim, RunController |
| `#/analyze` | `pages/analyze.js` | Lite, Contract, full ML pipeline |
| `#/dqlab` | `pages/dqlab.js` | Contract, full ML pipeline |
| `#/physics` | `pages/physics.js` | Physics projection |
| `#/economics` | `pages/economics.js` | Economics, Physics |
| `#/database` | `pages/database.js` | — (reads demo tables + localStorage) |
| `#/evidence` | `pages/evidence.js` | Markdown renderer |
| `#/relife` | `pages/relife.js` | ReLife BMS |
| `#/hardware` | `pages/hardware.js` | ESP32sim constants, BMS constants |
| `#/backend` | `pages/backend.js` | — (fetch calls to FastAPI) |

---

## 🎯 TASK: Debug, fix, and rebuild the frontend

### Phase 1 — Fix page loading and routing bugs

1. Open each of the 11 pages via its hash route and verify it renders without errors.
2. Check the browser console for: import failures, undefined references, missing DOM elements, unhandled promise rejections, `TypeError`/`ReferenceError` on render.
3. Fix any page that fails to load. Common issues:
   - A page module imports a symbol that `dom.js` or `charts.js` doesn't export.
   - A page calls an engine function with wrong argument shape.
   - A page reads `app.assets.X` before boot finishes or when `X` is `null`.
   - SVG rendering errors in `charts.js` (NaN coordinates, missing data guards).
   - `localStorage` parse errors crashing a page.
4. Ensure `boot()` in `app.js` completes without errors — all 8 demo CSVs, all model JSONs, relife.json, circuit.json load and parse.
5. Ensure the theme toggle works and re-renders the current page.
6. Ensure the mobile sidebar (hamburger menu) opens/closes.

### Phase 2 — Fix engine integration on each page

For each page, verify the engine actually runs and produces visible output:

**Circuit Studio (`#/bench`):**
- "Replay" source starts and the BMS engine processes readings → voltage/current/temperature KPIs update, SOC gauge moves, SOH gauge shows a value with basis text, traces chart draws.
- "Simulator" source starts the SimulatedESP32 → same live display, fault injection buttons work.
- "Real ESP32" shows the Web Serial UI (or a "not supported" banner in unsupported browsers).
- The circuit SVG diagram renders with colored wires and pin labels.
- Stop button stops the run. Decision card appears when the run ends.

**Analyze batteries (`#/analyze`):**
- "Assess demo pack" button works → runs `pipeline.assess()` → full report renders (decision card, 14 DQ checks, gate details, state, projection charts, economics).
- File upload (CSV/XLSX/ZIP) works → lite analyzer runs → report shows.
- Sample files from `data/samples/` can be loaded.
- The lite ↔ full engine toggle works.

**Data-quality lab (`#/dqlab`):**
- Bundles load from `data/bundles.json`.
- Selecting a bundle and clicking "Run" calls `pipeline.assess()` → report renders.
- Metadata editing and re-run works.

**Physics projection (`#/physics`):**
- Entering SOH, cycles, bounds → `project()` runs → central/ML/MC/knee trajectories chart draws with bands.

**Economics (`#/economics`):**
- Pack inputs → recycle vs second-life value table renders.
- Price-sensitivity sweep chart draws.

**Database (`#/database`):**
- All 8 demo tables render in scrollable tables.
- Upload log, run log, assessment history tables render.
- CSV export buttons work.

**Model evidence (`#/evidence`):**
- Validation reports load and render as formatted JSON/tables.
- Model cards (.md files) render as HTML.

**ReLife BMS Studio (`#/relife`):**
- Profile + adapter selection → compatibility check → scenario evaluation table → 30s pulse test chart.

**Firmware & hardware (`#/hardware`):**
- Circuit diagram, line protocol table, safety limits render.
- `.ino` file download button works.

**Backend connector (`#/backend`):**
- URL input, health/batteries/assessments/uploads buttons work (show response or connection error).

### Phase 3 — Rebuild the Overview as a unified dashboard

Replace the current Overview page (`pages/overview.js`) with a **minimalistic engine dashboard**. Requirements:

1. **Engine Status Grid** — a 2×2 (or 4-column) grid of cards, one per backend engine:
   - **ESP32 Hardware**: status indicator (firmware file present ✓), link to `#/bench` and `#/hardware`.
   - **BMS Engine**: status indicator (BMS loaded ✓, last run count from `app.runLog`), link to `#/bench`.
   - **ML Engine**: status indicator (models loaded ✓, model stats — folds, trees, MC draws), link to `#/analyze`, `#/dqlab`, `#/physics`, `#/economics`.
   - **Database**: status indicator (tables loaded ✓, row counts per table), link to `#/database`.

2. **Quick Actions Row** — buttons that jump straight to key engine demos:
   - "Run Demo Assessment" → `#/analyze` (pre-selects demo pack)
   - "Start Bench Test" → `#/bench`
   - "Open DQ Lab" → `#/dqlab`
   - "View Database" → `#/database`

3. **System Health KPIs** — 4 KPIs in a row:
   - Models loaded (count of loaded assets)
   - Demo tables (count, total rows)
   - Assessment history (count from `app.history`)
   - Run log entries (count from `app.runLog`)

4. Keep the existing decision-flow stepper and provenance legend below the dashboard section, but make them collapsible (`<details>`).

5. **Design rules for the dashboard:**
   - Use only existing CSS classes and `dom.js` helpers (`card`, `kpi`, `h`, `icon`, `pill`, `banner`).
   - No new CSS classes — compose from existing ones.
   - No external libraries.
   - Cards should be tappable links to the relevant page.

### Phase 4 — UI cleanup (minimalism pass)

Apply these rules to every page module:

1. **Remove visual clutter**: collapse secondary info into `<details>` elements. Keep primary KPIs, charts, and decision cards visible.
2. **Consistent card structure**: every page follows `page-head` → optional `banner` → KPI row → main content cards → secondary/details.
3. **Error states**: every page that calls an engine wraps the call in try/catch and shows `banner("bad", ...)` on failure instead of a blank screen.
4. **Loading states**: show `spinner` while an engine computation runs (especially `pipeline.assess()` which may take a moment).
5. **Empty states**: show the `.empty` placeholder (dashed border, muted text) when there's no data yet, with a clear call-to-action.

---

## 🔧 FILES YOU MAY EDIT

```
index.html                         ← Only the shell markup if needed for layout fixes
assets/css/app.css                 ← Only to fix existing bugs (broken layouts, z-index, overflow)
assets/js/app.js                   ← Only to fix boot/routing bugs
assets/js/pages/*.js               ← Primary edit targets: all 11 page modules
assets/js/ui/dom.js                ← Fix/extend DOM helpers if a page needs a missing utility
assets/js/ui/charts.js             ← Fix chart rendering bugs (NaN guards, axis scaling)
assets/js/ui/report.js             ← Fix report rendering bugs
```

## ❌ FILES YOU MUST NOT EDIT

```
assets/js/engines/*.js             ← All 12 engine files
assets/js/lib/*.js                 ← All 4 library files
assets/vendor/*                    ← JSZip + SheetJS
data/**/*                          ← All data files
tests/**/*                         ← All test files
tools/**/*                         ← All tooling scripts
data/firmware/*.ino                ← ESP32 firmware
```

---

## 📋 VERIFICATION CHECKLIST

After all changes, verify:

- [ ] `python -m http.server 8080` serves the app at `localhost:8080`
- [ ] All 11 pages load without console errors
- [ ] Overview dashboard shows all 4 engine statuses as "loaded"
- [ ] Circuit Studio: Replay starts, BMS processes readings, charts update live
- [ ] Circuit Studio: Simulator starts with default params, fault injection works
- [ ] Analyze: "Assess demo pack" produces a full ML report
- [ ] Analyze: Uploading `data/samples/1_healthy_pack.csv` produces a lite report
- [ ] DQ Lab: selecting any bundle and running produces a report
- [ ] Physics: entering SOH/cycles draws projection charts
- [ ] Economics: entering pack params shows recycle vs second-life
- [ ] Database: all 8 demo tables display with correct row counts
- [ ] Evidence: reports and model cards render
- [ ] ReLife: profile → adapter → compatibility → pulse test chart
- [ ] Hardware: circuit diagram, firmware download button work
- [ ] Backend: health check button shows connection error (no server running) gracefully
- [ ] Dark mode toggle works on every page
- [ ] Mobile responsive layout works (sidebar collapses)
- [ ] `npm test` still passes (you haven't touched engines or tests)

---

## 💡 IMPLEMENTATION NOTES

- The `app` object (exported from `app.js`) is the shared state. Every page receives it via `render(root, app)`. Read `app.assets`, `app.demo`, `app.relife`, `app.circuit`, `app.liteStore`, `app.history`, `app.runLog`.
- Use `h(tag, attrs, ...children)` from `dom.js` for all DOM creation. Never use `innerHTML` except through the `html` attribute in `h()`.
- Use `card(title, body)`, `kpi(label, value, sub)`, `banner(tone, title, text)`, `pill(text, tone)`, `decisionCard(...)` for consistent UI.
- Charts use `lineChart({ series, xLabel, yLabel, height })` and `gauge(value, max, label, unit, color)` from `charts.js`.
- Engine functions are pure: `pipeline.assess(bundle, assets)` returns a result object. `bms.process(sample)` returns reading data. They never touch the DOM.
- All pages export `render(root, app)` and optionally `unmount()`. The router calls `unmount()` before navigating away.
- Serve locally with `python -m http.server 8080`. Browsers block ES modules from `file://`.
