"""Local curated battery catalog and import/export."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from models import BatteryProfile

ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "battery_catalog.json"
SOURCES = [
    {
        "title": "Second-life LFP battery dataset (23 LongTTech cells)",
        "url": "https://zenodo.org/records/18630889",
        "license": "CC BY 4.0",
        "method": "Three capacity tests; time-series voltage/current/temperature/SOC at 1 s; test temperature 25 C. SOC is computed from nominal capacity.",
        "chemistry": "LFP",
        "manufacturer": "LongTTech",
        "count": 23,
    },
    {
        "title": "Long-Term Sweat Testing Dataset for Second-Life Batteries",
        "url": "https://doi.org/10.1038/s41597-025-05360-7",
        "license": "See repository record",
        "method": "Long-term cycling of repurposed EV batteries for six modeled stationary use cases; dataset released via Loughborough repository.",
        "chemistry": "Lithium-ion (cell-specific details in source files)",
        "manufacturer": "Multiple / source-specific",
        "count": None,
    },
    {
        "title": "NASA Ames PCoE Li-ion Battery Aging Dataset",
        "url": "https://data.nasa.gov/dataset/li-ion-battery-aging-datasets",
        "license": "NASA Open Data; review record terms",
        "method": "Laboratory charge/discharge/impedance cycles; recorded voltage, current, temperature, time, and discharge capacity. 18650 cells; nominal 2 Ah; accelerated aging to capacity fade criterion.",
        "chemistry": "Li-ion NCA",
        "manufacturer": "Commercial cells; model unspecified in portal record",
        "count": 4,
    },
    {
        "title": "NASA PCoE Randomized and Recommissioned Battery Dataset",
        "url": "https://data.nasa.gov/dataset/randomized-and-recommissioned-battery-dataset",
        "license": "U.S. Government work; see dataset record",
        "method": "26 accelerated-life 2-cell 18650 packs, constant/random load profiles, includes load cycling of surviving cells assembled into second-life packs.",
        "chemistry": "Li-ion",
        "manufacturer": "Research packs; cell model per dataset files",
        "count": None,
    },
]
NASA_AGING_IDS = ["B0005", "B0006", "B0007", "B0018"]
RESEARCH_NOTE = "Research record, not a battery listing for sale. Import source data to fill per-cell measurements."


def seed_profiles() -> list[BatteryProfile]:
    """Dataset identity records. Individual cell metrics stay unknown until source data is imported."""
    profiles = []
    for source in SOURCES:
        title = source["title"]
        for n in range(1, (source["count"] or 1) + 1):
            is_nasa_aging = title.startswith("NASA Ames")
            if is_nasa_aging:
                profile_id = NASA_AGING_IDS[n - 1]
                name = f"NASA PCoE {profile_id}"
            elif title.startswith("NASA PCoE Randomized"):
                profile_id = f"NASA-RR-{n:02d}"
                name = "NASA recommissioned 2-cell research pack"
            elif title.startswith("Second-life"):
                profile_id = f"WEB-LFP23-{n:02d}"
                name = f"LongTTech second-life LFP cell {n:02d}"
            else:
                profile_id = f"WEB-SL-LT-{n:02d}"
                name = "Repurposed EV battery research dataset"
            profiles.append(BatteryProfile(
                id=profile_id,
                name=name,
                chemistry=source["chemistry"],
                manufacturer=source["manufacturer"],
                model="18650 research cell" if is_nasa_aging else "Unknown",
                series_cells=1 if is_nasa_aging else None,
                capacity_value=2.0 if is_nasa_aging else None,
                capacity_unit="Ah",
                source_kind="research_dataset",
                source_title=title,
                source_url=source["url"],
                license=source["license"],
                measurement_method=source["method"],
                notes=RESEARCH_NOTE,
            ))
    return profiles


class BatteryCatalog:
    def __init__(self, path: Path | str = CATALOG):
        self.path = Path(path)
        self.profiles: list[BatteryProfile] = []
        self._by_id: dict[str, BatteryProfile] = {}
        self._search_text: dict[str, str] = {}
        self.load()

    def load(self) -> list[BatteryProfile]:
        saved = []
        if self.path.exists():
            try:
                saved = [BatteryProfile.from_dict(x) for x in json.loads(self.path.read_text(encoding="utf-8"))]
            except (ValueError, TypeError):
                saved = []
        known = {p.id for p in saved}
        self.profiles = saved + [p for p in seed_profiles() if p.id not in known]
        self._reindex()
        return self.profiles

    def _reindex(self) -> None:
        self._by_id = {p.id: p for p in self.profiles}
        self._search_text = {p.id: self._text_for(p) for p in self.profiles}

    @staticmethod
    def _text_for(p: BatteryProfile) -> str:
        return " ".join((p.id, p.name, p.chemistry, p.manufacturer, p.model, p.source_title)).casefold()

    def _register(self, profile: BatteryProfile) -> None:
        self.profiles.append(profile)
        self._by_id[profile.id] = profile
        self._search_text[profile.id] = self._text_for(profile)

    def save(self) -> None:
        text = json.dumps([p.to_dict() for p in self.profiles], indent=2, ensure_ascii=False)
        self.path.write_text(text, encoding="utf-8")

    def get(self, profile_id: str) -> BatteryProfile | None:
        return self._by_id.get(profile_id)

    def add(self, profile: BatteryProfile) -> None:
        if profile.id in self._by_id:
            raise ValueError("That profile ID already exists")
        self._register(profile)
        self.save()

    def search(self, query: str) -> list[BatteryProfile]:
        query = query.casefold().strip()
        if not query:
            return list(self.profiles)
        return [p for p in self.profiles if query in self._search_text[p.id]]

    def import_csv(self, path: Path | str) -> list[BatteryProfile]:
        """Add one profile per CSV row. Rows without an id are skipped.

        Raises ValueError when the file has no id column, which also catches the pack data
        CSVs: those belong in the database, through the Pack data page.
        """
        added = []
        with open(path, newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if "id" not in (reader.fieldnames or []):
                raise ValueError(
                    "This file has no 'id' column, so it isn't a battery profile list. "
                    "To load pack data such as telemetry.csv, use Import data on the Pack data page."
                )
            for row in reader:
                row.setdefault("source_kind", "imported_dataset")
                row.setdefault("source_title", Path(path).name)
                profile = BatteryProfile.from_dict(row)
                if not profile.id:
                    continue
                base_id = profile.id
                suffix = 1
                while profile.id in self._by_id:
                    profile.id = f"{base_id}-IMPORT{suffix}"
                    suffix += 1
                self._register(profile)
                added.append(profile)
        self.save()
        return added
