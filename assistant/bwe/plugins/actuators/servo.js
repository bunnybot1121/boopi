const Actuator = require('../../peripherals/base_actuator');
const peripheralBus = require('../../peripherals/peripheral_bus');
const bweEngine = require('../../core/engine');

class ServoPlugin extends Actuator {
  constructor(id, config = {}) {
    super(id, 'servo_motor', config);
    this.controlPin = config.pin !== undefined ? config.pin : 18; // Default Servo pin
    this.speed = config.speed || 5.0; // Rotation speed (lerp factor)
    
    this.targetAngle = 0.0;
    this.currentAngle = 0.0;
  }

  initialize() {
    super.initialize();
    peripheralBus.gpio.setPinMode(this.controlPin, 'INPUT');
  }

  update(dt) {
    super.update(dt);
    
    // 1. Get current PWM signal from virtual peripheral bus
    const pwm = peripheralBus.pwm.getPWM(this.controlPin);
    
    // 2. Map standard 50Hz servo pulses (0.05 to 0.10 duty cycle) to 0 - 180 degrees
    // Standard SG90 servo: 1.0ms pulse (5% duty) -> 0 deg, 2.0ms pulse (10% duty) -> 180 deg
    let angle = 0;
    if (pwm.duty >= 0.04 && pwm.duty <= 0.11) {
      angle = ((pwm.duty - 0.05) / 0.05) * 180.0;
    } else {
      // Fallback: If duty is set directly (e.g. 0.0 to 1.0)
      angle = pwm.duty * 180.0;
    }
    
    this.targetAngle = Math.max(0.0, Math.min(180.0, angle));

    // 3. Smooth transition to target angle (simulates transit time)
    const angleDiff = this.targetAngle - this.currentAngle;
    this.currentAngle += angleDiff * Math.min(1.0, this.speed * dt);

    // 4. Update the parent SceneObject's relative rotation (supporting sub-mesh horn rotation)
    const selfObj = bweEngine.sceneGraph.getObject(this.id);
    if (selfObj) {
      let hornMesh = null;
      
      // Look for a specific moving part (horn/arm/shaft) in custom 3D model groups
      if (selfObj.mesh) {
        selfObj.mesh.traverse(child => {
          const name = child.name.toLowerCase();
          if (name.includes('horn') || name.includes('arm') || name.includes('shaft') || name.includes('rotor')) {
            hornMesh = child;
          }
        });
      }
      
      const targetRad = (this.currentAngle * Math.PI) / 180.0;
      if (hornMesh) {
        // Rotate ONLY the moving arm/horn sub-mesh, leaving casing static!
        hornMesh.rotation.y = targetRad;
      } else {
        // Fallback: Rotate the entire procedural mesh
        selfObj.rotation.y = targetRad;
      }
    }
  }
}

module.exports = ServoPlugin;
