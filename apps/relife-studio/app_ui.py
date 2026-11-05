"""ReLife BMS Studio main window. Pages are built the first time they're opened."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout,
    QWidget,
)

import theme
from app_state import AppState
from battery_details import SOURCES
from bench_page import BenchPage
from catalog_page import CatalogPage
from circuit_page import CircuitPage
from pack_page import PackPage
from widgets import Banner, Card, KpiTile, Page, fmt, label

WORKFLOW = (
    ("Check your pack data", "See readings, health history and safety events from your database.", "pack"),
    ("Review batteries", "Add a battery or pick a research record. Unknown facts stay unknown.", "catalog"),
    ("Inspect the circuit", "See how the BMS parts and signal paths connect.", "circuit"),
    ("Run a virtual test", "Run a synthetic pulse and read the screening result.", "bench"),
)


class OverviewPage(Page):
    def __init__(self, state: AppState, go_to, parent: QWidget | None = None):
        super().__init__("ReLife BMS Studio", "Read, analyze and screen battery data for second-life use.", parent=parent)
        self.state = state
        self.go_to = go_to

        self.content.addWidget(Banner(
            "Simulation only. No physical battery connection or real protection is implemented, and public research "
            "records are laboratory data rather than batteries for sale.", "info",
        ))

        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.tile_database = KpiTile("Database")
        self.tile_packs = KpiTile("Packs in database")
        self.tile_profiles = KpiTile("Battery profiles", caption="Your entries and research records")
        self.tile_sources = KpiTile("Research sources", str(len(SOURCES)), "Public datasets, cited")
        for tile in (self.tile_database, self.tile_packs, self.tile_profiles, self.tile_sources):
            tiles.addWidget(tile, 1)
        self.content.addLayout(tiles)

        self.pack_card = Card("Linked pack")
        self.pack_text = label("", wrap=True)
        self.pack_card.body.addWidget(self.pack_text)
        open_pack = QPushButton("Open pack data")
        open_pack.setObjectName("primary")
        open_pack.clicked.connect(lambda: self.go_to("pack"))
        row = QHBoxLayout()
        row.addWidget(open_pack)
        row.addStretch(1)
        self.pack_card.body.addLayout(row)
        self.content.addWidget(self.pack_card)

        steps = Card("Workflow")
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        for i, (title, text, page) in enumerate(WORKFLOW):
            grid.addWidget(label(f"{i + 1}. {title}", "sectionTitle"), i, 0)
            grid.addWidget(label(text, "caption", wrap=True), i, 1)
            button = QPushButton("Open")
            button.clicked.connect(lambda _=False, target=page: self.go_to(target))
            grid.addWidget(button, i, 2)
        steps.body.addLayout(grid)
        self.content.addWidget(steps)
        self.content.addStretch(1)

        state.database_changed.connect(self.refresh)
        state.profiles_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        status = self.state.status
        name = status.path.name if status.path else "No file linked"
        if self.state.loading:
            self.tile_database.set("Connecting", name)
        else:
            self.tile_database.set("Connected" if status.connected else "Not connected", name)
        self.tile_packs.set(str(len(self.state.packs)), "Stored in the linked database")
        self.tile_profiles.set(str(len(self.state.catalog.profiles)))
        if self.state.pack_profiles:
            pack = self.state.pack_profiles[0]
            self.pack_text.setText(
                f"{pack.id}: {pack.chemistry}, {fmt(pack.nominal_voltage_v, 'V')}, {fmt(pack.capacity_value, pack.capacity_unit)}. "
                f"Latest: {fmt(pack.initial_soc_pct, '%')} charge, {fmt(pack.soh_pct, '%')} health."
                + (" Synthetic demo data." if self.state.packs[pack.id].is_synthetic else "")
            )
        elif not self.state.loading:
            self.pack_text.setText(
                f"{status.message}. Open Pack data to import your CSV bundle or link a database."
                if not status.connected else "This database has no pack data yet."
            )


class MainWindow(QMainWindow):
    def __init__(self, state: AppState | None = None):
        super().__init__()
        self.setWindowTitle("ReLife BMS Studio")
        self.setStyleSheet(theme.STYLE_SHEET)
        self.setMinimumSize(1080, 680)
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.resize(min(1440, available.width() - 40), min(900, available.height() - 60))

        self.state = state or AppState()
        self.pages: dict[str, QWidget] = {}
        self.factories = {
            "overview": lambda: OverviewPage(self.state, self.go_to),
            "pack": lambda: PackPage(self.state),
            "catalog": lambda: CatalogPage(self.state),
            "circuit": lambda: CircuitPage(self.state),
            "bench": lambda: BenchPage(self.state),
        }

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(root)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(208)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(12, 18, 12, 14)
        nav.setSpacing(3)
        nav.addWidget(label("ReLife", "appTitle"))
        nav.addWidget(label("BMS Studio", "caption"))
        nav.addSpacing(14)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons: dict[str, QPushButton] = {}
        for key, title in (
            ("overview", "Overview"), ("pack", "Pack data"), ("catalog", "Batteries"),
            ("circuit", "Circuit Studio"), ("bench", "Test bench"),
        ):
            button = QPushButton(title)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, target=key: self.go_to(target))
            self.nav_group.addButton(button)
            self.nav_buttons[key] = button
            nav.addWidget(button)
        nav.addStretch(1)
        nav.addWidget(label("Simulation only", "caption"))
        layout.addWidget(sidebar)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.state.test_requested.connect(self._open_test)
        self.go_to("overview")
        self.state.refresh_database()

    def page(self, key: str) -> QWidget:
        if key not in self.pages:
            page = self.factories[key]()
            self.pages[key] = page
            self.stack.addWidget(page)
        return self.pages[key]

    def go_to(self, key: str) -> None:
        self.stack.setCurrentWidget(self.page(key))
        self.nav_buttons[key].setChecked(True)

    def _open_test(self, profile_id: str) -> None:
        self.go_to("bench")
        self.pages["bench"].select_battery(profile_id)


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
