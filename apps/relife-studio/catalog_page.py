"""Battery catalog page: search, details, the add dialog and profile CSV import."""
from __future__ import annotations

import html
import uuid

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDoubleValidator, QIntValidator
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

from app_state import AppState
from models import BatteryProfile
from widgets import Badge, Card, Column, Page, fmt, label, make_table, safe_link

SEARCH_DELAY_MS = 120
CHEMISTRY_COLUMN_WIDTH = 170
SOURCE_NAMES = {
    "research_dataset": "Research record",
    "user_entered": "Your entry",
    "imported_dataset": "Imported",
    "database": "Database",
}
CONDITIONS = ["Unknown", "New", "Used", "Needs assessment", "Damaged - do not test"]
CATEGORIES = ["Unclassified", "EV traction", "Stationary storage", "UPS / backup", "Telecom", "Portable / tool", "Industrial", "Other"]
CHEMISTRIES = ["Unknown", "LFP", "NMC", "NCA", "Li-ion", "Lead-acid", "NiMH", "NiCd", "Sodium-ion", "Other"]


def _capacity(profile: BatteryProfile) -> str:
    return fmt(profile.capacity_value, profile.capacity_unit)


def _status(profile: BatteryProfile) -> str:
    return "Ready" if not profile.completeness()[1] else "Incomplete"


