const eventBus = require('../core/event_bus');
const peripheralBus = require('../peripherals/peripheral_bus');

class HILBridge {
  constructor() {
    this.wsClient = null;
    this.mqttClient = null;
    this.isConnected = false;
    
    // Latency metrics
    this.latencyHistory = [];
    this.lastPingSent = 0;
    this.currentLatency = 0;

    // Listen to virtual sensor updates in the simulation and forward them to the hardware
    eventBus.subscribe('wiring.signal_propagated', ({ devId, pin, type, value }) => {
      this.forwardSensorStateToHardware(devId, pin, type, value);
    });
  }

  connect(wsUrl = 'ws://127.0.0.1:8767') {
    console.log(`[HILBridge] Connecting to Bupi Node Server at ${wsUrl}...`);
    try {
      // Connect to the Python/WebSocket node server
      const WebSocket = require('ws');
      this.wsClient = new WebSocket(wsUrl);

      this.wsClient.on('open', () => {
        this.isConnected = true;
        console.log('[HILBridge] Connected to Bupi Node Server.');
        eventBus.publish('hil.connected', { channel: 'WebSocket' });
        
        // Start latency monitoring ping loop
        this.startPingLoop();
      });

      this.wsClient.on('message', (data) => {
        try {
          const payload = JSON.parse(data.toString());
          this.handleIncomingHardwareMessage(payload);
        } catch (e) {
          // Handle raw text
          this.handleIncomingHardwareMessage({ type: 'raw', text: data.toString() });
        }
      });

      this.wsClient.on('close', () => {
        this.isConnected = false;
        console.log('[HILBridge] Disconnected from Bupi Node Server.');
        eventBus.publish('hil.disconnected', { channel: 'WebSocket' });
        // Attempt reconnect after 5 seconds
        setTimeout(() => this.connect(wsUrl), 5000);
      });

      this.wsClient.on('error', (err) => {
        console.error('[HILBridge] Connection error:', err.message);
      });

    } catch (e) {
      console.warn('[HILBridge] WebSocket require failed or connection error. Running in browser-only bridge mode.');
      // Browser environment fallback
      if (typeof window !== 'undefined' && window.WebSocket) {
        this.connectBrowser(wsUrl);
      }
    }
  }

  connectBrowser(wsUrl) {
    this.wsClient = new window.WebSocket(wsUrl);
    this.wsClient.onopen = () => {
      this.isConnected = true;
      eventBus.publish('hil.connected', { channel: 'BrowserWebSocket' });
      this.startPingLoop();
    };
    this.wsClient.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        this.handleIncomingHardwareMessage(payload);
      } catch (e) {
        this.handleIncomingHardwareMessage({ type: 'raw', text: event.data });
      }
    };
    this.wsClient.onclose = () => {
      this.isConnected = false;
      eventBus.publish('hil.disconnected', { channel: 'BrowserWebSocket' });
      setTimeout(() => this.connectBrowser(wsUrl), 5000);
    };
  }

  handleIncomingHardwareMessage(msg) {
    if (msg.cmd) {
      // HIL Command parser from physical MCU
      const { cmd, pin, val, type, addr, reg, data } = msg;

      switch (cmd) {
        case 'write':
          if (type === 'PWM') {
            peripheralBus.pwm.setPWM(pin, val);
          } else if (type === 'ANALOG') {
            peripheralBus.analog.analogWrite(pin, val);
          } else {
            peripheralBus.gpio.digitalWrite(pin, val);
          }
          break;

        case 'read':
          // ESP32 requests sensor read. Fetch from Virtual Peripheral Bus and return response.
          let readVal = 0;
          if (type === 'ANALOG') {
            readVal = peripheralBus.analog.analogRead(pin);
          } else {
            readVal = peripheralBus.gpio.digitalRead(pin);
          }
          this.sendToHardware({ cmd: 'read_res', pin, val: readVal });
          break;

        case 'i2c_write':
          peripheralBus.i2c.write(addr, reg, data);
          break;

        case 'i2c_read':
          const readBytes = peripheralBus.i2c.request(addr, reg, val); // val stores length
          this.sendToHardware({ cmd: 'i2c_read_res', addr, reg, data: readBytes });
          break;

        case 'ping_res':
          // Calculate round-trip time
          const rtt = performance.now() - this.lastPingSent;
          this.currentLatency = rtt;
          this.latencyHistory.push(rtt);
          if (this.latencyHistory.length > 50) this.latencyHistory.shift();
          
          eventBus.publish('hil.latency_update', { latency: rtt, history: this.latencyHistory });
          break;
      }
    }
  }

  sendToHardware(payload) {
    if (this.isConnected && this.wsClient) {
      const msgStr = JSON.stringify(payload);
      if (this.wsClient.send) {
        this.wsClient.send(msgStr);
      }
    }
  }

  forwardSensorStateToHardware(devId, pin, type, value) {
    // If a virtual sensor changes its state, notify the physical MCU
    if (this.isConnected) {
      this.sendToHardware({
        cmd: 'sensor_update',
        device: devId,
        pin: pin,
        type: type,
        value: value
      });
    }
    
    // Also push to local MQTT if available
    try {
      const pahoPublish = `footmo2/${devId}/sensor/${pin}`;
      eventBus.publish('mqtt.publish', { topic: pahoPublish, payload: JSON.stringify({ value }) });
    } catch(e) {}
  }

  startPingLoop() {
    const ping = () => {
      if (!this.isConnected) return;
      this.lastPingSent = performance.now();
      this.sendToHardware({ cmd: 'ping' });
      setTimeout(ping, 2000); // Ping every 2 seconds
    };
    ping();
  }

  disconnect() {
    if (this.wsClient) {
      this.wsClient.close();
      this.wsClient = null;
    }
    this.isConnected = false;
  }
}

module.exports = new HILBridge();
