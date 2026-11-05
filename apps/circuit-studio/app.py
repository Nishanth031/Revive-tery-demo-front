"""REVIVE-TERY Circuit Studio: a single-page dashboard built with Dash and Cytoscape.

Everything happens on one URL. Dash callbacks update parts of the page in place, so running
a test, switching battery and reading the result never reload the page.

Run it with: python src/app.py
Then open:   http://127.0.0.1:8050

A background thread runs each test and stores its readings in RunController. A timer on the
page asks for the latest values, and it only ticks while a test is running.
"""
from __future__ import annotations

import threading
import uuid
from collections import deque
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone

import dash_cytoscape as cyto
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, callback_context, dcc, html, no_update

from bms_engine import (
    BMSEngine, BatteryProfile, DatabaseUnavailable, HardwareError, Reading, SerialStats, TelemetryLogger,
    list_battery_ids, list_serial_port_details, load_battery_profile, read_esp32_telemetry,
)
import ml_panel
from run_controller import (
    SIM_MAX_LOAD_A, SIMULATED_CUTOFF_V, SIMULATED_RATED_AH, SOURCE_HARDWARE, SOURCE_SIMULATED, SOURCE_VIRTUAL,
    SPEED_LIMITS, HardwareSettings, RunController, fault_flags,
)
from esp32_sim import FAULT_NONE, FAULTS, SimulatedESP32, SimulationSettings
from test_bench import BUNDLE_DISCHARGE_POSITIVE, VirtualBattery, get_decision_for_ui

HOST = "127.0.0.1"  # Local only: this dashboard has no login, so it stays off the network.
PORT = 8050
REFRESH_MS = 400
TRACE_POINTS = 600
HARDWARE_VOLTAGE_LIMIT_V = 26.0  # The INA219's rated bus voltage limit.
TEMPERATURE_GAUGE_RANGE = (0.0, 80.0)
# The firmware sends a reading every second, so this many seconds of silence means a problem.
STALE_READING_S = 3.0

SIMULATED_VOLTAGE_RANGE = (0.0, 5.0)  # A 1S cell. The scale widens if a reading falls outside it.

# Colours.
SURFACE = "#fcfcfb"
PAGE = "#f4f4f1"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
ACCENT = "#2a78d6"
SERIES_2 = "#eb6834"
GOOD = "#0ca30c"
WARNING = "#fab219"
CRITICAL = "#d03b3b"
FONT = '"Segoe UI", system-ui, sans-serif'

CARD = {"background": SURFACE, "border": f"1px solid {GRID}", "borderRadius": "8px", "padding": "14px 16px"}
CAPTION = {"color": INK_SECONDARY, "fontSize": "12px"}
SECTION_TITLE = {"fontSize": "14px", "fontWeight": 600, "margin": "0 0 8px"}
PRIMARY_BUTTON = {
    "background": ACCENT, "color": "white", "border": f"1px solid {ACCENT}", "borderRadius": "6px",
    "padding": "8px 16px", "fontWeight": 600, "cursor": "pointer",
}
BUTTON = {
    "background": SURFACE, "color": INK, "border": f"1px solid {AXIS}", "borderRadius": "6px",
    "padding": "8px 16px", "fontWeight": 500, "cursor": "pointer",
}
INPUT = {"border": f"1px solid {AXIS}", "borderRadius": "6px", "padding": "6px 8px", "width": "100%", "boxSizing": "border-box"}


# ------------------------------------------------------------------------------------
# The circuit: components, pins and wires
# ------------------------------------------------------------------------------------

# Each component: (id, title, kind, pins). Each pin: (id, label, x, y, side the wire leaves).
# This is the low-voltage bench kit. The INA219 is rated to 26 V, so it can't go on an EV pack.
COMPONENTS = [
    ("battery", "BATTERY", "battery", [
        ("bat_pos", "B+", 110, 110, "right"),
        ("bat_neg", "B−", 110, 210, "right"),
    ]),
    ("load", "TEST LOAD", "load", [
        ("load_pos", "L+", 110, 330, "right"),
        ("load_neg", "L−", 110, 400, "right"),
    ]),
    ("ina219", "INA219 VOLTAGE/CURRENT", "sensor", [
        ("ina_vin_pos", "VIN+", 290, 90, "left"),
        ("ina_vin_neg", "VIN−", 290, 170, "left"),
        ("ina_vcc", "VCC", 430, 60, "right"),
        ("ina_gnd", "GND", 430, 110, "right"),
        ("ina_sda", "SDA", 430, 160, "right"),
        ("ina_scl", "SCL", 430, 210, "right"),
    ]),
    ("ds18b20", "DS18B20 TEMPERATURE", "sensor", [
        ("ds_vdd", "VDD", 430, 320, "right"),
        ("ds_dq", "DQ", 430, 370, "right"),
        ("ds_gnd", "GND", 430, 420, "right"),
    ]),
    ("r1", "R1 4.7 kΩ", "passive", [
        ("r1_a", "A", 560, 300, "right"),
        ("r1_b", "B", 560, 360, "right"),
    ]),
    ("esp32", "ESP32", "mcu", [
        ("esp_3v3", "3V3", 700, 60, "left"),
        ("esp_gnd", "GND", 700, 130, "left"),
        ("esp_21", "GPIO21", 700, 200, "left"),
        ("esp_22", "GPIO22", 700, 270, "left"),
        ("esp_4", "GPIO4", 700, 340, "left"),
        ("esp_usb", "USB", 840, 200, "right"),
    ]),
    ("laptop", "LAPTOP", "host", [
        ("pc_usb", "USB", 960, 200, "left"),
    ]),
]

