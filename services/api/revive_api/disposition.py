"""Reuse / repurpose / recycle: an additive reading of the ML engine's decision text.

Reads config/decision_map.json (platform root). Engine logic and reports are never changed; this only
labels a decision in the problem statement's vocabulary.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import settings

DECISION_MAP_PATH = Path(settings.APP_ROOT) / "config" / "decision_map.json"
WORKLOADS_PATH = Path(settings.APP_ROOT) / "engines" / "ml" / "configs" / "workloads.yaml"


@lru_cache(maxsize=1)
def _decision_map() -> dict[str, Any]:
    return json.loads(DECISION_MAP_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _label_to_key() -> dict[str, str]:
    """Workload label -> key, so 'Second-Life: Low-speed EV' resolves to 'low_speed_ev'."""
    try:
        import yaml
        workloads = yaml.safe_load(WORKLOADS_PATH.read_text(encoding="utf-8")).get("workloads") or {}
    except (OSError, ImportError, AttributeError):
        return {}
    return {str(v.get("label", "")).strip().lower(): k for k, v in workloads.items() if isinstance(v, dict)}


def _application_key(decision: str, application: str | None) -> str | None:
    candidates = [application] if application else []
    if ":" in decision:
        candidates.append(decision.split(":", 1)[1])
    keys = _label_to_key()
    for c in candidates:
        c = str(c).strip()
        if c in keys.values():
            return c
        if c.lower() in keys:
            return keys[c.lower()]
    return None


def disposition(decision: str, application: str | None) -> dict[str, str]:
    """Map an engine decision (and its application) to {"code": ..., "label": ...}."""
    m = _decision_map()
    labels = m["labels"]
    decision = (decision or "").strip()
    for rule in m["rules"]:
        if not decision.startswith(rule["match_prefix"]):
            continue
        code = rule.get("disposition")
        if code is None:  # Second-Life: decided by the application
            key = _application_key(decision, application)
            if key in rule.get("application_keys_to_REUSE", []):
                code = "REUSE"
            elif key in rule.get("application_keys_to_REPURPOSE", []):
                code = "REPURPOSE"
            else:
                code = rule.get("default_disposition", "REPURPOSE")
        return {"code": code, "label": labels[code]}
    return {"code": "NO_DECISION", "label": labels["NO_DECISION"]}