class CatalogPage(Page):
    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(
            "Batteries", "Packs from your database, your own entries and public research records.", scroll=False, parent=parent,
        )
        self.state = state
        self.selected_id: str | None = None

        add = QPushButton("Add battery")
        add.setObjectName("primary")
        add.clicked.connect(self.add_battery)
        imp = QPushButton("Import profiles CSV…")
        imp.clicked.connect(self.import_csv)
        self.actions.addWidget(imp)
        self.actions.addWidget(add)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by name, chemistry, manufacturer, model or dataset")
        self.search.setClearButtonEnabled(True)
        # Waits for a pause in typing, so each keystroke doesn't rebuild the list.
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DELAY_MS)
        self._search_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(self._search_timer.start)
        self.content.addWidget(self.search)

        columns = [
            Column("Battery", lambda p: p.name),
            Column("Chemistry", lambda p: p.chemistry),
            Column("Series", lambda p: p.series_cells, lambda p: fmt(p.series_cells)),
            Column("Capacity", lambda p: p.capacity_value, _capacity),
            Column("Source", lambda p: SOURCE_NAMES.get(p.source_kind, p.source_kind)),
            Column("Profile", _status),
        ]
        self.table, self.model = make_table(columns, stretch=0)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        header = self.table.horizontalHeader()
        for section in range(2, len(columns)):
            header.setSectionResizeMode(section, QHeaderView.ResizeMode.ResizeToContents)
        # A fixed width, because one dataset's chemistry is a long sentence. Hover shows it all.
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(1, CHEMISTRY_COLUMN_WIDTH)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)

        self.detail_card = Card(spacing=8)
        self.detail_card.setMinimumWidth(330)
        self.detail_title = label("", "sectionTitle", wrap=True)
        self.detail_status = Badge()
        self.detail_body = QLabel()
        self.detail_body.setWordWrap(True)
        self.detail_body.setTextFormat(Qt.TextFormat.RichText)
        self.detail_body.setOpenExternalLinks(True)
        self.detail_body.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.detail_body.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        holder.setObjectName("card")
        holder.setStyleSheet("QWidget#card{background:transparent;border:0}")
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 8, 0)
        holder_layout.addWidget(self.detail_body)
        holder_layout.addStretch(1)
        scroll.setWidget(holder)
        scroll.setStyleSheet("QScrollArea{background:transparent} QScrollArea > QWidget > QWidget{background:transparent}")
        self.test_button = QPushButton("Run a virtual test")
        self.test_button.clicked.connect(self._test_selected)
        self.detail_card.body.addWidget(self.detail_title)
        self.detail_card.body.addWidget(self.detail_status)
        self.detail_card.body.addWidget(scroll, 1)
        self.detail_card.body.addWidget(self.test_button)

        splitter = QSplitter()
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail_card)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setChildrenCollapsible(False)
        self.content.addWidget(splitter, 1)

        state.profiles_changed.connect(self.refresh)
        self.refresh()

    def _visible_profiles(self) -> list[BatteryProfile]:
        query = self.search.text()
        matches = self.state.catalog.search(query)
        needle = query.casefold().strip()
        packs = [
            p for p in self.state.pack_profiles
            if not needle or needle in " ".join((p.id, p.name, p.chemistry, p.model, p.source_title)).casefold()
        ]
        return packs + matches

    def refresh(self) -> None:
        keep = self.selected_id
        self.model.set_rows(self._visible_profiles())
        rows = self.model.rows
        target = next((i for i, p in enumerate(rows) if p.id == keep), 0 if rows else None)
        if target is None:
            self.selected_id = None
            self._show_detail(None)
            return
        self.table.selectRow(target)
        self._show_detail(rows[target])

    def _selection_changed(self) -> None:
        indexes = self.table.selectionModel().selectedRows()
        if indexes:
            profile = self.model.rows[indexes[0].row()]
            self.selected_id = profile.id
            self._show_detail(profile)

    def _show_detail(self, profile: BatteryProfile | None) -> None:
        self.test_button.setEnabled(profile is not None)
        if profile is None:
            self.detail_title.setText("No matching batteries")
            self.detail_status.set("Try a different search", "neutral")
            self.detail_body.setText("")
            return
        missing = profile.completeness()[1]
        self.detail_title.setText(profile.name)
        if missing:
            self.detail_status.set("Incomplete profile", "warning")
        else:
            self.detail_status.set("Ready for simulation", "good")

        def row(name: str, value: str) -> str:
            return (f'<tr><td style="color:#52514e;padding:2px 12px 2px 0">{name}</td>'
                    f'<td style="padding:2px 0">{html.escape(value)}</td></tr>')

        rows = [
            row("ID", profile.id),
            row("Chemistry", profile.chemistry),
            row("Manufacturer", profile.manufacturer),
            row("Model", profile.model),
            row("Category", profile.category),
            row("Nominal voltage", fmt(profile.nominal_voltage_v, "V")),
            row("Rated capacity", _capacity(profile)),
            row("Cells", f"{fmt(profile.series_cells)}S × {fmt(profile.parallel_cells)}P"),
            row("Mass", fmt(profile.mass_kg, "kg")),
            row("Condition", profile.condition),
            row("Measured voltage", fmt(profile.measured_voltage_v, "V")),
            row("Measured capacity", fmt(profile.measured_capacity_ah, "Ah")),
            row("State of health", fmt(profile.soh_pct, "%")),
            row("Resistance", fmt(profile.internal_resistance_mohm, "mΩ")),
        ]
        parts = [f'<table>{"".join(rows)}</table>']
        if missing:
            parts.append(f"<p><b>Still needed:</b> {html.escape(', '.join(missing))}</p>")
        source = f"<p><b>Source:</b> {html.escape(profile.source_title)}"
        if profile.source_url:
            source += f"<br>{safe_link(profile.source_url)}"
        source += f"<br>Method: {html.escape(profile.measurement_method)}<br>License: {html.escape(profile.license)}</p>"
        parts.append(source)
        if profile.notes:
            parts.append(f'<p style="color:#52514e">{html.escape(profile.notes)}</p>')
        self.detail_body.setText("".join(parts))

    def _test_selected(self) -> None:
        if self.selected_id:
            self.state.test_requested.emit(self.selected_id)

    def add_battery(self) -> None:
        dialog = IntakeDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                profile = dialog.profile()
                self.state.catalog.add(profile)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Could not save", str(exc))
                return
            self.selected_id = profile.id
            self.state.profiles_changed.emit()

    def import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import battery profiles", "", "CSV files (*.csv)")
        if not path:
            return
        try:
            added = self.state.catalog.import_csv(path)
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        QMessageBox.information(self, "Import complete", f"Imported {len(added)} profiles.")
        self.state.profiles_changed.emit()


