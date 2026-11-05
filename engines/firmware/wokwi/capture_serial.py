"""Run the Wokwi project for 60 s and save the serial output to captured_serial.log (only with wokwi-cli + token)."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
cli = shutil.which("wokwi-cli")
if not cli or not os.environ.get("WOKWI_CLI_TOKEN"):
    print("skipped: needs wokwi-cli and WOKWI_CLI_TOKEN")
    sys.exit(0)
sys.exit(subprocess.run([cli, str(HERE), "--timeout", "60000", "--serial-log-file", str(HERE / "captured_serial.log")]).returncode)
