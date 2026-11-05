"""Colours and the application style sheet. Every colour in the UI comes from here."""

SURFACE = "#fcfcfb"
PAGE = "#f4f4f1"
SIDEBAR = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
BORDER = "#e1e0d9"
ACCENT = "#2a78d6"
ACCENT_HOVER = "#256abf"
ACCENT_PRESSED = "#1c5cab"
ACCENT_WASH = "#e8f1fb"

# Chart series, in fixed order. Slots 1 and 2 stay distinguishable with colour blindness.
SERIES_1 = "#2a78d6"
SERIES_2 = "#eb6834"

# Status colours always appear beside a glyph and a label, never alone.
STATUS = {
    "good": ("#0ca30c", "✓"),
    "warning": ("#fab219", "!"),
    "serious": ("#ec835a", "!"),
    "critical": ("#d03b3b", "×"),
    "neutral": (MUTED, "•"),
    "info": (ACCENT, "i"),
}

# Wire colour and line style by net type. The style means colour isn't the only signal.
NET_STYLES = {
    "power": ("#e34948", "solid", "Power"),
    "sense": ("#2a78d6", "dash", "Sensing"),
    "signal": ("#6250d6", "dot", "Signal"),
    "control": ("#008300", "dashdot", "Control"),
    "isolated": ("#eb6834", "dashdotdot", "Isolated"),
}
# Which net colour marks each part kind on the circuit canvas.
PART_GROUPS = {
    "battery": "power", "fuse": "power", "switch": "power", "connector": "power", "precharge": "power", "shunt": "power",
    "afe": "sense", "thermistor": "sense", "voltmeter": "sense", "balance": "sense",
    "mcu": "control", "driver": "control",
    "isolation": "isolated", "supply": "isolated",
}

STYLE_SHEET = f"""
* {{ font-family: "Segoe UI", system-ui, sans-serif; font-size: 13px; color: {INK}; }}
QMainWindow, QDialog, QWidget#page, QWidget#pageBody, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {PAGE}; }}
QLabel {{ background: transparent; }}
QLabel#pageTitle {{ font-size: 22px; font-weight: 600; }}
QLabel#pageSubtitle, QLabel#caption, QLabel#kpiLabel {{ color: {INK_SECONDARY}; }}
QLabel#sectionTitle {{ font-size: 14px; font-weight: 600; }}
QLabel#kpiValue {{ font-size: 24px; font-weight: 600; }}
QLabel#appTitle {{ font-size: 16px; font-weight: 700; }}

QFrame#sidebar {{ background: {SIDEBAR}; border: 0; border-right: 1px solid {BORDER}; }}
QPushButton#nav {{
    background: transparent; border: 0; border-radius: 6px; padding: 9px 12px; text-align: left; font-weight: 500;
    color: {INK_SECONDARY};
}}
QPushButton#nav:hover {{ background: {PAGE}; }}
QPushButton#nav:checked {{ background: {ACCENT_WASH}; color: {ACCENT_PRESSED}; font-weight: 600; }}

QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; }}
QFrame#banner {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; }}

QPushButton {{
    background: {SURFACE}; border: 1px solid {AXIS}; border-radius: 6px; padding: 7px 14px; font-weight: 500;
}}
QPushButton:hover {{ background: {PAGE}; }}
QPushButton:pressed {{ background: {GRID}; }}
QPushButton:disabled {{ color: {MUTED}; background: {PAGE}; border-color: {BORDER}; }}
QPushButton#primary {{ background: {ACCENT}; color: white; border: 1px solid {ACCENT}; font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton#primary:pressed {{ background: {ACCENT_PRESSED}; border-color: {ACCENT_PRESSED}; }}
QPushButton#primary:disabled {{ background: {GRID}; border-color: {GRID}; color: {MUTED}; }}
QToolButton#disclosure {{ background: transparent; border: 0; font-weight: 600; padding: 2px 0; }}

QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{
    background: {SURFACE}; border: 1px solid {AXIS}; border-radius: 6px; padding: 6px 8px; min-height: 18px;
    selection-background-color: {ACCENT}; selection-color: white;
}}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus {{ border: 1px solid {ACCENT}; }}
/* A spin box contains a line edit, which would otherwise get a second border and padding. */
QDoubleSpinBox QLineEdit, QSpinBox QLineEdit {{ background: transparent; border: 0; padding: 0 0 0 8px; min-height: 0; }}
/* Hide the arrows here. setButtonSymbols(NoButtons) with a style sheet shrinks the editor to 1 px. */
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button, QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: 0; }}
QComboBox::drop-down {{ border: 0; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE}; border: 1px solid {BORDER}; selection-background-color: {ACCENT_WASH};
    selection-color: {INK}; outline: 0;
}}

QTableView {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; gridline-color: transparent;
    selection-background-color: {ACCENT_WASH}; selection-color: {INK}; outline: 0;
}}
QTableView::item {{ padding: 0 8px; border-bottom: 1px solid {GRID}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: {SURFACE}; color: {INK_SECONDARY}; border: 0; border-bottom: 1px solid {AXIS};
    padding: 7px 8px; font-weight: 600;
}}

QTabWidget::pane {{ border: 0; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent; padding: 8px 14px; color: {INK_SECONDARY}; border: 0; border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {INK}; font-weight: 600; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: {INK}; }}

QProgressBar {{ background: {GRID}; border: 0; border-radius: 2px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}
QSplitter::handle {{ background: transparent; }}
QGraphicsView {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {AXIS}; border-radius: 4px; min-height: 28px; margin: 1px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {AXIS}; border-radius: 4px; min-width: 28px; margin: 1px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: 0; width: 0; height: 0; }}
QToolTip {{ background: {SURFACE}; color: {INK}; border: 1px solid {AXIS}; padding: 4px; }}
"""
