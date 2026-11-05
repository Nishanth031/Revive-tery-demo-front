"""Virtual test bench page: run the 30 second synthetic pulse and read its result."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QProgressBar, QPushButton, QWidget,
)

import theme
from app_state import AppState
from bms_engine import ADAPTERS, PULSE_DURATION_S, SCENARIOS, check_compatibility, evaluate, screening_summary, stress_test
from widgets import Badge, Banner, Card, Disclosure, KpiTile, LineChart, Page, Series, fit_combo, fmt, label

TICK_MS = 250
STATUS_TONES = {"READY": "good", "REVIEW": "warning", "FAULT": "critical", "BLOCKED": "serious"}
METHOD_NOTE = (
    "State of health: once the current step is measurable, pack resistance is estimated as R ≈ |ΔV| / |ΔI|. "
    "The SOH proxy is reference resistance ÷ estimated resistance × 100, limited to 0–100%. A profile's own SOH "
    "only sets how the synthetic battery ages. It isn't copied to the result.\n\n"
    "State of charge starts from the profile, or from a voltage estimate if it's missing, then follows coulomb "
    "counting: ΔSOC (%) = current (A) × time (h) ÷ capacity (Ah) × 100.\n\n"
    "Voltage responds to the stepped load through internal resistance, ΔV ≈ I × R, with small SOC and temperature "
    "effects. The requested voltage is a target, and no DC/DC converter is modeled. The peak current is what the "
    "load asks for, so delivered current can be lower.\n\n"
    "This is an educational screening estimate. It can't predict an explosion, certify reuse or establish physical "
    "battery safety."
)


def _seconds(x: float) -> str:
    return f"{x:g} s"


class BenchPage(Page):
    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__("Virtual test bench", "A 30 second synthetic pulse. No real battery is connected, and every reading here is simulated.", parent=parent)
        self.state = state
        self.result: dict | None = None
        self.tested_profile = None
        self.index = 0
        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self._tick)

        controls = Card()
        form = QGridLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(6)
        self.battery = fit_combo(QComboBox(), 26)
        self.adapter = fit_combo(QComboBox(), 26)
        for adapter in ADAPTERS:
            self.adapter.addItem(adapter.name, adapter.id)
        self.scenario = fit_combo(QComboBox(), 18)
        self.scenario.addItems(SCENARIOS)
        self.mode = fit_combo(QComboBox(), 18)
        self.mode.addItems(["Discharge", "Charge"])
        self.target_voltage = QDoubleSpinBox()
        self.target_voltage.setRange(0.1, 100000)
        self.target_voltage.setDecimals(2)
        self.target_voltage.setSuffix(" V")
        self.demand = QDoubleSpinBox()
        self.demand.setRange(0, 100000)
        self.demand.setDecimals(2)
        self.demand.setSuffix(" A")
        self.demand.setSpecialValueText("Auto, from scenario")
        self.demand.setValue(0)
        for column, (title, widget) in enumerate((("Battery", self.battery), ("Virtual adapter", self.adapter), ("Scenario", self.scenario))):
            form.addWidget(label(title, "kpiLabel"), 0, column)
            form.addWidget(widget, 1, column)
        for column, (title, widget) in enumerate((("Direction", self.mode), ("Requested voltage", self.target_voltage), ("Peak current demand", self.demand))):
            form.addWidget(label(title, "kpiLabel"), 2, column)
            form.addWidget(widget, 3, column)
        form.setColumnStretch(0, 2)
        form.setColumnStretch(1, 2)
        form.setColumnStretch(2, 2)
        controls.body.addLayout(form)

        run_row = QHBoxLayout()
        run_row.setSpacing(10)
        self.readiness = Badge()
        self.readiness_notes = label("", "caption", wrap=True)
        self.run_button = QPushButton("Start test")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self.start_test)
        self.finish_button = QPushButton("Skip to result")
        self.finish_button.setEnabled(False)
        self.finish_button.clicked.connect(self.finish_now)
        run_row.addWidget(self.readiness)
        run_row.addWidget(self.readiness_notes, 1)
        run_row.addWidget(self.finish_button)
        run_row.addWidget(self.run_button)
        controls.body.addLayout(run_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        controls.body.addWidget(self.progress)
        self.content.addWidget(controls)

        kpis = QHBoxLayout()
        kpis.setSpacing(12)
        self.kpi_soc = KpiTile("State of charge", caption="Simulated")
        self.kpi_soh = KpiTile("SOH proxy", caption="From simulated pulse")
        self.kpi_voltage = KpiTile("Terminal voltage", caption="Simulated")
        self.kpi_current = KpiTile("Delivered current", caption="Simulated")
        self.kpi_temp = KpiTile("Temperature", caption="Simulated")
        self.kpi_power = KpiTile("Power", caption="Simulated")
        for tile in (self.kpi_soc, self.kpi_soh, self.kpi_voltage, self.kpi_current, self.kpi_temp, self.kpi_power):
            kpis.addWidget(tile, 1)
        self.content.addLayout(kpis)

        charts = Card("Simulated traces")
        grid = QGridLayout()
        grid.setSpacing(14)
        self.chart_voltage = LineChart("Voltage", "V", _seconds)
        self.chart_current = LineChart("Current", "A", _seconds)
        self.chart_temp = LineChart("Temperature", "°C", _seconds)
        self.chart_soc = LineChart("State of charge", "%", _seconds)
        grid.addWidget(self.chart_voltage, 0, 0)
        grid.addWidget(self.chart_current, 0, 1)
        grid.addWidget(self.chart_temp, 1, 0)
        grid.addWidget(self.chart_soc, 1, 1)
        charts.body.addLayout(grid)
        self.content.addWidget(charts)

        results = Card("Result", spacing=8)
        self.verdict = Badge("Run a test to see a result", "neutral")
        self.use_text = label("", wrap=True)
        self.reason_text = label("", "caption", wrap=True)
        self.needed_text = label("", "caption", wrap=True)
        self.faults_text = label("", wrap=True)
        self.numbers_text = label("", "caption", wrap=True)
        for widget in (self.verdict, self.use_text, self.reason_text, self.faults_text, self.needed_text, self.numbers_text):
            results.body.addWidget(widget)
        method = label(METHOD_NOTE, "caption", wrap=True)
        results.body.addWidget(Disclosure("How these figures are calculated", method))
        self.content.addWidget(results)
        self.content.addWidget(Banner("Simulation only. This can't replace qualified engineering assessment of a real battery.", "info"))
        self.content.addStretch(1)

        self.voltage_series = Series("Terminal", theme.SERIES_1)
        self.target_series = Series("Requested", theme.SERIES_2)
        self.current_series = Series("Delivered", theme.SERIES_1)
        self.demand_series = Series("Requested", theme.SERIES_2)
        self.temp_series = Series("Temperature", theme.SERIES_1)
        self.soc_series = Series("SOC", theme.SERIES_1)
        # Requested goes first, so the actual reading is drawn on top when the two match.
        self.chart_voltage.set_series([self.target_series, self.voltage_series])
        self.chart_current.set_series([self.demand_series, self.current_series])
        self.chart_temp.set_series([self.temp_series])
        self.chart_soc.set_series([self.soc_series])
        self._all_series = (self.voltage_series, self.target_series, self.current_series, self.demand_series, self.temp_series, self.soc_series)
        self._charts = (self.chart_voltage, self.chart_current, self.chart_temp, self.chart_soc)

        self.battery.currentIndexChanged.connect(self._battery_changed)
        self.adapter.currentIndexChanged.connect(self._update_readiness)
        self.scenario.currentIndexChanged.connect(self._update_readiness)
        state.profiles_changed.connect(self._fill_batteries)
        self._fill_batteries()

    def _current_profile(self):
        return self.state.profile(self.battery.currentData()) if self.battery.count() else None

    def _fill_batteries(self) -> None:
        keep = self.battery.currentData()
        self.battery.blockSignals(True)
        self.battery.clear()
        for profile in self.state.all_profiles():
            self.battery.addItem(f"{profile.name} ({profile.id})", profile.id)
        index = self.battery.findData(keep)
        if index >= 0:
            self.battery.setCurrentIndex(index)
        self.battery.blockSignals(False)
        self._battery_changed()

    def select_battery(self, profile_id: str) -> None:
        index = self.battery.findData(profile_id)
        if index >= 0:
            self.battery.setCurrentIndex(index)

    def _battery_changed(self) -> None:
        profile = self._current_profile()
        if profile is None:
            return
        voltage = profile.measured_voltage_v if profile.measured_voltage_v is not None else profile.nominal_voltage_v
        if voltage is not None and voltage > 0:
            self.target_voltage.setValue(voltage)
        # Choose the first adapter that fits, so a usable pack doesn't start out blocked.
        for i, adapter in enumerate(ADAPTERS):
            if check_compatibility(profile, adapter)[0]:
                self.adapter.blockSignals(True)
                self.adapter.setCurrentIndex(i)
                self.adapter.blockSignals(False)
                break
        self._update_readiness()

    def _update_readiness(self) -> None:
        profile = self._current_profile()
        if profile is None:
            return
        adapter = next(a for a in ADAPTERS if a.id == self.adapter.currentData())
        check = evaluate(profile, adapter, self.scenario.currentText())
        # Every profile gets the generic SOC notice, so on its own it isn't worth flagging.
        notes = check["errors"] or check["faults"] or [w for w in check["warnings"] if not w.startswith("SOC is")]
        status = "READY" if check["status"] == "REVIEW" and not notes else check["status"]
        labels = {"READY": "Ready", "REVIEW": "Ready, with notes", "FAULT": "Fault scenario", "BLOCKED": "Adapter doesn't fit"}
        self.readiness.set(labels[status], STATUS_TONES[status])
        text = "; ".join(notes)
        if check["status"] == "BLOCKED":
            text += ". You can still run the pulse: unknown values use labeled synthetic defaults."
        self.readiness_notes.setText(text)

    def start_test(self) -> None:
        profile = self._current_profile()
        if profile is None:
            return
        demand = self.demand.value()
        self.result = stress_test(
            profile, self.scenario.currentText(), mode=self.mode.currentText(),
            target_voltage_v=self.target_voltage.value(), demand_current_a=demand if demand > 0 else None,
        )
        self.tested_profile = profile
        self.index = 0
        for series in self._all_series:
            series.xs.clear()
            series.ys.clear()
        for chart in self._charts:
            chart.data_changed()
        self.verdict.set("Test running", "neutral")
        for widget in (self.use_text, self.reason_text, self.needed_text, self.faults_text, self.numbers_text):
            widget.setText("")
            widget.setVisible(False)
        self._set_running(True)
        self.timer.start()

    def _set_running(self, running: bool) -> None:
        self.run_button.setEnabled(not running)
        self.finish_button.setEnabled(running)
        for widget in (self.battery, self.adapter, self.scenario, self.mode, self.target_voltage, self.demand):
            widget.setEnabled(not running)

    def _append(self, point: dict) -> None:
        t = point["time_s"]
        for series, key in (
            (self.voltage_series, "voltage_v"), (self.target_series, "target_voltage_v"),
            (self.current_series, "current_a"), (self.demand_series, "demand_current_a"),
            (self.temp_series, "temperature_c"), (self.soc_series, "soc_pct"),
        ):
            series.xs.append(t)
            series.ys.append(point[key])

    def _tick(self) -> None:
        points = self.result["points"]
        if self.index < len(points):
            point = points[self.index]
            self._append(point)
            self.index += 1
            self._show_point(point)
            for chart in self._charts:
                chart.data_changed()
        if self.index >= len(points):
            self._finish()

    def finish_now(self) -> None:
        if self.result is None:
            return
        points = self.result["points"]
        for point in points[self.index:]:
            self._append(point)
        self.index = len(points)
        for chart in self._charts:
            chart.data_changed()
        if points:
            self._show_point(points[-1])
        self._finish()

    def _show_point(self, point: dict) -> None:
        self.kpi_soc.set(fmt(point["soc_pct"], "%", 2))
        soh = point["soh_pct"]
        self.kpi_soh.set(fmt(soh, "%", 1) if soh is not None else "Waiting", "From simulated pulse")
        self.kpi_voltage.set(fmt(point["voltage_v"], "V", 2))
        self.kpi_current.set(fmt(point["current_a"], "A", 2))
        self.kpi_temp.set(fmt(point["temperature_c"], "°C", 1))
        self.kpi_power.set(fmt(point["power_w"], "W", 0))
        self.progress.setValue(int(100 * point["time_s"] / PULSE_DURATION_S))

    def _finish(self) -> None:
        self.timer.stop()
        self._set_running(False)
        self.progress.setValue(100)
        result = self.result
        profile = self.tested_profile
        summary = screening_summary(profile, result)
        self.verdict.set(summary["label"], summary["tone"])
        self.use_text.setText(summary["use"])
        self.reason_text.setText(summary["reason"])
        self.faults_text.setText("Flags: " + "; ".join(result["faults"]) if result["faults"] else "")
        self.needed_text.setText("Data still needed: " + ", ".join(summary["gaps"]) if summary["gaps"] else "")

        points = result["points"]
        if result.get("soh_proxy_clamped"):
            soh_caption = "Hit the model's limit"
        else:
            soh_caption = "From simulated pulse"
        self.kpi_soh.caption.setText(soh_caption)
        recorded = f" · Recorded SOH in profile: {profile.soh_pct:g}%" if profile.soh_pct is not None else ""
        self.numbers_text.setText(
            f"{result['mode']} · {points[0]['voltage_v']:.2f} → {points[-1]['voltage_v']:.2f} V · "
            f"peak demand {result['demand_current_a']:.2f} A · peak delivered {result['peak_current_a']:.2f} A · "
            f"available {result['current_capability_a']:.2f} A · peak temperature {result['peak_temperature_c']:.1f} °C · "
            f"resistance {result['resistance_mohm']:.2f} mΩ{recorded}"
        )
        for widget in (self.use_text, self.reason_text, self.needed_text, self.faults_text, self.numbers_text):
            widget.setVisible(bool(widget.text()))
