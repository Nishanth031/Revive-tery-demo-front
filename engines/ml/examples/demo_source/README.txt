EV BATTERY DIGITAL PASSPORT — DEMO CSV BUNDLE

IMPORTANT DATA INTEGRITY NOTE
This bundle is a hackathon showcase dataset, not a real manufacturer's battery passport.
All pack-level specifications, module mapping, telemetry, charge sessions, health values,
safety events and estimated material masses are synthetic/illustrative. They are designed
to demonstrate an importable data model and dashboard workflow. Do not use these values
for engineering, safety, warranty, diagnosis or regulatory compliance decisions.

Files
- battery_asset.csv: key/value master record for one illustrative EV traction pack
- modules.csv: four illustrative module records linked by asset_id
- telemetry.csv: time-series SOC, SOH, voltage, current and temperature
- charge_sessions.csv: charging history
- health_history.csv: capacity fade, SOH, resistance and illustrative RUL trend
- safety_events.csv: example warning/monitoring events
- materials_recycling.csv: illustrative material categories and mass estimates
- data_sources.csv: public references and provenance notes

Suggested import order
1. battery_asset.csv
2. modules.csv
3. telemetry.csv
4. charge_sessions.csv
5. health_history.csv
6. safety_events.csv
7. materials_recycling.csv
8. data_sources.csv

Join key: asset_id (modules also have module_id).
The NASA and CALCE references describe experimental cell-level datasets. They do not
provide this complete fictional EV pack passport. To replace synthetic values with
real measurements, download source data and preserve its original identifiers,
units, metadata and license/citation requirements.

Public references:
NASA Ames PCoE: https://data.nasa.gov/dataset/li-ion-battery-aging-datasets
CALCE: https://calce.umd.edu/battery-data
Battery Archive: https://www.batteryarchive.org/
Battery Data Commons: https://batterydatacommons.org/find-data/
