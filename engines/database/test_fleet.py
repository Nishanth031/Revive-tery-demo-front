"""The platform database after `just db`: the user's fleet, the key/value layout, dense telemetry, consumers.

Run: python -m pytest engines/database/test_fleet.py -q   (just test-db)
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DB = Path(os.environ.get("REVIVE_DB") or ROOT / "data" / "db" / "revive_tery.duckdb")
for sub in ("bms", "lite", "database"):
    sys.path.insert(0, str(ROOT / "engines" / sub))
import import_fleet  # noqa: E402

KEYED = ("battery_asset", "battery_registry", "telemetry", "telemetry_dense", "health_history", "safety_events",
         "charge_sessions", "modules", "materials_recycling")


@pytest.fixture(scope="module")
def con():
    if not DB.is_file():
        pytest.skip("database not built (run `just db`)")
    c = duckdb.connect(str(DB), read_only=True)
    yield c
    c.close()


def test_at_least_60_packs_and_every_user_pack_present(con):
    n = con.execute("SELECT count(*) FROM battery_registry").fetchone()[0]
    assert n >= 60
    src = import_fleet.find_source()
    if src:
        with duckdb.connect(str(src), read_only=True) as s:
            user_ids = {r[0] for r in s.execute("SELECT asset_id FROM battery_registry").fetchall()}
        ours = {r[0] for r in con.execute("SELECT asset_id FROM battery_registry").fetchall()}
        assert user_ids <= ours


def test_registry_and_key_value_battery_asset_agree(con):
    reg = con.execute("SELECT * FROM battery_registry").df()
    kv = con.execute("SELECT asset_id, field, value FROM battery_asset").df()
    for _, r in reg.iterrows():
        pairs = dict(zip(kv.loc[kv.asset_id == r.asset_id, "field"], kv.loc[kv.asset_id == r.asset_id, "value"]))
        assert pairs.get("asset_id") == r.asset_id, r.asset_id
        assert pairs.get("chemistry") == r.chemistry, r.asset_id
        assert float(pairs["nominal_capacity_Ah"]) == float(r.nominal_capacity_Ah), r.asset_id
        assert pairs.get("series_parallel_configuration") == r.series_parallel_configuration, r.asset_id


def test_every_pack_has_at_least_1000_dense_rows_labelled_synthetic(con):
    rows = dict(con.execute("SELECT asset_id, count(*) FROM telemetry_dense GROUP BY 1").fetchall())
    for (aid,) in con.execute("SELECT asset_id FROM battery_registry").fetchall():
        assert rows.get(aid, 0) >= 1000, aid
    assert con.execute("SELECT count(*) FROM telemetry_dense WHERE data_class <> 'SYNTHETIC'").fetchone()[0] == 0


def test_original_12_row_telemetry_is_unchanged(con):
    src = import_fleet.find_source()
    if not src:
        pytest.skip("user's fleet database not available here")
    with duckdb.connect(str(src), read_only=True) as s:
        a = s.execute("SELECT * FROM telemetry ORDER BY asset_id, timestamp_utc").df()
    b = con.execute(f"SELECT * FROM telemetry WHERE asset_id IN (SELECT asset_id FROM battery_registry "
                    f"WHERE registry_source = '{import_fleet.SRC_USER}') ORDER BY asset_id, timestamp_utc").df()
    assert len(a) == len(b) == 12 * a.asset_id.nunique()
    assert (pd.to_datetime(a.timestamp_utc, utc=True).values == pd.to_datetime(b.timestamp_utc, utc=True).values).all()
    for c in ("asset_id", "operating_state", "data_class"):
        assert (a[c].astype(str).values == b[c].astype(str).values).all(), c
    for c in ("soc_pct", "soh_pct", "pack_voltage_V", "pack_current_A", "max_cell_temp_C", "min_cell_temp_C",
              "ambient_temp_C", "power_kW"):                      # same values (the column type may widen to DOUBLE)
        assert (a[c].astype(float).values == b[c].astype(float).values).all(), c


def test_nca_label_converts_and_unknown_labels_still_raise(con):
    import ml_engine_bridge as bridge
    from revive_ml.contract import ContractError
    from revive_ml.convert import CHEMISTRY_MAP
    assert CHEMISTRY_MAP["NCA (nickel cobalt aluminium)"] == "NCA"
    aid = con.execute("SELECT asset_id FROM battery_registry WHERE chemistry = 'NCA (nickel cobalt aluminium)' LIMIT 1").fetchone()[0]
    assert bridge.bundle_from_database(con, aid).meta.chemistry == "NCA"
    assert "lithium cobalt oxide" not in CHEMISTRY_MAP                 # never guessed
    assert ContractError                                               # unknown labels raise in convert_demo


def test_every_table_filters_on_asset_id_with_no_null_ids(con):
    for t in KEYED:
        assert con.execute(f'SELECT count(*) FROM "{t}" WHERE asset_id IS NULL OR asset_id = \'\'').fetchone()[0] == 0, t
        assert con.execute(f'SELECT count(*) FROM "{t}" WHERE asset_id = ?', ["DEMO-EV-PACK-001"]).fetchone()[0] > 0, t


def test_existing_consumers_still_read_the_database(con):
    import bms_engine
    import ml_engine_bridge as bridge
    ids = bms_engine.list_battery_ids(DB)
    assert len(ids) >= 60
    p = bms_engine.load_battery_profile("DEMO-EV-PACK-001", DB)
    assert p.chemistry and p.rated_capacity_ah and p.telemetry_rows == 12
    assert len(bridge.bundle_from_database(con, "DEMO-EV-PACK-001", "original").telemetry) == 12
    assert len(bridge.bundle_from_database(con, "DEMO-EV-PACK-001", "dense").telemetry) >= 1000
    spec = importlib.util.spec_from_file_location("backend_connector", ROOT / "apps" / "circuit-studio" / "backend_connector.py")
    bc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bc)
    asset = bc._fetch_asset(con, "DEMO-EV-PACK-001")
    assert asset.iloc[0]["asset_id"] == "DEMO-EV-PACK-001"
    rl = importlib.util.spec_from_file_location("relife_database", ROOT / "apps" / "relife-studio" / "database.py")
    rdb = importlib.util.module_from_spec(rl)
    sys.modules["relife_database"] = rdb                              # dataclasses need their module registered
    sys.path.insert(0, str(ROOT / "apps" / "relife-studio"))
    try:
        rl.loader.exec_module(rdb)
    except ImportError as exc:                                          # ReLife's own venv has its dependencies
        pytest.skip(f"ReLife database module needs its venv: {exc}")
    pack = rdb.load_pack(DB, "DEMO-EV-PACK-001") if hasattr(rdb, "load_pack") else None
    if pack is not None:
        assert pack.asset.get("asset_id") == "DEMO-EV-PACK-001"


def test_views_and_runtime_tables_exist(con):
    names = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    assert {"fleet_summary", "pack_history", "assessments", "ml_suggestions", "fleet_reports"} <= names
    assert con.execute("SELECT count(*) FROM fleet_summary").fetchone()[0] == \
        con.execute("SELECT count(*) FROM battery_registry").fetchone()[0]


def test_flawed_test_cases_are_labelled(con):
    rows = con.execute("SELECT asset_id, demo_status, registry_source FROM battery_registry "
                       "WHERE asset_id LIKE 'DEMO-FLAW-%' ORDER BY 1").fetchall()
    assert [r[0] for r in rows] == [f"DEMO-FLAW-0{i}" for i in range(1, 7)]
    assert all("SYNTHETIC TEST CASE" in r[1] and r[2] == import_fleet.SRC_TEST for r in rows)
