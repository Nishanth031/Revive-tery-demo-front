"""Circuit Studio page: a draggable BMS schematic with live wires and a details panel."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGraphicsItem, QGraphicsPathItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView, QHBoxLayout,
    QLineEdit, QMessageBox, QPushButton, QWidget,
)
from shiboken6 import isValid

import theme
from app_state import AppState
from circuit_studio import PART_KINDS, CircuitDesign, Net, Part
from widgets import Card, Page, fit_combo, label

PART_WIDTH = 150
PART_HEIGHT = 72
SCENE_MARGIN = 30
PEN_STYLES = {
    "solid": Qt.PenStyle.SolidLine,
    "dash": Qt.PenStyle.DashLine,
    "dot": Qt.PenStyle.DotLine,
    "dashdot": Qt.PenStyle.DashDotLine,
    "dashdotdot": Qt.PenStyle.DashDotDotLine,
}


def _net_pen(net_type: str) -> QPen:
    colour, style, _ = theme.NET_STYLES.get(net_type, (theme.MUTED, "solid", ""))
    return QPen(QColor(colour), 2.5 if net_type == "power" else 1.75, PEN_STYLES[style])


class PartItem(QGraphicsRectItem):
    def __init__(self, part: Part, canvas: "CircuitCanvas"):
        super().__init__(0, 0, PART_WIDTH, PART_HEIGHT)
        self.part = part
        self.canvas = canvas
        self.setPos(part.x, part.y)
        self.setZValue(2)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(f"{part.ref}: {part.name}")

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.part.x = float(value.x())
            self.part.y = float(value.y())
            self.canvas.part_moved(self.part.ref)
        return super().itemChange(change, value)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        group = theme.PART_GROUPS.get(self.part.kind)
        stripe = theme.NET_STYLES[group][0] if group else theme.MUTED
        border = theme.ACCENT if self.isSelected() else theme.AXIS
        painter.setPen(QPen(QColor(border), 2 if self.isSelected() else 1))
        painter.setBrush(QColor(theme.SURFACE))
        painter.drawRoundedRect(rect, 6, 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(stripe))
        painter.drawRoundedRect(QRectF(rect.left() + 3, rect.top() + 8, 4, rect.height() - 16), 2, 2)
        ref_font = QFont(painter.font())
        ref_font.setPixelSize(13)
        ref_font.setWeight(QFont.Weight.DemiBold)
        # The canvas scales to fit the window, and hinted letters space badly when scaled.
        ref_font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        painter.setFont(ref_font)
        painter.setPen(QColor(theme.INK))
        painter.drawText(QRectF(14, 7, PART_WIDTH - 20, 18), Qt.AlignmentFlag.AlignLeft, self.part.ref)
        name_font = QFont(painter.font())
        name_font.setPixelSize(11)
        name_font.setWeight(QFont.Weight.Normal)
        painter.setFont(name_font)
        painter.setPen(QColor(theme.INK_SECONDARY))
        painter.drawText(QRectF(14, 26, PART_WIDTH - 20, PART_HEIGHT - 30),
                         Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, self.part.name)


class CircuitCanvas(QGraphicsView):
    """Only the wires touching a moved part are redrawn, so dragging stays smooth."""

    def __init__(self, design: CircuitDesign, parent: QWidget | None = None):
        super().__init__(parent)
        self.design = design
        self.graphics = QGraphicsScene(self)
        self.setScene(self.graphics)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setMinimumHeight(420)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.part_items: dict[str, PartItem] = {}
        self.wires: list[tuple[QGraphicsPathItem, str, str]] = []
        self.wires_by_ref: dict[str, list[tuple[QGraphicsPathItem, str, str]]] = {}
        self._building = False
        self.rebuild()

    def rebuild(self) -> None:
        self._building = True
        self.graphics.clear()
        self.part_items = {}
        self.wires = []
        self.wires_by_ref = {}
        for part in self.design.parts:
            self.add_part_item(part)
        for net in self.design.nets:
            self._add_net(net)
        self._building = False
        self._fit()

    def add_part_item(self, part: Part) -> PartItem:
        item = PartItem(part, self)
        self.graphics.addItem(item)
        self.part_items[part.ref] = item
        return item

    def _add_net(self, net: Net) -> None:
        ends = [ref for ref, _ in net.endpoints if ref in self.part_items]
        for a, b in zip(ends[::2], ends[1::2]):
            wire = QGraphicsPathItem()
            wire.setPen(_net_pen(net.net_type))
            wire.setZValue(1)
            wire.setToolTip(f"{net.name} ({net.net_type})")
            self.graphics.addItem(wire)
            record = (wire, a, b)
            self.wires.append(record)
            self.wires_by_ref.setdefault(a, []).append(record)
            self.wires_by_ref.setdefault(b, []).append(record)
            self._route(record)

    def _route(self, record: tuple[QGraphicsPathItem, str, str]) -> None:
        wire, a, b = record
        first = self.part_items[a].pos()
        second = self.part_items[b].pos()
        start = QPointF(first.x() + PART_WIDTH, first.y() + PART_HEIGHT / 2)
        end = QPointF(second.x(), second.y() + PART_HEIGHT / 2)
        mid = (start.x() + end.x()) / 2
        path = QPainterPath(start)
        path.lineTo(mid, start.y())
        path.lineTo(mid, end.y())
        path.lineTo(end)
        wire.setPath(path)

    def part_moved(self, ref: str) -> None:
        if self._building:
            return
        for record in self.wires_by_ref.get(ref, ()):
            self._route(record)
        self._fit_scene_rect()

    def _fit_scene_rect(self) -> None:
        self.graphics.setSceneRect(self.graphics.itemsBoundingRect().adjusted(-SCENE_MARGIN, -SCENE_MARGIN, SCENE_MARGIN, SCENE_MARGIN))

    def _fit(self) -> None:
        self._fit_scene_rect()
        self.fitInView(self.graphics.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        if self.transform().m11() > 1.2:  # Don't blow parts up on a very large window.
            self.resetTransform()
            self.scale(1.2, 1.2)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()


class NetSwatch(QWidget):
    """A short sample of one wire style, for the legend."""

    def __init__(self, net_type: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.net_type = net_type
        self.setFixedSize(30, 14)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(_net_pen(self.net_type))
        painter.drawLine(QPointF(1, 7), QPointF(29, 7))


class CircuitPage(Page):
    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__("Circuit Studio", "A conceptual BMS schematic. Drag parts to rearrange it, and select one to see its connections.", scroll=False, parent=parent)
        self.state = state
        self.design = state.design

        legend = QHBoxLayout()
        legend.setSpacing(6)
        for net_type, (_, _, title) in theme.NET_STYLES.items():
            legend.addWidget(NetSwatch(net_type))
            legend.addWidget(label(title, "caption"))
            legend.addSpacing(12)
        legend.addStretch(1)
        self.content.addLayout(legend)

        self.canvas = CircuitCanvas(self.design)
        self.canvas.graphics.selectionChanged.connect(self._selection_changed)

        panel = Card(spacing=8)
        panel.setFixedWidth(290)
        self.part_title = label("Select a part", "sectionTitle", wrap=True)
        self.part_body = label("Click any part on the schematic to see what it connects to.", "caption", wrap=True)
        panel.body.addWidget(self.part_title)
        panel.body.addWidget(self.part_body)
        self.battery_combo = fit_combo(QComboBox(), 20)
        self.test_button = QPushButton("Test this battery")
        self.test_button.setObjectName("primary")
        self.test_button.clicked.connect(self._test_battery)
        self.battery_label = label("Battery to test", "kpiLabel")
        panel.body.addWidget(self.battery_label)
        panel.body.addWidget(self.battery_combo)
        panel.body.addWidget(self.test_button)
        panel.body.addStretch(1)

        rule = QFrame()
        rule.setFrameShape(QFrame.Shape.HLine)
        rule.setStyleSheet(f"color:{theme.BORDER}")
        panel.body.addWidget(rule)
        panel.body.addWidget(label("Add a part", "sectionTitle"))
        self.part_name = QLineEdit()
        self.part_name.setPlaceholderText("Part name")
        self.part_kind = QComboBox()
        self.part_kind.addItems(PART_KINDS)
        add = QPushButton("Add part")
        add.clicked.connect(self.add_part)
        panel.body.addWidget(self.part_name)
        panel.body.addWidget(self.part_kind)
        panel.body.addWidget(add)

        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(self.canvas, 1)
        row.addWidget(panel)
        self.content.addLayout(row, 1)

        state.profiles_changed.connect(self._fill_batteries)
        self._fill_batteries()
        self._set_battery_controls(False)

    def _set_battery_controls(self, visible: bool) -> None:
        for widget in (self.battery_label, self.battery_combo, self.test_button):
            widget.setVisible(visible)

    def _fill_batteries(self) -> None:
        keep = self.battery_combo.currentData()
        self.battery_combo.blockSignals(True)
        self.battery_combo.clear()
        for profile in self.state.all_profiles():
            self.battery_combo.addItem(f"{profile.name} ({profile.id})", profile.id)
        index = self.battery_combo.findData(keep)
        if index >= 0:
            self.battery_combo.setCurrentIndex(index)
        self.battery_combo.blockSignals(False)

    def _selection_changed(self) -> None:
        # The scene also reports a selection change while it's being destroyed on exit.
        if not isValid(self.canvas) or not isValid(self.canvas.graphics):
            return
        selected = self.canvas.graphics.selectedItems()
        items = [item for item in selected if isinstance(item, PartItem)]
        if not items:
            self.part_title.setText("Select a part")
            self.part_body.setText("Click any part on the schematic to see what it connects to.")
            self._set_battery_controls(False)
            return
        part = items[0].part
        nets = self.design.nets_for(part.ref)
        self.part_title.setText(f"{part.ref}: {part.name}")
        lines = [f"Type: {part.kind}", "Pins: " + ", ".join(part.pins)]
        if nets:
            lines.append("Connections:")
            for net in nets:
                others = [ref for ref, _ in net.endpoints if ref != part.ref]
                lines.append(f"• {net.name} to {', '.join(others)}")
        else:
            lines.append("Not connected to anything yet.")
        self.part_body.setText("\n".join(lines))
        self._set_battery_controls(part.ref == "BAT1")

    def _test_battery(self) -> None:
        battery = self.battery_combo.currentData()
        if battery:
            self.state.test_requested.emit(battery)

    def add_part(self) -> None:
        name = self.part_name.text().strip()
        if not name:
            self.part_name.setFocus()
            return
        count = len(self.design.parts)
        lowest = max((p.y for p in self.design.parts), default=0)
        x = 40 + (count % 4) * 190
        y = lowest + PART_HEIGHT + 30 if count % 4 == 0 else lowest
        try:
            part = self.design.add_part(self.design.next_ref(), name, self.part_kind.currentText(), x, y, ["IN", "OUT"])
        except ValueError as exc:
            QMessageBox.warning(self, "Part", str(exc))
            return
        item = self.canvas.add_part_item(part)
        self.canvas.graphics.clearSelection()
        item.setSelected(True)
        self.part_name.clear()
        self.canvas._fit()