# Each wire: (from pin, to pin, type, description).
WIRES = [
    ("bat_pos", "ina_vin_pos", "power", "Battery positive into the current sensor"),
    ("ina_vin_neg", "load_pos", "power", "Current sensor out to the test load"),
    ("load_neg", "bat_neg", "ground", "Test load back to battery negative"),
    ("bat_neg", "esp_gnd", "ground", "Common ground, needed for the voltage reading"),
    ("ina_vcc", "esp_3v3", "logic", "Sensor power from the ESP32"),
    ("ina_gnd", "esp_gnd", "ground", "Sensor ground"),
    ("ina_sda", "esp_21", "i2c", "I2C data"),
    ("ina_scl", "esp_22", "i2c", "I2C clock"),
    ("ds_vdd", "esp_3v3", "logic", "Temperature sensor power"),
    ("ds_gnd", "esp_gnd", "ground", "Temperature sensor ground"),
    ("ds_dq", "esp_4", "onewire", "1-Wire temperature data"),
    ("r1_a", "esp_3v3", "logic", "Pull-up resistor to 3.3 V"),
    ("r1_b", "ds_dq", "onewire", "Pull-up on the 1-Wire data line"),
    ("esp_usb", "pc_usb", "usb", "Telemetry to the laptop. Monitor-only: nothing is sent back"),
]
PIN_LOOKUP = {pin[0]: (component[0], component[1], pin[1]) for component in COMPONENTS for pin in component[3]}
WIRES_WITH_CURRENT = {"power", "ground"}


def circuit_elements(battery_id: str | None) -> list[dict]:
    """Build the Cytoscape graph. Each component is a parent node with its pins inside it."""
    elements = []
    for component_id, title, kind, pins in COMPONENTS:
        name = title
        if kind == "battery":
            name = f"BATTERY\n{battery_id or 'no battery loaded'}\nTap to switch"
        elements.append({"data": {"id": component_id, "label": name, "component": component_id}, "classes": kind})
        for pin_id, pin_label, x, y, side in pins:
            elements.append({
                "data": {"id": pin_id, "label": pin_label, "parent": component_id, "component": component_id},
                "position": {"x": x, "y": y},
                "classes": f"pin pin-{side}",
            })
    for source, target, wire_type, description in WIRES:
        elements.append({
            "data": {"id": f"{source}__{target}", "source": source, "target": target, "wire": wire_type, "description": description},
        })
    return elements


def circuit_stylesheet(running: bool) -> list[dict]:
    """Wire colours and line styles. Thicker current-carrying wires show when a test is live."""
    power_width = 5 if running else 3
    return [
        {"selector": "node", "style": {"font-family": "Segoe UI, sans-serif", "color": INK}},
        {"selector": ":parent", "style": {
            "background-color": SURFACE, "background-opacity": 1, "border-color": AXIS, "border-width": 1,
            "shape": "round-rectangle", "label": "data(label)", "text-valign": "top", "text-halign": "center",
            "font-size": 11, "font-weight": 600, "text-wrap": "wrap", "text-margin-y": -4,
            "padding": 26,
        }},
        {"selector": ".battery", "style": {"background-color": "#e8f1fb", "border-color": ACCENT, "border-width": 2}},
        {"selector": ".pin", "style": {
            "width": 12, "height": 12, "background-color": INK_SECONDARY, "border-color": SURFACE, "border-width": 2,
            "label": "data(label)", "font-size": 10, "color": INK_SECONDARY, "text-valign": "center",
        }},
        {"selector": ".pin-right", "style": {"text-halign": "left", "text-margin-x": -4}},
        {"selector": ".pin-left", "style": {"text-halign": "right", "text-margin-x": 4}},
        {"selector": "edge", "style": {"curve-style": "taxi", "taxi-direction": "horizontal", "width": 2, "line-color": AXIS}},
        {"selector": 'edge[wire = "power"]', "style": {"line-color": "#e34948", "width": power_width}},
        {"selector": 'edge[wire = "ground"]', "style": {"line-color": INK, "width": power_width}},
        {"selector": 'edge[wire = "logic"]', "style": {"line-color": "#6250d6", "line-style": "dashed"}},
        {"selector": 'edge[wire = "i2c"]', "style": {"line-color": ACCENT, "line-style": "dotted", "width": 3}},
        {"selector": 'edge[wire = "onewire"]', "style": {"line-color": "#008300", "line-style": "dashed"}},
        {"selector": 'edge[wire = "usb"]', "style": {"line-color": SERIES_2, "width": 3}},
    ]


