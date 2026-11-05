"""ML analyzer panel for Circuit Studio: upload battery files or pick a database battery, and get a
second-life suggestion.

Two engines, tried in this order (engine "Auto"):
    full  revive-tery-ml, through ml_engine_bridge: data-quality checks, safety gate, ML remaining life with
          an interval, physics projections and economics. It needs timestamps and capacity data.
    lite  ml_analyzer_suggester: capacity-based triage, used when the data can't meet the full engine's
          contract. The panel says why it fell back.
Uploads still go through BatteryFileExtractor -> DuckDBSeeder first, so every upload is stored and readable
by both engines. A zip holding a data-contract bundle (metadata.json + telemetry) goes straight to the full engine.
It adds one card to the page and its own callbacks; it does not touch the test-bench callbacks.

app.py wires it in with two calls:
    ml_panel.layout(styles)   inside serve_layout()
    ml_panel.register(app)    after the Dash app is created
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
from dash import Dash, Input, Output, State, callback_context, dash_table, dcc, html, no_update

import ml_engine_bridge as bridge
from bms_engine import DatabaseUnavailable, list_battery_ids, open_db
from ml_analyzer_suggester import (
    BatterySpec,
    DuckDBSeeder,
    IngestionError,
    SecondLifeSuggester,
    ingest_and_suggest,
)

ENGINE_AUTO = "auto"
ENGINE_LITE = "lite"


@dataclass(frozen=True)
class FormSpec:
    """The panel's form, in the shape ml_engine_bridge.Spec expects."""
    chemistry: str
    series_cells: int
    parallel_cells: int = 1
    rated_capacity_ah: float | None = None
    nominal_voltage_v: float | None = None

# Uploaded rows go into this module's own tables (ml_telemetry, ml_ingest_log) in the project
# database; the demo tables are never changed. Resolved from this file so the cwd doesn't matter.
#   Set REVIVE_ML_DB to another .duckdb file to test without writing into the project database.
DB_PATH = Path(os.environ.get("REVIVE_ML_DB") or os.environ.get("REVIVE_DB")
               or Path(__file__).resolve().parents[2] / "data" / "db" / "revive_tery.duckdb")
MAX_UPLOAD_BYTES = 200 * 1024 * 1024

DECISION_COLOURS = {"Second-Life Reuse": "#0ca30c", "Repurpose": "#2a78d6", "Buy New": "#fab219",
                    "Recycle": "#d03b3b"}
VERDICT_COLOURS = {"Pass": "#0ca30c", "Quarantine": "#fab219", "Reject": "#d03b3b"}

_styles: dict[str, Any] = {}


def _s(name: str) -> dict[str, Any]:
    return _styles.get(name, {})


def _labelled(text: str, control: Any) -> html.Div:
    return html.Div(style={"flex": "1", "minWidth": "140px"}, children=[
        html.Label(text, style={**_s("CAPTION"), "display": "block", "marginBottom": "3px"}), control])


def _database_battery_options() -> list[str]:
    try:
        return list_battery_ids(DB_PATH)
    except DatabaseUnavailable:
        return []


def _engine_status() -> html.Div:
    if bridge.ENGINE_AVAILABLE:
        return html.Div(f"Full ML engine connected: revive-tery-ml {bridge.ENGINE_VERSION}. The lite analyzer is "
                        "the fallback when data lacks timestamps or capacity.",
                        style={**_s("CAPTION"), "color": "#0ca30c", "marginBottom": "8px"})
    return html.Div(f"Lite analyzer only: {bridge.ENGINE_IMPORT_ERROR}",
                    style={**_s("CAPTION"), "color": "#9a6a00", "marginBottom": "8px"})


