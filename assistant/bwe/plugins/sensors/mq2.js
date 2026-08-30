const Sensor = require('../../peripherals/base_sensor');
const peripheralBus = require('../../peripherals/peripheral_bus');
const bweEngine = require('../../core/engine');

class MQ2Plugin extends Sensor {
  constructor(id, config = {}) {
    super(id, 'gas_sensor', {
      warmupTime: 15, // 15 seconds warmup for testing convenience (physical MQ2 is 20s+)
      noiseLevel: 0.03, // 3% random noise
      calibrationDrift: 0.005, // Slight calibration drift over time
      ...config
    });
    
    this.analogPin = config.pin !== undefined ? config.pin : 34; // Default ESP32 analog pin for MQ2
    this.ambientPpm = 100.0;
  }

  initialize() {
    super.initialize();
    // Configure pin mode to analog input
    peripheralBus.gpio.setPinMode(this.analogPin, 'INPUT');
  }

  update(dt) {
    super.update(dt);
    
    // 1. Calculate gas concentration based on distance to any 'gas_source' in BWE scene graph
    let maxConcentration = this.ambientPpm;
    const allObjects = bweEngine.sceneGraph.getAllObjects();
    const gasSources = allObjects.filter(o => o.type === 'gas_source');
    
    const selfObj = bweEngine.sceneGraph.getObject(this.id);
    if (selfObj) {
      for (const source of gasSources) {
        const dx = source.position.x - selfObj.position.x;
        const dy = source.position.y - selfObj.position.y;
        const dz = source.position.z - selfObj.position.z;
        const distSq = dx * dx + dy * dy + dz * dz;
        
        // Inverse square drop-off with a gas release intensity metadata
        const intensity = source.metadata.intensity || 8000;
        const sourceContribution = intensity / (distSq + 0.1); // Avoid division by zero
        maxConcentration += sourceContribution;
      }
    }
    
    this.rawValue = maxConcentration;
    const noisyPpm = this.read();

    // 2. Map PPM back to physical Voltage (0.5V - 3.3V)
    // 100 PPM -> 0.5V, 300 PPM -> 1.0V, 600 PPM -> 2.0V, 1000 PPM -> 3.0V
    let voltage = 0.5;
    if (noisyPpm <= 100) {
      voltage = (noisyPpm / 100.0) * 0.5;
    } else if (noisyPpm <= 300) {
      voltage = 0.5 + ((noisyPpm - 100) / 200.0) * 0.5;
    } else if (noisyPpm <= 600) {
      voltage = 1.0 + ((noisyPpm - 300) / 300.0) * 1.0;
    } else {
      voltage = 2.0 + ((noisyPpm - 600) / 400.0) * 1.0;
    }
    
    // Clamp to reference voltage
    voltage = Math.min(3.3, Math.max(0.0, voltage));

    // 3. Set physical ESP32 ADC pin voltage
    peripheralBus.analog.setPinVoltage(this.analogPin, voltage);
  }
}

module.exports = MQ2Plugin;
