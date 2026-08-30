const eventBus = require('../core/event_bus');

class AnalogManager {
  constructor() {
    this.adcResolution = 12; // 12-bit standard for ESP32 (0-4095)
    this.dacResolution = 8;   // 8-bit standard for ESP32 DAC (0-255)
    this.referenceVoltage = 3.3; // ESP32 works at 3.3V logic
    this.voltages = new Map(); // pin -> voltage (float)
  }

  setADCResolution(bits) {
    this.adcResolution = bits;
  }

  setDACResolution(bits) {
    this.dacResolution = bits;
  }

  setPinVoltage(pin, voltage) {
    // Clamp voltage to reference bounds
    const clampedVolts = Math.max(0.0, Math.min(this.referenceVoltage, voltage));
    const prev = this.voltages.get(pin) || 0.0;
    
    if (Math.abs(prev - clampedVolts) > 0.001) {
      this.voltages.set(pin, clampedVolts);
      eventBus.publish('analog.changed', { pin, voltage: clampedVolts, raw: this.voltageToADC(clampedVolts) });
    }
  }

  getPinVoltage(pin) {
    return this.voltages.get(pin) || 0.0;
  }

  analogRead(pin) {
    const volts = this.getPinVoltage(pin);
    return this.voltageToADC(volts);
  }

  analogWrite(pin, rawDACValue) {
    // ESP32 DAC write (e.g. Pin 25 or 26)
    const maxVal = Math.pow(2, this.dacResolution) - 1;
    const clamped = Math.max(0, Math.min(maxVal, rawDACValue));
    const voltage = (clamped / maxVal) * this.referenceVoltage;
    
    this.setPinVoltage(pin, voltage);
  }

  voltageToADC(voltage) {
    const maxADCVal = Math.pow(2, this.adcResolution) - 1;
    return Math.round((voltage / this.referenceVoltage) * maxADCVal);
  }

  adcToVoltage(adcValue) {
    const maxADCVal = Math.pow(2, this.adcResolution) - 1;
    return (adcValue / maxADCVal) * this.referenceVoltage;
  }

  clear() {
    this.voltages.clear();
  }
}

module.exports = new AnalogManager();
