"""Reusable interface parts: cards, status badges, tables, charts and background tasks."""
from __future__ import annotations

import html
import math
from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Any, Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPointF, QRectF, QRunnable, QThreadPool, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QScrollArea, QSizePolicy, QTableView,
    QToolButton, QVBoxLayout, QWidget,
)

import theme

UNKNOWN = "Unknown"


def fmt(value: Any, unit: str = "", digits: int | None = None) -> str:
    """Show a value with its unit, or Unknown. Zero is a real value and is shown as zero."""
    if value is None or value == "":
        return UNKNOWN
    if isinstance(value, float):
        text = f"{value:.{digits}f}" if digits is not None else f"{value:g}"
    else:
        text = str(value)
    return f"{text} {unit}".strip()


def safe_link(url: str) -> str:
    """A clickable link, but only for web addresses. Imported files can contain any text."""
    if url.lower().startswith(("https://", "http://")):
        escaped = html.escape(url, quote=True)
        return f'<a href="{escaped}">{escaped}</a>'
    return html.escape(url)


# ---------------------------------------------------------------- background tasks

_running_tasks: set = set()


class _TaskSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any], signals: _TaskSignals):
        super().__init__()
        self.fn = fn
        self.signals = signals

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:  # Reported to the user by the callback, on the UI thread.
            self.signals.failed.emit(str(exc))
        else:
            self.signals.done.emit(result)


class _Receiver(QObject):
    """Lives on the UI thread, so results reach the callbacks there and not on the worker."""

    def __init__(self, on_done, on_error):
        super().__init__()
        self.on_done = on_done
        self.on_error = on_error

    @Slot(object)
    def done(self, result) -> None:
        _running_tasks.discard(self)
        self.on_done(result)

    @Slot(str)
    def failed(self, message: str) -> None:
        _running_tasks.discard(self)
        self.on_error(message)


def run_async(fn: Callable[[], Any], on_done: Callable[[Any], None], on_error: Callable[[str], None]) -> None:
    """Run slow work off the UI thread, so the window stays responsive."""
    receiver = _Receiver(on_done, on_error)
    signals = _TaskSignals(receiver)
    signals.done.connect(receiver.done, Qt.ConnectionType.QueuedConnection)
    signals.failed.connect(receiver.failed, Qt.ConnectionType.QueuedConnection)
    _running_tasks.add(receiver)
    QThreadPool.globalInstance().start(_Task(fn, signals))


# ---------------------------------------------------------------- layout parts


def label(text: str = "", name: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def fit_combo(combo: QComboBox, characters: int = 24) -> QComboBox:
    """Stop a long item from forcing the whole page wider than the window."""
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(characters)
    combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return combo


class Card(QFrame):
    """A white panel with an optional title."""

    def __init__(self, title: str = "", parent: QWidget | None = None, spacing: int = 10):
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 14)
        self.body.setSpacing(spacing)
        if title:
            self.body.addWidget(label(title, "sectionTitle"))


class Badge(QLabel):
    """A status: glyph plus words, so meaning never depends on colour alone."""

    def __init__(self, text: str = "", tone: str = "neutral", parent: QWidget | None = None):
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.set(text, tone)

    def set(self, text: str, tone: str = "neutral") -> None:
        self.tone = tone
        self.status_text = text
        colour, glyph = theme.STATUS.get(tone, theme.STATUS["neutral"])
        self.setText(f'<span style="color:{colour};font-weight:700">{glyph}</span>&nbsp;<b>{html.escape(text)}</b>')


