const eventBus = require('../core/event_bus');

class GPIOManager {
  constructor() {
    this.pins = new Map(); // pinNumber -> { mode: 'INPUT', value: 0 }
  }

  setPinMode(pin, mode) {
    const validModes = ['INPUT', 'OUTPUT', 'INPUT_PULLUP', 'INPUT_PULLDOWN'];
    if (!validModes.includes(mode)) {
      console.warn(`[GPIOManager] Invalid mode ${mode} for pin ${pin}`);
      return;
    }
    
    const prev = this.pins.get(pin) || { mode: 'INPUT', value: 0 };
    let defaultValue = 0;
    if (mode === 'INPUT_PULLUP') defaultValue = 1;
    
    this.pins.set(pin, { mode, value: prev.mode === mode ? prev.value : defaultValue });
    eventBus.publish('gpio.mode_changed', { pin, mode });
  }

  digitalWrite(pin, value) {
    const pinState = this.pins.get(pin);
    if (!pinState) {
      this.pins.set(pin, { mode: 'OUTPUT', value: value ? 1 : 0 });
    } else {
      if (pinState.mode !== 'OUTPUT') {
        console.warn(`[GPIOManager] Writing to non-output pin ${pin} (mode: ${pinState.mode})`);
      }
      const val = value ? 1 : 0;
      if (pinState.value !== val) {
        pinState.value = val;
        eventBus.publish('gpio.changed', { pin, value: val });
      }
    }
  }

  digitalRead(pin) {
    const pinState = this.pins.get(pin);
    if (!pinState) {
      return 0;
    }
    return pinState.value;
  }

  // Used by virtual sensors to feed values to ESP32 inputs
  setInputValue(pin, value) {
    const pinState = this.pins.get(pin);
    if (pinState && pinState.mode.startsWith('INPUT')) {
      const val = value ? 1 : 0;
      if (pinState.value !== val) {
        pinState.value = val;
        eventBus.publish('gpio.changed', { pin, value: val });
      }
    }
  }

  getPinMode(pin) {
    const pinState = this.pins.get(pin);
    return pinState ? pinState.mode : 'INPUT';
  }

  getPinValue(pin) {
    const pinState = this.pins.get(pin);
    return pinState ? pinState.value : 0;
  }

  clear() {
    this.pins.clear();
  }
}

module.exports = new GPIOManager();
