// INA219 model for Wokwi (Chips API, beta). NOT BUILT HERE: build it to chips/ina219.chip.wasm with the Wokwi
// chip toolchain (see ../../README.md). I2C slave at 0x40 with the registers the Adafruit library uses:
// 0x00 configuration, 0x01 shunt voltage, 0x02 bus voltage, 0x03 power, 0x04 current, 0x05 calibration.
// Two controls (busVoltage in V, currentMa in mA) drive the readings; a 0.1 ohm shunt is assumed, as on the breakout.
// The registers follow the INA219 datasheet: shunt LSB 10 uV, bus LSB 4 mV (bits 15..3, CNVR bit 1),
// current = shunt * calibration / 4096, power = current * bus / 5000.
#include "wokwi-api.h"
#include <stdint.h>
#include <stdlib.h>

#define INA219_ADDRESS 0x40
#define SHUNT_OHMS 0.1f

typedef struct {
  uint32_t bus_attr, current_attr;
  uint8_t reg;          // register pointer
  uint8_t write_count;  // bytes written in this transaction (1st = pointer, then 2 data bytes)
  uint16_t write_value;
  uint8_t read_count;
  uint16_t config, calibration;
} chip_state_t;

static int16_t clamp16(float v) {
  if (v > 32767.0f) return 32767;
  if (v < -32768.0f) return -32768;
  return (int16_t)v;
}

static uint16_t reg_value(chip_state_t *c) {
  const float bus_v = attr_read_float(c->bus_attr);
  const float current_a = attr_read_float(c->current_attr) / 1000.0f;
  const int16_t shunt = clamp16(current_a * SHUNT_OHMS / 0.00001f);          // 10 uV per LSB
  const int16_t current = (int16_t)(((int32_t)shunt * (int32_t)c->calibration) / 4096);
  switch (c->reg) {
    case 0x00: return c->config;
    case 0x01: return (uint16_t)shunt;
    case 0x02: {
      uint32_t raw = (uint32_t)(bus_v / 0.004f);
      if (raw > 0x1FFF) raw = 0x1FFF;
      return (uint16_t)((raw << 3) | 0x0002);                               // CNVR set: conversion ready
    }
    case 0x03: return (uint16_t)abs((int32_t)current * (int32_t)(bus_v / 0.004f) / 5000);
    case 0x04: return (uint16_t)current;
    case 0x05: return c->calibration;
    default: return 0;
  }
}

static bool on_connect(void *user_data, uint32_t address, bool read) {
  chip_state_t *c = user_data;
  c->write_count = 0;
  c->read_count = 0;
  return true;
}

static uint8_t on_read(void *user_data) {
  chip_state_t *c = user_data;
  const uint16_t v = reg_value(c);
  const uint8_t out = (c->read_count++ % 2 == 0) ? (uint8_t)(v >> 8) : (uint8_t)(v & 0xFF);  // big-endian
  return out;
}

static bool on_write(void *user_data, uint8_t data) {
  chip_state_t *c = user_data;
  if (c->write_count == 0) {
    c->reg = data;
  } else if (c->write_count == 1) {
    c->write_value = (uint16_t)data << 8;
  } else if (c->write_count == 2) {
    c->write_value |= data;
    if (c->reg == 0x00) c->config = (c->write_value & 0x8000) ? 0x399F : c->write_value;   // bit 15 = reset
    if (c->reg == 0x05) c->calibration = c->write_value;
  }
  c->write_count++;
  return true;
}

static void on_disconnect(void *user_data) {}

void chip_init(void) {
  chip_state_t *c = calloc(1, sizeof(chip_state_t));
  c->bus_attr = attr_init_float("busVoltage", 3.7f);
  c->current_attr = attr_init_float("currentMa", 500.0f);
  c->config = 0x399F;
  const i2c_config_t cfg = {
    .user_data = c,
    .address = INA219_ADDRESS,
    .scl = pin_init("SCL", INPUT_PULLUP),
    .sda = pin_init("SDA", INPUT_PULLUP),
    .connect = on_connect,
    .read = on_read,
    .write = on_write,
    .disconnect = on_disconnect,
  };
  i2c_init(&cfg);
}