WIRE_LEGEND = (
    ("Power", "#e34948", "solid"), ("Ground", INK, "solid"), ("Sensor power", "#6250d6", "dashed"),
    ("I2C", ACCENT, "dotted"), ("1-Wire", "#008300", "dashed"), ("USB, read-only", SERIES_2, "solid"),
)


# ------------------------------------------------------------------------------------
# Test runs
# ------------------------------------------------------------------------------------


controller = RunController()


def reading_is_stale(snap: dict, now: float | None = None) -> bool:
    """True during a hardware test when the newest reading is too old to call live."""
    if snap["status"] != "running" or snap["source"] != SOURCE_HARDWARE:
        return False
    stats = snap["stats"]
    if stats.fault_is_active:
        return True
    newest = stats.last_reading_wall if stats.last_reading_wall is not None else snap["run_started_at"]
    return (now if now is not None else time.time()) - newest > STALE_READING_S


def port_choices(current: str | None = None) -> tuple[list[dict], str | None]:
    """Labelled port options, and which to select.

    A port is only preselected when it's clear which one is meant: the one you already chose,
    or the only USB serial port. Otherwise you choose, because a wrong guess wastes a test.
    """
    details = list_serial_port_details()
    options = []
    for info in details:
        kind = "Bluetooth, not the ESP32's USB" if info.is_bluetooth else info.description
        options.append({"label": f"{info.device}: {kind}", "value": info.device})
    names = [info.device for info in details]
    if current in names:
        return options, current
    usb = [info.device for info in details if info.is_usb]
    return options, usb[0] if len(usb) == 1 else None


# ------------------------------------------------------------------------------------
# Figures
# ------------------------------------------------------------------------------------


def gauge_figure(title: str, value: float | None, unit: str, low: float, high: float) -> go.Figure:
    """A dial with a plain arc: a colour here would imply safety limits the data doesn't state."""
    figure = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        number={"suffix": f" {unit}", "font": {"size": 28, "color": INK}, "valueformat": ".2f"},
        title={"text": title, "font": {"size": 13, "color": INK_SECONDARY}},
        gauge={
            "axis": {"range": [low, high], "tickcolor": AXIS, "tickfont": {"size": 10, "color": INK_SECONDARY}},
            "bar": {"color": ACCENT, "thickness": 0.3},
            "bgcolor": GRID,
            "borderwidth": 0,
        },
    ))
    figure.update_layout(margin={"l": 24, "r": 24, "t": 44, "b": 8}, height=210, paper_bgcolor=SURFACE, font={"family": FONT})
    return figure


def trace_figure(title: str, unit: str, series: list[tuple[str, str, list, list]]) -> go.Figure:
    figure = go.Figure()
    for name, colour, xs, ys in series:
        figure.add_trace(go.Scatter(
            x=xs, y=ys, name=name, mode="lines", line={"color": colour, "width": 2},
            hovertemplate=f"%{{y:.2f}} {unit}<extra>{name}</extra>",
        ))
    figure.update_layout(
        title={"text": f"{title} ({unit})", "font": {"size": 13, "color": INK}, "x": 0, "xanchor": "left"},
        margin={"l": 44, "r": 12, "t": 34, "b": 28}, height=210, paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font={"family": FONT, "size": 11, "color": INK_SECONDARY}, hovermode="x unified",
        showlegend=len(series) > 1, legend={"orientation": "h", "x": 1, "xanchor": "right", "y": 1.2},
        xaxis={"showgrid": False, "linecolor": AXIS, "title": None},
        yaxis={"gridcolor": GRID, "zeroline": False, "title": None},
    )
    return figure


def voltage_range(profile: BatteryProfile | None, source: str, readings: list[Reading],
                  simulated: bool = False) -> tuple[float, float]:
    """The voltmeter's scale: the battery's stated limits, widened if a reading falls outside them."""
    if source == SOURCE_HARDWARE and simulated:
        low, high = SIMULATED_VOLTAGE_RANGE
    elif source == SOURCE_HARDWARE:
        low, high = 0.0, HARDWARE_VOLTAGE_LIMIT_V
    elif profile and profile.min_voltage_v is not None and profile.max_voltage_v is not None:
        low, high = profile.min_voltage_v, profile.max_voltage_v
    elif profile and profile.nominal_voltage_v:
        low, high = 0.0, profile.nominal_voltage_v * 1.25
    else:
        low, high = 0.0, 1.0
    values = [r.sample.voltage_v for r in readings]
    if values:
        low, high = min(low, min(values)), max(high, max(values))
    return low, high


def reading_time(reading: Reading) -> str:
    return datetime.fromtimestamp(reading.sample.timestamp, timezone.utc).strftime("%H:%M:%S")


def kpi(title: str, value: str, caption: str) -> html.Div:
    return html.Div(style={**CARD, "flex": "1", "minWidth": "120px"}, children=[
        html.Div(title, style=CAPTION),
        html.Div(value, style={"fontSize": "22px", "fontWeight": 600, "margin": "2px 0"}),
        html.Div(caption, style=CAPTION),
    ])


def fmt(value: float | None, unit: str = "", digits: int = 1) -> str:
    return "—" if value is None else f"{value:.{digits}f} {unit}".strip()