class Banner(QFrame):
    """One line of important context, with a status glyph."""

    def __init__(self, text: str = "", tone: str = "info", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("banner")
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(10)
        self.glyph = QLabel()
        self.glyph.setTextFormat(Qt.TextFormat.RichText)
        self.glyph.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.message = label("", wrap=True)
        self.message.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row.addWidget(self.glyph)
        row.addWidget(self.message, 1)
        self.set(text, tone)

    def set(self, text: str, tone: str = "info") -> None:
        colour, glyph = theme.STATUS.get(tone, theme.STATUS["info"])
        self.glyph.setText(f'<span style="color:{colour};font-weight:700;font-size:14px">{glyph}</span>')
        self.message.setText(text)


class KpiTile(QFrame):
    """A headline figure with a label and a caption saying where it came from."""

    def __init__(self, title: str, value: str = "—", caption: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(2)
        layout.addWidget(label(title, "kpiLabel"))
        self.value = label(value, "kpiValue")
        layout.addWidget(self.value)
        self.caption = label(caption, "caption", wrap=True)
        layout.addWidget(self.caption)
        layout.addStretch(1)

    def set(self, value: str, caption: str | None = None) -> None:
        self.value.setText(value)
        if caption is not None:
            self.caption.setText(caption)


class Disclosure(QWidget):
    """A heading that shows or hides details, to keep long explanations out of the way."""

    def __init__(self, title: str, content: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.button = QToolButton()
        self.button.setObjectName("disclosure")
        self.button.setText(title)
        self.button.setCheckable(True)
        self.button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.button.setArrowType(Qt.ArrowType.RightArrow)
        self.button.toggled.connect(self._toggle)
        self.content = content
        content.setVisible(False)
        layout.addWidget(self.button)
        layout.addWidget(content)

    def _toggle(self, opened: bool) -> None:
        self.button.setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow)
        self.content.setVisible(opened)


class Page(QWidget):
    """A page with a title, a subtitle, optional action buttons and a body."""

    def __init__(self, title: str, subtitle: str = "", scroll: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        container = QWidget()
        container.setObjectName("pageBody")
        self.content = QVBoxLayout(container)
        self.content.setContentsMargins(28, 22, 28, 24)
        self.content.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(8)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label(title, "pageTitle"))
        if subtitle:
            titles.addWidget(label(subtitle, "pageSubtitle", wrap=True))
        header.addLayout(titles, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        header.addLayout(self.actions)
        self.content.addLayout(header)

        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            area.setWidget(container)
            outer.addWidget(area)
        else:
            outer.addWidget(container)


# ---------------------------------------------------------------- tables


@dataclass
class Column:
    """value is what the column sorts by. text, if given, is what it shows."""
    title: str
    value: Callable[[Any], Any]
    text: Callable[[Any], str] | None = None


class RowsModel(QAbstractTableModel):
    """A table model over a Python list. Rows draw on demand, so long lists stay fast."""

    def __init__(self, columns: list[Column], parent: QObject | None = None):
        super().__init__(parent)
        self.columns = columns
        self.rows: list = []
        self._sort: tuple[int, Qt.SortOrder] | None = None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.columns[section].title
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None
        column = self.columns[index.column()]
        row = self.rows[index.row()]
        if column.text is not None:
            return column.text(row)
        value = column.value(row)
        return "" if value is None else str(value)

    def set_rows(self, rows: list) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        if self._sort is not None:
            self._apply_sort(*self._sort)
        self.endResetModel()

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        self._sort = (column, order)
        self.layoutAboutToBeChanged.emit()
        self._apply_sort(column, order)
        self.layoutChanged.emit()

    def _apply_sort(self, column: int, order: Qt.SortOrder) -> None:
        getter = self.columns[column].value

        def key(row):
            value = getter(row)
            # Numbers sort as numbers. Unknown values stay at the bottom in both directions.
            if value is None or value == "":
                return (1, 0, "")
            if isinstance(value, (int, float)):
                return (0, value, "")
            return (0, 0, str(value).casefold())

        known = [row for row in self.rows if key(row)[0] == 0]
        blank = [row for row in self.rows if key(row)[0] == 1]
        known.sort(key=key, reverse=order == Qt.SortOrder.DescendingOrder)
        self.rows = known + blank


def make_table(columns: list[Column], stretch: int | None = None) -> tuple[QTableView, RowsModel]:
    model = RowsModel(columns)
    view = QTableView()
    view.setModel(model)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setShowGrid(False)
    view.setSortingEnabled(True)
    view.setWordWrap(False)
    view.verticalHeader().setVisible(False)
    view.verticalHeader().setDefaultSectionSize(34)
    view.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    header = view.horizontalHeader()
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setHighlightSections(False)
    header.setSortIndicatorShown(True)
    header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
    if stretch is not None:
        header.setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
    return view, model


# ---------------------------------------------------------------- charts


@dataclass
class Series:
    label: str
    color: str
    xs: list[float] = field(default_factory=list)
    ys: list[float | None] = field(default_factory=list)


def nice_ticks(low: float, high: float, count: int = 4) -> list[float]:
    """Round axis values, such as 340, 360, 380, that span the range."""
    span = high - low
    if span <= 0:
        return [low]
    raw = span / count
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next((m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw), 10 * magnitude)
    first = math.floor(low / step) * step
    ticks = []
    value = first
    while value < high + step * 0.5 and len(ticks) < 12:
        ticks.append(round(value, 10))
        value += step
    return ticks


class LineChart(QWidget):
    """A small line chart with one y axis, gridlines and a hover readout.

    Painted directly rather than through a graphics scene, so a live update only costs a
    repaint of the line. Very long series are thinned to the chart's pixel width.
    """

    LEFT_MIN = 44

    def __init__(self, title: str, unit: str = "", x_format: Callable[[float], str] | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.title = title
        self.unit = unit
        self.x_format = x_format or (lambda x: f"{x:g}")
        self.series: list[Series] = []
        self._bounds = None
        self._paths: dict[int, QPainterPath] = {}
        self._path_size = None
        self._hover_x: float | None = None
        self.setMinimumHeight(190)
        self.setMouseTracking(True)
        self.setAccessibleName(f"{title} chart")
        self._title_font = QFont(self.font())
        self._title_font.setPixelSize(13)
        self._title_font.setWeight(QFont.Weight.DemiBold)
        self._small_font = QFont(self.font())
        self._small_font.setPixelSize(11)

    def set_series(self, series: list[Series]) -> None:
        self.series = series
        self.data_changed()

    def data_changed(self) -> None:
        self._bounds = None
        self._paths = {}
        self.update()

    def _compute_bounds(self):
        if self._bounds is None:
            xs = [x for s in self.series for x in s.xs]
            ys = [y for s in self.series for y in s.ys if y is not None]
            if not xs or not ys:
                return None
            y_low, y_high = min(ys), max(ys)
            if y_low == y_high:
                pad = abs(y_low) * 0.05 or 1.0
                y_low, y_high = y_low - pad, y_high + pad
            ticks = nice_ticks(y_low, y_high)
            self._bounds = (min(xs), max(xs), min(ticks[0], y_low), max(ticks[-1], y_high), ticks)
        return self._bounds

    def _plot_rect(self, ticks: list[float]) -> QRectF:
        metrics = QFontMetrics(self._small_font)
        left = max(self.LEFT_MIN, max(metrics.horizontalAdvance(f"{t:g}") for t in ticks) + 14)
        return QRectF(left, 34, max(self.width() - left - 14, 10), max(self.height() - 34 - 26, 10))

    def _build_path(self, s: Series, plot: QRectF, bounds) -> QPainterPath:
        x_low, x_high, y_low, y_high, _ = bounds
        x_span = (x_high - x_low) or 1.0
        y_span = (y_high - y_low) or 1.0

        def to_point(x: float, y: float) -> QPointF:
            return QPointF(plot.left() + (x - x_low) / x_span * plot.width(),
                           plot.bottom() - (y - y_low) / y_span * plot.height())

        points = list(zip(s.xs, s.ys))
        if len(points) > plot.width() * 2:
            # Keep each pixel column's lowest and highest values, so spikes stay visible.
            buckets: dict[int, list] = {}
            for x, y in points:
                if y is None:
                    continue
                column = int((x - x_low) / x_span * plot.width())
                bucket = buckets.get(column)
                if bucket is None:
                    buckets[column] = [(x, y), (x, y)]
                else:
                    if y < bucket[0][1]:
                        bucket[0] = (x, y)
                    if y > bucket[1][1]:
                        bucket[1] = (x, y)
            points = [p for column in sorted(buckets) for p in sorted(set(buckets[column]))]

        path = QPainterPath()
        pen_down = False
        for x, y in points:
            if y is None:
                pen_down = False  # A gap in the data stays a visible gap in the line.
                continue
            point = to_point(x, y)
            if pen_down:
                path.lineTo(point)
            else:
                path.moveTo(point)
                pen_down = True
        return path

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(theme.SURFACE))
        painter.setFont(self._title_font)
        painter.setPen(QColor(theme.INK))
        heading = f"{self.title} ({self.unit})" if self.unit else self.title
        painter.drawText(QRectF(2, 2, self.width() - 4, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, heading)
        self._draw_legend(painter)

        bounds = self._compute_bounds()
        painter.setFont(self._small_font)
        if bounds is None:
            painter.setPen(QColor(theme.INK_SECONDARY))
            painter.drawText(self.rect().adjusted(0, 24, 0, 0), Qt.AlignmentFlag.AlignCenter, "No data yet")
            return

        x_low, x_high, y_low, y_high, ticks = bounds
        plot = self._plot_rect(ticks)
        y_span = (y_high - y_low) or 1.0
        for tick in ticks:
            if tick < y_low or tick > y_high:
                continue
            y = plot.bottom() - (tick - y_low) / y_span * plot.height()
            painter.setPen(QPen(QColor(theme.GRID), 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(QRectF(0, y - 8, plot.left() - 6, 16),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{tick:g}")
        painter.setPen(QPen(QColor(theme.AXIS), 1))
        painter.drawLine(plot.bottomLeft(), plot.bottomRight())

        painter.setPen(QColor(theme.MUTED))
        steps = max(1, min(4, int(plot.width() // 110)))
        x_span = x_high - x_low
        positions = [x_low] if x_span == 0 else [x_low + x_span * i / steps for i in range(steps + 1)]
        # Label real data points, so an axis reads 08:15 and not an in-between 08:13.
        known_xs = self.series[0].xs if self.series else []
        if known_xs:
            positions = [known_xs[min(bisect_left(known_xs, x), len(known_xs) - 1)] for x in positions]
        for i, x in enumerate(positions):
            px = plot.left() + (0 if x_span == 0 else (x - x_low) / x_span * plot.width())
            align = Qt.AlignmentFlag.AlignLeft if i == 0 else (Qt.AlignmentFlag.AlignRight if i == len(positions) - 1 else Qt.AlignmentFlag.AlignHCenter)
            box = QRectF(px, plot.bottom() + 4, 100, 18) if i == 0 else (
                QRectF(px - 100, plot.bottom() + 4, 100, 18) if i == len(positions) - 1 else QRectF(px - 50, plot.bottom() + 4, 100, 18))
            painter.drawText(box, align | Qt.AlignmentFlag.AlignVCenter, self.x_format(x))

        size = (self.width(), self.height())
        if self._path_size != size:
            self._paths = {}
            self._path_size = size
        for i, s in enumerate(self.series):
            path = self._paths.get(i)
            if path is None:
                path = self._paths[i] = self._build_path(s, plot, bounds)
            painter.setPen(QPen(QColor(s.color), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            known = [(x, y) for x, y in zip(s.xs, s.ys) if y is not None]
            if len(known) == 1:  # A single reading has no line, so it needs a marker to be seen.
                x = plot.left() if x_span == 0 else plot.left() + (known[0][0] - x_low) / x_span * plot.width()
                y = plot.bottom() - (known[0][1] - y_low) / y_span * plot.height()
                painter.setBrush(QColor(s.color))
                painter.setPen(QPen(QColor(theme.SURFACE), 2))
                painter.drawEllipse(QPointF(x, y), 5, 5)

        self._draw_hover(painter, plot, bounds)

    def _draw_legend(self, painter: QPainter) -> None:
        if len(self.series) < 2:
            return
        painter.setFont(self._small_font)
        metrics = painter.fontMetrics()
        x = self.width() - 4
        for s in reversed(self.series):
            width = metrics.horizontalAdvance(s.label)
            x -= width
            painter.setPen(QColor(theme.INK_SECONDARY))
            painter.drawText(
                QRectF(x, 3, width, 18),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextDontClip,
                s.label,
            )
            x -= 22
            painter.setPen(QPen(QColor(s.color), 2))
            painter.drawLine(QPointF(x, 12), QPointF(x + 16, 12))
            x -= 12

    def _draw_hover(self, painter: QPainter, plot: QRectF, bounds) -> None:
        if self._hover_x is None or not plot.contains(QPointF(self._hover_x, plot.center().y())):
            return
        x_low, x_high, y_low, y_high, _ = bounds
        x_span = (x_high - x_low) or 1.0
        y_span = (y_high - y_low) or 1.0
        target = x_low + (self._hover_x - plot.left()) / plot.width() * x_span
        lines = []
        marks = []
        nearest_x = None
        for s in self.series:
            if not s.xs:
                continue
            i = min(bisect_left(s.xs, target), len(s.xs) - 1)
            if i > 0 and abs(s.xs[i - 1] - target) < abs(s.xs[i] - target):
                i -= 1
            nearest_x = s.xs[i]
            if s.ys[i] is None:
                continue
            lines.append(f"{s.label}: {s.ys[i]:.2f} {self.unit}".rstrip())
            marks.append((s.color, plot.left() + (s.xs[i] - x_low) / x_span * plot.width(),
                          plot.bottom() - (s.ys[i] - y_low) / y_span * plot.height()))
        if nearest_x is None or not lines:
            return
        cross = plot.left() + (nearest_x - x_low) / x_span * plot.width()
        painter.setPen(QPen(QColor(theme.AXIS), 1))
        painter.drawLine(QPointF(cross, plot.top()), QPointF(cross, plot.bottom()))
        for colour, mx, my in marks:
            painter.setBrush(QColor(colour))
            painter.setPen(QPen(QColor(theme.SURFACE), 2))
            painter.drawEllipse(QPointF(mx, my), 4.5, 4.5)

        painter.setFont(self._small_font)
        metrics = painter.fontMetrics()
        rows = [self.x_format(nearest_x), *lines]
        width = max(metrics.horizontalAdvance(row) for row in rows) + 16
        height = len(rows) * (metrics.height() + 1) + 10
        box_x = cross + 10 if cross + 10 + width < self.width() else cross - width - 10
        box = QRectF(box_x, plot.top() + 2, width, height)
        painter.setBrush(QColor(theme.SURFACE))
        painter.setPen(QPen(QColor(theme.AXIS), 1))
        painter.drawRoundedRect(box, 4, 4)
        painter.setPen(QColor(theme.INK))
        y = box.top() + 5
        for row in rows:
            painter.drawText(QRectF(box.left() + 8, y, width - 12, metrics.height()),
                             Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextDontClip, row)
            y += metrics.height() + 1

    def mouseMoveEvent(self, event) -> None:
        self._hover_x = event.position().x()
        self.update()

    def leaveEvent(self, event) -> None:
        self._hover_x = None
        self.update()
