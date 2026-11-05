"""Provenance tags. Every number in a report is wrapped by `tag()`.

measured  - read or directly derived from measured data
synthetic - read or directly derived from synthetic or simulated data
modelled  - output of a fitted or physics model
assumed   - a literature or configuration constant
"""

from __future__ import annotations

from typing import Any, Literal

Provenance = Literal["measured", "modelled", "assumed", "synthetic"]
PROVENANCES: tuple[str, ...] = ("measured", "modelled", "assumed", "synthetic")
PROJECTED_LABEL = "Projected (physics model)"


def tag(
    value: float | int | None,
    provenance: Provenance,
    unit: str | None = None,
    note: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    if provenance not in PROVENANCES:
        raise ValueError(f"unknown provenance {provenance!r}")
    out: dict[str, Any] = {
        "value": None if value is None else _clean(value),
        "provenance": provenance,
    }
    if unit:
        out["unit"] = unit
    if note:
        out["note"] = note
    out.update(extra)
    return out


def _clean(v: float | int) -> float | int:
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    f = float(v)
    return round(f, 6) if abs(f) < 1e9 else f


def data_provenance_tag(data_provenance: str) -> Provenance:
    """Provenance of numbers read from a bundle. Simulated data is never 'measured'."""
    return "measured" if data_provenance == "measured" else "synthetic"


# Integer values under these keys are bookkeeping (row counts, indices), not quantities,
# and are exempt from tagging. Every float, and every other integer, must be tagged.
BOOKKEEPING_KEYS = frozenset(
    {"row", "rows", "count", "n", "seed", "index", "indices", "schema_version", "first_rows",
     "year", "cycle_index", "duplicates", "non_monotonic_steps", "gaps"}
)


def _is_bookkeeping(key: str) -> bool:
    return (key in BOOKKEEPING_KEYS or key.startswith("n_") or key.endswith("_rows")
            or key.endswith("_run"))


def untagged_numbers(obj: Any, path: str = "$") -> list[str]:
    """Return JSON paths of numbers that are not wrapped in a provenance tag."""
    bad: list[str] = []
    if isinstance(obj, dict):
        if "provenance" in obj and ("value" in obj or "values" in obj):
            return bad  # everything inside a tagged dict shares its provenance
        for k, v in obj.items():
            p = f"{path}.{k}"
            if isinstance(v, bool):
                continue
            if isinstance(v, int | float):
                if _is_bookkeeping(k) and isinstance(v, int):
                    continue
                bad.append(p)
            else:
                bad.extend(untagged_numbers(v, p))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, int | float) and not isinstance(v, bool):
                if not _is_bookkeeping(path.rsplit(".", 1)[-1]):
                    bad.append(f"{path}[{i}]")
            else:
                bad.extend(untagged_numbers(v, f"{path}[{i}]"))
    return bad
