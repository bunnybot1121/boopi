const eventBus = require('../core/event_bus');
const gpioManager = require('./gpio_manager');
const pwmManager = require('./pwm_manager');
const analogManager = require('./analog_manager');
const { i2cManager, spiManager, uartManager } = require('./comm_managers');
const interruptManager = require('./interrupt_manager');

class PeripheralBus {
  constructor() {
    this.gpio = gpioManager;
    this.pwm = pwmManager;
    this.analog = analogManager;
    this.i2c = i2cManager;
    this.spi = spiManager;
    this.uart = uartManager;
    this.interrupt = interruptManager;

    this.wires = []; // Array of { id, from: { dev, pin }, to: { dev, pin }, color }
    this.errors = [];

    // Propagate signal changes across wires automatically
    eventBus.subscribe('gpio.changed', ({ pin, value }) => {
      this.propagateSignal('GPIO', pin, value);
    });

    eventBus.subscribe('analog.changed', ({ pin, voltage }) => {
      this.propagateSignal('ANALOG', pin, voltage);
    });
  }

  addWire(fromDev, fromPin, toDev, toPin, color = '#8e94f2') {
    const id = `${fromDev}_${fromPin}_to_${toDev}_${toPin}`;
    // Avoid duplicates
    if (this.wires.find(w => w.id === id)) return id;

    const wire = { id, from: { dev: fromDev, pin: fromPin }, to: { dev: toDev, pin: toPin }, color };
    this.wires.push(wire);
    
    eventBus.publish('wiring.wire_added', wire);
    this.validateWiring();
    return id;
  }

  removeWire(wireId) {
    this.wires = this.wires.filter(w => w.id !== wireId);
    eventBus.publish('wiring.wire_removed', { id: wireId });
    this.validateWiring();
  }

  getWiresForDevice(devId) {
    return this.wires.filter(w => w.from.dev === devId || w.to.dev === devId);
  }

  propagateSignal(type, sourcePin, value) {
    // Find all wires connected to this sourcePin on the active controller (or device)
    for (const wire of this.wires) {
      if (wire.from.dev === 'esp32' && wire.from.pin === sourcePin) {
        this.applySignalToDevice(wire.to.dev, wire.to.pin, type, value);
      } else if (wire.to.dev === 'esp32' && wire.to.pin === sourcePin) {
        this.applySignalToDevice(wire.from.dev, wire.from.pin, type, value);
      }
    }
  }

  applySignalToDevice(devId, devPin, type, value) {
    eventBus.publish('wiring.signal_propagated', { devId, pin: devPin, type, value });
  }

  validateWiring() {
    this.errors = [];

    // Track active pin drivers to check for short circuits (multiple outputs on one net)
    const nets = new Map();

    for (const wire of this.wires) {
      // Simple net indexing: combine pins
      const netKey = [wire.from.dev, wire.from.pin, wire.to.dev, wire.to.pin].sort().join('-');
      
      // 1. Check for Power-to-Ground shorts
      const isPowerA = String(wire.from.pin).toUpperCase().includes('VCC') || String(wire.from.pin).toUpperCase().includes('5V') || String(wire.from.pin).toUpperCase().includes('3V3');
      const isGndA = String(wire.from.pin).toUpperCase().includes('GND');
      const isPowerB = String(wire.to.pin).toUpperCase().includes('VCC') || String(wire.to.pin).toUpperCase().includes('5V') || String(wire.to.pin).toUpperCase().includes('3V3');
      const isGndB = String(wire.to.pin).toUpperCase().includes('GND');

      if ((isPowerA && isGndB) || (isGndA && isPowerB)) {
        this.errors.push({
          type: 'SHORT_CIRCUIT',
          severity: 'CRITICAL',
          message: `Direct short circuit between Power and Ground detected on wire from ${wire.from.dev}:${wire.from.pin} to ${wire.to.dev}:${wire.to.pin}!`
        });
      }

      // 2. Voltage mismatch check
      const is5VA = String(wire.from.pin).toUpperCase().includes('5V');
      const is3V3B = String(wire.to.pin).toUpperCase().includes('3V3');
      const is5VB = String(wire.to.pin).toUpperCase().includes('5V');
      const is3V3A = String(wire.from.pin).toUpperCase().includes('3V3');

      if ((is5VA && is3V3B) || (is3V3A && is5VB)) {
        this.errors.push({
          type: 'VOLTAGE_MISMATCH',
          severity: 'WARNING',
          message: `Voltage level mismatch! Connecting 5V directly to 3.3V power rails without level shifting.`
        });
      }
    }

    eventBus.publish('wiring.validation_results', { errors: this.errors });
    return this.errors;
  }

  clear() {
    this.wires = [];
    this.errors = [];
    this.gpio.clear();
    this.pwm.clear();
    this.analog.clear();
    this.i2c.clear();
    this.spi.clear();
    this.uart.clear();
    this.interrupt.clear();
  }
}

module.exports = new PeripheralBus();
