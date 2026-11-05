"""Drive the real window offscreen. Uses a temp database and catalog, never the real ones."""
import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import database as db  # noqa: E402
from app_state import AppState  # noqa: E402
from app_ui import MainWindow  # noqa: E402
from battery_details import BatteryCatalog  # noqa: E402
from models import BatteryProfile  # noqa: E402
from pack_page import ImportDialog  # noqa: E402
from test_database import BUNDLE  # noqa: E402
from widgets import LineChart, Series, nice_ticks  # noqa: E402

app = QApplication.instance() or QApplication([])


def pump_until(condition, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


class UiTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="relife_ui_")
        root = Path(self._temp.name)
        self.csv_dir = root / "bundle"
        self.csv_dir.mkdir()
        for table, text in BUNDLE.items():
            (self.csv_dir / f"{table}.csv").write_text(text, encoding="utf-8")
        self.db_path = root / db.DB_FILE_NAME
        preview = db.preview_upload([self.csv_dir], self.db_path)
        db.import_bundle(preview, self.db_path)
        preview.close()
        self.catalog = BatteryCatalog(root / "catalog.json")
        self.state = AppState(catalog=self.catalog, db_path=self.db_path, remember=False)
        self.window = MainWindow(self.state)
        self.window.show()
        self.assertTrue(pump_until(lambda: not self.state.loading))

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        app.processEvents()
        self._temp.cleanup()

    def test_every_page_opens(self):
        for key in self.window.factories:
            self.window.go_to(key)
            app.processEvents()
            self.assertIs(self.window.stack.currentWidget(), self.window.pages[key])

    def test_pages_are_built_on_first_visit_only(self):
        self.assertEqual(set(self.window.pages), {"overview"})
        self.window.go_to("bench")
        self.assertEqual(set(self.window.pages), {"overview", "bench"})

    def test_pack_page_shows_database_values_and_labels_them_synthetic(self):
        self.window.go_to("pack")
        page = self.window.pages["pack"]
        app.processEvents()
        self.assertEqual(page.current_id, "PACK-A")
        self.assertEqual(page.kpi_soc.value.text(), "70 %")
        self.assertEqual(page.kpi_soh.value.text(), "96.8 %")
        self.assertEqual(page.kpi_voltage.value.text(), "370.5 V")
        self.assertTrue(page.synthetic_banner.isVisible())
        self.assertEqual(page.db_badge.tone, "good")
        self.assertEqual(len(page.chart_voltage.series[0].xs), 2)
        self.assertEqual(page.tables["safety"].model.rowCount(), 1)

    def test_missing_database_shows_a_message_and_not_a_crash(self):
        self.state.set_database(Path(self._temp.name) / "missing.duckdb")
        self.assertTrue(pump_until(lambda: not self.state.loading))
        self.window.go_to("pack")
        page = self.window.pages["pack"]
        app.processEvents()
        self.assertEqual(page.db_badge.tone, "critical")
        self.assertFalse(page.detail.isVisible())
        self.assertTrue(page.empty.isVisible())
        self.assertFalse(page.test_button.isEnabled())

    def test_import_dialog_previews_then_replaces_tables(self):
        self.window.go_to("pack")
        changed = Path(self._temp.name) / "changed"
        changed.mkdir()
        updated = dict(BUNDLE, telemetry=BUNDLE["telemetry"] + "2026-01-01T03:00:00Z,PACK-A,60,360.5,-40,32.5,DRIVING,SYNTHETIC\n")
        for table, text in updated.items():
            (changed / f"{table}.csv").write_text(text, encoding="utf-8")
        dialog = ImportDialog(self.state, self.window.pages["pack"], candidates=[changed])
        dialog.setProperty("quiet", True)
        self.assertTrue(pump_until(lambda: dialog.import_button.isEnabled()))
        self.assertEqual(dialog.table_model.rowCount(), 8)
        self.assertEqual(self.state.status.tables["telemetry"], 2)  # Nothing changes until confirmed.
        dialog.start_import()
        self.assertTrue(pump_until(lambda: dialog.result_info is not None and not self.state.loading))
        self.assertEqual(self.state.status.tables["telemetry"], 3)
        self.assertEqual(self.window.pages["pack"].kpi_soc.value.text(), "60 %")

    def test_import_dialog_blocks_bad_files(self):
        bad = Path(self._temp.name) / "bad"
        bad.mkdir()
        (bad / "telemetry.csv").write_text("time,battery\n1,2\n", encoding="utf-8")
        dialog = ImportDialog(self.state, None, candidates=[bad])
        self.assertTrue(pump_until(lambda: dialog.preview is not None))
        self.assertFalse(dialog.import_button.isEnabled())
        self.assertIn("timestamp_utc", dialog.preview.files[0].problem)
        dialog.reject()

    def test_database_pack_appears_in_catalog_and_can_be_tested(self):
        self.window.go_to("catalog")
        catalog_page = self.window.pages["catalog"]
        app.processEvents()
        self.assertEqual(catalog_page.model.rows[0].id, "PACK-A")
        catalog_page.table.selectRow(0)
        catalog_page.test_button.click()
        app.processEvents()
        bench = self.window.pages["bench"]
        self.assertIs(self.window.stack.currentWidget(), bench)
        self.assertEqual(bench.battery.currentData(), "PACK-A")
        self.assertEqual(bench.adapter.currentData(), "V-HV-PACK")
        self.assertEqual(bench.readiness.tone, "good")

    def test_bench_runs_live_and_skip_gives_a_result(self):
        self.window.go_to("bench")
        bench = self.window.pages["bench"]
        bench.select_battery("PACK-A")
        bench.start_test()
        self.assertFalse(bench.run_button.isEnabled())
        self.assertFalse(bench.battery.isEnabled())
        self.assertTrue(pump_until(lambda: len(bench.voltage_series.xs) >= 2, timeout=5))
        bench.finish_now()
        self.assertFalse(bench.timer.isActive())
        self.assertEqual(len(bench.voltage_series.xs), 121)
        self.assertTrue(bench.run_button.isEnabled())
        self.assertNotEqual(bench.verdict.status_text, "Test running")
        self.assertEqual(bench.progress.value(), 100)

    def test_bench_number_fields_show_their_values(self):
        self.window.go_to("bench")
        bench = self.window.pages["bench"]
        bench.select_battery("PACK-A")
        app.processEvents()
        for spin in (bench.target_voltage, bench.demand):
            editor = spin.lineEdit()
            # A style sheet once left the inner editor 1 px wide, so the value was invisible.
            self.assertGreater(editor.width(), editor.fontMetrics().horizontalAdvance(editor.text()))
            image = spin.grab().toImage()
            dark = sum(
                image.pixelColor(x, y).lightness() < 90
                for y in range(4, image.height() - 4) for x in range(4, image.width() - 4)
            )
            self.assertGreater(dark, 10, "No text was drawn in this field")

    def test_scenario_changes_the_load_when_demand_is_auto(self):
        self.window.go_to("bench")
        bench = self.window.pages["bench"]
        bench.select_battery("PACK-A")
        peaks = {}
        for scenario in ("Normal", "High load"):
            bench.scenario.setCurrentText(scenario)
            bench.start_test()
            bench.finish_now()
            peaks[scenario] = bench.result["demand_current_a"]
        self.assertGreater(peaks["High load"], peaks["Normal"])

    def test_dragging_bat1_moves_it_and_its_wires_without_opening_anything(self):
        self.window.go_to("circuit")
        page = self.window.pages["circuit"]
        app.processEvents()
        canvas = page.canvas
        item = canvas.part_items["BAT1"]
        wire = canvas.wires_by_ref["BAT1"][0][0]
        before = wire.path().elementAt(0)
        before_x = before.x
        item.setPos(item.pos() + QPointF(60, 40))
        app.processEvents()
        self.assertEqual(page.design.parts[0].x, 100)
        self.assertNotEqual(wire.path().elementAt(0).x, before_x)
        self.assertIsNone(QApplication.activeModalWidget())

    def test_selecting_bat1_offers_a_test(self):
        self.window.go_to("circuit")
        page = self.window.pages["circuit"]
        app.processEvents()
        page.canvas.part_items["F1"].setSelected(True)
        app.processEvents()
        self.assertFalse(page.test_button.isVisible())
        page.canvas.graphics.clearSelection()
        page.canvas.part_items["BAT1"].setSelected(True)
        app.processEvents()
        self.assertTrue(page.test_button.isVisible())
        self.assertIn("F1", page.part_body.text())

    def test_added_part_stays_inside_the_scene(self):
        self.window.go_to("circuit")
        page = self.window.pages["circuit"]
        for n in range(6):
            page.part_name.setText(f"Extra {n}")
            page.add_part()
        rect = page.canvas.graphics.sceneRect()
        for item in page.canvas.part_items.values():
            self.assertTrue(rect.contains(item.sceneBoundingRect()))

    def test_search_waits_for_typing_then_filters(self):
        self.window.go_to("catalog")
        page = self.window.pages["catalog"]
        app.processEvents()
        everything = page.model.rowCount()
        QTest.keyClicks(page.search, "B0005")
        self.assertEqual(page.model.rowCount(), everything)  # Not yet: the delay hasn't passed.
        self.assertTrue(pump_until(lambda: page.model.rowCount() == 1, timeout=2))
        self.assertEqual(page.selected_id, "B0005")

    def test_table_sorts_numbers_numerically_with_unknowns_last(self):
        self.window.go_to("catalog")
        page = self.window.pages["catalog"]
        for capacity, profile_id in ((9.0, "S-A"), (100.0, "S-B")):
            self.catalog.add(BatteryProfile(id=profile_id, name=profile_id, capacity_value=capacity))
        self.state.profiles_changed.emit()
        page.model.sort(3, Qt.SortOrder.AscendingOrder)
        values = [p.capacity_value for p in page.model.rows]
        known = [v for v in values if v is not None]
        self.assertEqual(known, sorted(known))
        self.assertIsNone(values[-1])
        self.assertEqual(values[:len(known)], known)

    def test_imported_text_cannot_inject_markup_or_links(self):
        self.window.go_to("catalog")
        page = self.window.pages["catalog"]
        self.catalog.add(BatteryProfile(
            id="HACK", name="<img src=x>", notes="<script>x</script>", source_title="<b>t</b>", source_url="file:///C:/secret",
        ))
        self.state.profiles_changed.emit()
        app.processEvents()
        page.search.setText("HACK")
        self.assertTrue(pump_until(lambda: page.selected_id == "HACK", timeout=2))
        body = page.detail_body.text()
        self.assertNotIn("<script>", body)
        self.assertNotIn("<b>t</b>", body)
        self.assertNotIn('href="file', body)
        self.assertIn("&lt;script&gt;", body)

    def test_add_dialog_keeps_blank_unknown_and_zero_real(self):
        from catalog_page import IntakeDialog
        dialog = IntakeDialog()
        dialog.fields["name"].setText("Mine")
        dialog.fields["measured_current_a"].setText("0")
        dialog.fields["measured_temperature_c"].setText("-5")
        profile = dialog.profile()
        self.assertEqual(profile.measured_current_a, 0.0)
        self.assertEqual(profile.measured_temperature_c, -5.0)
        self.assertIsNone(profile.measured_voltage_v)
        self.assertEqual(profile.manufacturer, "Unknown")

    def test_chart_handles_empty_single_gap_and_long_series(self):
        chart = LineChart("Test", "V")
        chart.resize(400, 220)
        chart.grab()
        chart.set_series([Series("A", "#2a78d6", [0.0], [5.0])])
        chart.grab()
        chart.set_series([Series("A", "#2a78d6", [0.0, 1.0, 2.0], [1.0, None, 3.0])])
        chart.grab()
        xs = [float(i) for i in range(200_000)]
        chart.set_series([Series("A", "#2a78d6", xs, [float(i % 97) for i in range(200_000)])])
        started = time.perf_counter()
        chart.grab()
        self.assertLess(time.perf_counter() - started, 1.0)
        self.assertEqual(nice_ticks(0, 100)[0], 0)


if __name__ == "__main__":
    unittest.main()
