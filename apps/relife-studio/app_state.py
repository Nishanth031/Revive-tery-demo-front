"""Data shared by every page: the catalog, the linked database and its packs."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Signal

import database as db
from battery_details import BatteryCatalog
from circuit_studio import CircuitDesign
from models import BatteryProfile
from widgets import run_async

SETTING_DB_PATH = "database/path"


def _load_everything(path: Path | None) -> tuple[db.DatabaseStatus, dict[str, db.PackData]]:
    status = db.check_database(path)
    packs = {}
    if status.connected:
        for pack_id in status.pack_ids:
            packs[pack_id] = db.load_pack(status.path, pack_id)
    return status, packs


class AppState(QObject):
    profiles_changed = Signal()
    database_changed = Signal()
    test_requested = Signal(str)

    def __init__(self, catalog: BatteryCatalog | None = None, db_path: Path | None = None, remember: bool = True,
                 parent: QObject | None = None):
        super().__init__(parent)
        self.catalog = catalog or BatteryCatalog()
        self.design = CircuitDesign.starter()
        self.remember = remember
        self.settings = QSettings("ReLife", "BMS Studio") if remember else None
        self.db_path = db_path if db_path is not None else self._initial_db_path()
        self.status = db.DatabaseStatus(self.db_path, False, "Connecting…")
        self.packs: dict[str, db.PackData] = {}
        self.pack_profiles: list[BatteryProfile] = []
        self.loading = False
        self._load_token = 0

    def _initial_db_path(self) -> Path | None:
        if self.settings is not None:
            saved = self.settings.value(SETTING_DB_PATH, "", str)
            if saved and Path(saved).is_file():
                return Path(saved)
        return db.discover_database()

    def all_profiles(self) -> list[BatteryProfile]:
        return self.pack_profiles + self.catalog.profiles

    def profile(self, profile_id: str) -> BatteryProfile | None:
        for profile in self.pack_profiles:
            if profile.id == profile_id:
                return profile
        return self.catalog.get(profile_id)

    def set_database(self, path: Path) -> None:
        self.db_path = path
        if self.settings is not None:
            self.settings.setValue(SETTING_DB_PATH, str(path))
        self.refresh_database()

    def refresh_database(self, wait: bool = False) -> None:
        """Reload the linked database, off the UI thread unless wait is True."""
        self._load_token += 1
        token = self._load_token
        path = self.db_path
        self.loading = True
        if wait:
            try:
                self._apply(token, _load_everything(path))
            except db.DatabaseError as exc:
                self._apply_error(token, str(exc))
            return
        run_async(lambda: _load_everything(path), lambda result: self._apply(token, result),
                  lambda message: self._apply_error(token, message))

    def _apply(self, token: int, result) -> None:
        if token != self._load_token:
            return  # A newer reload has started, so this result is out of date.
        self.status, self.packs = result
        name = self.db_path.name if self.db_path else db.DB_FILE_NAME
        self.pack_profiles = [db.profile_from_pack(pack, name) for pack in self.packs.values()]
        self.loading = False
        self.database_changed.emit()
        self.profiles_changed.emit()

    def _apply_error(self, token: int, message: str) -> None:
        if token != self._load_token:
            return
        self.status = db.DatabaseStatus(self.db_path, False, message)
        self.packs = {}
        self.pack_profiles = []
        self.loading = False
        self.database_changed.emit()
        self.profiles_changed.emit()
