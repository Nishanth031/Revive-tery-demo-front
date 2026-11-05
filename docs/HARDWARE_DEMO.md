# Hardware demo

**Say out loud first:** low voltage only (one 18650-type cell), the INA219 is rated to 26 V, never an EV pack; there is a
fuse on the positive lead and a manual switch on the load; the ESP32 only reports, it cannot switch anything.

## If the ESP32 is present (45 s)

1. Firmware v1.1.0 flashed beforehand with the Arduino IDE (it was compiled here with arduino-cli, not flashed).
2. Circuit Studio -> Real ESP32 -> pick the port -> Start test. Point at the live V/A/°C tags on the circuit, the current
   flow, and the link line (lines per second, dropped lines, CRC errors).
3. Open the switch by hand: the current drops to zero; close it again. Unplug the cell DS18B20: `temperature` becomes null
   and the alert timeline shows the message.

## If it is not present

- Circuit Studio -> Simulator (or Live assessment -> a BMS preset): same JSON lines, same messages, labelled SIMULATED.
- Firmware & hardware page: the realistic circuit, the test-load calculator and the Wokwi card (download the project zip;
  open it on wokwi.com; the INA219 sliders drive the readings once the custom chip is built).

Averaging: the printed current is the mean of 10 samples in each second, so the host's 1 s coulomb counting equals the
sampled integral for that second. No accuracy gain is claimed (not measured). Power savings are not measured either.