def layout(styles: dict[str, Any]) -> html.Div:
    """The ML card. `styles` passes app.py's CARD, CAPTION, SECTION_TITLE, INPUT and button styles."""
    _styles.update(styles)
    db_batteries = _database_battery_options()
    return html.Div(style={**_s("CARD"), "marginTop": "12px"}, children=[
        html.H3("ML analyzer: second-life suggestion for a battery", style=_s("SECTION_TITLE")),
        _engine_status(),
        html.Div("Upload .csv, .xlsx or .zip files, or a zipped data-contract bundle (metadata.json plus "
                 "telemetry). Columns are matched to voltage_v, current_a, temperature_c, capacity_ah, cycle_index "
                 "and timestamp_utc by name; unmatched columns are listed, never guessed. Uploaded rows are stored "
                 "in the ml_telemetry table.", style={**_s("CAPTION"), "marginBottom": "10px"}),
        html.Div(style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "alignItems": "flex-end"}, children=[
            html.Div(style={"flex": "2", "minWidth": "260px"}, children=[
                dcc.Upload(id="ml-upload", multiple=True, max_size=MAX_UPLOAD_BYTES, children=html.Div([
                    "Drag files here or ", html.A("choose files", style={"textDecoration": "underline"})]),
                    style={"border": "1px dashed #c3c2b7", "borderRadius": "8px", "padding": "18px",
                           "textAlign": "center", "cursor": "pointer"}),
                html.Div(id="ml-upload-names", style={**_s("CAPTION"), "marginTop": "4px"}),
            ]),
            _labelled("Chemistry", dcc.Dropdown(id="ml-chemistry", clearable=False, value="LFP",
                                                options=["LFP", "NMC", "NCA"])),
            _labelled("Cells in series", dcc.Input(id="ml-series", type="number", min=1, step=1, value=1,
                                                   style=_s("INPUT"))),
            _labelled("Rated capacity (Ah, optional)", dcc.Input(id="ml-rated", type="number", min=0,
                                                                 step=0.01, style=_s("INPUT"))),
            _labelled("Data is", dcc.Dropdown(id="ml-provenance", clearable=False, value="synthetic",
                                              options=["synthetic", "simulated", "measured"])),
            _labelled("Engine", dcc.Dropdown(id="ml-engine", clearable=False, value=ENGINE_AUTO, options=[
                {"label": "Auto: full ML, else lite", "value": ENGINE_AUTO},
                {"label": "Lite analyzer only", "value": ENGINE_LITE}])),
            html.Button("Analyze files", id="ml-analyze", n_clicks=0, style=_s("PRIMARY_BUTTON")),
        ]),
        html.Div(style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "alignItems": "flex-end",
                        "marginTop": "10px"}, children=[
            _labelled("Or assess a database battery", dcc.Dropdown(
                id="ml-db-battery", options=db_batteries, value=db_batteries[0] if db_batteries else None,
                placeholder="No batteries in the database")),
            html.Button("Assess with the full ML engine", id="ml-assess-db", n_clicks=0, style=_s("BUTTON"),
                        disabled=not (bridge.ENGINE_AVAILABLE and db_batteries)),
            html.Div(style={"flex": "2"}),
        ]),
        dcc.Loading(type="dot", children=html.Div(id="ml-messages", style={"marginTop": "10px"})),
        html.Div(style={"display": "flex", "gap": "12px", "alignItems": "flex-end", "marginTop": "8px"}, children=[
            _labelled("Battery", dcc.Dropdown(id="ml-battery", placeholder="Analyze files to list batteries")),
            html.Div(style={"flex": "3"}),
        ]),
        html.Div(id="ml-result", style={"marginTop": "10px"}),
        dcc.Store(id="ml-reports"),
        dcc.Store(id="ml-spec"),
    ])


# ------------------------------------------------------------------------------------
# Rendering helpers
# ------------------------------------------------------------------------------------

def _num(tagged: dict | None, digits: int = 2, unit: bool = True) -> str:
    if not tagged or tagged.get("value") is None:
        return "n/a"
    v = tagged["value"]
    text = f"{v:,.{digits}f}" if isinstance(v, int | float) else str(v)
    return f"{text} {tagged.get('unit', '')}".strip() if unit else text


def _pill(text: str, colour: str) -> html.Span:
    return html.Span(text, style={"background": colour, "color": "white", "borderRadius": "12px",
                                  "padding": "2px 10px", "fontWeight": 600, "fontSize": "12px"})


def _kv(label: str, value: str, caption: str = "") -> html.Div:
    return html.Div(style={**_s("CARD"), "flex": "1", "minWidth": "150px", "padding": "10px 12px"}, children=[
        html.Div(label, style=_s("CAPTION")),
        html.Div(value, style={"fontSize": "18px", "fontWeight": 600}),
        html.Div(caption, style=_s("CAPTION")),
    ])


def _capacity_figure(df) -> go.Figure | None:
    cap = df.dropna(subset=["capacity_ah"])
    if cap.empty:
        return None
    if cap["cycle_index"].notna().any():
        per = cap.groupby("cycle_index")["capacity_ah"].max().sort_index()
        x, title = per.index.astype(float), "Cycle"
    else:
        per = cap["capacity_ah"].reset_index(drop=True)
        x, title = per.index, "Row"
    fig = go.Figure(go.Scatter(x=list(x), y=list(per.to_numpy()), mode="lines+markers",
                               marker={"size": 4}, line={"color": "#2a78d6"}, name="Capacity"))
    fig.update_layout(title="Capacity per cycle", height=260, margin=dict(l=40, r=10, t=36, b=36),
                      xaxis_title=title, yaxis_title="Ah", plot_bgcolor="white", paper_bgcolor="white")
    return fig


