"""Understand an uploaded table: which column is voltage, current, time, capacity ...?

Two signals are combined for every (column, field) pair:
  header  a small trained classifier (char n-gram TF-IDF + logistic regression, trained at first use from
          configs/intelligence.yaml) says how likely the column NAME means the field;
  values  a plausibility check on the numbers themselves (range, monotonic time, integer cycle counts ...).
A column is mapped only when both agree enough. Columns the model is unsure about are returned as
unmapped with their best guess, never forced into the data. Units are converted only when the header
states them (mV, mA, mAh, degF, K, ms, min, h) or a value rule is logged; every conversion is reported.
Current is never sign-flipped.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

from revive_ml.config import load

STANDARD_FIELDS = ("battery_id", "timestamp_utc", "test_time_s", "cycle_index", "voltage_v",
                   "current_a", "temperature_c", "capacity_ah", "soc_pct")
NUMERIC_FIELDS = ("test_time_s", "voltage_v", "current_a", "temperature_c", "capacity_ah", "soc_pct")
OTHER = "other"


# ---------------------------------------------------------------------------------------------
# header model
# ---------------------------------------------------------------------------------------------

def normalise_header(name: Any) -> str:
    """'PackVoltage (V)' -> 'pack voltage v'; 'Temp [°C]' -> 'temp c'."""
    s = str(name).strip().replace("°", "").replace("%", " pct ")
    s = re.sub(r"(?<=[a-z])(?=[A-Z][a-z])", " ", s)           # camelCase, but keep 'mV' together
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


_PREFIXES = ("", "pack ", "cell ", "batt ", "battery ", "measured ", "max ", "avg ")
_PLAIN_FIELDS = ("battery_id", "timestamp_utc", "cycle_index")      # no prefix/unit augmentation


def _variants(phrase: str, fld: str, units: list[str]) -> set[str]:
    base = normalise_header(phrase)
    out = {base, base.replace(" ", "")}
    if fld in _PLAIN_FIELDS or fld == OTHER:
        return out
    for p in _PREFIXES:
        out.add((p + base).strip())
    for u in units:
        out.add(f"{base} {u}")
        out.add(f"{base}{u}")
    return out


class HeaderClassifier:
    """phrase lexicon -> probability that a header means each label (plus an 'other' class)."""

    def __init__(self, lexicon: dict[str, list[str]], other: list[str], unit_words: dict[str, list[str]] | None = None):
        unit_words = unit_words or {}
        texts: list[str] = []
        labels: list[str] = []
        for label, phrases in lexicon.items():
            for phrase in phrases:
                for v in _variants(phrase, label, unit_words.get(label, [])):
                    texts.append(v)
                    labels.append(label)
        for phrase in other:
            for v in _variants(phrase, OTHER, []):
                texts.append(v)
                labels.append(OTHER)
        self.pipeline = make_pipeline(
            TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True),
            LogisticRegression(C=25.0, max_iter=2000, class_weight="balanced"),
        )
        self.pipeline.fit(texts, labels)
        self.classes = list(self.pipeline.classes_)
        self.n_training_phrases = len(texts)

    def proba(self, header: Any) -> dict[str, float]:
        text = normalise_header(header)
        if not text:
            return {c: (1.0 if c == OTHER else 0.0) for c in self.classes}
        p = self.pipeline.predict_proba([text])[0]
        return dict(zip(self.classes, (float(x) for x in p)))


@lru_cache(maxsize=1)
def column_classifier() -> HeaderClassifier:
    cfg = load("intelligence.yaml")
    return HeaderClassifier({k: v["phrases"] for k, v in cfg["fields"].items()}, cfg["other"]["phrases"],
                            cfg.get("unit_words"))


# ---------------------------------------------------------------------------------------------
# units
# ---------------------------------------------------------------------------------------------

_KNOWN_UNITS = {"mv", "v", "kv", "ma", "a", "ka", "mah", "ah", "c", "degc", "celsius", "f", "degf", "fahrenheit",
                "k", "kelvin", "pct", "percent", "ms", "s", "sec", "min", "h", "hr"}


def unit_hint(raw_header: Any) -> str | None:
    """The unit a header states: 'Voltage (mV)' -> 'mv', 'temp_F' -> 'f', 'Time' -> None."""
    s = str(raw_header).strip().lower().replace("°", "").replace("%", "pct")
    m = re.search(r"[\(\[]\s*([a-z]+)\s*[\)\]]\s*$", s) or re.search(r"[\(\[]\s*([a-z]+)\s*[\)\]]", s)
    if m and m.group(1) in _KNOWN_UNITS:
        return m.group(1)
    tail = re.split(r"[\s_\-/]+", s)[-1] if re.search(r"[\s_\-/]", s) else None
    if tail in _KNOWN_UNITS:
        return tail
    # camelCase like 'voltageMV' / 'tempF'
    m = re.search(r"[a-z]([A-Z]{1,2}[a-z]?)$", str(raw_header).strip().replace("°", ""))
    if m and m.group(1).lower() in _KNOWN_UNITS:
        return m.group(1).lower()
    return None


@dataclass
class Conversion:
    unit_from: str
    unit_to: str
    factor: float = 1.0
    offset: float = 0.0          # value_to = (value_from + offset) * factor
    basis: str = "header states the unit"

    def apply(self, x: pd.Series) -> pd.Series:
        return (x + self.offset) * self.factor


_TO_UNIT = {"voltage_v": "V", "current_a": "A", "temperature_c": "degC", "capacity_ah": "Ah",
            "soc_pct": "%", "test_time_s": "s"}
_SCALES = {
    "voltage_v": {"mv": 1e-3, "kv": 1e3},
    "current_a": {"ma": 1e-3, "ka": 1e3},
    "capacity_ah": {"mah": 1e-3},
    "test_time_s": {"ms": 1e-3, "min": 60.0, "h": 3600.0, "hr": 3600.0},
}


def plan_conversion(fld: str, raw_header: Any, num: pd.Series) -> Conversion | None:
    """Decide the unit conversion for one mapped numeric column, or None when none is needed."""
    unit = unit_hint(raw_header)
    if fld in _SCALES and unit in _SCALES[fld]:
        return Conversion(unit, _TO_UNIT[fld], factor=_SCALES[fld][unit])
    if fld == "temperature_c":
        if unit in ("f", "degf", "fahrenheit"):
            return Conversion("degF", "degC", factor=5 / 9, offset=-32.0)
        if unit in ("k", "kelvin"):
            return Conversion("K", "degC", offset=-273.15)
    if fld == "soc_pct" and unit not in ("pct", "percent"):
        v = num.dropna()
        if len(v) and v.min() >= 0 and v.max() <= 1.0 and v.nunique() > 2:
            return Conversion("fraction", "%", factor=100.0, basis="values all within 0-1 and the header gives no unit")
    return None


# ---------------------------------------------------------------------------------------------
# value plausibility
# ---------------------------------------------------------------------------------------------

def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _mono(v: pd.Series) -> float:
    d = v.diff().dropna()
    return float((d >= 0).mean()) if len(d) else 1.0


def value_fit(fld: str, raw: pd.Series, conv: Conversion | None) -> float:
    """0..1: do the values look like this field? (Never negative evidence by itself: see mapping rules.)"""
    s = raw.dropna()
    if s.empty:
        return 0.0
    if fld == "battery_id":
        n = _num(s)
        if n.notna().mean() > 0.9 and (n % 1 != 0).any():
            return 0.0                                     # decimals: a measurement, not an identifier
        ratio = s.astype(str).nunique() / len(s)
        return 1.0 if ratio <= 0.5 else (0.5 if ratio <= 0.9 else 0.25)
    if fld == "timestamp_utc":
        n = _num(s)
        if n.notna().mean() > 0.9:                          # numeric: only an epoch counts
            med = float(n.median())
            return 0.9 if (1e9 <= med <= 4e9 or 1e12 <= med <= 4e12) else 0.0
        parsed = pd.to_datetime(s.astype(str), errors="coerce", utc=True)
        return 1.0 if parsed.notna().mean() >= 0.9 else float(parsed.notna().mean()) * 0.5
    n = _num(s)
    if n.notna().mean() < 0.9:
        return 0.0
    v = n.dropna()
    if conv is not None:
        v = conv.apply(v)
    q05, q95, med = (float(x) for x in v.quantile([0.05, 0.95, 0.5]))
    if fld == "test_time_s":
        if v.nunique() <= 1:
            return 0.3
        return 1.0 if (_mono(v) >= 0.95 and v.min() >= 0) else 0.3
    if fld == "cycle_index":
        if (v % 1 != 0).any():
            return 0.1
        if _mono(v) < 0.95:
            return 0.3
        return 1.0 if v.nunique() < 0.9 * len(v) else 0.5   # repeated values: cycles; all-distinct: row/time index
    if fld == "voltage_v":
        return 1.0 if (q05 >= 0.5 and q95 <= 1500) else 0.3
    if fld == "current_a":
        if max(abs(q05), abs(q95)) > 3000:
            return 0.2
        return 1.0 if v.std() > 0 else 0.6
    if fld == "temperature_c":
        return 1.0 if (q05 >= -50 and q95 <= 120) else 0.2
    if fld == "capacity_ah":
        return 1.0 if (med > 0 and q95 <= 10000) else 0.3
    if fld == "soc_pct":
        return 1.0 if (q05 >= -1 and q95 <= 101) else 0.2
    return 0.5


# ---------------------------------------------------------------------------------------------
# mapping
# ---------------------------------------------------------------------------------------------

@dataclass
class ColumnMatch:
    column: str
    field: str
    score: float
    header_prob: float
    value_fit: float
    conversion: Conversion | None = None
    runner_up: str | None = None


@dataclass
class MappingResult:
    source: str
    matches: list[ColumnMatch] = field(default_factory=list)
    unmapped: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    is_telemetry: bool = False

    @property
    def mapping(self) -> dict[str, str]:
        return {m.column: m.field for m in self.matches}

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source, "is_telemetry": self.is_telemetry, "warnings": self.warnings,
            "mapped": [{"column": m.column, "field": m.field, "score": round(m.score, 3),
                        "header_prob": round(m.header_prob, 3), "value_fit": round(m.value_fit, 3),
                        "conversion": asdict(m.conversion) if m.conversion else None} for m in self.matches],
            "unmapped": self.unmapped,
        }


def map_columns(df: pd.DataFrame, source: str = "") -> MappingResult:
    cfg = load("intelligence.yaml")["mapping"]
    clf = column_classifier()
    sample = df.head(int(cfg["sample_rows"]))
    res = MappingResult(source=source)
    candidates: list[tuple[float, str, str, float, float, Conversion | None]] = []
    best_other: dict[str, tuple[str, float]] = {}
    for col in df.columns:
        proba = clf.proba(col)
        best_other[str(col)] = max(proba.items(), key=lambda kv: kv[1])
        for fld in STANDARD_FIELDS:
            hp = proba.get(fld, 0.0)
            if hp < 0.05:
                continue
            raw = sample[col]
            conv = plan_conversion(fld, col, _num(raw)) if fld in NUMERIC_FIELDS else None
            vf = value_fit(fld, raw, conv)
            score = cfg["header_weight"] * hp + (1 - cfg["header_weight"]) * vf
            candidates.append((score, str(col), fld, hp, vf, conv))
    used_cols: set[str] = set()
    used_fields: set[str] = set()
    for score, col, fld, hp, vf, conv in sorted(candidates, key=lambda c: -c[0]):
        if col in used_cols or fld in used_fields:
            continue
        if hp < cfg["min_header_prob"] or score < cfg["accept_score"] or vf < 0.5:
            continue
        res.matches.append(ColumnMatch(col, fld, score, hp, vf, conv))
        used_cols.add(col)
        used_fields.add(fld)
    for m in res.matches:
        alt = [c for c in candidates if c[1] == m.column and c[2] != m.field]
        m.runner_up = max(alt, key=lambda c: c[0])[2] if alt else None
    for col in df.columns:
        c = str(col)
        if c in used_cols:
            continue
        top_label, top_p = best_other[c]
        guess = max((x for x in candidates if x[1] == c), key=lambda x: x[0], default=None)
        res.unmapped.append({
            "column": c,
            "reason": ("recognised as a column that is not stored (e.g. ambient temperature, power, notes)"
                       if top_label == OTHER and top_p >= 0.5 else "not confident enough to map"),
            "best_guess": guess[2] if guess else None,
            "best_guess_score": round(guess[0], 3) if guess else None,
        })
    for m in res.matches:
        if m.conversion:
            res.warnings.append(f"{m.column}: converted {m.conversion.unit_from} -> {m.conversion.unit_to} "
                                f"({m.conversion.basis})")
    res.is_telemetry = "voltage_v" in {m.field for m in res.matches}
    if not res.is_telemetry:
        res.warnings.append("no voltage column was recognised, so this table is not treated as telemetry")
    return res


def standardise(df: pd.DataFrame, mapping: MappingResult, source: str) -> pd.DataFrame:
    """Apply the mapping: rename, convert recorded units, coerce types. Values are never invented."""
    out = pd.DataFrame(index=df.index)
    for m in mapping.matches:
        col = df[m.column]
        if m.field == "battery_id":
            out["battery_id"] = col.astype(str).str.strip()
        elif m.field == "timestamp_utc":
            n = _num(col)
            if n.notna().mean() > 0.9:
                unit = "ms" if float(n.median()) > 1e11 else "s"
                out["timestamp_utc"] = pd.to_datetime(n, unit=unit, utc=True, errors="coerce")
                mapping.warnings.append(f"{m.column}: numeric epoch read as {unit} since 1970 (UTC)")
            else:
                out["timestamp_utc"] = pd.to_datetime(col, utc=True, errors="coerce")
                if not col.astype(str).str.contains(r"Z|[+-]\d\d:?\d\d$", regex=True).any():
                    mapping.warnings.append(f"{m.column}: timestamps carry no time zone; read as UTC")
        elif m.field == "cycle_index":
            out["cycle_index"] = _num(col).astype("Int64")
        else:
            num = _num(col)
            bad = int(num.isna().sum() - col.isna().sum())
            if bad:
                mapping.warnings.append(f"{m.column}: {bad} non-numeric value(s) set to empty")
            out[m.field] = m.conversion.apply(num) if m.conversion else num
    if "battery_id" not in out:
        out["battery_id"] = Path(source.split("#")[0]).stem
        mapping.warnings.append("no battery id column; the file name is used as the battery id")
    out["source_file"] = source
    out["row_in_file"] = np.arange(len(out))
    return out
