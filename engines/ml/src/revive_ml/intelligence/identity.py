"""Who is this battery? Chemistry, maker and the pack spec, from what the upload says or implies.

Order of evidence, strongest first: what the user typed, a metadata table in the upload (for example
``chemistry,LFP``) and names in file/sheet/id text (``BYD``, ``LiFePO4``). The voltage window of a single
cell is only a hint (it is reported but never counts as confirmation), and packs of unknown series count
cannot be told apart by voltage at all, so chemistry, series count and an ambiguous maker (CATL, Tesla,
"Li-ion" ...) are reported in ``needs`` instead of guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import pandas as pd

from revive_ml.config import load
from revive_ml.intelligence.mapper import HeaderClassifier, _num

CHEMISTRIES = ("LFP", "NMC", "NCA")


@lru_cache(maxsize=1)
def profiles() -> dict[str, Any]:
    return load("battery_profiles.yaml")


@lru_cache(maxsize=1)
def _spec_classifier() -> HeaderClassifier:
    cfg = load("intelligence.yaml")
    return HeaderClassifier({k: v["phrases"] for k, v in cfg["spec_fields"].items()}, cfg["spec_other"]["phrases"])


def _word(alias: str) -> re.Pattern[str]:
    return re.compile(r"(?<![a-z0-9])" + re.escape(alias.lower()).replace(r"\ ", r"[\s_\-]*") + r"(?![a-z0-9])")


@dataclass
class Identity:
    chemistry: str | None = None
    chemistry_basis: str = "unknown"          # user | stated in upload | name in upload | voltage window | unknown
    brand: str | None = None
    brand_note: str | None = None
    brand_ambiguous: bool = False
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"chemistry": self.chemistry, "chemistry_basis": self.chemistry_basis, "brand": self.brand,
                "brand_note": self.brand_note, "brand_ambiguous": self.brand_ambiguous, "evidence": self.evidence}


def detect_identity(texts: list[str]) -> Identity:
    """Look for chemistry and maker names in free text (file names, sheet names, ids, metadata values)."""
    prof = profiles()
    blob = " \n ".join(str(t).lower() for t in texts if t is not None)
    ident = Identity()
    chem_hits: dict[str, str] = {}
    for chem, c in prof["chemistries"].items():
        for alias in c["aliases"]:
            if _word(alias).search(blob):
                chem_hits.setdefault(chem, alias)
    brand_hit = None
    for b in prof["brands"]:
        for alias in b["aliases"]:
            if _word(alias).search(blob):
                brand_hit = (b, alias)
                break
        if brand_hit and not b["name"] == "Generic Li-ion":
            break
    if brand_hit:
        b, alias = brand_hit
        ident.brand, ident.brand_note, ident.brand_ambiguous = b["name"], b["note"], bool(b["ambiguous"])
        ident.evidence.append(f"maker name '{alias}' found in the upload")
    if len(chem_hits) == 1:
        chem, alias = next(iter(chem_hits.items()))
        ident.chemistry, ident.chemistry_basis = chem, "name in upload"
        ident.evidence.append(f"chemistry name '{alias}' found in the upload")
    elif len(chem_hits) > 1:
        ident.evidence.append(f"conflicting chemistry names in the upload: {sorted(chem_hits)}; not used")
    elif brand_hit and not brand_hit[0]["ambiguous"] and brand_hit[0]["chemistry"]:
        ident.chemistry, ident.chemistry_basis = brand_hit[0]["chemistry"], "name in upload"
        ident.evidence.append(f"{brand_hit[0]['name']} is normally {ident.chemistry}")
    return ident


# ---------------------------------------------------------------------------------------------
# key/value metadata tables
# ---------------------------------------------------------------------------------------------

def parse_spec_table(df: pd.DataFrame) -> dict[str, Any]:
    """Read a (key, value) metadata table. Returns {spec_field: value}; empty when it is not one.

    Accepts two columns (field, value) or three with a leading id column (asset_id, field, value).
    """
    if df.shape[1] not in (2, 3) or len(df) > 200 or len(df) < 1:
        return {}
    cols = [str(c).strip().lower() for c in df.columns]
    if "field" in cols and "value" in cols:
        key_col, val_col = df.columns[cols.index("field")], df.columns[cols.index("value")]
    else:
        key_col, val_col = df.columns[-2], df.columns[-1]
    if _num(df[key_col]).notna().mean() > 0.5:           # numeric 'keys' are data, not metadata
        return {}
    clf = _spec_classifier()
    out: dict[str, Any] = {}
    for k, v in zip(df[key_col], df[val_col]):
        proba = clf.proba(k)
        label, p = max(((c, x) for c, x in proba.items() if c != "other"), key=lambda kv: kv[1])
        if p >= 0.5 and proba.get("other", 0) < p and label not in out and pd.notna(v):
            out[label] = v
    return out


def spec_from_table(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise parsed metadata values into spec hints (numbers as numbers, '96s40p' split)."""
    out: dict[str, Any] = {}
    for k in ("rated_capacity_ah", "nominal_voltage_v", "series_cells", "parallel_cells", "rated_energy_kwh"):
        if k in raw:
            n = pd.to_numeric(pd.Series([raw[k]]), errors="coerce").iloc[0]
            if pd.notna(n) and n > 0:
                out[k] = float(n) if k != "series_cells" and k != "parallel_cells" else int(n)
    if "configuration" in raw:
        m = re.fullmatch(r"\s*(\d+)\s*s\s*(\d+)\s*p\s*", str(raw["configuration"]).lower())
        if m:
            out.setdefault("series_cells", int(m.group(1)))
            out.setdefault("parallel_cells", int(m.group(2)))
    for k in ("chemistry", "brand", "cell_model"):
        if k in raw:
            out[k] = str(raw[k])
    return out


