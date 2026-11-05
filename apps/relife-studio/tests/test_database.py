"""Database link and upload checks. Everything runs in temp folders on made-up rows."""
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

import duckdb

import database as db

BUNDLE = {
    "battery_asset": (
        "field,value\nasset_id,PACK-A\nvehicle_id,VEH-1\nchemistry,NMC\nseries_parallel_configuration,96s40p\n"
        "nominal_voltage_V,355.2\nnominal_capacity_Ah,200\nnominal_energy_kWh,71.04\npack_mass_kg,450\n"
        "demo_status,SYNTHETIC DEMO\n"
    ),
    "modules": "module_id,asset_id,cell_count\nM1,PACK-A,960\n",
    "charge_sessions": "session_id,asset_id,start_utc\nS2,PACK-A,2026-01-02T00:00:00Z\nS1,PACK-A,2026-01-01T00:00:00Z\n",
    "telemetry": (
        "timestamp_utc,asset_id,soc_pct,pack_voltage_V,pack_current_A,max_cell_temp_C,operating_state,data_class\n"
        "2026-01-01T02:00:00Z,PACK-A,70,370.5,-40,31.5,DRIVING,SYNTHETIC\n"
        "2026-01-01T01:00:00Z,PACK-A,80,380.5,-40,30.5,DRIVING,SYNTHETIC\n"
    ),
    "health_history": (
        "assessment_date,asset_id,cycle_count,measured_capacity_Ah,soh_pct,internal_resistance_mOhm\n"
        "2026-06-30,PACK-A,960,193.6,96.8,2.2\n2024-06-30,PACK-A,120,198.8,99.4,1.82\n"
    ),
    "safety_events": "event_id,asset_id,timestamp_utc,event_type,severity\nE1,PACK-A,2026-01-01T00:00:00Z,TEMP,LOW\n",
    "materials_recycling": "asset_id,material,estimated_mass_kg\nPACK-A,Nickel,10\n",
    "data_sources": "source_id,publisher\nD1,NASA\n",
}


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="relife_test_")
        # An apostrophe, because the real project path has one.
        self.root = Path(self._temp.name) / "it's here"
        self.csv_dir = self.root / "bundle"
        self.csv_dir.mkdir(parents=True)
        for table, text in BUNDLE.items():
            (self.csv_dir / f"{table}.csv").write_text(text, encoding="utf-8")
        self.db_path = self.root / "data" / "database" / db.DB_FILE_NAME

    def tearDown(self):
        self._temp.cleanup()

    def _import_folder(self, folder=None):
        preview = db.preview_upload([folder or self.csv_dir], self.db_path)
        self.addCleanup(preview.close)
        self.assertTrue(preview.can_import, [f.problem for f in preview.files])
        return db.import_bundle(preview, self.db_path)

    def _zip_bundle(self, name="bundle.zip", members=None):
        archive = self.root / name
        with zipfile.ZipFile(archive, "w") as bundle:
            for table, text in (members or BUNDLE).items():
                bundle.writestr(f"{table}.csv", text)
            bundle.writestr("README.txt", "not data")
        return archive

    def test_upload_from_folder_creates_all_tables_and_indexes(self):
        self._import_folder()
        status = db.check_database(self.db_path)
        self.assertTrue(status.connected)
        self.assertEqual(set(status.tables), set(db.BUNDLE_SCHEMA))
        self.assertEqual(status.pack_ids, ["PACK-A"])
        with duckdb.connect(str(self.db_path), read_only=True) as con:
            indexes = {r[0] for r in con.execute("SELECT index_name FROM duckdb_indexes()").fetchall()}
        self.assertIn("idx_telemetry_asset_id_timestamp_utc", indexes)
        self.assertIn("idx_safety_events_asset_id", indexes)

    def test_upload_from_zip_ignores_other_files(self):
        preview = db.preview_upload([self._zip_bundle()], self.db_path)
        self.addCleanup(preview.close)
        self.assertEqual(len(preview.files), 8)
        self.assertEqual(preview.ignored, ["README.txt"])
        db.import_bundle(preview, self.db_path)
        self.assertEqual(db.check_database(self.db_path).tables["telemetry"], 2)

    def test_zip_with_path_traversal_writes_only_inside_its_temp_folder(self):
        archive = self.root / "evil.zip"
        outside = self.root / "telemetry.csv"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("../../telemetry.csv", BUNDLE["telemetry"])
        preview = db.preview_upload([archive], self.db_path)
        self.addCleanup(preview.close)
        self.assertEqual([f.table for f in preview.files], ["telemetry"])
        self.assertFalse(outside.exists())

    def test_rows_are_sorted_with_real_datetimes(self):
        self._import_folder()
        pack = db.load_pack(self.db_path, "PACK-A")
        self.assertIsInstance(pack.telemetry[0]["timestamp_utc"], datetime)
        self.assertEqual([r["soc_pct"] for r in pack.telemetry], [80, 70])
        self.assertEqual([r["session_id"] for r in pack.charges], ["S1", "S2"])
        self.assertEqual(pack.health[-1]["soh_pct"], 96.8)
        self.assertEqual(pack.asset["chemistry"], "NMC")
        self.assertTrue(pack.is_synthetic)

    def test_profile_uses_only_stated_values(self):
        self._import_folder()
        profile = db.profile_from_pack(db.load_pack(self.db_path, "PACK-A"))
        self.assertEqual((profile.series_cells, profile.parallel_cells), (96, 40))
        self.assertEqual(profile.nominal_voltage_v, 355.2)
        self.assertEqual(profile.measured_voltage_v, 370.5)  # The latest reading, not the first row.
        self.assertEqual(profile.soh_pct, 96.8)
        self.assertEqual(profile.rated_energy_wh, 71040)
        self.assertIsNone(profile.discharge_limit_a)
        self.assertEqual(profile.manufacturer, "Unknown")
        self.assertEqual(profile.source_kind, "database")

    def test_missing_column_blocks_the_import_and_says_which(self):
        (self.csv_dir / "telemetry.csv").write_text("timestamp,battery_id\n2026-01-01,X\n", encoding="utf-8")
        preview = db.preview_upload([self.csv_dir], self.db_path)
        self.addCleanup(preview.close)
        self.assertFalse(preview.can_import)
        problem = next(f.problem for f in preview.files if f.table == "telemetry")
        self.assertIn("timestamp_utc", problem)
        with self.assertRaises(db.DatabaseError):
            db.import_bundle(preview, self.db_path)
        self.assertFalse(self.db_path.exists())

    def test_failed_import_keeps_old_tables_and_indexes(self):
        self._import_folder()
        changed = dict(BUNDLE, telemetry=BUNDLE["telemetry"] + "2026-01-01T03:00:00Z,PACK-A,60,360,-40,32,DRIVING,X\n")
        folder = self.root / "changed"
        folder.mkdir()
        for table, text in changed.items():
            (folder / f"{table}.csv").write_text(text, encoding="utf-8")
        preview = db.preview_upload([folder], self.db_path)
        self.addCleanup(preview.close)
        self.assertTrue(preview.can_import)
        # The last table to load disappears after the preview, so the load fails partway,
        # after telemetry has already been replaced inside the transaction.
        (folder / "data_sources.csv").unlink()
        with self.assertRaises(db.DatabaseError):
            db.import_bundle(preview, self.db_path)
        status = db.check_database(self.db_path)
        self.assertEqual(status.tables["telemetry"], 2)
        self.assertEqual(len(status.tables), 8)
        with duckdb.connect(str(self.db_path), read_only=True) as con:
            indexes = con.execute("SELECT COUNT(*) FROM duckdb_indexes()").fetchone()[0]
        self.assertEqual(indexes, 7)

    def test_upload_makes_a_backup_and_prunes_old_ones(self):
        self.assertIsNone(self._import_folder()["backup"])  # Nothing to back up the first time.
        second = self._import_folder()
        self.assertTrue(second["backup"].is_file())
        for n in range(5):
            older = self.db_path.with_name(f"{self.db_path.stem}.backup-2000010{n}-000000{self.db_path.suffix}")
            older.write_bytes(b"x")
        self._import_folder()
        self.assertEqual(len(list(self.db_path.parent.glob("*.backup-*"))), db.MAX_BACKUPS)

    def test_rows_for_another_pack_produce_a_warning(self):
        (self.csv_dir / "modules.csv").write_text("module_id,asset_id\nM1,OTHER-PACK\n", encoding="utf-8")
        preview = db.preview_upload([self.csv_dir], self.db_path)
        self.addCleanup(preview.close)
        self.assertTrue(any("OTHER-PACK" in warning for warning in preview.warnings))

    def test_single_table_upload_replaces_only_that_table(self):
        self._import_folder()
        update = self.root / "telemetry.csv"
        update.write_text(BUNDLE["telemetry"] + "2026-01-01T03:00:00Z,PACK-A,60,360,-40,32,DRIVING,X\n", encoding="utf-8")
        preview = db.preview_upload([update], self.db_path)
        self.addCleanup(preview.close)
        db.import_bundle(preview, self.db_path)
        status = db.check_database(self.db_path)
        self.assertEqual(status.tables["telemetry"], 3)
        self.assertEqual(status.tables["modules"], 1)

    def test_empty_database_file_is_reported_not_crashed_on(self):
        empty = self.root / "empty.duckdb"
        empty.write_bytes(b"")
        status = db.check_database(empty)
        self.assertFalse(status.connected)
        self.assertIn("empty", status.message)
        self.assertFalse(db.check_database(self.root / "missing.duckdb").connected)
        preview = db.preview_upload([self.csv_dir], empty)
        self.addCleanup(preview.close)
        with self.assertRaises(db.DatabaseError):
            db.import_bundle(preview, empty)

    def test_discovery_skips_empty_files_and_finds_bundles(self):
        app_dir = self.root / "Hackathon project ev (3)" / "Hackathon project ev"
        app_dir.mkdir(parents=True)
        (self.root / db.DB_FILE_NAME).write_bytes(b"")
        self.assertIsNone(db.discover_database(app_dir))
        built = self.root / "bulid X" / "data" / "database" / db.DB_FILE_NAME
        built.parent.mkdir(parents=True)
        built.write_bytes(b"not empty")
        self.assertEqual(db.discover_database(app_dir), built.resolve())
        archive = self._zip_bundle("ev_bundle.zip")
        self.assertIn(archive.resolve(), db.discover_bundles(app_dir))

    def test_data_checks_flag_inconsistent_telemetry(self):
        pack = db.PackData(
            asset_id="A",
            asset={"nominal_capacity_Ah": "200"},
            telemetry=[
                {"timestamp_utc": datetime(2026, 1, 1, 8), "soc_pct": 80, "pack_current_a": -10, "pack_voltage_v": 380, "operating_state": "DRIVING"},
                {"timestamp_utc": datetime(2026, 1, 1, 9), "soc_pct": 50, "pack_current_a": -10, "pack_voltage_v": 370, "operating_state": "REGENERATIVE_BRAKING"},
            ],
        )
        notes = " ".join(db.data_checks(pack))
        self.assertIn("regenerative", notes)
        self.assertIn("SOC changed by -30", notes)
        consistent = db.PackData(
            asset_id="A",
            asset={"nominal_capacity_Ah": "100"},
            telemetry=[
                {"timestamp_utc": datetime(2026, 1, 1, 8), "soc_pct": 80, "pack_current_a": -10, "pack_voltage_v": 380, "operating_state": "DRIVING"},
                {"timestamp_utc": datetime(2026, 1, 1, 9), "soc_pct": 70, "pack_current_a": -10, "pack_voltage_v": 370, "operating_state": "DRIVING"},
            ],
        )
        self.assertEqual(db.data_checks(consistent), [])


if __name__ == "__main__":
    unittest.main()
