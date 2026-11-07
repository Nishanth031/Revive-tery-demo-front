# REVIVE-TERY

> **Give used EV batteries a second life.** Assess the health of a used EV battery in minutes and decide whether it should be **reused, repurposed or recycled**, with the reasons attached.

**Team BX-125** · Track: AI/ML · battery analytics · EV technology · predictive analytics

| | |
|---|---|
| Repository | [Nishanth031/Revive-tery-demo-front](https://github.com/Nishanth031/ReviveTery) |
| Pitch deck | see [Pitch deck](#pitch-deck)) |
| Business model | [Business model](#business-model)) |

> **Honesty note.** All data in this repository is synthetic or simulated. Results show that the pipeline works, not anything about a real battery. Prices and tariffs are placeholders. Hardware is monitor-only and low-voltage only (never an EV pack).

---

## Table of contents

1. [The problem](#the-problem)
2. [The solution](#the-solution)
3. [How it works](#how-it-works)
4. [Business model](#business-model)
5. [Pitch deck](#pitch-deck)
6. [Repository layout](#repository-layout)
7. [Architecture](#architecture)
8. [Quick start](#quick-start)
9. [The front end (`apps/revive-front`)](#the-front-end-appsrevive-front)
10. [Backend API](#backend-api)
11. [Hardware bench](#hardware-bench)
12. [Testing and guard rails](#testing-and-guard-rails)
13. [Working day to day](#working-day-to-day)
14. [Demo](#demo)
15. [Limitations](#limitations)
16. [Documentation index](#documentation-index)

---

## The problem

Electric-vehicle batteries are retired long before they are dead. A pack that no longer meets a vehicle's range needs may still hold most of its capacity, but nobody can cheaply tell which packs are worth keeping. Today the choice is slow, manual capacity testing or a blunt state-of-health threshold, so good packs get recycled early and unsafe ones risk being reused.

REVIVE-TERY answers one question for every retired pack: **reuse, repurpose or recycle?**

## The solution

REVIVE-TERY runs each pack through five stages and returns a decision, the reasons, and how confident it is.

| Stage | What it does |
|---|---|
| 1. Data quality | 14 checks on the incoming telemetry. If the data is untrustworthy the engine stops and says why; nothing is guessed. |
| 2. Safety gate | Over-temperature or resistance growth overrules economics. The pack goes to recycling with no second-use suggestion. |
| 3. State of health and remaining life | ML estimate of SOH and RUL with a CV+ prediction interval. |
| 4. Physics projection | Degradation projection with a Monte Carlo band against each application's SOH limit. |
| 5. Economics | Value per usable kWh per year for each candidate application, including break-even tariffs. |

### Decision vocabulary

The engine's native decision text is mapped to the problem-statement vocabulary by [`config/decision_map.json`](config/decision_map.json). It is an additive mapping layer; engine logic is untouched.

| Disposition | Meaning |
|---|---|
| **REUSE** | Second life in a vehicle (low-speed EV) |
| **REPURPOSE** | Second life in stationary storage (residential, commercial peak shaving, telecom backup) |
| **RECYCLE** | Recover materials (includes safety-rejected packs) |
| **INSPECT** | Manual inspection required before any decision |
| **NO_DECISION** | Data not sufficient or not trustworthy |

### Key benefits (from the business model)

- **Instant assessments:** AI-driven, real-time battery health evaluation.
- **Reuse routing:** direct used batteries toward sustainable reuse, improving lifecycle management and cutting waste.
- **Cost reduction:** lower testing cost through AI-based assessment.
- **Headline value proposition:** a targeted **30% increase in battery longevity** (maximised lifespan).

## How it works

```
 ESP32 / uploaded files ──▶ data contract ──▶ [ data quality → safety gate → SOH/RUL → physics → economics ]
                                                                      │
                                      decision (reuse / repurpose / recycle / inspect / no decision)
                                      + reasons, confidence, what-if, next actions, fleet plan, battery passport
```

1. **The user supplies data:** a zipped bundle (`telemetry.csv` + `metadata.json`), a `.csv`/`.xlsx` upload, or live readings from the monitor-only ESP32 bench.
2. **The platform assesses it** with the full ML engine, or with the lite analyzer when an upload cannot meet the contract (for example, no time column). The reason for the fallback is always reported.
3. **The user gets a verdict:** the disposition, the top reasons (each citing a field of the report), a confidence value (a documented heuristic, not a probability), RUL and years ranges, and a what-if on the economics.
4. **Fleet view:** packs are assigned to applications under per-application limits, and the value given up versus greedy routing is shown.

## Business model

Source: `BX125_BMC.pdf` (Team BX-125, 5 November 2026).

| Canvas block | Content |
|---|---|
| **Value proposition** | 30% increase in longevity; instant AI assessments, reuse routing, cost reduction |
| **Customer segments** | EV fleets, e-waste solutions, energy storage systems (ESS), original equipment manufacturers (OEMs) |
| **Channels** | B2B sales, API documentation, industry conferences, partnerships with recyclers |
| **Key partners** | EV manufacturers, e-waste recycling firms, battery management system (BMS) suppliers, cloud providers |
| **Key activities** | AI/ML training, battery health assessments, API development, hardware integration |
| **Key resources** | Advanced AI capabilities and a skilled technology team |

### Customer relationships

| Priority | Relationship | Engagement | KPI |
|---|---|---|---|
| High | B2B API | API documentation | Usage metrics |
| Medium | Tech support | Direct contact | Response time |
| Medium | Sustainability | Partnerships | Engagement rate |
| Low | Community outreach | Events | Attendance numbers |
| Low | Feedback loop | Surveys | Satisfaction scores |

### Cost structure and revenue

| Cost item | Type | Amount | Period |
|---|---|---|---|
| Cloud costs | Fixed | $200,000 | Annual |
| R&D | Variable | $150,000 | Annual |
| Hosting | Fixed | $100,000 | Annual |

| Revenue line | Amount |
|---|---|
| SaaS subscriptions | $120,000 |
| API fees (consulting revenue) | $50,000 |

> The canvas figures are reproduced as stated. They are planning inputs, not results. On the canvas as written, annual costs ($450,000) exceed listed revenue ($170,000), so the model has not yet reached break-even. The financials page also repeats the cost amounts under a "Revenue streams" heading (labelled Cost 1–3); the table above reads them as costs.

### How the platform maps to the model

| Business-model element | Where it lives in this repo |
|---|---|
| B2B API (high-priority relationship, API fees) | [`services/api`](services/api) FastAPI backend, versioned [`contracts/`](contracts) |
| AI/ML training and assessments | [`engines/ml`](engines/ml) (`revive-tery-ml`) and [`engines/lite`](engines/lite) |
| Hardware integration and BMS suppliers | [`engines/firmware`](engines/firmware) (ESP32) and [`engines/bms`](engines/bms) |
| EV fleets and ESS customers | Fleet Command Center and fleet plan in the front end |
| E-waste / recycler partners | RECYCLE disposition, materials data in [`engines/database`](engines/database) |
| SaaS subscriptions | The front end and API as the hosted product surface |

## Pitch deck

`BuildX_Pitch_Deck_Template.pptx` is the BuildX template and was supplied **unfilled** (placeholders such as "Your Idea Name" and "Your Team ID"). Its structure, with the REVIVE-TERY content that belongs in each slide, is:

| Slide | Template prompt | REVIVE-TERY content |
|---|---|---|
| 1. Title | Idea name, one-liner, team ID/name, problem statement | REVIVE-TERY: assess a used EV battery and decide reuse, repurpose or recycle · Team BX-125 · AI/ML, battery analytics, EV technology, predictive analytics |
| 2. The problem | Who faces it, why it matters, today's workaround, one number with source | EV fleets, recyclers and ESS buyers; slow manual testing or a blunt SOH threshold. The headline statistic still needs a sourced number. |
| 3. Our solution | What you built, three key features, prototype screenshot | Five-stage assessment, explainable verdict, fleet planning. Screenshots can be generated with `apps/revive-front/tools/shoot.mjs`. |
| 4. How it works | Three steps | Upload or stream data, engine assesses, user gets a decision with reasons |
| 5. What makes us different | Existing solutions vs ours | Threshold-only triage vs safety gate, calibrated intervals, honest refusals, what-if economics |
| 6. Market and impact | Target users, market size, impact | Segments from the canvas; market size and impact figures still need sourcing |
| 7. Our team | Four members with role and key skill | To be filled in |
| 8. Thank you | Team ID, team name, contact | Team BX-125 |

## Repository layout

```
REVIVE-TERY-Platform/
├─ README.md  MASTER_PROMPT.md  UPGRADE_LOG.md  registry.json  justfile
├─ docs/            PROJECT_INVENTORY  FOLDER_WORKFLOWS  ARCHITECTURE  CHANGE_GUIDE  DEMO_SCRIPT  HARDWARE_DEMO  legacy/
├─ contracts/       JSON schemas between parts + CHANGELOG.md
├─ config/          platform.json, decision_map.json (engine tunables stay in engines/ml/configs)
├─ engines/
│   ├─ firmware/    ESP32 sketch
│   ├─ bms/         BMS engine, ESP32 simulator, run controller
│   ├─ lite/        lite analyzer + upload bridge
│   ├─ ml/          full ML engine (revive-tery-ml, own layout)
│   └─ database/    DuckDB build scripts, demo CSV bundle, sample uploads
├─ services/api/    FastAPI backend
├─ apps/
│   ├─ revive-front/     the luxury, animated front end (static ES modules, no build step)
│   ├─ web-studio/       static browser app (JS ports of every engine)
│   ├─ circuit-studio/   Dash dashboard
│   └─ relife-studio/    PySide6 prototype
├─ data/            db/ (DuckDB), samples/
├─ scripts/         migrate_from_legacy.py  impact.py  check_contracts.py  fleet_parity.py  fw_build.py ...
└─ tests/           contract guard tests
```

Every module has a `MODULE.md` (purpose, public interface, rules, origin, how to run and test).

## Architecture

```
 firmware ─▶ bms ─▶ database ─▶ api ─▶ web apps (read-only GETs)
 uploads ──▶ lite ─▶ database ─▶ api
                  └─▶ ml (full engine) ─▶ api, web-studio (ports)
```

Dependencies point one way: `contracts` → engines → services → apps. Why edits stay local:

- **Contracts** are the only agreed shapes between parts (bundle metadata, telemetry columns, ESP32 line, report).
- **Config in files:** ML tunables in `engines/ml/configs/*.yaml`, platform settings in `config/`.
- **Registry** (`registry.json`) lists components, consumers and what to run after a change; `scripts/impact.py` turns a diff into a checklist.
- **Parity tests:** browser engines are ports of the Python ones and are compared to golden outputs generated from Python.
- **Independence rule:** `engines/ml` imports nothing else from the platform.

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/CHANGE_GUIDE.md](docs/CHANGE_GUIDE.md).

## Quick start

Requirements: Python 3.13 (the ML engine is built on it), Node.js for the web app tests, and [`just`](https://github.com/casey/just) (`pip install rust-just`).

```bash
git clone https://github.com/Nishanth031/Revive-tery-demo-front
cd Revive-tery-demo-front
pip install rust-just
just check          # contracts + monitor-only firmware guard + circuit rules
```

Run the demo front end with no backend (SNAPSHOT mode, fully offline):

```bash
cd apps/revive-front
npm run sync        # copy the studio's snapshot data into data/
npm run serve       # http://localhost:8090
```

Run with the live backend (LIVE mode):

```bash
just api            # FastAPI on http://127.0.0.1:8000  (docs at /docs)
# then, in another shell
cd apps/revive-front && npm run serve
```

Other entry points: `just web` (web-studio, port 8080) · `just studio` (Circuit Studio) · `just relife` (ReLife Studio).

## The front end (`apps/revive-front`)

A luxury, heavily animated, multi-layer front end. Static ES modules, vendored libraries, no build step, runs offline. A status chip shows **LIVE** or **SNAPSHOT** depending on whether the API answers.

| Route | What |
|---|---|
| `#/` | Scroll film in 8 beats: hero, the question, five stages, the verdict, trust, what-if, honesty, closing |
| `#/fleet` | Command Center: filters, sort, 70 pack cards |
| `#/pack/<id>` | Verdict, reasons, confidence, RUL and years ranges, projection, economics, what-if, next actions, evidence, passport |
| `#/plan` | Fleet assignment under per-application pack limits (live) |
| `#/analyze` | Upload with dry-run column mapping, then an explicit "Store and assess" (live) |
| `#/bench` | Simulated ESP32 bench over server-sent events (live) |
| `#/evidence` | Model cards and judge Q&A |

Shortcuts: `?demo=1` or `D` starts a 60-second scripted tour (`Esc` stops it) · `?` lists shortcuts · `1`–`6` jump between routes.

Tools in `apps/revive-front/tools`: `sync_snapshot.mjs` (copy snapshot data), `mock_sse.mjs` (mock bench endpoints, no database), `shoot.mjs` (screenshots of every route at 1440/1024/390 px with a console, overflow and NaN report). The app is deployable as static files (`vercel.json` included). See its [README](apps/revive-front/README.md) and [HANDOFF.md](apps/revive-front/HANDOFF.md).

## Backend API

FastAPI service bound to `127.0.0.1` with no login. Hardware access is monitor-only: the API reads from the ESP32 and cannot write to it.

| Method and path | Does |
|---|---|
| `GET /api/health` | Status, database path and tables, ML engine version |
| `GET /api/fleet`, `GET /api/battery/{id}` | Fleet reports and per-pack detail |
| `POST /api/whatif` | Re-run the economics with changed inputs |
| `GET /api/meta`, `GET /api/history/*` | Database metadata and history |
| `POST /api/uploads` | Store `.csv`/`.xlsx`/`.zip` with a data-provenance tag |
| `POST /api/assessments` | Assess a battery (`engine` = `auto`, `full` or `lite`) |
| `POST /api/runs`, `GET /api/runs/stream` | Start and stream a virtual, simulated or hardware run (SSE) |

The list above is a summary; interactive documentation is at `http://127.0.0.1:8000/docs` and the full table is in [services/api/README.md](services/api/README.md). Every assessment returns a normalised `summary` plus the complete `report` with a provenance tag on every number.

## Hardware bench

A low-voltage, monitor-only bench: ESP32 with an INA219 current sensor and DS18B20 temperature sensors, fuse on the positive lead and a manual switch on the load. The ESP32 only reports; nothing on the battery path is driven by software. Each serial line carries a sequence number and CRC so dropped and corrupt lines are counted. If no hardware is present, the same JSON lines come from a labelled SIMULATED source. See [docs/HARDWARE_DEMO.md](docs/HARDWARE_DEMO.md).

## Testing and guard rails

| Command | Covers |
|---|---|
| `just check` | Contract examples, monitor-only firmware guard, circuit rules |
| `just test-ml` | ML engine (physics, gate, state, economics, data quality, intelligence) |
| `just test-db` | Fleet database |
| `just test-bms` | Firmware line format |
| `just test-api` | Backend API (runs on a scratch copy of the database) |
| `just test-web` | Browser-engine parity against Python golden outputs |
| `just test-relife` | ReLife Studio |
| `just test-all` | All of the above |

## Working day to day

| I want to... | Do this |
|---|---|
| Know what my edit affects | `just impact` (uses git) or `just impact <files>` |
| Tune the ML engine | edit `engines/ml/configs/*.yaml`, then `just test-ml`, `just web-regen` |
| Change an interface | edit `contracts/`, bump `contracts/CHANGELOG.md`, update every consumer in `registry.json` |
| Rebuild the database and snapshot | `just web-db` |
| Regenerate browser engines after a Python change | `just web-regen` |
| Add an engine or app | add a folder, one entry in `registry.json`, and a `MODULE.md` |

## Demo

A 5-minute guided script (Command Center, a Repurpose pack, the tariff what-if that flips a decision, a safety-rejected pack, a data-quality refusal, fleet plan, hardware, model evidence) is in [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md), with a 60-second version and a fallback plan. Every screen runs offline from the snapshot if the API or network fails.

## Limitations

- All 70 packs and their dense telemetry are **synthetic**. Results show the pipeline works, not anything about real batteries.
- Costs and the tariff are **placeholder** inputs. The decision flips near 0.06–0.08 USD/kWh.
- The state model is **LFP-trained**. It does not transfer to NMC/NCA chemistries, and the app says so.
- Hardware is monitor-only and low-voltage. The firmware was compiled for both range profiles but not flashed in this repository's test environment.
- Business-model figures (costs, revenue, the 30% longevity target) are planning inputs from the canvas, not measured results.

## Documentation index

[PROJECT_INVENTORY](docs/PROJECT_INVENTORY.md) · [FOLDER_WORKFLOWS](docs/FOLDER_WORKFLOWS.md) · [ARCHITECTURE](docs/ARCHITECTURE.md) · [CHANGE_GUIDE](docs/CHANGE_GUIDE.md) · [DEMO_SCRIPT](docs/DEMO_SCRIPT.md) · [HARDWARE_DEMO](docs/HARDWARE_DEMO.md) · [MIGRATION_REPORT](docs/MIGRATION_REPORT.md) · [MASTER_PROMPT](MASTER_PROMPT.md) · [UPGRADE_LOG](UPGRADE_LOG.md) · [contracts/CHANGELOG](contracts/CHANGELOG.md)
