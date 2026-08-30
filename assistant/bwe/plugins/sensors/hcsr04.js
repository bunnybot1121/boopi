const Sensor = require('../../peripherals/base_sensor');
const peripheralBus = require('../../peripherals/peripheral_bus');
const bweEngine = require('../../core/engine');

class HCSR04Plugin extends Sensor {
  constructor(id, config = {}) {
    super(id, 'distance_sensor', {
      noiseLevel: 0.01, // 1% ultrasonic echo scatter noise
      maxRange: 4.0, // 4 meters max
      minRange: 0.02, // 2 cm min
      ...config
    });
    
    this.trigPin = config.trigPin !== undefined ? config.trigPin : 12;
    this.echoPin = config.echoPin !== undefined ? config.echoPin : 13;
  }

  initialize() {
    super.initialize();
    peripheralBus.gpio.setPinMode(this.trigPin, 'INPUT');
    peripheralBus.gpio.setPinMode(this.echoPin, 'OUTPUT');
  }

  update(dt) {
    super.update(dt);

    const selfObj = bweEngine.sceneGraph.getObject(this.id);
    if (!selfObj) return;

    // 1. Calculate direction vector from sensor euler rotation
    // Assuming sensor points along the Z axis locally
    const headingY = selfObj.rotation.y;
    const rayDir = {
      x: Math.sin(headingY),
      y: 0,
      z: Math.cos(headingY)
    };

    const rayOrigin = selfObj.position;
    let minDistance = this.metadata.maxRange;

    // 2. Ray-AABB intersection test for all physics bodies in scene
    for (const body of bweEngine.physicsEngine.bodies) {
      if (body.id === this.id || body.id === 'root') continue;

      const dist = this.intersectRayAABB(rayOrigin, rayDir, body.getAABB(), body.rotation);
      if (dist !== null && dist < minDistance) {
        minDistance = dist;
      }
    }

    // 3. Simulating reflection errors (angular echo loss)
    // If the incidence angle is too steep, ultrasonic wave bounces off and does not return
    const incidenceReflectionAngle = Math.random() * 90;
    if (incidenceReflectionAngle > 75) {
      // Echo lost! Return maximum sensor reading
      minDistance = this.metadata.maxRange;
    }

    this.rawValue = minDistance * 100.0; // Convert meters to centimeters for physical reading
    const noisyDist = this.read();

    // 4. Send trigger-echo timing simulation back to GPIO
    // In Arduino, distance = duration * 0.034 / 2;
    // So duration (us) = distance / 0.017;
    const durationUs = noisyDist / 0.017;
    
    // Feed the trigger response back
    peripheralBus.gpio.setInputValue(this.echoPin, noisyDist <= this.metadata.maxRange * 100 ? 1 : 0);
    
    // Set analog/telemetry voltage sync too
    peripheralBus.analog.setPinVoltage(this.trigPin, (noisyDist / 400.0) * 3.3);
  }

  intersectRayAABB(origin, dir, aabb, rotation) {
    let tmin = (aabb.min.x - origin.x) / (dir.x || 0.00001);
    let tmax = (aabb.max.x - origin.x) / (dir.x || 0.00001);

    if (tmin > tmax) [tmin, tmax] = [tmax, tmin];

    let tymin = (aabb.min.y - origin.y) / (dir.y || 0.00001);
    let tymax = (aabb.max.y - origin.y) / (dir.y || 0.00001);

    if (tymin > tymax) [tymin, tymax] = [tymax, tymin];

    if ((tmin > tymax) || (tymin > tmax)) return null;

    if (tymin > tmin) tmin = tymin;
    if (tymax < tmax) tmax = tymax;

    let tzmin = (aabb.min.z - origin.z) / (dir.z || 0.00001);
    let tzmax = (aabb.max.z - origin.z) / (dir.z || 0.00001);

    if (tzmin > tzmax) [tzmin, tzmax] = [tzmax, tzmin];

    if ((tmin > tzmax) || (tzmin > tmax)) return null;

    if (tzmin > tmin) tmin = tzmin;
    if (tzmax < tmax) tmax = tzmax;

    return tmin >= 0 ? tmin : null;
  }
}

module.exports = HCSR04Plugin;
