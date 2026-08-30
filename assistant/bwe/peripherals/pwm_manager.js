const eventBus = require('../core/event_bus');

class PWMManager {
  constructor() {
    this.pwms = new Map(); // pin -> { duty: 0.0, frequency: 50, channel: 0 }
  }

  setPWM(pin, duty, frequency = 50, channel = 0) {
    // Normalize duty cycle to float 0.0 - 1.0
    let normDuty = duty;
    if (duty > 1.0) {
      // Assume 8-bit (0-255) or 10-bit (0-1023)
      if (duty <= 255) normDuty = duty / 255.0;
      else normDuty = duty / 1023.0;
    }
    normDuty = Math.max(0.0, Math.min(1.0, normDuty));

    const prev = this.pwms.get(pin) || { duty: 0.0, frequency: 50, channel: 0 };
    if (prev.duty !== normDuty || prev.frequency !== frequency) {
      this.pwms.set(pin, { duty: normDuty, frequency, channel });
      eventBus.publish('pwm.changed', { pin, duty: normDuty, frequency, channel });
    }
  }

  getPWM(pin) {
    return this.pwms.get(pin) || { duty: 0.0, frequency: 50, channel: 0 };
  }

  clear() {
    this.pwms.clear();
  }
}

module.exports = new PWMManager();
