"""Pack data page: the linked database, its charts and tables, and the upload dialog."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView, QMessageBox, QPushButton, QSizePolicy,
    QTabWidget, QVBoxLayout, QWidget,
)

import database as db
import theme
from app_state import AppState
from widgets import (
    Badge, Banner, Card, Column, KpiTile, LineChart, Page, Series, fit_combo, fmt, label, make_table, run_async,
)

HIDDEN_COLUMNS = {db.KEY_COLUMN}
MAX_VISIBLE_ROWS = 8
ROW_HEIGHT = 34
HEADER_HEIGHT = 38
SCROLLBAR_ROOM = 14


def _utc_stamp(value) -> float:
    return value.timestamp()


def _time_label(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, timezone.utc).strftime("%H:%M")


def _date_label(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, timezone.utc).strftime("%b %Y")


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y %H:%M UTC")
    if isinstance(value, date):
        return value.strftime("%d %b %Y")
    return f"{value:g}" if isinstance(value, float) else str(value)


def _heading(key: str) -> str:
    """Turn a column name into a heading, keeping unit suffixes such as _kwh readable."""
    units = {"pct": "%", "kwh": "kWh", "kw": "kW", "ah": "Ah", "c": "°C", "kg": "kg", "v": "V", "a": "A", "mohm": "mΩ"}
    parts = key.split("_")
    unit = units.get(parts[-1]) if len(parts) > 1 else None
    words = " ".join(parts[:-1] if unit else parts).capitalize().replace(" utc", " (UTC)")
    return f"{words} ({unit})" if unit else words


def _series(rows: list[dict], key: str, label_text: str, color: str, x_key: str) -> Series:
    series = Series(label_text, color)
    for row in rows:
        stamp = row.get(x_key)
        if isinstance(stamp, date) and not isinstance(stamp, datetime):
            stamp = datetime(stamp.year, stamp.month, stamp.day, tzinfo=timezone.utc)
        if not isinstance(stamp, datetime):
            continue
        value = row.get(key)
        series.xs.append(_utc_stamp(stamp))
        series.ys.append(float(value) if isinstance(value, (int, float)) else None)
    return series


class RowsTable(QWidget):
    """A table built from whichever columns the data has, sized to its row count."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 8, 0, 0)
        self.view = None
        self.model = None

    def set_rows(self, rows: list[dict]) -> None:
        while self.layout_.count():  # Clears the old table and its spacer.
            item = self.layout_.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        keys = [k for k in (rows[0] if rows else {}) if k not in HIDDEN_COLUMNS]
        columns = [
            Column(_heading(k), (lambda row, k=k: row.get(k)), (lambda row, k=k: _cell_text(row.get(k)))) for k in keys
        ]
        self.view, self.model = make_table(columns)
        self.model.set_rows(rows)
        header = self.view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        visible = min(len(rows), MAX_VISIBLE_ROWS)
        if len(rows) <= MAX_VISIBLE_ROWS:
            self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Room for the header, the rows and a sideways scrollbar for wide records.
        self.view.setFixedHeight(HEADER_HEIGHT + visible * ROW_HEIGHT + SCROLLBAR_ROOM)
        self.layout_.addWidget(self.view, 0, Qt.AlignmentFlag.AlignTop)
        self.layout_.addStretch(1)


