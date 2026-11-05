/*
  REVIVE-TERY ESP32 telemetry firmware v1.1.0

  Reads pack voltage and current from an INA219 and temperature from a DS18B20 (a second DS18B20 on the same bus
  reads ambient temperature), then prints one JSON line per second over USB. engines/bms/bms_engine.py reads it:

    {"voltage":3.712,"current":0.5210,"temperature":28.44,"ambient":24.10,"seq":42,"t_ms":42011,"crc":"XX"}

  "voltage", "current" and "temperature" are unchanged from v1.0, so old readers keep working. New, optional keys
  (contract v1.1): "ambient" (degC or null), "seq" (line counter, wraps), "t_ms" (millis() at sampling) and "crc"
  (CRC-8, polynomial 0x07, init 0x00, no reflection, no final xor, over the exact bytes from the opening "{" up to
  but not including ",\"crc\""; two upper-case hex digits; always the last key).

  AVERAGING: the INA219 is read SAMPLES_PER_PERIOD times per second and the printed voltage and current are the
  means of that second. The host integrates current over 1 s steps, so the charge it counts for a second equals
  the integral of the sampled current for that second. (No accuracy gain is claimed: it has not been measured.)

  MONITOR-ONLY: this sketch never reads from the USB serial port, so the laptop can't send it commands. It drives
  no relay, MOSFET or other output, so it can't switch the battery or load. The only pin it ever drives is the
  I2C clock line, open-drain, during an I2C bus-clear after a failed read (what the I2C peripheral itself does).
  It provides no protection: the battery needs its own fuse (see engines/firmware/CIRCUIT.md).

  SAFETY: LOW-VOLTAGE BENCH USE ONLY. The INA219 is rated to 26 V. Never connect it to an EV pack.

  RANGE PROFILES (RANGE_PROFILE below)
    RANGE_32V_2A     default, unchanged: 0.1 ohm shunt, up to 3.2 A, over-voltage limit 26 V (the chip's rating)
    RANGE_16V_400MA  finer current resolution for small cells: up to 0.4 A, over-voltage limit 16 V. It uses its
                     own limits: "# OVER 16 V..." and "# Current above the 0.4 A range..." messages.

  POWER: CPU at 80 MHz, Wi-Fi and Bluetooth off, a yielding wait between samples. LOW_POWER_SLEEP (off by default,
  always off under WOKWI) adds timer light sleep between samples. Savings are NOT measured; check them with a USB
  power meter before quoting any number.

  WIRING (matches apps/web-studio/data/circuit.json and engines/firmware/CIRCUIT.md)
    Battery +         -> fuse (recommended) -> INA219 VIN+
    INA219 VIN-       -> disconnect switch (recommended) -> Test load +
    Test load -       -> Battery -
    Battery -         -> ESP32 GND    (common ground, needed for the voltage reading)
    INA219 VCC        -> ESP32 3V3
    INA219 GND        -> ESP32 GND
    INA219 SDA        -> ESP32 GPIO21
    INA219 SCL        -> ESP32 GPIO22
    DS18B20 VDD (x2)  -> ESP32 3V3
    DS18B20 GND (x2)  -> ESP32 GND
    DS18B20 DQ  (x2)  -> ESP32 GPIO4   (index 0 = cell sensor, index 1 = ambient; addresses printed at boot)
    4.7 kOhm resistor between the 1-Wire DQ line and 3V3 (one for both sensors)

  SETUP: Arduino IDE or arduino-cli with the esp32 core and the libraries Adafruit INA219, OneWire and
  DallasTemperature; board "ESP32 Dev Module"; Serial Monitor at 115200 baud. See engines/firmware/MODULE.md.

  READING THE OUTPUT: a line starting with "#" is a message. No reading is sent while a value is known to be
  invalid, because a wrong number would be logged as a measurement. A missing DS18B20 sends null. A repeated
  warning is printed at most once per WARN_REPEAT_MS, with "(x<n>)" counting the occurrences since the last print.
  Current is positive while the battery discharges through the wiring above.
*/

#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <esp_system.h>
#include <esp_task_wdt.h>
#include <esp_sleep.h>
#include <Adafruit_INA219.h>
#include <OneWire.h>
#include <DallasTemperature.h>

// ------------------------------------------------------------------------------------------------- constants
#define FW_VERSION "1.1.0"
#define RANGE_32V_2A 1
#define RANGE_16V_400MA 2
#ifndef RANGE_PROFILE
#define RANGE_PROFILE RANGE_32V_2A
#endif
#ifndef WOKWI
#define WOKWI 0              // set to 1 only in engines/firmware/wokwi/sketch.ino
#endif
#ifndef LOW_POWER_SLEEP
#define LOW_POWER_SLEEP 0    // opt-in; never under WOKWI
#endif