def _voltage_figure(df) -> go.Figure:
    d = df.tail(5000)
    fig = go.Figure(go.Scatter(y=list(d["voltage_v"]), mode="lines", line={"color": "#52514e"}, name="Voltage"))
    fig.update_layout(title="Voltage (last 5,000 rows)", height=260, margin=dict(l=40, r=10, t=36, b=36),
                      xaxis_title="Row", yaxis_title="V", plot_bgcolor="white", paper_bgcolor="white")
    return fig


def render_report(report: dict[str, Any], mapping: dict[str, Any] | None) -> list:
    """Turn one suggester report into cards, charts and tables."""
    sug = report.get("suggestion") or {}
    cat = sug.get("category")
    colour = DECISION_COLOURS.get(cat or "", "#52514e")
    children: list = [html.Div(style={**_s("CARD"), "borderLeft": f"6px solid {colour}", "marginBottom": "10px"},
                               children=[
        html.Div("Suggestion", style=_s("CAPTION")),
        html.Div(sug.get("decision", "n/a"), style={"fontSize": "20px", "fontWeight": 700, "color": colour}),
        html.Div(sug.get("reason", ""), style={"marginTop": "4px"}),
        html.Div(f"Placeholder economic inputs: {', '.join(sug['placeholder_inputs'])}. Replace them in "
                 "ml_analyzer_suggester.ECONOMICS before relying on the money figures.",
                 style={**_s("CAPTION"), "marginTop": "6px"}) if sug.get("placeholder_inputs") else None,
    ])]
    for w in report.get("warnings", []):
        children.append(html.Div(w, style={**_s("CAPTION"), "color": "#9a6a00", "marginBottom": "6px"}))

    # How the file was read
    if mapping:
        rows = []
        for src, m in mapping.items():
            rows.append({"file": src,
                         "mapped": ", ".join(f"{k} -> {v}" for k, v in m["mapped"].items()),
                         "not used": ", ".join(m["unmapped"]) or "-",
                         "warnings": "; ".join(m["warnings"]) or "-"})
        children.append(html.Details(open=True, style={"marginBottom": "10px"}, children=[
            html.Summary("1. How the files were read", style={"fontWeight": 600, "cursor": "pointer"}),
            dash_table.DataTable(rows, style_cell={"textAlign": "left", "whiteSpace": "normal",
                                                   "fontFamily": "inherit", "fontSize": "12px"}),
        ]))

    # Safety gate
    gate = report.get("safety_gate") or {}
    if gate:
        children.append(html.Details(open=True, style={"marginBottom": "10px"}, children=[
            html.Summary("2. Safety gate", style={"fontWeight": 600, "cursor": "pointer"}),
            html.Div(style={"display": "flex", "gap": "10px", "alignItems": "center", "margin": "6px 0"}, children=[
                _pill(gate["verdict"], VERDICT_COLOURS.get(gate["verdict"], "#52514e")),
                html.Span(gate.get("wording", ""), style=_s("CAPTION")),
            ]),
            html.Div(style={"display": "flex", "gap": "10px", "flexWrap": "wrap"}, children=[
                _kv("Lowest cell voltage", _num(gate.get("min_cell_voltage"), 3),
                    f"limit {gate['limits']['cell_v_min']['value']} V"),
                _kv("Highest temperature", _num(gate.get("max_temperature"), 1),
                    f"limit {gate['limits']['temp_max_c']['value']} degC"),
            ]),
            html.Ul([html.Li(r) for r in gate.get("reasons", [])] or [html.Li("no limit breached")]),
            html.Div(gate.get("note", ""), style=_s("CAPTION")),
        ]))

    # State estimate
    st = report.get("state") or {}
    if st:
        cards = [_kv("State of health", _num(st.get("soh"), 1), "capacity / rated"),
                 _kv("Current capacity", _num(st.get("current_capacity"), 3), "median of last 5 cycles"),
                 _kv("Rated capacity", _num(st.get("rated_capacity"), 3),
                     (st.get("rated_capacity") or {}).get("note", "")),
                 _kv("Fade rate", _num(st.get("fade_rate"), 4), "SoH points per cycle"),
                 _kv("Cycles to 60 % SoH", _num(st.get("cycles_to_end_of_use"), 0), "linear, optimistic"),
                 _kv("Resistance proxy", _num(st.get("resistance_proxy"), 1), "|dV/dI| between rows"),
                 _kv("Voltage variance", _num(st.get("voltage_variance"), 4), "")]
        children.append(html.Details(open=True, style={"marginBottom": "10px"}, children=[
            html.Summary("3. State estimate", style={"fontWeight": 600, "cursor": "pointer"}),
            html.Div(st.get("reason", ""), style={"color": "#d03b3b"}) if st.get("status") != "ok" else None,
            html.Div(cards, style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginTop": "6px"}),
        ]))

    # Economics
    econ = report.get("economics") or {}
    if econ:
        rows = [{"use case": o["use_case"], "category": o["category"],
                 "service years": _num(o["service_years"], 1, False),
                 "energy value (USD)": _num(o["energy_value"], 0, False),
                 "buy-new cap (USD)": _num(o["buy_new_cap"], 0, False),
                 "refurbish cost (USD)": _num(o["refurbishment_cost"], 0, False),
                 "net value (USD)": _num(o["net_value"], 0, False),
                 "cost per kWh delivered": _num(o["cost_per_kwh_delivered"], 3, False)}
                for o in econ.get("options", [])]
        children.append(html.Details(open=True, style={"marginBottom": "10px"}, children=[
            html.Summary("4. Cost comparison", style={"fontWeight": 600, "cursor": "pointer"}),
            html.Div(style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "margin": "6px 0"}, children=[
                _kv("Pack energy now", _num(econ.get("pack_energy_now"), 2), "nominal V x capacity"),
                _kv("Recycle now", _num(econ.get("recycle_now"), 0), "placeholder value"),
                _kv("New storage cost", _num(econ.get("new_storage_cost_per_kwh_delivered"), 3),
                    "per kWh delivered (benchmark)"),
            ]),
            dash_table.DataTable(rows, style_cell={"textAlign": "left", "fontFamily": "inherit",
                                                   "fontSize": "12px"}) if rows else
            html.Div("SoH is below every reuse threshold, so no reuse option was costed.", style=_s("CAPTION")),
        ]))
    return children