class PackPage(Page):
    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__("Pack data", "Readings and history from your linked DuckDB database.", parent=parent)
        self.state = state
        self.current_id: str | None = None

        self.test_button = QPushButton("Test this pack")
        self.test_button.clicked.connect(self._test_pack)
        self.change_button = QPushButton("Change database…")
        self.change_button.clicked.connect(self._choose_database)
        self.import_button = QPushButton("Import data…")
        self.import_button.setObjectName("primary")
        self.import_button.clicked.connect(self.open_import)
        for button in (self.test_button, self.change_button, self.import_button):
            self.actions.addWidget(button)

        connection = Card()
        row = QHBoxLayout()
        row.setSpacing(12)
        self.db_badge = Badge("Connecting…")
        self.db_path_label = label("", "caption", wrap=True)
        self.db_path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.db_path_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.pack_combo = fit_combo(QComboBox(), 20)
        self.pack_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.pack_combo.currentIndexChanged.connect(self._pack_chosen)
        row.addWidget(self.db_badge)
        row.addWidget(self.db_path_label, 1)
        row.addWidget(self.pack_combo)
        connection.body.addLayout(row)
        self.content.addWidget(connection)

        self.synthetic_banner = Banner("", "warning")
        self.content.addWidget(self.synthetic_banner)

        self.detail = QWidget()
        detail = QVBoxLayout(self.detail)
        detail.setContentsMargins(0, 0, 0, 0)
        detail.setSpacing(14)

        kpis = QHBoxLayout()
        kpis.setSpacing(12)
        self.kpi_soc = KpiTile("State of charge")
        self.kpi_soh = KpiTile("State of health")
        self.kpi_voltage = KpiTile("Pack voltage")
        self.kpi_current = KpiTile("Pack current")
        self.kpi_temp = KpiTile("Hottest cell")
        self.kpi_cycles = KpiTile("Charge cycles")
        for tile in (self.kpi_soc, self.kpi_soh, self.kpi_voltage, self.kpi_current, self.kpi_temp, self.kpi_cycles):
            kpis.addWidget(tile, 1)
        detail.addLayout(kpis)

        self.checks_card = Card("Data checks", spacing=6)
        self.checks_list = label("", wrap=True)
        self.checks_card.body.addWidget(self.checks_list)
        detail.addWidget(self.checks_card)

        telemetry = Card("Telemetry")
        grid = QGridLayout()
        grid.setSpacing(14)
        self.chart_voltage = LineChart("Pack voltage", "V", _time_label)
        self.chart_current = LineChart("Pack current", "A", _time_label)
        self.chart_temp = LineChart("Cell temperature", "°C", _time_label)
        self.chart_soc = LineChart("State of charge", "%", _time_label)
        grid.addWidget(self.chart_voltage, 0, 0)
        grid.addWidget(self.chart_current, 0, 1)
        grid.addWidget(self.chart_temp, 1, 0)
        grid.addWidget(self.chart_soc, 1, 1)
        telemetry.body.addLayout(grid)
        detail.addWidget(telemetry)

        health = Card("Health history")
        health_row = QHBoxLayout()
        health_row.setSpacing(14)
        self.chart_soh = LineChart("State of health", "%", _date_label)
        self.chart_resistance = LineChart("Internal resistance", "mΩ", _date_label)
        health_row.addWidget(self.chart_soh)
        health_row.addWidget(self.chart_resistance)
        health.body.addLayout(health_row)
        detail.addWidget(health)

        records = Card("Records", spacing=2)
        self.tabs = QTabWidget()
        self.tables = {}
        for key, title in (
            ("safety", "Safety events"), ("charges", "Charging"), ("health", "Health"), ("modules", "Modules"),
            ("specs", "Specifications"), ("materials", "Materials"), ("sources", "Sources"),
        ):
            table = RowsTable()
            self.tables[key] = table
            self.tabs.addTab(table, title)
        records.body.addWidget(self.tabs)
        detail.addWidget(records)

        self.content.addWidget(self.detail)
        self.empty = Banner("", "warning")
        self.content.addWidget(self.empty)
        self.content.addStretch(1)

        state.database_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        status = self.state.status
        path = status.path
        self.db_path_label.setText(str(path) if path else "No database linked")
        if status.connected:
            rows = sum(status.tables.values())
            self.db_badge.set(f"Connected · {len(status.tables)} tables · {rows:,} rows", "good")
        elif self.state.loading:
            self.db_badge.set("Connecting…", "neutral")
        else:
            self.db_badge.set("Not connected", "critical")

        self.pack_combo.blockSignals(True)
        self.pack_combo.clear()
        self.pack_combo.addItems(list(self.state.packs))
        if self.current_id in self.state.packs:
            self.pack_combo.setCurrentText(self.current_id)
        self.pack_combo.blockSignals(False)
        self.pack_combo.setVisible(len(self.state.packs) > 1)
        self.current_id = self.pack_combo.currentText() or None

        has_pack = self.current_id is not None
        self.detail.setVisible(has_pack)
        self.test_button.setEnabled(has_pack)
        self.empty.setVisible(not has_pack and not self.state.loading)
        if not has_pack:
            self.synthetic_banner.setVisible(False)
            self.empty.set(
                (status.message + ". " if not status.connected else "This database has no pack data yet. ")
                + "Use Import data to load your CSV bundle, or Change database to link another file.",
                "warning",
            )
            return
        self._show_pack(self.state.packs[self.current_id])

    def _pack_chosen(self) -> None:
        self.current_id = self.pack_combo.currentText() or None
        if self.current_id in self.state.packs:
            self._show_pack(self.state.packs[self.current_id])

    def _show_pack(self, pack: db.PackData) -> None:
        self.synthetic_banner.setVisible(pack.is_synthetic)
        if pack.is_synthetic:
            self.synthetic_banner.set(
                "Synthetic demo data. These values are illustrative, as this data set itself states. "
                "They are not measurements of a real battery, so don't use them for engineering, "
                "safety, warranty or compliance decisions.",
                "warning",
            )

        latest = pack.telemetry[-1] if pack.telemetry else {}
        when = latest.get(db.TIME_COLUMN)
        stamp = f"Latest reading, {when:%d %b %H:%M} UTC" if isinstance(when, datetime) else "No telemetry"
        health = pack.health[-1] if pack.health else {}
        assessed = health.get("assessment_date")
        assessed_text = f"Assessed {assessed:%d %b %Y}" if isinstance(assessed, date) else "No assessment"
        self.kpi_soc.set(fmt(latest.get("soc_pct"), "%"), stamp)
        self.kpi_soh.set(fmt(health.get("soh_pct"), "%"), assessed_text)
        self.kpi_voltage.set(fmt(latest.get("pack_voltage_v"), "V"), stamp)
        self.kpi_current.set(fmt(latest.get("pack_current_a"), "A"), str(latest.get("operating_state") or "State unknown").replace("_", " ").capitalize())
        self.kpi_temp.set(fmt(latest.get("max_cell_temp_c"), "°C"), stamp)
        self.kpi_cycles.set(fmt(health.get("cycle_count")), assessed_text)

        checks = db.data_checks(pack)
        self.checks_card.setVisible(bool(checks))
        self.checks_list.setText("\n".join(f"• {note}" for note in checks))

        rows = pack.telemetry
        key = db.TIME_COLUMN
        self.chart_voltage.set_series([_series(rows, "pack_voltage_v", "Voltage", theme.SERIES_1, key)])
        self.chart_current.set_series([_series(rows, "pack_current_a", "Current", theme.SERIES_1, key)])
        self.chart_temp.set_series([
            _series(rows, "max_cell_temp_c", "Hottest", theme.SERIES_2, key),
            _series(rows, "min_cell_temp_c", "Coolest", theme.SERIES_1, key),
        ])
        self.chart_soc.set_series([_series(rows, "soc_pct", "SOC", theme.SERIES_1, key)])
        self.chart_soh.set_series([_series(pack.health, "soh_pct", "SOH", theme.SERIES_1, "assessment_date")])
        self.chart_resistance.set_series([_series(pack.health, "internal_resistance_mohm", "Resistance", theme.SERIES_1, "assessment_date")])

        self.tables["safety"].set_rows(pack.safety)
        self.tables["charges"].set_rows(pack.charges)
        self.tables["health"].set_rows(pack.health)
        self.tables["modules"].set_rows(pack.modules)
        self.tables["specs"].set_rows([{"field": k.replace("_", " ").capitalize(), "value": v} for k, v in pack.asset.items()])
        self.tables["materials"].set_rows(pack.materials)
        self.tables["sources"].set_rows(pack.sources)
        self.tabs.setTabText(0, f"Safety events ({len(pack.safety)})")

    def _test_pack(self) -> None:
        if self.current_id:
            self.state.test_requested.emit(self.current_id)

    def _choose_database(self) -> None:
        start = str(self.state.db_path.parent) if self.state.db_path else str(db.ROOT)
        path, _ = QFileDialog.getOpenFileName(self, "Link a DuckDB database", start, "DuckDB database (*.duckdb);;All files (*)")
        if path:
            self.state.set_database(Path(path))

    def open_import(self) -> None:
        dialog = ImportDialog(self.state, self)
        dialog.exec()