const unsigned long SERIAL_BAUD = 115200;
const int PIN_I2C_SDA = 21;
const int PIN_I2C_SCL = 22;
const int PIN_ONE_WIRE = 4;
const uint32_t CPU_MHZ = 80;
const uint16_t I2C_TIMEOUT_MS = 50;
const int I2C_CLEAR_PULSES = 9;

// A 12-bit DS18B20 conversion takes up to 750 ms, so a 1 s period always leaves it enough time.
const unsigned long SAMPLE_PERIOD_MS = 1000;
const int SAMPLES_PER_PERIOD = 10;
const unsigned long OVERSAMPLE_MS = SAMPLE_PERIOD_MS / SAMPLES_PER_PERIOD;
const unsigned long SENSOR_RETRY_MS = 5000;
const unsigned long HEARTBEAT_MS = 10000;
const unsigned long WARN_REPEAT_MS = 10000;
const uint32_t WATCHDOG_TIMEOUT_S = 8;

#if RANGE_PROFILE == RANGE_16V_400MA
const char *PROFILE_NAME = "RANGE_16V_400MA";
const float MAX_BUS_VOLTAGE_V = 16.0f;       // this profile's own limit
const float SHUNT_SATURATED_MV = 39.9f;      // 0.1 ohm: 400 mA = 40 mV full scale at gain /1
const char *MSG_OVER_VOLTAGE = "# OVER 16 V: disconnect now, this exceeds the 16 V range profile";
const char *MSG_OVER_CURRENT = "# Current above the 0.4 A range: reading withheld";
#else
const char *PROFILE_NAME = "RANGE_32V_2A";
const float MAX_BUS_VOLTAGE_V = 26.0f;       // the chip's rated limit
// With a 0.1 ohm shunt, setCalibration_32V_2A measures up to 320 mV, or 3.2 A. Beyond that the reading
// saturates and would undercount the charge, so it's treated as invalid.
const float SHUNT_SATURATED_MV = 319.0f;
const char *MSG_OVER_VOLTAGE = "# OVER 26 V: disconnect now, this exceeds the INA219's rating";
const char *MSG_OVER_CURRENT = "# Current above the 3.2 A range: reading withheld";
#endif
const char *MSG_NOT_FOUND = "# INA219 not found: check SDA, SCL, VCC and GND";
const char *MSG_READ_FAILED = "# INA219 read failed: check the wiring";

// ------------------------------------------------------------------------------------------------- state
Adafruit_INA219 packSensor;
OneWire oneWire(PIN_ONE_WIRE);
DallasTemperature temperatureSensor(&oneWire);

bool packSensorReady = false;
unsigned long periodStartMs = 0;
unsigned long lastOversampleMs = 0;
unsigned long lastRetryMs = 0;
unsigned long lastHeartbeatMs = 0;
uint32_t seq = 0;

// one second of oversampled readings
float sumVoltageV = 0.0f, sumCurrentA = 0.0f;
float minCurrentA = 0.0f, maxCurrentA = 0.0f;   // kept for a future field; not printed in v1.1
int nSamples = 0;
bool periodOverVoltage = false, periodOverCurrent = false;

struct Throttle {          // flood control for one repeated warning
  unsigned long lastMs;
  uint32_t count;
  bool printed;
};
Throttle thrNotFound = {0, 0, false}, thrReadFailed = {0, 0, false}, thrOverVoltage = {0, 0, false}, thrOverCurrent = {0, 0, false};

// ------------------------------------------------------------------------------------------------- helpers
// False for NaN, infinity and absurd values, which could otherwise reach the JSON as "nan".
bool isUsable(float value) {
  return value == value && value > -1000000.0f && value < 1000000.0f;
}

uint8_t crc8(const char *data, size_t len) {     // polynomial 0x07, init 0x00, no reflection, no final xor
  uint8_t crc = 0x00;
  for (size_t i = 0; i < len; i++) {
    crc ^= (uint8_t)data[i];
    for (int b = 0; b < 8; b++) {
      crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
    }
  }
  return crc;
}

// Prints `text` at most once per WARN_REPEAT_MS while the condition persists; "(x<n>)" counts occurrences
// since the previous print. The exact base text is kept, so the apps can still classify it.
void warn(Throttle &t, const char *text) {
  const unsigned long now = millis();
  t.count++;
  if (!t.printed || now - t.lastMs >= WARN_REPEAT_MS) {
    if (t.printed && t.count > 1) {
      Serial.print(text);
      Serial.print(" (x");
      Serial.print(t.count);
      Serial.println(")");
    } else {
      Serial.println(text);
    }
    t.printed = true;
    t.lastMs = now;
    t.count = 0;
  }
}
void clearWarn(Throttle &t) { t.printed = false; t.count = 0; }