FULL_DECISION_COLOURS = (("Second-Life", "#0ca30c"), ("Recycle", "#d03b3b"), ("Inspection", "#fab219"),
                         ("Insufficient", "#9a6a00"))
STATUS_COLOURS = {"pass": "#0ca30c", "warn": "#fab219", "fail": "#d03b3b", "inconclusive": "#9a6a00",
                  "not_applicable": "#898781"}


def _tagged_text(tagged: Any, digits: int = 2) -> str:
    """A number from the full engine, which tags every value with its provenance."""
    if not isinstance(tagged, dict) or tagged.get("value") is None:
        return "n/a"
    v = tagged["value"]
    text = f"{v:,.{digits}f}" if isinstance(v, int | float) else str(v)
    return f"{text} {tagged.get('unit', '')}".strip()


def _projection_figure(proj: dict[str, Any]) -> go.Figure:
    """SOH over the years for one workload, with the engine's two uncertainty bands kept separate."""
    pts = proj.get("points") or []
    years = [p["year"] for p in pts]
    central = [(p.get("soh") or {}).get("value") for p in pts]
    fig = go.Figure()
    for key, name, colour in (("mc_band", "Monte Carlo band (assumption-conditional)", "rgba(235,104,52,0.18)"),
                              ("ml_band", "ML interval band", "rgba(42,120,214,0.22)")):
        lo = [(p.get(key) or {}).get("values", [None, None])[0] for p in pts]
        hi = [(p.get(key) or {}).get("values", [None, None])[1] for p in pts]
        fig.add_trace(go.Scatter(x=years + years[::-1], y=hi + lo[::-1], fill="toself", fillcolor=colour,
                                 line={"width": 0}, name=name, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=years, y=central, mode="lines", line={"color": "#2a78d6", "width": 2}, name="Central"))
    knee = [(p.get("knee_scenario") or {}).get("value") for p in pts]
    if any(v is not None for v in knee):
        fig.add_trace(go.Scatter(x=years, y=knee, mode="lines", line={"color": "#52514e", "dash": "dash"},
                                 name="Late-life knee scenario"))
    limit = ((proj.get("workload") or {}).get("values") or {}).get("min_soh_pct")
    if limit is not None:
        fig.add_hline(y=limit, line={"color": "#d03b3b", "dash": "dot"}, annotation_text=f"limit {limit} %")
    fig.update_layout(title=f"{proj.get('workload', {}).get('label', '')}: {proj.get('label', '')}", height=300,
                      margin=dict(l=40, r=10, t=40, b=36), xaxis_title="Years from now", yaxis_title="SOH %",
                      plot_bgcolor="white", paper_bgcolor="white", legend={"orientation": "h", "y": -0.25})
    return fig


