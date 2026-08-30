const eventBus = require('../core/event_bus');

class Sensor {
  constructor(id, type, metadata = {}) {
    this.id = id;
    this.type = type;
    this.metadata = {
      updateRate: 20, // Hz
      noiseLevel: 0.05, // Standard deviation of gaussian noise
      warmupTime: 0, // In seconds (default: instant)
      calibrationDrift: 0.0001, // Drift rate per second
      ...metadata
    };

    this.simulatedTime = 0.0;
    this.isWarmingUp = this.metadata.warmupTime > 0;
    this.warmupTimer = 0.0;
    this.driftAccumulator = 0.0;
    this.rawValue = 0.0;
    this.calibratedOffset = 0.0;
  }

  initialize() {
    eventBus.publish('sensor.initialized', { id: this.id, type: this.type });
  }

  update(dt) {
    this.simulatedTime += dt;
    
    // 1. Warmup Simulation
    if (this.isWarmingUp) {
      this.warmupTimer += dt;
      if (this.warmupTimer >= this.metadata.warmupTime) {
        this.isWarmingUp = false;
        eventBus.publish('sensor.warmed_up', { id: this.id });
      }
    }

    // 2. Drift Accumulation
    this.driftAccumulator += this.metadata.calibrationDrift * dt * (Math.random() - 0.5);
  }

  // Applies gaussian noise to simulate realistic ADC / sensor readings
  applyRealismModel(baseValue) {
    if (this.isWarmingUp) {
      // Return erratic readings during warmup
      return baseValue * 0.2 + (Math.random() * 800) + Math.sin(this.simulatedTime * 10) * 100;
    }

    // Add gaussian noise + drift
    const noise = this.generateGaussianNoise(0, this.metadata.noiseLevel * baseValue);
    const finalValue = baseValue + noise + this.driftAccumulator + this.calibratedOffset;
    
    return Math.max(0, finalValue); // Floor at zero for environmental parameters
  }

  generateGaussianNoise(mean = 0, stdDev = 1) {
    // Box-Muller transform
    const u1 = Math.random();
    const u2 = Math.random();
    const randStdNormal = Math.sqrt(-2.0 * Math.log(u1)) * Math.sin(2.0 * Math.PI * u2);
    return mean + stdDev * randStdNormal;
  }

  read() {
    return this.applyRealismModel(this.rawValue);
  }

  calibrate(referenceValue) {
    this.calibratedOffset = referenceValue - this.rawValue;
    this.driftAccumulator = 0.0; // Reset drift
    eventBus.publish('sensor.calibrated', { id: this.id, offset: this.calibratedOffset });
  }
}

module.exports = Sensor;
