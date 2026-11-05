# REVIVE-TERY bench circuit (v1.1, monitor-only)

> **Safety.** Low-voltage bench only. The INA219 is rated to 26 V: never connect an EV pack or anything above that.
> The circuit gives no protection beyond a fuse. The firmware never drives an output on the battery or load path and
> never reads the serial port. Protective parts here (fuse, disconnect switch) are passive or manual.

The connections Wokwi can simulate are defined once in `wokwi/diagram.json`; `circuit_meta.json` adds the parts it
cannot simulate (battery, fuse, switch, load, capacitors, laptop). `just wokwi-sync` writes the web app's
`apps/web-studio/data/circuit.json` from both, and `just check` runs the design rules (`scripts/check_circuit.py`).

## Wiring

| From | To | Why |
|---|---|---|
| Battery + | Fuse IN | protection on the positive lead, before anything else |
| Fuse OUT | INA219 VIN+ | fused positive into the current sensor |
| INA219 VIN- | Switch 1 | the manual disconnect switch is in series with the load |
| Switch 2 | Test load + | |
| Test load - | Battery - | |
| Battery - | ESP32 GND | common ground at ONE point, needed for the voltage reading |
| INA219 VCC / GND | ESP32 3V3 / GND | sensor power; 100 nF (C1) across VCC-GND at the INA219 |
| INA219 SDA / SCL | ESP32 GPIO21 / GPIO22 | I2C; 4.7 kOhm pull-ups to 3V3 **only if your breakout has none** (most do; check yours) |
| DS18B20 #0 (cell) VDD / GND / DQ | 3V3 / GND / GPIO4 | cell temperature; 100 nF (C2) across VDD-GND |
| DS18B20 #1 (ambient) VDD / GND / DQ | 3V3 / GND / GPIO4 | same 1-Wire bus; fills the `ambient` field (contract `ambient_temperature_c`) |
| 4.7 kOhm (R1) | DQ to 3V3 | one pull-up for the whole 1-Wire bus |
| 10 uF (C3) | 3V3 to GND near the ESP32 | only if the board does not already have a bulk capacitor (most DevKits do) |
| ESP32 USB | laptop | telemetry, monitor-only |

## Choosing the parts

**Fuse.** Rating above the highest test current and below 3.2 A (the INA219 range with the default profile; 0.4 A with
`RANGE_16V_400MA`), and below what the cell and wiring can take. Example: a 1 A test current on an 18650 with
short 22 AWG leads -> a 2 A fast-blow fuse in an inline holder.

**Test load (power resistor).** R = V / I_target; P = V x I_target; pick a resistor rated at least 2 x P.
Worked example: a 4.2 V cell at 1.0 A target -> R = 4.2 ohm (use 3.9 or 4.7 ohm, the current then becomes 1.08 A or
0.89 A at 4.2 V), P = 4.2 W -> a 10 W resistor. The web app's Firmware & hardware page has this calculator; it warns
when the current exceeds the INA219 range or the voltage exceeds 26 V.

**Cell holder.** A single 18650-type cell in a holder instead of loose leads. Tape the cell DS18B20 to the cell with
kapton tape or use thermal paste, away from the high-current path; the ambient DS18B20 stays in free air.

**Wiring practice.** Short, thick wires on the high-current path (battery, fuse, switch, shunt, load). Short I2C wires.
One common ground point.

## Bill of materials (generic values; no brands, no prices)

| Qty | Part | Value / note |
|---|---|---|
| 1 | ESP32 DevKit board | USB to the laptop |
| 1 | INA219 breakout | 0.1 ohm shunt, 26 V max |
| 2 | DS18B20 | cell + ambient, same bus |
| 1 | Resistor | 4.7 kOhm, 1-Wire pull-up |
| 2 | Resistor (conditional) | 4.7 kOhm I2C pull-ups, only if the breakout has none |
| 2 | Ceramic capacitor | 100 nF (INA219, DS18B20) |
| 1 | Electrolytic capacitor (conditional) | 10 uF at 3V3, only if the board has none |
| 1 | Inline fuse holder + fuse | below 3.2 A, above the test current |
| 1 | SPST switch | manual load disconnect, rated for the test current |
| 1 | Power resistor | from the calculation above, >= 2 x the dissipated power |
| 1 | 18650-type cell holder | single cell |

## What changed and why

| Change | Accuracy | Noise | Protection | Robustness |
|---|---|---|---|---|
| Firmware averages 10 INA219 samples per printed second | the printed current is the mean over the second, so 1 s coulomb counting equals the sampled integral (no accuracy gain is claimed: not measured) | lower | | |
| 100 nF decoupling at both sensors | | lower supply noise | | fewer I2C/1-Wire glitches |
| Inline fuse before the INA219 | | | limits a short on the battery lead | |
| Manual disconnect switch | | | stop the discharge by hand, no electronics | |
| Second DS18B20 (ambient) | thermal context for the cell reading | | | |
| CRC + seq on every line | corrupt lines are rejected, lost lines counted | | | link health visible |
| Watchdog, I2C timeout and bus-clear | | | | recovers from a stuck I2C bus without a manual reset |

Not verified here: real hardware (nothing was built or flashed), power savings (not measured; check with a USB power
meter), and the circuit in Wokwi (no wokwi-cli in this environment).