def render_full_report(report: dict[str, Any], notes: list[str]) -> list:
    """Turn one revive-tery-ml report into cards, charts and tables."""
    decision = report.get("decision", "n/a")
    colour = next((c for prefix, c in FULL_DECISION_COLOURS if decision.startswith(prefix)), "#52514e")
    summary = bridge.summarize_full(report)
    readiness = report["data_quality"]["readiness"]
    gate = report.get("gate") or {}
    children: list = [html.Div(style={**_s("CARD"), "borderLeft": f"6px solid {colour}", "marginBottom": "10px"},
                               children=[
        html.Div(f"Suggestion from the full ML engine ({report.get('engine', 'revive-tery-ml')})", style=_s("CAPTION")),
        html.Div(decision, style={"fontSize": "20px", "fontWeight": 700, "color": colour}),
        html.Ul([html.Li(r) for r in report.get("rationale") or []], style={"margin": "6px 0"}),
        html.Div(style={"display": "flex", "gap": "8px", "flexWrap": "wrap", "alignItems": "center"}, children=[
            _pill(f"Data: {readiness['verdict']}", STATUS_COLOURS["pass" if readiness["verdict"] == "READY" else
                                                                 "fail" if readiness["verdict"] == "NOT_READY" else "warn"]),
            _pill(f"Gate: {gate['verdict']}", VERDICT_COLOURS.get(gate["verdict"], "#52514e")) if gate else None,
            html.Span(f"Old fixed-threshold rule would say: {summary['legacy_rule']}", style=_s("CAPTION"))
            if summary.get("legacy_rule") else None,
        ]),
    ])]
    for w in [*notes, *report.get("warnings", [])]:
        children.append(html.Div(w, style={**_s("CAPTION"), "color": "#9a6a00", "marginBottom": "6px"}))

    checks = report["data_quality"]["checks"]
    children.append(html.Details(open=readiness["verdict"] != "READY", style={"marginBottom": "10px"}, children=[
        html.Summary(f"1. Data quality: {readiness['n_pass']} pass, {readiness['n_warn']} warn, "
                     f"{readiness['n_fail']} fail, {readiness['n_inconclusive']} inconclusive",
                     style={"fontWeight": 600, "cursor": "pointer"}),
        html.Div(readiness.get("rule_applied", ""), style={**_s("CAPTION"), "margin": "4px 0"}),
        dash_table.DataTable([{"check": c["name"], "status": c["status"], "severity": c["severity"],
                               "finding": c["message"]} for c in checks],
                             style_cell={"textAlign": "left", "whiteSpace": "normal", "fontFamily": "inherit",
                                         "fontSize": "12px"},
                             style_data_conditional=[{"if": {"filter_query": f'{{status}} = "{s}"', "column_id": "status"},
                                                      "color": col, "fontWeight": 600} for s, col in STATUS_COLOURS.items()]),
    ]))

    if gate:
        children.append(html.Details(open=True, style={"marginBottom": "10px"}, children=[
            html.Summary("2. Safety gate", style={"fontWeight": 600, "cursor": "pointer"}),
            html.Div(style={"display": "flex", "gap": "10px", "alignItems": "center", "margin": "6px 0"}, children=[
                _pill(gate["verdict"], VERDICT_COLOURS.get(gate["verdict"], "#52514e")),
                html.Span(gate.get("wording", ""), style=_s("CAPTION")),
            ]),
            html.Ul([html.Li(r) for r in gate.get("reasons", [])] or [html.Li("no limit breached")]),
        ]))

    st = report.get("state") or {}
    if st:
        rul = st.get("rul_cycles_reference") or {}
        interval = f"{rul.get('lower', 'n/a')} to {rul.get('upper', 'n/a')} cycles" if rul else ""
        coverage = rul.get("measured_coverage_on_held_out_cells")
        cards = [_kv("State of health", _tagged_text(st.get("soh"), 1), (st.get("soh") or {}).get("note", "")),
                 _kv("Remaining life (reference)", _tagged_text(rul, 0),
                     f"{interval}; measured coverage {coverage:.0%} on held-out cells" if coverage else interval),
                 _kv("Fade rate", _tagged_text(st.get("fade_rate_ref"), 6), "SOH fraction per reference cycle")]
        children.append(html.Details(open=True, style={"marginBottom": "10px"}, children=[
            html.Summary("3. State estimate (ML)", style={"fontWeight": 600, "cursor": "pointer"}),
            html.Div(cards, style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginTop": "6px"}),
            html.Div(st.get("distribution_shift_note", ""), style={**_s("CAPTION"), "marginTop": "6px"})
            if st.get("out_of_distribution") else None,
        ]))

    projections = report.get("projections") or {}
    if projections:
        rec_key = (report.get("recommendation") or {}).get("application")
        first = rec_key if rec_key in projections else next(iter(projections))
        rows = []
        for key, proj in projections.items():
            years = proj.get("years_to_application_limit") or {}
            rows.append({"application": (proj.get("workload") or {}).get("label", key),
                         "central (years)": _tagged_text(years.get("central"), 1),
                         "ML range (years)": f"{_tagged_text(years.get('ml_conservative'), 1)} to "
                                             f"{_tagged_text(years.get('ml_optimistic'), 1)}",
                         "Monte Carlo 5-95 % (years)": f"{_tagged_text(years.get('mc_p05'), 1)} to "
                                                       f"{_tagged_text(years.get('mc_p95'), 1)}",
                         "conservative (years)": _tagged_text(proj.get("conservative_years"), 1)})
        children.append(html.Details(open=True, style={"marginBottom": "10px"}, children=[
            html.Summary("4. Projected life per application (physics model)", style={"fontWeight": 600,
                                                                                   "cursor": "pointer"}),
            html.Div("Projections, not predictions: public training data stops near 80 % SOH. The Monte Carlo band "
                     "depends on assumed parameters.", style={**_s("CAPTION"), "margin": "4px 0"}),
            html.Div(dcc.Graph(figure=_projection_figure(projections[first]), config={"displayModeBar": False}),
                     style={**_s("CARD"), "marginBottom": "8px"}),
            dash_table.DataTable(rows, style_cell={"textAlign": "left", "fontFamily": "inherit", "fontSize": "12px"}),
        ]))

    econ = report.get("economics") or {}
    if econ.get("second_life_options"):
        rows = []
        for key, opt in econ["second_life_options"].items():
            row = {"application": opt.get("label", key)}
            for field, value in opt.items():
                if isinstance(value, dict) and "value" in value:
                    row[field.replace("_", " ")] = _tagged_text(value, 1)
            rows.append(row)
        recycle = econ.get("recycle") or {}
        children.append(html.Details(open=True, style={"marginBottom": "10px"}, children=[
            html.Summary("5. Economics", style={"fontWeight": 600, "cursor": "pointer"}),
            html.Div(style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "margin": "6px 0"}, children=[
                _kv("Pack energy", _tagged_text(econ.get("pack_energy"), 2), "nominal V x rated capacity"),
                _kv("Recycle now (net)", _tagged_text(recycle.get("net_value"), 0), "composition x recovery x payable"),
                _kv("Discount rate", _tagged_text(econ.get("discount_rate"), 2), "assumed"),
            ]),
            dash_table.DataTable(rows, style_cell={"textAlign": "left", "fontFamily": "inherit", "fontSize": "12px"}),
            html.Div(f"Placeholder inputs: {', '.join(econ.get('placeholder_inputs', []))}. Replace them in "
                     "revive-tery-ml/configs/economics.yaml before relying on the money figures.",
                     style={**_s("CAPTION"), "marginTop": "6px"}) if econ.get("placeholder_inputs") else None,
        ]))

    children.append(html.Details(children=[
        html.Summary("Full report JSON (every number with its provenance)", style={"fontWeight": 600,
                                                                                   "cursor": "pointer"}),
        html.Pre(json.dumps(report, indent=1, default=str)[:200_000],
                 style={"fontSize": "11px", "maxHeight": "400px", "overflow": "auto", "whiteSpace": "pre-wrap"}),
    ]))
    return children