def build_kpis(snap: dict) -> list[html.Div]:
    latest = snap["readings"][-1] if snap["readings"] else None
    if latest is None:
        return [
            kpi("SOC, coulomb counted", "—", "Starts with the test"),
            kpi("SOC, recorded", "—", "From the source"),
            kpi("SOH, live", "—", "Updates during the test"),
            kpi("Current", "—", "As the source records it"),
            kpi("Discharged", "—", "Charge counted this test"),
        ]
    sample = latest.sample
    live_soh = fmt(latest.soh_live_pct, "%")
    if latest.soh_live_pct is not None and latest.soh_basis.startswith("At least"):
        live_soh = "≥ " + live_soh
    return [
        kpi("SOC, coulomb counted", fmt(latest.soc_pct, "%"), "SOC(t-1) − I·Δt / capacity"),
        kpi("SOC, recorded", fmt(sample.reported_soc_pct, "%"), "From the source"),
        kpi("SOH, live", live_soh, latest.soh_basis),
        kpi("Current", fmt(sample.current_a, "A", 2), sample.state.replace("_", " ").capitalize() or "As the source records it"),
        kpi("Discharged", fmt(latest.discharged_ah, "Ah", 2), f"{len(snap['readings'])} readings"),
    ]


def build_profile_card(snap: dict) -> list:
    profile = snap["profile"]
    if profile is None:
        return [html.H3("Active battery", style=SECTION_TITLE), html.Div("None loaded", style=CAPTION)]
    rows = [
        ("ID", profile.asset_id), ("Chemistry", profile.chemistry or "Unknown"),
        ("Nominal voltage", fmt(profile.nominal_voltage_v, "V")),
        ("Rated capacity", fmt(profile.rated_capacity_ah, "Ah")),
        ("Measured capacity", fmt(profile.measured_capacity_ah, "Ah")),
        ("Telemetry rows", str(profile.telemetry_rows)),
    ]
    children = [html.H3("Active battery", style=SECTION_TITLE)]
    for name, value in rows:
        children.append(html.Div(style={"display": "flex", "justifyContent": "space-between", "gap": "12px", "padding": "2px 0"}, children=[
            html.Span(name, style=CAPTION), html.Span(value, style={"fontSize": "13px", "textAlign": "right"}),
        ]))
    return children


def build_decision_card(snap: dict) -> list:
    title = html.H3("Secondary use decision", style=SECTION_TITLE)
    decision = snap["decision"]
    if decision is None:
        text = "Test running. The decision appears when it ends." if snap["status"] == "running" else "Run a test to see a decision."
        return [title, html.Div(text, style=CAPTION)]
    children = [
        title,
        html.Div(decision["use_case"], id="decision-text", style={"fontSize": "26px", "fontWeight": 700}),
        html.Div(f"SOH {fmt(decision['soh_pct'], '%')}. {decision['basis']}.", style={"margin": "4px 0 8px"}),
        html.Div(decision["note"], style=CAPTION),
    ]
    if decision["flags"]:
        children.append(html.Div("Data checks", style={"fontWeight": 600, "marginTop": "10px"}))
        children.append(html.Ul([html.Li(flag) for flag in decision["flags"]], style={"margin": "4px 0 0", "paddingLeft": "18px"}))
    if snap["log_note"]:
        children.append(html.Div(snap["log_note"], style={**CAPTION, "marginTop": "10px"}))
    return children


def build_status(snap: dict) -> tuple[str, str]:
    """The status line, with a glyph as well as a colour so it never relies on colour alone."""
    if snap["source"] == SOURCE_HARDWARE:
        source_name = "simulated ESP32 (software)" if snap["simulated"] else "ESP32 hardware"
    else:
        source_name = "virtual battery"
    status = snap["status"]
    if snap["error"]:
        return f"× {snap['error']}", CRITICAL
    if status == "running":
        count = len(snap["readings"])
        if snap["source"] == SOURCE_HARDWARE:
            text = (
                f"● Monitoring {source_name}: {snap['good_lines']} good lines, {snap['bad_lines']} skipped, "
                f"{snap['message_lines']} firmware messages."
            )
            if not snap["good_lines"]:
                text = f"● Port open, waiting for telemetry from the ESP32. {snap['message_lines']} firmware messages so far."
            return text, GOOD
        return f"● Replaying the {source_name}: {count} readings so far.", GOOD
    if status == "finished":
        return "✓ Test finished.", GOOD
    if status == "stopped":
        return "■ Test stopped.", WARNING
    return f"{snap['notice'] or 'Ready. Tap the battery to reload it from DuckDB, or start a test.'}", INK_SECONDARY


FAULT_BANNER_BASE = {"borderRadius": "8px", "padding": "12px 16px", "marginBottom": "12px", "background": SURFACE}


