"""Firmware v1.1 line protocol: the sketch, the simulator and the parser agree (pytest engines/bms/test_firmware_lines.py)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SKETCH = ROOT / "engines" / "firmware" / "revive_tery_esp32" / "revive_tery_esp32.ino"
CAPTURE = ROOT / "engines" / "firmware" / "wokwi" / "captured_serial.log"
sys.path.insert(0, str(HERE))
import bms_engine as bms  # noqa: E402
import esp32_sim as sim  # noqa: E402


def _keys(fmt: str) -> list[str]:
    return re.findall(r'\\"(\w+)\\":', fmt) or re.findall(r'"(\w+)":', fmt)


def test_sketch_format_string_matches_the_simulator_key_order():
    src = SKETCH.read_text(encoding="utf-8")
    fmt = re.search(r'snprintf\(body,[^"]*"(\{.*?)"\s*,', src, re.S).group(1)
    assert _keys(fmt) == ["voltage", "current", "temperature", "ambient", "seq", "t_ms"]
    assert _keys(sim.LINE_V11_BODY) == _keys(fmt)
    assert '\\"crc\\"' in src and sim.LINE_V11_CRC.startswith(',"crc"')


def test_sketch_messages_match_the_simulator():
    src = SKETCH.read_text(encoding="utf-8")
    for msg in (sim.MSG_READY, sim.MSG_NOT_FOUND, sim.MSG_READ_FAILED, sim.MSG_OVER_VOLTAGE, sim.MSG_OVER_CURRENT):
        assert msg.replace("'", "'") in src.replace('\\"', '"'), msg
    assert f'#define FW_VERSION "{sim.FW_VERSION}"' in src


def test_crc_of_the_documented_example_and_rejection():
    body = '{"voltage":3.712,"current":0.5210,"temperature":28.44,"ambient":24.10,"seq":42,"t_ms":42011'
    assert bms.crc8(b"123456789") == 0xF4                      # the standard CRC-8 (poly 0x07) check value
    line = f'{body},"crc":"{bms.crc8(body.encode()):02X}"}}'.encode()
    assert bms.line_crc_ok(line) is True
    assert bms.parse_telemetry_line(line, 0.0).ambient_temperature_c == 24.1
    assert bms.parse_telemetry_line(line.replace(b"3.712", b"3.713"), 0.0) is None


def test_v10_lines_still_parse_exactly_as_before():
    s = bms.parse_telemetry_line(b'{"voltage":3.712,"current":0.5210,"temperature":28.44}', 5.0)
    assert (s.voltage_v, s.current_a, s.temperature_c, s.ambient_temperature_c, s.seq) == (3.712, 0.521, 28.44, None, None)
    assert bms.parse_telemetry_line(b'{"voltage":3.7,"current":0.5,"temperature":-127.0}', 0).temperature_c is None
    assert bms.line_crc_ok(b'{"voltage":3.7,"current":0.5}') is None


def _run(fault_plan: dict[int, str], seconds: int):
    s = sim.SimulatedESP32(sim.SimulationSettings(true_capacity_ah=1.8, load_current_a=1.0, speed=60.0, seed=7),
                           start_epoch=0.0, paced=False)
    s.open()
    lines = [q.decode().strip() for q in s._queue]
    s._queue.clear()
    for t in range(seconds):
        if t in fault_plan:
            s.set_fault(fault_plan[t])
        lines += s._tick()
    return lines


def test_a_30_second_fault_prints_its_warning_at_most_three_times():
    lines = _run({10: "overvoltage", 40: "none"}, 60)
    over = [l for l in lines if l.startswith("# OVER")]
    assert 1 <= len(over) <= 3, over
    assert any("(x" in l for l in over[1:]) or len(over) == 1
    assert all(bms.firmware_message_severity(l) == "critical" for l in over)


def test_crc_errors_and_seq_gaps_are_counted_and_never_logged():
    lines = _run({5: "crc_corruption", 9: "seq_gap", 14: "none"}, 20)
    stats = bms.SerialStats()
    good = 0
    for l in lines:
        raw = l.encode()
        if l.startswith("#"):
            stats.record_message(raw, 0)
            continue
        if bms.line_crc_ok(raw) is False:
            stats.crc_errors += 1
            continue
        smp = bms.parse_telemetry_line(raw, 0)
        stats.note_seq(smp.seq)
        good += 1
    assert stats.crc_errors == 4 and stats.dropped_lines >= 5 + 4      # lost lines + rejected ones
    assert all(bms.firmware_message_severity(l) == "info" for l in lines if l.startswith(("# fw=", "# hb", "# boot", "# ds18b20")))


def test_ambient_reaches_the_sample_and_is_absent_without_the_second_sensor():
    lines = _run({}, 5)
    s = bms.parse_telemetry_line(next(l for l in lines if l.startswith("{")).encode(), 0)
    assert s.ambient_temperature_c is not None
    no_amb = bms.parse_telemetry_line(b'{"voltage":3.7,"current":0.5,"temperature":25.0,"ambient":null,"seq":1,"t_ms":1}', 0)
    assert no_amb.ambient_temperature_c is None                       # nothing invented


def test_monitor_only_guard_passes_on_the_sketch_and_fails_on_serial_read(tmp_path):
    guard = ROOT / "engines" / "firmware" / "tools" / "check_monitor_only.py"
    assert subprocess.run([sys.executable, str(guard), str(SKETCH)]).returncode == 0
    bad = tmp_path / "bad.ino"
    bad.write_text("void loop() { int c = Serial.read(); digitalWrite(5, HIGH); }\n", encoding="utf-8")
    assert subprocess.run([sys.executable, str(guard), str(bad)], capture_output=True).returncode == 1


def test_captured_wokwi_serial_parses():
    if not CAPTURE.is_file():
        pytest.skip("no captured_serial.log (needs wokwi-cli and WOKWI_CLI_TOKEN)")
    lines = [l for l in CAPTURE.read_text(encoding="utf-8", errors="replace").splitlines() if l.startswith("{")]
    ok = sum(bms.parse_telemetry_line(l.encode(), 0) is not None for l in lines)
    assert lines and ok / len(lines) >= 0.95
    json.dumps(ok)
