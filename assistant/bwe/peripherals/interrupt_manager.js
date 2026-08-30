const eventBus = require('../core/event_bus');

class InterruptManager {
  constructor() {
    this.interrupts = new Map(); // pin -> [{ mode: 'CHANGE', callback }]
    
    // Subscribe to GPIO state changes to trigger active interrupts
    eventBus.subscribe('gpio.changed', ({ pin, value }) => {
      this.triggerInterrupt(pin, value);
    });
  }

  attachInterrupt(pin, callback, mode = 'CHANGE') {
    const validModes = ['RISING', 'FALLING', 'CHANGE', 'LOW', 'HIGH'];
    if (!validModes.includes(mode)) {
      console.warn(`[InterruptManager] Invalid interrupt mode ${mode} for pin ${pin}`);
      return;
    }
    
    if (!this.interrupts.has(pin)) {
      this.interrupts.set(pin, []);
    }
    this.interrupts.get(pin).push({ mode, callback, lastValue: null });
  }

  detachInterrupt(pin) {
    this.interrupts.delete(pin);
  }

  triggerInterrupt(pin, currentValue) {
    const list = this.interrupts.get(pin);
    if (!list || list.length === 0) return;

    for (const intr of list) {
      const prev = intr.lastValue;
      intr.lastValue = currentValue;

      if (prev === null) continue; // Skip first change to establish base value

      let shouldTrigger = false;
      switch (intr.mode) {
        case 'CHANGE':
          shouldTrigger = prev !== currentValue;
          break;
        case 'RISING':
          shouldTrigger = prev === 0 && currentValue === 1;
          break;
        case 'FALLING':
          shouldTrigger = prev === 1 && currentValue === 0;
          break;
        case 'LOW':
          shouldTrigger = currentValue === 0;
          break;
        case 'HIGH':
          shouldTrigger = currentValue === 1;
          break;
      }

      if (shouldTrigger) {
        try {
          intr.callback(currentValue);
        } catch (e) {
          console.error(`[InterruptManager] Error in interrupt callback for pin ${pin}:`, e);
        }
      }
    }
  }

  clear() {
    this.interrupts.clear();
  }
}

module.exports = new InterruptManager();
