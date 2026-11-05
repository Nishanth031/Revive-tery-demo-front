# Contract changelog

Bump the version here whenever a file in this folder changes, and list every consumer you updated.

| Version | Date | Change | Consumers updated |
|---|---|---|---|
| v1 | 2026-11-05 | Initial extraction from revive_ml.contract, bms_engine.parse_telemetry_line, pipeline.assess | (baseline) |
| v1.1 | 2026-11-05 | assessment_report: optional `insight` key (explain, confidence, ranges, robustness, next actions, rule gap). New `battery_passport.schema.json` (informational, not regulatory). Economics (inside the report, no schema change): `low_speed_ev` valued in `avoided_new_pack` mode (new pack it replaces, BNEF $108/kWh, 8-year assumed pack life, no buy-new storage cap); each option carries `valuation_mode`; `economics.region` (default `global_default`, same tariff as before). | engines/ml (insight, router, api), apps/web-studio (insight.js, econ.js, pipeline.js, pages), services/api, engines/database/fleet_reports.py |
| esp32_line v1.1 | 2026-11-05 | Optional `ambient`, `seq`, `t_ms`, `crc` (last key); info lines `# fw=`, `# hb`, `# boot`, `# ds18b20`; repeated warnings throttled with `(x<n>)`. Backward compatible: v1.0 lines parse as before. | engines/firmware (sketch v1.1.0), engines/bms (bms_engine parser + SerialStats crc_errors/dropped_lines + test_run_log columns, esp32_sim), engines/lite (ambient pass-through), apps/web-studio (bms.js, esp32sim.js, hardware.js) |