def build_fault_banner(snap: dict, now: float | None = None) -> tuple[str, dict]:
    """The hardware alert at the top of the page. It's the only view of the firmware's messages
    during a test, because the dashboard holds the COM port and a Serial Monitor can't open it."""
    hidden = {"display": "none"}
    if snap["source"] != SOURCE_HARDWARE:
        return "", hidden
    stats = snap["stats"]
    running = snap["status"] == "running"
    if running and stats.fault_is_active:
        if stats.last_fault_severity == "critical":
            style = {**FAULT_BANNER_BASE, "border": f"3px solid {CRITICAL}", "fontSize": "18px", "fontWeight": 700}
            return f"× {stats.last_fault}", style
        style = {**FAULT_BANNER_BASE, "border": f"3px solid {WARNING}", "fontSize": "15px", "fontWeight": 600}
        return f"! {stats.last_fault}. No new readings are arriving.", style
    if reading_is_stale(snap, now):
        moment = stats.last_reading_wall if stats.last_reading_wall is not None else snap["run_started_at"]
        waited = (now if now is not None else time.time()) - moment
        style = {**FAULT_BANNER_BASE, "border": f"3px solid {WARNING}", "fontSize": "15px", "fontWeight": 600}
        if stats.last_reading_wall is None:
            return f"! No readings yet after {waited:.0f} s. Check that this is the ESP32's port and that it's flashed.", style
        return f"! No reading for {waited:.0f} s. The ESP32 has gone silent, so check the USB cable and the board.", style
    if stats.last_fault:
        count = sum(stats.fault_counts.values())
        moment = datetime.fromtimestamp(stats.last_fault_at, timezone.utc).strftime("%H:%M:%S")
        style = {**FAULT_BANNER_BASE, "border": f"1px solid {AXIS}", "color": INK_SECONDARY}
        return f"Earlier in this test: {stats.last_fault} (last at {moment} UTC, {count} fault message{'s' if count != 1 else ''} in total).", style
    return "", hidden


def build_data_label(snap: dict) -> str:
    """Say plainly what kind of data is on screen."""
    if snap["source"] == SOURCE_HARDWARE and snap["simulated"]:
        return (
            "Simulated ESP32 and circuit: a software model of a made-up 1S cell, running through the same code as a "
            "real board. These readings are generated, not measured, and are logged as SIMULATED."
        )
    if snap["source"] == SOURCE_HARDWARE and snap["readings"]:
        return "Live readings from physical sensors. Monitor-only: nothing is sent to the ESP32."
    profile = snap["profile"]
    if profile and profile.is_synthetic:
        return (
            f"{profile.asset_id} is synthetic demo data, replayed as recorded. These aren't measurements of a real "
            "battery, so don't use them for engineering, safety, warranty or compliance decisions."
        )
    return "The virtual battery replays recorded telemetry from DuckDB, as stored."


# ------------------------------------------------------------------------------------
# Page layout
# ------------------------------------------------------------------------------------


def legend() -> html.Div:
    items = []
    for name, colour, style in WIRE_LEGEND:
        items.append(html.Span(style={"display": "inline-flex", "alignItems": "center", "gap": "6px"}, children=[
            html.Span(style={"display": "inline-block", "width": "26px", "borderTop": f"3px {style} {colour}"}),
            html.Span(name, style=CAPTION),
        ]))
    return html.Div(items, style={"display": "flex", "flexWrap": "wrap", "gap": "14px"})


def labelled(text: str, control) -> html.Div:
    return html.Div(style={"flex": "1", "minWidth": "130px"}, children=[html.Label(text, style={**CAPTION, "display": "block", "marginBottom": "3px"}), control])