# ------------------------------------------------------------------------------------
# Running the engines
# ------------------------------------------------------------------------------------

def _error(text: str) -> html.Div:
    return html.Div(text, style={"color": "#d03b3b"})


def _run_full(bundle) -> dict[str, Any]:
    return json.loads(json.dumps(bridge.run_full(bundle), default=str))   # plain JSON for the Store


def _try_full(battery_id: str, spec: FormSpec) -> tuple[dict[str, Any] | None, str]:
    """The full engine on stored upload rows, or (None, why it couldn't run)."""
    if not bridge.ENGINE_AVAILABLE:
        return None, bridge.ENGINE_IMPORT_ERROR
    try:
        bundle = bridge.bundle_from_rows(DuckDBSeeder(DB_PATH).load_battery(battery_id), battery_id, spec,
                                         source="Circuit Studio")
        return _run_full(bundle), ""
    except bridge.AdapterError as exc:
        return None, str(exc)
    except Exception as exc:  # noqa: BLE001 - an engine failure falls back to lite, and says so
        return None, f"the full engine failed: {exc}"


def analyze_uploads(paths: list[Path], spec: FormSpec, provenance: str, engine: str) -> tuple[dict, list]:
    """Run uploads through the engines. Returns (store, messages)."""
    results: dict[str, Any] = {}
    msgs: list = []
    mappings: dict[str, Any] = {}
    contract = [p for p in paths if p.suffix.lower() == ".zip" and bridge.is_contract_zip(p)]
    others = [p for p in paths if p not in contract]

    for path in contract:
        if engine == ENGINE_LITE or not bridge.ENGINE_AVAILABLE:
            msgs.append(_error(f"{path.name} is a data-contract bundle, which only the full ML engine reads."))
            continue
        try:
            bundle = bridge.bundle_from_zip(path, MAX_UPLOAD_BYTES)
            results[bundle.meta.asset_id] = {"engine": "full", "report": _run_full(bundle), "notes": []}
            msgs.append(html.Div(f"{path.name}: data-contract bundle for {bundle.meta.asset_id}, assessed by the "
                                 "full ML engine.", style={"color": "#0ca30c"}))
        except bridge.AdapterError as exc:
            msgs.append(_error(f"{path.name}: {exc}"))

    if others:
        lite_spec = BatterySpec(chemistry=spec.chemistry, series_cells=spec.series_cells,
                                rated_capacity_ah=spec.rated_capacity_ah)
        result = ingest_and_suggest(others, lite_spec, db_path=DB_PATH, data_provenance=provenance)
        msgs.extend(_error(e) for e in result["errors"])
        if result["reports"]:
            ing = result["ingest"]
            mappings = ing["column_mappings"]
            msgs.append(html.Div(f"Stored {ing['rows_inserted']:,} rows from {len(ing['files'])} table(s) "
                                 f"(ingest {ing['ingest_id']}). Batteries: {', '.join(ing['battery_ids'])}.",
                                 style={"color": "#0ca30c"}))
        for battery_id, lite_report in result["reports"].items():
            if engine == ENGINE_AUTO:
                full, why = _try_full(battery_id, spec)
                if full is not None:
                    results[battery_id] = {"engine": "full", "report": full, "notes": [],
                                           "lite_decision": (lite_report.get("suggestion") or {}).get("decision")}
                    continue
                note = f"Full ML engine skipped: {why}. This is the lite analyzer's suggestion."
            else:
                note = "Lite analyzer chosen in the Engine menu."
            results[battery_id] = {"engine": "lite", "report": lite_report, "notes": [note]}
    return {"results": results, "mappings": mappings}, msgs


