# ReLife BMS Studio

A simulation-first desktop prototype for reading battery data, screening it for second-life use, and exploring a BMS design.

> **Simulation only.** No physical battery connection, measurement hardware, or real protection is implemented. Public research records describe laboratory measurements; they are not offers of batteries for sale or proof that a battery is suitable for reuse. Unknown specifications remain unknown. A qualified engineer must design and validate any real hardware.

## Run it

Python 3.11 or newer on Windows:

```powershell
python -m pip install -r requirements.txt
python main.py
```

Run the checks:

```powershell
$env:PYTHONPATH = "tests"; python -m unittest discover -s tests
```

## Pages

- **Overview:** database status, the linked pack and the workflow.
- **Pack data:** telemetry, health history, safety events and data checks from the linked database, plus the data upload.
- **Batteries:** search your database packs, your own entries and public research records. Add a battery or import a profile list.
- **Circuit Studio:** a draggable conceptual schematic. Select a part to see its connections.
- **Test bench:** a 30 second synthetic pulse with its screening result. **Skip to result** avoids waiting out the live replay.

## Files

- `main.py`: application launcher
- `app_ui.py`: main window and Overview page
- `pack_page.py`, `catalog_page.py`, `circuit_page.py`, `bench_page.py`: the other pages
- `app_state.py`: data shared between pages
- `widgets.py`: cards, badges, tables, charts and background tasks
- `theme.py`: every colour, and the style sheet
- `database.py`: DuckDB link and CSV bundle upload (no interface code)
- `models.py`: shared battery, adapter and measurement types
- `battery_details.py`: local JSON catalog, sourced research records, profile CSV import
- `bms_engine.py`: adapter checks, virtual fault logic and the pulse model
- `circuit_studio.py`: editable component and net model
- `battery_catalog.json`: created when you first save a battery
- `tests/`: engine, database and interface checks

## The database link

On startup the app looks for a built `revive_tery.duckdb` in this folder and up to three levels above it, including `bulid X/data/database/`. Empty files are skipped, because DuckDB can't open them. **Change database** links any other file, and the app remembers your choice.

Reads are read-only and brief, so other tools can use the file too. Stop anything that has the database open for writing before you import.

## Uploading data

**Pack data → Import data** accepts a zip, a folder or individual CSV files. Each file is checked and previewed before anything changes.

| File | Required columns |
| --- | --- |
| `battery_asset.csv` | `field`, `value` (with an `asset_id` row) |
| `modules.csv` | `module_id`, `asset_id` |
| `charge_sessions.csv` | `session_id`, `asset_id`, `start_utc` |
| `telemetry.csv` | `timestamp_utc`, `asset_id`, `soc_pct`, `pack_voltage_V`, `pack_current_A` |
| `health_history.csv` | `assessment_date`, `asset_id`, `soh_pct` |
| `safety_events.csv` | `event_id`, `asset_id`, `timestamp_utc`, `event_type`, `severity` |
| `materials_recycling.csv` | `asset_id`, `material` |
| `data_sources.csv` | `source_id` |

An import **replaces** the tables you upload, using the same tables and indexes as `src/build_relational_db.py`. It doesn't merge, because `battery_asset` describes a single pack. It runs in one transaction, so if a file fails, the old data stays. The newest 3 automatic backups are kept beside the database as `revive_tery.backup-*.duckdb`.

**Batteries → Import profiles CSV** is separate. It adds catalog entries from a list with `BatteryProfile` field names: `id`, `name`, `category`, `chemistry`, `manufacturer`, `model`, `series_cells`, `parallel_cells`, `nominal_voltage_v`, `capacity_value`, `capacity_unit`, `rated_energy_wh`, `charge_limit_a`, `discharge_limit_a`, `mass_kg`, `manufacture_date`, `condition`, `cycle_count`, `measured_capacity_ah`, `measured_voltage_v`, `measured_current_a`, `measured_temperature_c`, `initial_soc_pct`, `soh_pct`, `internal_resistance_mohm`, `source_kind`, `source_title`, `source_url`, `license`, `measurement_method` and `notes`.

## Research data included

The starter catalog includes 23 identity/provenance records for the [Second-life LFP battery dataset](https://zenodo.org/records/18630889), a repurposed-EV long-term dataset, four NASA PCoE aging profiles, and a NASA randomized/recommissioned second-life pack dataset. NASA describes voltage, current, temperature, time and capacity measurements in its [aging dataset](https://data.nasa.gov/dataset/li-ion-battery-aging-datasets), and variable-load aging with cells assembled into second-life packs in its [recommissioned dataset](https://data.nasa.gov/dataset/randomized-and-recommissioned-battery-dataset). Individual measurements remain unknown until their source data is imported. These are research records, not inventory listings.

## Virtual stress-test calculations

The test bench lets you choose **Charge** or **Discharge**, a requested test voltage, and peak current demand. Leave demand on **Auto** to let the scenario set it: High load asks for 1.5 times the base current, and Overcurrent for 1.25 times the discharge limit. It then runs a 30-second synthetic pulse (low baseline, full demand, reduced demand, full demand) and displays requested voltage/current beside modeled battery terminal voltage and delivered current. The model is direct-source only; it does not simulate a DC/DC converter. Requested and delivered current may differ because the virtual adapter profile limits current based on profile capacity, voltage, temperature, and synthetic health condition.

SOC begins with the entered initial SOC. If that is missing, the app makes a clearly labeled voltage-based starting estimate. It then uses coulomb counting: `ΔSOC (%) = signed current (A) × elapsed time (h) / capacity (Ah) × 100`. Discharge lowers SOC and charge raises it. Capacity in Wh/kWh is converted to Ah using nominal voltage when available.

SOH is estimated from pulse telemetry rather than copied from the profile field. After a measurable current step, the engine estimates resistance with `R ≈ |ΔV| / |ΔI|`, then reports an impedance proxy `SOH (%) ≈ reference resistance / estimated resistance × 100`, bounded to 0–100%. A profile-provided SOH or measured capacity may set the *synthetic plant's aging characteristics*, but the displayed stress-test estimate is calculated from its generated voltage/current response. Profiles without a resistance measurement receive different deterministic virtual resistances based on their profile data instead of one shared 25 mΩ value. A zero-current or unmeasurable pulse leaves SOH unavailable.

The reference resistance is a rough scale from pack voltage and capacity. If a pack's real resistance falls outside its limits (10% to 500% of reference), the proxy pegs at its limit and says nothing about that battery, so the result reads **Inconclusive** rather than as a pass. Packs with low measured resistance, such as large EV packs, can hit this.

Voltage changes under load because the model applies internal impedance (`ΔV ≈ I × R`) with a small SOC/temperature effect. Current is the requested virtual load/charger demand; it is not a fixed current that a battery produces by itself. Temperature follows a simplified synthetic `I²R` model. The output is an educational screening estimate, not a validated battery diagnostic, safety certification, or explosion prediction. Real SOH requires validated, chemistry-aware capacity/resistance testing and appropriately measured sensor data. Adapter compatibility is a virtual capability check only.