def serve_layout() -> html.Div:
    """The whole page. The port list here is the starting point; Rescan ports updates it."""
    port_options, port_value = port_choices()
    return html.Div(style={"background": PAGE, "minHeight": "100vh", "padding": "20px 24px", "fontFamily": FONT, "color": INK, "fontSize": "13px", "boxSizing": "border-box"}, children=[
        html.H1("REVIVE-TERY Circuit Studio", style={"fontSize": "22px", "fontWeight": 600, "margin": 0}),
        html.Div("Monitor a battery, calculate SOC and SOH, and screen it for a second life.", style={"color": INK_SECONDARY, "marginBottom": "12px"}),

        html.Div(id="fault-banner", role="alert", style={"display": "none"}),
        html.Div(id="data-label", style={**CARD, "padding": "10px 14px", "marginBottom": "12px"}),

        html.Div(style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "marginBottom": "12px"}, children=[
            html.Div(style={**CARD, "flex": "3", "minWidth": "560px"}, children=[
                html.H3("Bench circuit", style=SECTION_TITLE),
                cyto.Cytoscape(
                    id="circuit",
                    elements=circuit_elements(None),
                    stylesheet=circuit_stylesheet(False),
                    layout={"name": "preset", "fit": True, "padding": 16},
                    style={"width": "100%", "height": "450px"},
                    autoungrabify=True,  # Parts stay put, so a page update can't scramble them.
                    userZoomingEnabled=False,
                    userPanningEnabled=False,
                ),
                legend(),
                html.Div(id="tap-info", style={**CAPTION, "marginTop": "8px", "minHeight": "16px"}),
                html.Div(
                    "Bench wiring is for the low-voltage kit only. The INA219 is rated to 26 V: never connect it to an EV pack.",
                    style={**CAPTION, "marginTop": "4px"},
                ),
            ]),
            html.Div(style={"flex": "1", "minWidth": "260px", "display": "flex", "flexDirection": "column", "gap": "12px"}, children=[
                html.Div(id="profile-card", style=CARD),
                html.Div(style=CARD, children=[
                    html.H3("Run a test", style=SECTION_TITLE),
                    dcc.RadioItems(
                        id="source",
                        options=[
                            {"label": " Virtual battery", "value": SOURCE_VIRTUAL},
                            {"label": " ESP32 hardware", "value": SOURCE_HARDWARE},
                            {"label": " Simulated ESP32 (no hardware needed)", "value": SOURCE_SIMULATED},
                        ],
                        value=SOURCE_VIRTUAL,
                        labelStyle={"display": "block", "padding": "2px 0"},
                    ),
                    html.Div(id="virtual-panel", style={"marginTop": "8px"}, children=[
                        labelled("Delay between rows (seconds)", dcc.Input(id="delay", type="number", min=0.05, max=10, step=0.05, value=1.0, style=INPUT)),
                    ]),
                    html.Div(id="hardware-panel", style={"display": "none"}, children=[
                        html.Div(style={"display": "flex", "gap": "8px", "flexWrap": "wrap", "marginTop": "8px"}, children=[
                            # display: contents keeps these in the row, and display: none hides them for the simulator.
                            html.Div(id="port-block", style={"display": "contents"}, children=[
                                html.Div(style={"flexBasis": "100%"}, children=[
                                    labelled("COM port", dcc.Dropdown(id="port", options=port_options, value=port_value, placeholder="Choose the ESP32's port")),
                                    html.Button("Rescan ports", id="rescan", n_clicks=0, style={**BUTTON, "marginTop": "6px", "padding": "4px 10px"}),
                                ]),
                                labelled("Baud rate", dcc.Input(id="baud", type="number", value=115200, style=INPUT)),
                            ]),
                            labelled("Rated capacity (Ah)", dcc.Input(id="rated", type="number", min=0, step=0.01, style=INPUT)),
                            labelled("Starting SOC (%)", dcc.Input(id="start-soc", type="number", min=0, max=100, value=100, style=INPUT)),
                            labelled("Cutoff voltage (V)", dcc.Input(id="cutoff", type="number", min=0, step=0.01, style=INPUT)),
                        ]),
                        dcc.Checklist(
                            id="discharge-positive",
                            options=[{"label": " Discharge current reads positive", "value": "yes"}],
                            value=["yes"],
                            style={"marginTop": "8px"},
                        ),
                    ]),
                    html.Div(id="sim-panel", style={"display": "none"}, children=[
                        html.Div(style={"display": "flex", "gap": "8px", "flexWrap": "wrap", "marginTop": "8px"}, children=[
                            labelled("Cell's true capacity (Ah)", dcc.Input(id="sim-capacity", type="number", min=0.05, step=0.05, value=1.8, style=INPUT)),
                            labelled("Load current (A, max 3.2)", dcc.Input(id="sim-load", type="number", min=0.05, max=3.0, step=0.05, value=1.0, style=INPUT)),
                            labelled("Speed (× real time)", dcc.Input(id="sim-speed", type="number", min=SPEED_LIMITS[0], max=SPEED_LIMITS[1], step=1, value=60, style=INPUT)),
                        ]),
                        html.Div(style={"marginTop": "8px"}, children=[
                            labelled("Inject a fault, any time during the test", dcc.Dropdown(
                                id="sim-fault", clearable=False, value=FAULT_NONE,
                                options=[{"label": text, "value": key} for key, text in FAULTS.items()],
                            )),
                        ]),
                        html.Div(
                            "A made-up 1S Li-ion cell, a test load, an INA219 and a DS18B20, all in software. The test ends when the "
                            "load empties the cell. Rated capacity above is what the dashboard assumes, so a true capacity below it "
                            "gives an SOH below 100%.",
                            style={**CAPTION, "marginTop": "8px"},
                        ),
                    ]),
                    html.Div(style={"display": "flex", "gap": "8px", "marginTop": "12px"}, children=[
                        html.Button("Start test", id="start", n_clicks=0, style=PRIMARY_BUTTON),
                        html.Button("Stop", id="stop", n_clicks=0, style=BUTTON, disabled=True),
                    ]),
                    html.Div(id="status", style={"marginTop": "10px"}),
                ]),
            ]),
        ]),

        html.Div(style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "marginBottom": "12px"}, children=[
            html.Div(style={**CARD, "flex": "1", "minWidth": "260px"}, children=[dcc.Graph(id="voltmeter", config={"displayModeBar": False})]),
            html.Div(style={**CARD, "flex": "1", "minWidth": "260px"}, children=[dcc.Graph(id="thermometer", config={"displayModeBar": False})]),
            html.Div(style={**CARD, "flex": "1", "minWidth": "300px"}, children=[dcc.Graph(id="trace-voltage", config={"displayModeBar": False})]),
            html.Div(style={**CARD, "flex": "1", "minWidth": "300px"}, children=[dcc.Graph(id="trace-soc", config={"displayModeBar": False})]),
        ]),

        html.Div(id="kpis", style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "marginBottom": "12px"}),
        html.Div(id="decision-card", style=CARD),

        # Batch uploads: ML file analysis and second-life suggestion (src/ml_panel.py).
        ml_panel.layout({"CARD": CARD, "CAPTION": CAPTION, "SECTION_TITLE": SECTION_TITLE, "INPUT": INPUT,
                         "BUTTON": BUTTON, "PRIMARY_BUTTON": PRIMARY_BUTTON}),

        # The timer only runs during a test. tick redraws the page after a button or tap.
        dcc.Interval(id="timer", interval=REFRESH_MS, disabled=True),
        dcc.Store(id="tick", data=0),
        dcc.Store(id="drawn-battery", data=None),
    ])


