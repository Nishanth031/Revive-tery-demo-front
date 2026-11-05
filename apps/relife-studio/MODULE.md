# apps/relife-studio: ReLife BMS Studio (PySide6, simulation only)

**Purpose:** screening / BMS-design prototype: battery profiles, virtual adapters, scenario evaluation, 30 s virtual pulse test, circuit sketch, catalog of research records, database import.
**Entry:** `main.py`. **Engine files (ported to JS):** `bms_engine.py`, `models.py`, `battery_details.py`, `circuit_studio.py`. Everything else is UI.
**Rule:** simulation only; results are labelled synthetic; "Inconclusive" when resistance pegs outside 10-500 % of reference.
**Self-contained:** keeps its own flat imports and its own `bms_engine.py` (different from `engines/bms/bms_engine.py`; do not merge).
**Origin:** `Hackathon project ev (3)/Hackathon project ev/` (git history stays in the original).
**Run:** `just relife` (needs PySide6). **Test:** `just test-relife`.
