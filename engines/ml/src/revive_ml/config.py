"""YAML configuration loading."""

from __future__ import annotations

from functools import cache
from typing import Any

import yaml

from revive_ml.paths import config_path


@cache
def load(name: str) -> dict[str, Any]:
    with open(config_path(name), encoding="utf-8") as fh:
        return yaml.safe_load(fh)
