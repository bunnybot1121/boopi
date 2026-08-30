const eventBus = require('../core/event_bus');

class I2CManager {
  constructor() {
    this.devices = new Map(); // address (hex string) -> virtual device callback/component
  }

  registerDevice(address, device) {
    const addrHex = this.normalizeAddress(address);
    this.devices.set(addrHex, device);
    console.log(`[I2CManager] Registered device at address ${addrHex}`);
  }

  unregisterDevice(address) {
    const addrHex = this.normalizeAddress(address);
    this.devices.delete(addrHex);
  }

  write(address, register, data) {
    const addrHex = this.normalizeAddress(address);
    const device = this.devices.get(addrHex);
    if (!device) {
      // console.warn(`[I2CManager] Write failed: No device registered at ${addrHex}`);
      return false;
    }
    
    if (typeof device.receiveI2CWrite === 'function') {
      try {
        device.receiveI2CWrite(register, data);
        eventBus.publish('i2c.write', { address: addrHex, register, data });
        return true;
      } catch (e) {
        console.error(`[I2CManager] Error on write to device ${addrHex}:`, e);
      }
    }
    return false;
  }

  request(address, register, length) {
    const addrHex = this.normalizeAddress(address);
    const device = this.devices.get(addrHex);
    if (!device) {
      // console.warn(`[I2CManager] Request failed: No device registered at ${addrHex}`);
      return [];
    }

    if (typeof device.receiveI2CRead === 'function') {
      try {
        const data = device.receiveI2CRead(register, length);
        eventBus.publish('i2c.read', { address: addrHex, register, data });
        return data || [];
      } catch (e) {
        console.error(`[I2CManager] Error on request from device ${addrHex}:`, e);
      }
    }
    return [];
  }

  normalizeAddress(addr) {
    if (typeof addr === 'number') {
      return '0x' + addr.toString(16).toUpperCase();
    }
    return addr.toString().toLowerCase().startsWith('0x') ? addr.toUpperCase() : '0x' + parseInt(addr, 16).toString(16).toUpperCase();
  }

  clear() {
    this.devices.clear();
  }
}

class SPIManager {
  constructor() {
    this.devices = new Map(); // csPin -> virtual device component
  }

  registerDevice(csPin, device) {
    this.devices.set(csPin, device);
  }

  unregisterDevice(csPin) {
    this.devices.delete(csPin);
  }

  transfer(csPin, data) {
    const device = this.devices.get(csPin);
    if (!device) return 0;
    
    if (typeof device.receiveSPITransfer === 'function') {
      const response = device.receiveSPITransfer(data);
      eventBus.publish('spi.transfer', { csPin, send: data, receive: response });
      return response;
    }
    return 0;
  }

  clear() {
    this.devices.clear();
  }
}

class UARTManager {
  constructor() {
    this.ports = new Map(); // portNumber/txRxPins -> { device, buffer: [] }
  }

  registerDevice(port, rxPin, txPin, device) {
    const key = `${rxPin}_${txPin}`;
    this.ports.set(key, { device, rxBuffer: [], txBuffer: [] });
    this.ports.set(String(port), { device, rxBuffer: [], txBuffer: [] });
  }

  write(portOrPins, data) {
    const entry = this.ports.get(String(portOrPins));
    if (!entry) return;
    
    if (typeof entry.device.receiveUARTWrite === 'function') {
      entry.device.receiveUARTWrite(data);
      eventBus.publish('uart.write', { port: portOrPins, data });
    }
  }

  // Virtual devices populate the read buffer for the ESP32 to retrieve
  feedReadBuffer(portOrPins, data) {
    const entry = this.ports.get(String(portOrPins));
    if (entry) {
      if (Array.isArray(data)) {
        entry.rxBuffer.push(...data);
      } else {
        entry.rxBuffer.push(data);
      }
      eventBus.publish('uart.rx_buffered', { port: portOrPins });
    }
  }

  read(portOrPins) {
    const entry = this.ports.get(String(portOrPins));
    if (!entry || entry.rxBuffer.length === 0) return null;
    return entry.rxBuffer.shift();
  }

  clear() {
    this.ports.clear();
  }
}

module.exports = {
  i2cManager: new I2CManager(),
  spiManager: new SPIManager(),
  uartManager: new UARTManager()
};