def assess_database_battery(battery_id: str) -> tuple[dict, list]:
    """The full engine on a battery that has asset records in the project database (the demo pack)."""
    with open_db(read_only=True, path=DB_PATH) as con:
        bundle = bridge.bundle_from_database(con, battery_id)
    report = _run_full(bundle)
    store = {"results": {battery_id: {"engine": "full", "report": report, "notes": [
        "Assessed from the project database's own tables (battery_asset, telemetry, health_history, safety_events)."]}},
        "mappings": {}}
    return store, [html.Div(f"{battery_id}: assessed by the full ML engine from the database.",
                            style={"color": "#0ca30c"})]


# ------------------------------------------------------------------------------------
# Callbacks
# ------------------------------------------------------------------------------------

def register(app: Dash) -> None:
    @app.callback(Output("ml-upload-names", "children"), Input("ml-upload", "filename"))
    def show_names(names):
        return f"Selected: {', '.join(names)}" if names else ""

    @app.callback(
        Output("ml-reports", "data"), Output("ml-spec", "data"), Output("ml-messages", "children"),
        Output("ml-battery", "options"), Output("ml-battery", "value"),
        Input("ml-analyze", "n_clicks"), Input("ml-assess-db", "n_clicks"),
        State("ml-upload", "contents"), State("ml-upload", "filename"),
        State("ml-chemistry", "value"), State("ml-series", "value"), State("ml-rated", "value"),
        State("ml-provenance", "value"), State("ml-engine", "value"), State("ml-db-battery", "value"),
        prevent_initial_call=True,
    )
    def analyze(_clicks, _db_clicks, contents, names, chemistry, series, rated, provenance, engine, db_battery):
        fail = (no_update, no_update)
        spec = FormSpec(chemistry=chemistry, series_cells=int(series or 1),
                        rated_capacity_ah=float(rated) if rated else None)
        try:
            if callback_context.triggered_id == "ml-assess-db":
                if not db_battery:
                    return *fail, _error("Choose a database battery first."), no_update, no_update
                store, msgs = assess_database_battery(db_battery)
            else:
                if not contents:
                    return *fail, _error("Choose at least one file first."), no_update, no_update
                with tempfile.TemporaryDirectory(prefix="revive_ml_upload_") as tmp:
                    paths = []
                    for content, name in zip(contents, names, strict=True):
                        try:
                            _, b64 = content.split(",", 1)
                            target = Path(tmp) / Path(name).name   # basename only: no path tricks from the browser
                            target.write_bytes(base64.b64decode(b64))
                            paths.append(target)
                        except (ValueError, OSError) as exc:
                            return *fail, _error(f"Could not read {name}: {exc}"), no_update, no_update
                    store, msgs = analyze_uploads(paths, spec, provenance, engine or ENGINE_AUTO)
        except (IngestionError, bridge.AdapterError, DatabaseUnavailable, ValueError) as exc:
            return *fail, _error(str(exc)), no_update, no_update
        except Exception as exc:  # noqa: BLE001 - shown to the user instead of a blank page
            return *fail, _error(f"Database or analysis error: {exc}"), no_update, no_update
        if not store["results"]:
            return *fail, msgs or "No battery telemetry found.", no_update, no_update
        ids = list(store["results"])
        return store, spec.__dict__, msgs, [{"label": b, "value": b} for b in ids], ids[0]

    @app.callback(Output("ml-result", "children"), Input("ml-battery", "value"), State("ml-reports", "data"),
                  prevent_initial_call=True)
    def show_battery(battery_id, store):
        if not battery_id or not store:
            return no_update
        entry = store["results"].get(battery_id)
        if entry is None:
            return html.Div("No report for this battery.")
        if entry["engine"] == "full":
            children = render_full_report(entry["report"], entry.get("notes", []))
            if entry.get("lite_decision"):
                children.insert(1, html.Div(f"For comparison, the lite analyzer suggested: {entry['lite_decision']}",
                                            style={**_s("CAPTION"), "marginBottom": "8px"}))
        else:
            report = entry["report"]
            # only the files that contained this battery
            mapping = {src: m for src, m in store["mappings"].items()
                       if any(src == f for f in _files_for(battery_id))} or store["mappings"]
            children = render_report(report, mapping)
            for note in reversed(entry.get("notes", [])):
                children.insert(1, html.Div(note, style={**_s("CAPTION"), "color": "#9a6a00", "marginBottom": "6px"}))
            children.append(html.Details(children=[
                html.Summary("Full report table (every number with its provenance)",
                             style={"fontWeight": 600, "cursor": "pointer"}),
                dash_table.DataTable(SecondLifeSuggester.to_dataframe(report).astype(str).to_dict("records"),
                                     page_size=25, style_cell={"textAlign": "left", "fontSize": "12px",
                                                               "fontFamily": "inherit"}),
            ]))
        df = DuckDBSeeder(DB_PATH).load_battery(battery_id)
        if not df.empty:
            figs = [f for f in (_capacity_figure(df), _voltage_figure(df)) if f is not None]
            children.insert(1, html.Div(style={"display": "flex", "gap": "12px", "flexWrap": "wrap",
                                               "marginBottom": "10px"},
                                        children=[html.Div(dcc.Graph(figure=f, config={"displayModeBar": False}),
                                                           style={**_s("CARD"), "flex": "1", "minWidth": "300px"})
                                                  for f in figs]))
        return children


def _files_for(battery_id: str) -> list[str]:
    """Source files that hold rows for this battery (from the ingest log tables)."""
    df = DuckDBSeeder(DB_PATH).load_battery(battery_id)
    return sorted(df["source_file"].unique()) if not df.empty else []
