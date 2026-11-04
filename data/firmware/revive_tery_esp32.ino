/*
  REVIVE-TERY ESP32 telemetry firmware

  Reads pack voltage and current from an INA219 and temperature from a DS18B20, then prints
  one JSON line per second over USB. src/bms_engine.py reads these lines:

    {"voltage":3.712,"current":0.5210,"temperature":28.44}

  MONITOR-ONLY: this sketch never reads from the USB serial port, so the laptop can't send it
  commands. It drives no relay, MOSFET or other output, so it can't switch the battery or load.
  It provides no protection either. Your battery and load need their own fuse and protection.

  SAFETY: LOW-VOLTAGE BENCH USE ONLY. The INA219 is rated to 26 V. Never connect it to an EV pack.

  WIRING (matches the circuit shown in the Circuit Studio)
    Battery +         -> INA219 VIN+
    INA219 VIN-       -> Test load +
    Test load -       -> Battery -
    Battery -         -> ESP32 GND    (common ground, needed for the voltage reading)
    INA219 VCC        -> ESP32 3V3
    INA219 GND        -> ESP32 GND
    INA219 SDA        -> ESP32 GPIO21
    INA219 SCL        -> ESP32 GPIO22
    DS18B20 VDD       -> ESP32 3V3
    DS18B20 GND       -> ESP32 GND
    DS18B20 DQ        -> ESP32 GPIO4
    4.7 kOhm resistor between DS18B20 DQ and 3V3

  SETUP IN THE ARDUINO IDE
    1. File > Preferences > Additional boards manager URLs, add:
       https://espressif.github.io/arduino-esp32/package_esp32_index.json
    2. Tools > Board > Boards Manager: install "esp32" by Espressif Systems.
    3. Sketch > Include Library > Manage Libraries: install "Adafruit INA219",
       "OneWire" and "DallasTemperature". Accept any dependencies it offers.
    4. Tools > Board: choose "ESP32 Dev Module". Tools > Port: choose the ESP32's COM port.
    5. Upload, then open Tools > Serial Monitor at 115200 baud to check the output.
    6. Close the Serial Monitor before starting the dashboard: only one program can use the port.

  READING THE OUTPUT
    A line starting with "#" is a plain message, such as a missing sensor. The dashboard counts
    these as skipped lines. No reading is sent while a value is known to be invalid, because a
    wrong number would be logged as a measurement. A missing DS18B20 sends "temperature":null,
    since voltage and current are still good.

    Current is positive while the battery discharges through the wiring above. That matches the
    dashboard's "Discharge current reads positive" option.
*/

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_INA219.h>
#include <OneWire.h>
#include <DallasTemperature.h>

const unsigned long SERIAL_BAUD = 115200;
const int PIN_I2C_SDA = 21;
const int PIN_I2C_SCL = 22;
const int PIN_ONE_WIRE = 4;

// A 12-bit DS18B20 conversion takes up to 750 ms, so this period always leaves it enough time.
const unsigned long SAMPLE_PERIOD_MS = 1000;
const unsigned long SENSOR_RETRY_MS = 5000;

const float INA219_MAX_BUS_VOLTAGE_V = 26.0f;  // The chip's rated limit.
// With a 0.1 ohm shunt, setCalibration_32V_2A measures up to 320 mV, or 3.2 A. Beyond that the
// reading saturates and would undercount the charge, so it's treated as invalid.
const float SHUNT_SATURATED_MV = 319.0f;

Adafruit_INA219 packSensor;
OneWire oneWire(PIN_ONE_WIRE);
DallasTemperature temperatureSensor(&oneWire);

bool packSensorReady = false;
unsigned long lastSampleMs = 0;
unsigned long lastRetryMs = 0;

// False for NaN, infinity and absurd values, which could otherwise reach the JSON as "nan".
bool isUsable(float value) {
  return value == value && value > -1000000.0f && value < 1000000.0f;
}

void startPackSensor() {
  packSensorReady = packSensor.begin();
  if (packSensorReady) {
    packSensor.setCalibration_32V_2A();
    Serial.println("# INA219 ready");
  } else {
    Serial.println("# INA219 not found: check SDA, SCL, VCC and GND");
  }
}

// Returns true with valid readings. success() only describes the latest read, so each is checked.
bool readPack(float &voltageV, float &currentA) {
  const float busV = packSensor.getBusVoltage_V();
  if (!packSensor.success()) {
    return false;
  }
  const float shuntMv = packSensor.getShuntVoltage_mV();
  if (!packSensor.success()) {
    return false;
  }
  const float currentMa = packSensor.getCurrent_mA();
  if (!packSensor.success()) {
    return false;
  }
  if (!isUsable(busV) || !isUsable(shuntMv) || !isUsable(currentMa)) {
    return false;
  }

  // The bus reading is taken after the shunt. Adding the shunt drop gives the battery's voltage.
  voltageV = busV + shuntMv / 1000.0f;
  currentA = currentMa / 1000.0f;
  return true;
}

void printReading(float voltageV, float currentA, float temperatureC, bool hasTemperature) {
  char line[96];
  if (hasTemperature) {
    snprintf(line, sizeof(line), "{\"voltage\":%.3f,\"current\":%.4f,\"temperature\":%.2f}", voltageV, currentA, temperatureC);
  } else {
    snprintf(line, sizeof(line), "{\"voltage\":%.3f,\"current\":%.4f,\"temperature\":null}", voltageV, currentA);
  }
  Serial.println(line);
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  startPackSensor();

  temperatureSensor.begin();
  temperatureSensor.setResolution(12);
  // Don't block for 750 ms per conversion. The sample period gives it the time instead.
  temperatureSensor.setWaitForConversion(false);
  temperatureSensor.requestTemperatures();

  lastSampleMs = millis();
  lastRetryMs = lastSampleMs;
}

void loop() {
  const unsigned long now = millis();
  // Subtracting stays correct when millis() wraps around after about 49 days.
  if (now - lastSampleMs < SAMPLE_PERIOD_MS) {
    return;
  }
  lastSampleMs = now;

  // Collect the conversion started last time, and start the next, whatever happens below.
  const float temperatureC = temperatureSensor.getTempCByIndex(0);
  const bool hasTemperature = temperatureC != DEVICE_DISCONNECTED_C && isUsable(temperatureC);
  temperatureSensor.requestTemperatures();

  if (!packSensorReady) {
    if (now - lastRetryMs >= SENSOR_RETRY_MS) {
      lastRetryMs = now;
      startPackSensor();  // Lets a loose wire recover without a reset.
    }
    return;
  }

  float voltageV = 0.0f;
  float currentA = 0.0f;
  if (!readPack(voltageV, currentA)) {
    Serial.println("# INA219 read failed: check the wiring");
    packSensorReady = false;
    lastRetryMs = now;
    return;
  }

  if (voltageV > INA219_MAX_BUS_VOLTAGE_V) {
    Serial.println("# OVER 26 V: disconnect now, this exceeds the INA219's rating");
    return;
  }
  // Below the saturation point, current is proportional to the shunt voltage (0.1 ohm: 1 A = 100 mV).
  if (currentA * 100.0f > SHUNT_SATURATED_MV || currentA * 100.0f < -SHUNT_SATURATED_MV) {
    Serial.println("# Current above the 3.2 A range: reading withheld");
    return;
  }

  printReading(voltageV, currentA, temperatureC, hasTemperature);
}