const char *resetReasonText(esp_reset_reason_t r) {
  switch (r) {
    case ESP_RST_POWERON: return "power_on";
    case ESP_RST_EXT: return "external_pin";
    case ESP_RST_SW: return "software";
    case ESP_RST_PANIC: return "panic";
    case ESP_RST_INT_WDT: return "interrupt_watchdog";
    case ESP_RST_TASK_WDT: return "task_watchdog";
    case ESP_RST_WDT: return "other_watchdog";
    case ESP_RST_DEEPSLEEP: return "deep_sleep";
    case ESP_RST_BROWNOUT: return "brownout";
    case ESP_RST_SDIO: return "sdio";
    default: return "unknown";
  }
}

void startWatchdog() {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  esp_task_wdt_config_t cfg = {};
  cfg.timeout_ms = WATCHDOG_TIMEOUT_S * 1000;
  cfg.idle_core_mask = 0;
  cfg.trigger_panic = true;
  if (esp_task_wdt_reconfigure(&cfg) != ESP_OK) {
    esp_task_wdt_init(&cfg);
  }
#else
  esp_task_wdt_init(WATCHDOG_TIMEOUT_S, true);
#endif
  esp_task_wdt_add(NULL);
}

// Frees an I2C bus held low by a confused slave: up to 9 clock pulses on SCL, open-drain, then I2C restarts.
void i2cBusClear() {
  Wire.end();
  pinMode(PIN_I2C_SDA, INPUT_PULLUP);
  pinMode(PIN_I2C_SCL, OUTPUT_OPEN_DRAIN);
  for (int i = 0; i < I2C_CLEAR_PULSES && digitalRead(PIN_I2C_SDA) == LOW; i++) {
    digitalWrite(PIN_I2C_SCL, LOW);
    delayMicroseconds(5);
    digitalWrite(PIN_I2C_SCL, HIGH);
    delayMicroseconds(5);
  }
  pinMode(PIN_I2C_SCL, INPUT_PULLUP);
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  Wire.setTimeOut(I2C_TIMEOUT_MS);
}

