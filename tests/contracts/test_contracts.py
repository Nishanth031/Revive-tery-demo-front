"""pytest wrapper so `pytest tests` also guards the contracts and the registry."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_contracts_and_registry_are_consistent():
    res = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_contracts.py")],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