app = Dash(__name__, title="REVIVE-TERY Circuit Studio", update_title=None)
app.layout = serve_layout
ml_panel.register(app)


# ------------------------------------------------------------------------------------
# Callbacks
# ------------------------------------------------------------------------------------


@app.callback(
    Output("virtual-panel", "style"),
    Output("hardware-panel", "style"),
    Output("sim-panel", "style"),
    Output("port-block", "style"),
    Output("rated", "value"),
    Output("cutoff", "value"),
    Input("source", "value"),
    State("rated", "value"),
    State("cutoff", "value"),
)
def show_source_settings(source, rated, cutoff):
    hidden = {"display": "none"}
    if source == SOURCE_HARDWARE:
        return hidden, {"display": "block"}, hidden, {"display": "contents"}, no_update, no_update
    if source == SOURCE_SIMULATED:
        # The simulated cell's defaults make a full test work straight away, but only fill empty boxes.
        return (
            hidden, {"display": "block"}, {"display": "block"}, hidden,
            no_update if rated else SIMULATED_RATED_AH, no_update if cutoff else SIMULATED_CUTOFF_V,
        )
    return {"display": "block", "marginTop": "8px"}, hidden, hidden, {"display": "contents"}, no_update, no_update


def simulation_settings(rated, start_soc, cutoff, capacity, load, speed) -> tuple[HardwareSettings, SimulationSettings] | str:
    """Check the simulator form. Returns the settings, or a message saying what to fix."""
    settings = hardware_settings("SIMULATED", 115200, rated, start_soc, cutoff, True)
    if isinstance(settings, str):
        return settings
    if not capacity or capacity <= 0:
        return "Enter the simulated cell's true capacity in Ah."
    if load is None or not 0 < load <= SIM_MAX_LOAD_A:
        return f"Enter a load current above 0 and up to {SIM_MAX_LOAD_A} A. Above that, the real sensor stops measuring."
    if not speed or not SPEED_LIMITS[0] <= speed <= SPEED_LIMITS[1]:
        return f"Enter a speed from {SPEED_LIMITS[0]:g} to {SPEED_LIMITS[1]:g} times real time."
    return settings, SimulationSettings(
        true_capacity_ah=float(capacity), start_soc_pct=settings.start_soc_pct, load_current_a=float(load), speed=float(speed),
    )


def hardware_settings(port, baud, rated, start_soc, cutoff, discharge_positive) -> HardwareSettings | str:
    """Check the form. Returns the settings, or a message saying what to fix."""
    if not port:
        return "Choose a COM port. If yours isn't listed, plug in the ESP32 and press Rescan ports."
    if not rated or rated <= 0:
        return "Enter the battery's rated capacity in Ah."
    if start_soc is None or not 0 <= start_soc <= 100:
        return "Enter a starting SOC between 0 and 100%."
    if not baud or baud <= 0:
        return "Enter a valid baud rate."
    return HardwareSettings(
        port=port, baudrate=int(baud), rated_capacity_ah=float(rated), start_soc_pct=float(start_soc),
        cutoff_voltage_v=float(cutoff) if cutoff else None, discharge_positive=bool(discharge_positive),
    )


@app.callback(
    Output("port", "options"),
    Output("port", "value"),
    Input("rescan", "n_clicks"),
    State("port", "value"),
    prevent_initial_call=True,
)
def rescan_ports(_clicks, current):
    """Find newly plugged-in boards without reloading the page and losing the form."""
    return port_choices(current)


