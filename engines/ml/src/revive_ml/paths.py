"""Filesystem locations used by the engine."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "configs"
REPORTS_DIR = REPO_ROOT / "reports"
MODELS_DIR = REPO_ROOT / "models"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"


def cache_dir() -> Path:
    """Raw-download cache. Kept outside the repo because the repo lives in OneDrive."""
    env = os.environ.get("REVIVE_ML_CACHE")
    if env:
        return Path(env)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".cache")
    return Path(base) / "revive-tery-ml" / "cache"


def config_path(name: str) -> Path:
    return CONFIG_DIR / name