void startPackSensor() {
  packSensorReady = packSensor.begin();
  if (packSensorReady) {
#if RANGE_PROFILE == RANGE_16V_400MA
    packSensor.setCalibration_16V_400mA();
#else
    packSensor.setCalibration_32V_2A();
#endif
    clearWarn(thrNotFound);
    Serial.println("# INA219 ready");
  } else {
    warn(thrNotFound, MSG_NOT_FOUND);
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

void resetPeriod() {
  sumVoltageV = 0.0f;
  sumCurrentA = 0.0f;
  nSamples = 0;
  periodOverVoltage = false;
  periodOverCurrent = false;
}

void oversample() {
  float voltageV = 0.0f, currentA = 0.0f;
  if (!readPack(voltageV, currentA)) {
    warn(thrReadFailed, MSG_READ_FAILED);
    packSensorReady = false;
    lastRetryMs = millis();
    resetPeriod();
    i2cBusClear();
    return;
  }
  clearWarn(thrReadFailed);
  if (voltageV > MAX_BUS_VOLTAGE_V) periodOverVoltage = true;
  // Below the saturation point, current is proportional to the shunt voltage (0.1 ohm: 1 A = 100 mV).
  if (currentA * 100.0f > SHUNT_SATURATED_MV || currentA * 100.0f < -SHUNT_SATURATED_MV) periodOverCurrent = true;
  if (nSamples == 0) {
    minCurrentA = currentA;
    maxCurrentA = currentA;
  } else {
    if (currentA < minCurrentA) minCurrentA = currentA;
    if (currentA > maxCurrentA) maxCurrentA = currentA;
  }
  sumVoltageV += voltageV;
  sumCurrentA += currentA;
  nSamples++;
}

void appendTemperature(char *buf, size_t size, float value, bool ok) {
  if (ok) {
    snprintf(buf, size, "%.2f", value);
  } else {
    snprintf(buf, size, "null");
  }
}

void printReading(float voltageV, float currentA, float temperatureC, bool hasTemperature, float ambientC,
                  bool hasAmbient, unsigned long tMs) {
  char temp[16], amb[16], body[200], line[220];
  appendTemperature(temp, sizeof(temp), temperatureC, hasTemperature);
  appendTemperature(amb, sizeof(amb), ambientC, hasAmbient);
  const int n = snprintf(body, sizeof(body), "{\"voltage\":%.3f,\"current\":%.4f,\"temperature\":%s,\"ambient\":%s,\"seq\":%lu,\"t_ms\":%lu",
                         voltageV, currentA, temp, amb, (unsigned long)seq, tMs);
  if (n <= 0 || n >= (int)sizeof(body)) {
    return;
  }
  snprintf(line, sizeof(line), "%s,\"crc\":\"%02X\"}", body, crc8(body, (size_t)n));
  Serial.println(line);
  seq++;
}

void printSensorAddresses() {
  const int count = temperatureSensor.getDeviceCount();
  for (int i = 0; i < count; i++) {
    DeviceAddress a;
    if (temperatureSensor.getAddress(a, i)) {
      char hex[17];
      for (int k = 0; k < 8; k++) snprintf(hex + 2 * k, 3, "%02X", a[k]);
      Serial.print("# ds18b20[");
      Serial.print(i);
      Serial.print("]=");
      Serial.println(hex);
    }
  }
}

// ------------------------------------------------------------------------------------------------- setup / loop
void setup() {
  setCpuFrequencyMhz(CPU_MHZ);     // 115200 baud still works at 80 MHz
  WiFi.mode(WIFI_OFF);
  btStop();
  Serial.begin(SERIAL_BAUD);
  Serial.print("# boot reason=");
  Serial.println(resetReasonText(esp_reset_reason()));
  Serial.print("# fw=revive_tery_esp32 v" FW_VERSION " profile=");
  Serial.print(PROFILE_NAME);
  Serial.println(" sensors=ina219,ds18b20");

  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  Wire.setTimeOut(I2C_TIMEOUT_MS);
  startPackSensor();

  temperatureSensor.begin();
  temperatureSensor.setResolution(12);
  printSensorAddresses();
  // Don't block for 750 ms per conversion. The sample period gives it the time instead.
  temperatureSensor.setWaitForConversion(false);
  temperatureSensor.requestTemperatures();

  startWatchdog();
  periodStartMs = millis();
  lastOversampleMs = periodStartMs;
  lastRetryMs = periodStartMs;
  lastHeartbeatMs = periodStartMs;
}

void endOfPeriod(unsigned long now) {
  // Collect the conversions started last period, and start the next, whatever happens below.
  const float temperatureC = temperatureSensor.getTempCByIndex(0);
  const bool hasTemperature = temperatureC != DEVICE_DISCONNECTED_C && isUsable(temperatureC);
  const float ambientC = temperatureSensor.getTempCByIndex(1);
  const bool hasAmbient = ambientC != DEVICE_DISCONNECTED_C && isUsable(ambientC);
  temperatureSensor.requestTemperatures();

  if (!packSensorReady) {
    if (now - lastRetryMs >= SENSOR_RETRY_MS) {
      lastRetryMs = now;
      startPackSensor();  // Lets a loose wire recover without a reset.
    }
    resetPeriod();
    return;
  }
  if (periodOverVoltage) {
    warn(thrOverVoltage, MSG_OVER_VOLTAGE);
    resetPeriod();
    return;
  }
  clearWarn(thrOverVoltage);
  if (periodOverCurrent) {
    warn(thrOverCurrent, MSG_OVER_CURRENT);
    resetPeriod();
    return;
  }
  clearWarn(thrOverCurrent);
  if (nSamples > 0) {
    printReading(sumVoltageV / nSamples, sumCurrentA / nSamples, temperatureC, hasTemperature, ambientC, hasAmbient, now);
  }
  resetPeriod();
}

void loop() {
  esp_task_wdt_reset();
  const unsigned long now = millis();
  // Subtracting stays correct when millis() wraps around after about 49 days.
  if (packSensorReady && now - lastOversampleMs >= OVERSAMPLE_MS && nSamples < SAMPLES_PER_PERIOD) {
    lastOversampleMs = now;
    oversample();
  }
  if (now - periodStartMs >= SAMPLE_PERIOD_MS) {
    periodStartMs = now;
    lastOversampleMs = now;
    endOfPeriod(now);
  }
  if (now - lastHeartbeatMs >= HEARTBEAT_MS) {
    lastHeartbeatMs = now;
    Serial.print("# hb seq=");
    Serial.println((unsigned long)seq);
  }
#if LOW_POWER_SLEEP && !WOKWI
  Serial.flush();
  esp_sleep_enable_timer_wakeup((uint64_t)(OVERSAMPLE_MS - 5) * 1000ULL);
  esp_light_sleep_start();
#else
  delay(2);                        // yield instead of busy-waiting at full CPU speed
#endif
}