@app.callback(
    Output("tick", "data"),
    Output("tap-info", "children"),
    Input("start", "n_clicks"),
    Input("stop", "n_clicks"),
    Input("circuit", "tapNode"),  # Not tapNodeData: that doesn't fire when the same part is tapped twice.
    Input("circuit", "tapEdge"),
    Input("sim-fault", "value"),
    State("tick", "data"),
    State("source", "value"),
    State("delay", "value"),
    State("port", "value"),
    State("baud", "value"),
    State("rated", "value"),
    State("start-soc", "value"),
    State("cutoff", "value"),
    State("discharge-positive", "value"),
    State("sim-capacity", "value"),
    State("sim-load", "value"),
    State("sim-speed", "value"),
    prevent_initial_call=True,
)
def handle_action(_start, _stop, tap_node, tap_edge, sim_fault, tick, source, delay, port, baud, rated, start_soc,
                  cutoff, positive, sim_capacity, sim_load, sim_speed):
    """Every button press and tap comes through here, then tick redraws the page."""
    trigger = callback_context.triggered_id
    info = no_update
    if trigger == "sim-fault":
        controller.set_sim_fault(sim_fault)
    elif trigger == "start":
        if source == SOURCE_SIMULATED:
            settings = simulation_settings(rated, start_soc, cutoff, sim_capacity, sim_load, sim_speed)
            if isinstance(settings, str):
                controller.notice = settings
                return (tick or 0) + 1, no_update
            controller.start_simulated(*settings, fault=sim_fault or FAULT_NONE)
        elif source == SOURCE_HARDWARE:
            settings = hardware_settings(port, baud, rated, start_soc, cutoff, positive)
            if isinstance(settings, str):
                controller.notice = settings
                return (tick or 0) + 1, no_update
            controller.start_hardware(settings)
        else:
            controller.start_virtual(float(delay) if delay else 1.0)
    elif trigger == "stop":
        controller.stop()
    elif trigger == "circuit":
        triggered = callback_context.triggered[0]["prop_id"]
        if triggered.endswith("tapEdge") and tap_edge:
            data = tap_edge["data"]
            start = PIN_LOOKUP.get(data["source"], ("", "", ""))
            end = PIN_LOOKUP.get(data["target"], ("", "", ""))
            info = f"Wire: {start[1]} {start[2]} to {end[1]} {end[2]}. {data.get('description', '')}"
        elif tap_node:
            data = tap_node["data"]
            if data.get("component") == "battery":
                controller.switch_battery()
                info = ""
            elif data.get("parent"):
                info = f"Pin {data['label']} on {PIN_LOOKUP[data['id']][1]}. Tap a wire to see what it connects."
            else:
                info = f"{data.get('label', '')}. Tap a wire to see what it connects."
    return (tick or 0) + 1, info


@app.callback(
    Output("voltmeter", "figure"),
    Output("thermometer", "figure"),
    Output("trace-voltage", "figure"),
    Output("trace-soc", "figure"),
    Output("kpis", "children"),
    Output("profile-card", "children"),
    Output("decision-card", "children"),
    Output("status", "children"),
    Output("status", "style"),
    Output("fault-banner", "children"),
    Output("fault-banner", "style"),
    Output("data-label", "children"),
    Output("circuit", "elements"),
    Output("circuit", "stylesheet"),
    Output("drawn-battery", "data"),
    Output("timer", "disabled"),
    Output("start", "disabled"),
    Output("stop", "disabled"),
    Input("timer", "n_intervals"),
    Input("tick", "data"),
    State("drawn-battery", "data"),
)
def refresh(_intervals, _tick, drawn_battery):
    """Redraw everything from the latest snapshot, in place, with no page reload."""
    controller.load_initial_battery()
    snap = controller.snapshot()
    readings = snap["readings"]
    latest = readings[-1] if readings else None
    profile = snap["profile"]
    running = snap["status"] == "running"

    low, high = voltage_range(profile, snap["source"], readings, snap["simulated"])
    # A dial frozen on its last value would look like a steady reading, so it goes blank instead.
    now = time.time()
    stale = reading_is_stale(snap, now)
    live = None if stale else latest
    suffix = ": no current reading" if stale else ""
    voltmeter = gauge_figure(f"Voltmeter{suffix}", live.sample.voltage_v if live else None, "V", low, high)
    thermometer = gauge_figure(f"Temperature{suffix}", live.sample.temperature_c if live else None, "°C", *TEMPERATURE_GAUGE_RANGE)
    fault_text, fault_style = build_fault_banner(snap, now)

    recent = readings[-TRACE_POINTS:]
    times = [reading_time(r) for r in recent]
    trace_voltage = trace_figure("Voltage", "V", [("Voltage", ACCENT, times, [r.sample.voltage_v for r in recent])])
    soc_series = [("Coulomb counted", ACCENT, times, [r.soc_pct for r in recent])]
    if any(r.sample.reported_soc_pct is not None for r in recent):
        soc_series.insert(0, ("Recorded", SERIES_2, times, [r.sample.reported_soc_pct for r in recent]))
    trace_soc = trace_figure("State of charge", "%", soc_series)

    status_text, status_colour = build_status(snap)
    battery_id = profile.asset_id if profile else None
    # Only redraw the graph when the battery changes, because redrawing it is the slow part.
    elements = circuit_elements(battery_id) if battery_id != drawn_battery else no_update

    return (
        voltmeter, thermometer, trace_voltage, trace_soc,
        build_kpis(snap), build_profile_card(snap), build_decision_card(snap),
        status_text, {"marginTop": "10px", "color": INK if status_colour == WARNING else status_colour},
        fault_text, fault_style,
        build_data_label(snap),
        elements, circuit_stylesheet(running), battery_id,
        not running, running, not running,
    )


if __name__ == "__main__":
    # debug stays off: its auto-reloader would start the app twice and duplicate test threads.
    app.run(host=HOST, port=PORT, debug=False)