class IntakeDialog(QDialog):
    """Enter a battery. A blank field stays unknown, and zero stays a real measurement."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Add a battery")
        self.resize(560, 680)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)
        root.addWidget(label("Add a battery", "pageTitle"))
        root.addWidget(label("Leave anything you don't know blank. It stays Unknown rather than being guessed.", "pageSubtitle", wrap=True))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        form = QFormLayout(body)
        form.setVerticalSpacing(8)
        form.setHorizontalSpacing(14)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self.fields: dict[str, QWidget] = {}
        groups = (
            ("Identity", [
                ("name", "Display name", "text"), ("category", "Category", CATEGORIES), ("chemistry", "Chemistry", CHEMISTRIES),
                ("manufacturer", "Manufacturer", "text"), ("model", "Model", "text"),
                ("manufacture_date", "Manufacture date or code", "text"), ("condition", "Condition", CONDITIONS),
            ]),
            ("Specifications", [
                ("series_cells", "Series cells", "int"), ("parallel_cells", "Parallel cells", "int"),
                ("nominal_voltage_v", "Nominal voltage (V)", "positive"), ("capacity_value", "Rated capacity", "positive"),
                ("capacity_unit", "Capacity unit", ["Ah", "Wh", "kWh"]), ("rated_energy_wh", "Rated energy (Wh)", "positive"),
                ("charge_limit_a", "Max charge current (A)", "positive"), ("discharge_limit_a", "Max discharge current (A)", "positive"),
                ("mass_kg", "Mass (kg)", "positive"),
            ]),
            ("Measurements", [
                ("measured_voltage_v", "Voltage now (V)", "positive"), ("measured_current_a", "Current now (A)", "signed"),
                ("measured_temperature_c", "Temperature (°C)", "signed"), ("measured_capacity_ah", "Measured capacity (Ah)", "positive"),
                ("initial_soc_pct", "State of charge (%)", "percent"), ("soh_pct", "State of health (%)", "percent"),
                ("internal_resistance_mohm", "Internal resistance (mΩ)", "positive"), ("cycle_count", "Cycle count", "int"),
            ]),
            ("Source", [("source_url", "Source URL", "text"), ("notes", "Notes", "text")]),
        )
        for group, specs in groups:
            form.addRow(label(group, "sectionTitle"))
            for key, title, kind in specs:
                if isinstance(kind, list):
                    widget = QComboBox()
                    widget.addItems(kind)
                else:
                    widget = QLineEdit()
                    if kind == "int":
                        widget.setValidator(QIntValidator(0, 10_000_000, widget))
                    elif kind in ("positive", "percent", "signed"):
                        low, high = {"positive": (0, 1e9), "percent": (0, 100), "signed": (-1e9, 1e9)}[kind]
                        validator = QDoubleValidator(low, high, 6, widget)
                        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
                        widget.setValidator(validator)
                self.fields[key] = widget
                form.addRow(title, widget)
        self.fields["name"].setPlaceholderText("Required")

        self.error = label("", "caption", wrap=True)
        root.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _validate(self) -> None:
        if not self.fields["name"].text().strip():
            self.error.setText("Enter a display name.")
            return
        for widget in self.fields.values():
            if isinstance(widget, QLineEdit) and widget.text() and not widget.hasAcceptableInput():
                self.error.setText(f"“{widget.text()}” isn't valid for one of the number fields.")
                widget.setFocus()
                return
        self.accept()

    def profile(self) -> BatteryProfile:
        values = {}
        for key, widget in self.fields.items():
            values[key] = widget.currentText() if isinstance(widget, QComboBox) else widget.text().strip()
        values["id"] = "USER-" + uuid.uuid4().hex[:8].upper()
        return BatteryProfile.from_dict(values)
