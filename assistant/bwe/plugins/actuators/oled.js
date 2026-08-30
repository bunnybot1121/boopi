const Actuator = require('../../peripherals/base_actuator');
const peripheralBus = require('../../peripherals/peripheral_bus');

class OLEDPlugin extends Actuator {
  constructor(id, config = {}) {
    super(id, 'oled_display', config);
    this.address = config.address || 0x3C; // Default SSD1306 OLED address
    this.width = config.width || 128;
    this.height = config.height || 64;
    
    // Display buffers
    this.lines = ['', '', '', '']; // 4 lines of text representation
    this.pixelBuffer = new Uint8Array(this.width * this.height / 8); // B/W pixel array
  }

  initialize() {
    super.initialize();
    // Register this device on the virtual I2C bus
    peripheralBus.i2c.registerDevice(this.address, this);
  }

  receiveI2CWrite(register, data) {
    // If the data is text data, parse it and display on screen
    if (data && data.length > 0) {
      const text = String.fromCharCode(...data.filter(c => c >= 32 && c <= 126));
      if (text.trim()) {
        // Shift lines up and insert new line
        this.lines.shift();
        this.lines.push(text);
        
        eventBus = require('../../core/event_bus');
        eventBus.publish('oled.updated', { id: this.id, lines: [...this.lines] });
      }
    }
  }

  receiveI2CRead(register, length) {
    // Return display configuration status if queried
    return [0x01, 0x00, 0x3C];
  }

  onDestroy() {
    super.onDestroy();
    peripheralBus.i2c.unregisterDevice(this.address);
  }
}

module.exports = OLEDPlugin;