class ImportDialog(QDialog):
    """Pick a zip, a folder or CSVs, check them, then load them into the database."""

    def __init__(self, state: AppState, parent: QWidget | None = None, candidates: list[Path] | None = None):
        super().__init__(parent)
        self.state = state
        self.preview: db.BundlePreview | None = None
        self.result_info: dict | None = None
        self.setWindowTitle("Import battery data")
        self.resize(760, 560)
        self.candidates = db.discover_bundles() if candidates is None else candidates

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(label("Import battery data", "pageTitle"))
        layout.addWidget(label(
            "Choose your CSV bundle as a zip, a folder or individual files. Nothing changes until you confirm.",
            "pageSubtitle", wrap=True,
        ))

        source = QHBoxLayout()
        source.setSpacing(8)
        self.source_combo = fit_combo(QComboBox(), 30)
        for path in self.candidates:
            self.source_combo.addItem(self._source_name(path), str(path))
        self.source_combo.currentIndexChanged.connect(self._source_chosen)
        source.addWidget(self.source_combo, 1)
        for text, handler in (("Zip…", self._pick_zip), ("Folder…", self._pick_folder), ("CSV files…", self._pick_files)):
            button = QPushButton(text)
            button.clicked.connect(handler)
            source.addWidget(button)
        layout.addLayout(source)

        columns = [
            Column("File", lambda f: f"{f.table}.csv"),
            Column("Rows", lambda f: f.rows, lambda f: f"{f.rows:,}"),
            Column("Columns", lambda f: len(f.columns)),
            Column("Check", lambda f: f.problem or "Ready"),
        ]
        self.table, self.table_model = make_table(columns, stretch=3)
        layout.addWidget(self.table, 1)

        self.message = Banner("", "info")
        layout.addWidget(self.message)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.import_button = QPushButton("Import")
        self.import_button.setObjectName("primary")
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self.start_import)
        buttons.addWidget(cancel)
        buttons.addWidget(self.import_button)
        layout.addLayout(buttons)

        if self.candidates:
            self.check_source([self.candidates[0]])
        else:
            self.message.set("Choose a zip, a folder or CSV files to check them.", "info")

    @staticmethod
    def _source_name(path: Path) -> str:
        kind = "Zip" if path.suffix.lower() == ".zip" else "Folder"
        return f"{kind}: {path.parent.name}{'/'}{path.name}"

    def _source_chosen(self) -> None:
        data = self.source_combo.currentData()
        if data:
            self.check_source([Path(data)])

    def _start_dir(self) -> str:
        return str(self.candidates[0].parent) if self.candidates else str(db.ROOT)

    def _pick_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a zip", self._start_dir(), "Zip files (*.zip)")
        if path:
            self.check_source([Path(path)])

    def _pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose a folder of CSV files", self._start_dir())
        if path:
            self.check_source([Path(path)])

    def _pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose CSV files", self._start_dir(), "CSV files (*.csv)")
        if paths:
            self.check_source([Path(p) for p in paths])

    def check_source(self, paths: list[Path]) -> None:
        self._discard_preview()
        self.import_button.setEnabled(False)
        self.table_model.set_rows([])
        self.message.set("Checking files…", "info")
        target = self.state.db_path
        run_async(lambda: db.preview_upload(paths, target), self._show_preview, self._show_error)

    def _discard_preview(self) -> None:
        if self.preview is not None:
            self.preview.close()
            self.preview = None

    def _show_error(self, message: str) -> None:
        self.message.set(message, "critical")

    def _show_preview(self, preview: db.BundlePreview) -> None:
        self._discard_preview()
        self.preview = preview
        self.table_model.set_rows(preview.files)
        self.table.resizeColumnToContents(0)
        self.table.resizeColumnToContents(1)
        self.table.resizeColumnToContents(2)
        if not preview.can_import:
            count = sum(1 for f in preview.files if not f.ok)
            self.message.set(f"{count} file(s) can't be imported. See the Check column. The database hasn't changed.", "critical")
            return
        count = len(preview.files)
        target = self.state.db_path.name if self.state.db_path else "a new database"
        notes = [f"Importing replaces {count} table(s) in {target}. A backup copy is saved first."]
        notes.extend(preview.warnings)
        self.message.set(" ".join(notes), "warning")
        self.import_button.setText(f"Replace {count} table(s)")
        self.import_button.setEnabled(True)

    def _target_path(self) -> Path | None:
        path = self.state.db_path
        if path is not None and not (path.is_file() and path.stat().st_size == 0):
            return path
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Create a database", str(db.ROOT / "data" / db.DB_FILE_NAME), "DuckDB database (*.duckdb)"
        )
        return Path(chosen) if chosen else None

    def start_import(self) -> None:
        if self.preview is None:
            return
        target = self._target_path()
        if target is None:
            return
        self.import_button.setEnabled(False)
        self.message.set("Importing…", "info")
        preview = self.preview
        run_async(
            lambda: db.import_bundle(preview, target),
            lambda result: self._import_done(result, target),
            self._import_failed,
        )

    def _import_failed(self, message: str) -> None:
        self.message.set(message, "critical")
        self.import_button.setEnabled(True)

    def _import_done(self, result: dict, target: Path) -> None:
        self.result_info = result
        self._discard_preview()
        self.state.set_database(target)
        self.accept()
        if not self.property("quiet"):
            backup = result["backup"]
            saved = f"\n\nBackup of the previous data: {backup.name}" if backup else ""
            QMessageBox.information(
                self.parent(), "Import complete",
                f"Loaded {len(result['tables'])} table(s), {sum(result['tables'].values()):,} rows, into {target.name}.{saved}",
            )

    def done(self, code: int) -> None:
        self._discard_preview()
        super().done(code)