# ---------------------------------------------------------------------------------------------
# spec inference
# ---------------------------------------------------------------------------------------------

@dataclass
class SpecItem:
    value: Any = None
    basis: str = "unknown"            # user | stated in upload | name in upload | inferred from data | unknown
    confident: bool = False
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "basis": self.basis, "confident": self.confident, "note": self.note}


@dataclass
class SpecInference:
    chemistry: SpecItem
    series_cells: SpecItem
    parallel_cells: SpecItem
    rated_capacity_ah: SpecItem
    nominal_voltage_v: SpecItem
    needs: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.needs

    def to_dict(self) -> dict[str, Any]:
        return {"chemistry": self.chemistry.to_dict(), "series_cells": self.series_cells.to_dict(),
                "parallel_cells": self.parallel_cells.to_dict(), "rated_capacity_ah": self.rated_capacity_ah.to_dict(),
                "nominal_voltage_v": self.nominal_voltage_v.to_dict(), "needs": self.needs, "complete": self.complete}


def _clean_chem(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip().upper()
    if s in CHEMISTRIES:
        return s
    ident = detect_identity([str(v)])
    return ident.chemistry


def infer_spec(df: pd.DataFrame, identity: Identity, table_spec: dict[str, Any] | None = None,
               hints: dict[str, Any] | None = None) -> SpecInference:
    """Pack spec for one battery from its standardised telemetry (columns as in mapper.STANDARD_FIELDS)."""
    table_spec, hints = table_spec or {}, hints or {}
    needs: list[str] = []

    def pick(key: str) -> tuple[Any, str] | None:
        if hints.get(key) not in (None, ""):
            return hints[key], "user"
        if table_spec.get(key) not in (None, ""):
            return table_spec[key], "stated in upload"
        return None

    v = _num(df["voltage_v"]).dropna() if "voltage_v" in df else pd.Series(dtype=float)
    vmax = float(v.quantile(0.995)) if len(v) else None
    single_cell = vmax is not None and vmax <= 4.35

    # chemistry
    chem = SpecItem()
    got = pick("chemistry")
    c = _clean_chem(got[0]) if got else None
    if c:
        chem = SpecItem(c, got[1], True)
    elif identity.chemistry:
        chem = SpecItem(identity.chemistry, identity.chemistry_basis, True, "; ".join(identity.evidence) or None)
    elif single_cell and vmax is not None:
        hi = vmax
        # A voltage window is only ever a hint, never a confirmation: a cell that stays below ~3.7 V fits LFP but
        # equally a partly discharged NMC/NCA cell, so the user is asked (confident=False -> "chemistry" in needs).
        if hi <= 3.72:
            chem = SpecItem("LFP", "inferred from data", False,
                            f"single-cell voltage peaks at {hi:.2f} V: fits LFP, but also a partly discharged "
                            "NMC or NCA cell; please confirm")
        elif hi >= 4.0:
            chem = SpecItem("NMC", "inferred from data", False,
                            f"single-cell voltage reaches {hi:.2f} V: NMC or NCA; assuming NMC, please confirm")
    if chem.value is None or not chem.confident:
        needs.append("chemistry")
        if chem.value is None:
            chem.note = (chem.note or "") + (" maker name is ambiguous; " if identity.brand_ambiguous else "") + \
                "the chemistry could not be established; choose LFP, NMC or NCA"

    # series / parallel
    got = pick("series_cells")
    if got:
        series = SpecItem(int(got[0]), got[1], True)
    elif single_cell:
        series = SpecItem(1, "inferred from data", True, f"voltage never exceeds {vmax:.2f} V: a single cell")
    else:
        series = SpecItem(None, "unknown", False, "a pack's series cell count cannot be told from voltage alone")
        needs.append("series_cells")
    got = pick("parallel_cells")
    parallel = SpecItem(int(got[0]), got[1], True) if got else \
        SpecItem(1, "assumed", True, "no parallel count given; 1 assumed (it does not change the voltage checks)")

    # rated capacity
    got = pick("rated_capacity_ah")
    cap = SpecItem()
    if got:
        cap = SpecItem(float(got[0]), got[1], True)
    elif "capacity_ah" in df and "cycle_index" in df and _num(df["capacity_ah"]).notna().any():
        d = df.dropna(subset=["capacity_ah", "cycle_index"])
        first = d.groupby("cycle_index")["capacity_ah"].max().sort_index().iloc[:5]
        if len(first):
            cap = SpecItem(float(first.max()), "inferred from data", True,
                           "highest discharge capacity in the first 5 cycles used as the rated capacity")
    if cap.value is None:
        cap.note = "no capacity column and no rated capacity given"
        needs.append("rated_capacity_ah")

    # nominal voltage
    got = pick("nominal_voltage_v")
    nominal = SpecItem(float(got[0]), got[1], True) if got else \
        SpecItem(None, "default", True, "derived from the chemistry's typical cell voltage when needed")
    return SpecInference(chem, series, parallel, cap, nominal, needs)

