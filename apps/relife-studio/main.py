"""ReLife BMS application launcher with a useful missing-dependency message."""
import sys

missing = []
for module, package in (("PySide6", "PySide6"), ("duckdb", "duckdb")):
    try:
        __import__(module)
    except ImportError:
        missing.append(package)
if missing:
    print(f"Missing: {', '.join(missing)}. Install dependencies with: python -m pip install -r requirements.txt")
    raise SystemExit(1)

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

try:
    from app_ui import main
except Exception as exc:
    print(f"ReLife interface failed to load: {exc}")
    raise SystemExit(1)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, "ReLife stopped", f"The app encountered an error:\n{exc}")
        raise SystemExit(1)
