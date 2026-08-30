const eventBus = require('./event_bus');

class PhysicsBody {
  constructor(id, options = {}) {
    this.id = id;
    this.mass = options.mass !== undefined ? options.mass : 1.0;
    this.isStatic = this.mass === 0 || !!options.isStatic;
    
    this.position = options.position ? { ...options.position } : { x: 0, y: 0, z: 0 };
    this.rotation = options.rotation ? { ...options.rotation } : { x: 0, y: 0, z: 0 };
    this.velocity = options.velocity ? { ...options.velocity } : { x: 0, y: 0, z: 0 };
    this.angularVelocity = options.angularVelocity ? { ...options.angularVelocity } : { x: 0, y: 0, z: 0 };
    
    this.shape = options.shape || 'box'; // 'box', 'sphere', 'plane'
    this.halfExtents = options.halfExtents ? { ...options.halfExtents } : { x: 0.5, y: 0.5, z: 0.5 };
    this.radius = options.radius || 0.5;
    
    this.friction = options.friction !== undefined ? options.friction : 0.5;
    this.restitution = options.restitution !== undefined ? options.restitution : 0.1;
    this.grounded = false;
  }

  getAABB() {
    return {
      min: {
        x: this.position.x - this.halfExtents.x,
        y: this.position.y - this.halfExtents.y,
        z: this.position.z - this.halfExtents.z
      },
      max: {
        x: this.position.x + this.halfExtents.x,
        y: this.position.y + this.halfExtents.y,
        z: this.position.z + this.halfExtents.z
      }
    };
  }
}

class PhysicsEngine {
  constructor() {
    this.bodies = [];
    this.gravity = { x: 0, y: -9.81, z: 0 };
    this.simSpeed = 1.0;
  }

  addBody(body) {
    if (!this.bodies.find(b => b.id === body.id)) {
      this.bodies.push(body);
    }
  }

  removeBody(id) {
    this.bodies = this.bodies.filter(b => b.id !== id);
  }

  clear() {
    this.bodies = [];
  }

  update(dt) {
    const adjDt = dt * this.simSpeed;
    if (adjDt <= 0) return;

    // 1. Integrate forces (Gravity & Velocity)
    for (const body of this.bodies) {
      if (body.isStatic) continue;

      // Apply gravity
      body.velocity.x += this.gravity.x * adjDt;
      body.velocity.y += this.gravity.y * adjDt;
      body.velocity.z += this.gravity.z * adjDt;

      // Apply positions
      body.position.x += body.velocity.x * adjDt;
      body.position.y += body.velocity.y * adjDt;
      body.position.z += body.velocity.z * adjDt;
      
      body.rotation.x += body.angularVelocity.x * adjDt;
      body.rotation.y += body.angularVelocity.y * adjDt;
      body.rotation.z += body.angularVelocity.z * adjDt;
      
      body.grounded = false;
    }

    // 2. Resolve Collisions with Ground Plane (y = 0 is default floor level)
    for (const body of this.bodies) {
      if (body.isStatic) continue;

      if (body.shape === 'box') {
        const bottomY = body.position.y - body.halfExtents.y;
        if (bottomY < 0) {
          // Collision with floor
          body.position.y = body.halfExtents.y;
          body.velocity.y = -body.velocity.y * body.restitution;
          if (Math.abs(body.velocity.y) < 0.05) body.velocity.y = 0;
          
          // Ground friction (horizontal dampening)
          body.velocity.x *= (1 - body.friction * 0.1);
          body.velocity.z *= (1 - body.friction * 0.1);
          body.angularVelocity.x *= 0.9;
          body.angularVelocity.y *= 0.9;
          body.angularVelocity.z *= 0.9;
          body.grounded = true;
        }
      } else if (body.shape === 'sphere') {
        const bottomY = body.position.y - body.radius;
        if (bottomY < 0) {
          body.position.y = body.radius;
          body.velocity.y = -body.velocity.y * body.restitution;
          if (Math.abs(body.velocity.y) < 0.05) body.velocity.y = 0;
          
          body.velocity.x *= (1 - body.friction * 0.1);
          body.velocity.z *= (1 - body.friction * 0.1);
          body.grounded = true;
        }
      }
    }

    // 3. Resolve Rigid-Body AABB-to-AABB collisions (Narrow Phase)
    for (let i = 0; i < this.bodies.length; i++) {
      for (let j = i + 1; j < this.bodies.length; j++) {
        const bA = this.bodies[i];
        const bB = this.bodies[j];

        if (bA.isStatic && bB.isStatic) continue;

        if (bA.shape === 'box' && bB.shape === 'box') {
          this.resolveBoxBoxCollision(bA, bB);
        }
      }
    }
  }

  resolveBoxBoxCollision(bA, bB) {
    const a = bA.getAABB();
    const b = bB.getAABB();

    // Check overlap
    const overlapX = Math.min(a.max.x, b.max.x) - Math.max(a.min.x, b.min.x);
    const overlapY = Math.min(a.max.y, b.max.y) - Math.max(a.min.y, b.min.y);
    const overlapZ = Math.min(a.max.z, b.max.z) - Math.max(a.min.z, b.min.z);

    if (overlapX > 0 && overlapY > 0 && overlapZ > 0) {
      // Collision detected! Determine minimal translation axis (MTA)
      let normal = { x: 0, y: 0, z: 0 };
      let penetration = 0;

      if (overlapX < overlapY && overlapX < overlapZ) {
        penetration = overlapX;
        normal.x = bA.position.x < bB.position.x ? -1 : 1;
      } else if (overlapY < overlapX && overlapY < overlapZ) {
        penetration = overlapY;
        normal.y = bA.position.y < bB.position.y ? -1 : 1;
      } else {
        penetration = overlapZ;
        normal.z = bA.position.z < bB.position.z ? -1 : 1;
      }

      // Resolve Penetration
      const massRatioA = bA.isStatic ? 0 : (bB.isStatic ? 1 : 0.5);
      const massRatioB = bB.isStatic ? 0 : (bA.isStatic ? 1 : 0.5);

      if (!bA.isStatic) {
        bA.position.x += normal.x * penetration * massRatioA;
        bA.position.y += normal.y * penetration * massRatioA;
        bA.position.z += normal.z * penetration * massRatioA;
      }
      if (!bB.isStatic) {
        bB.position.x -= normal.x * penetration * massRatioB;
        bB.position.y -= normal.y * penetration * massRatioB;
        bB.position.z -= normal.z * penetration * massRatioB;
      }

      // Relative Velocity
      const relVel = {
        x: bA.velocity.x - bB.velocity.x,
        y: bA.velocity.y - bB.velocity.y,
        z: bA.velocity.z - bB.velocity.z
      };

      // Velocity along normal
      const velAlongNormal = relVel.x * normal.x + relVel.y * normal.y + relVel.z * normal.z;

      // Do not resolve if velocities are separating
      if (velAlongNormal < 0) return;

      // Calculate impulse scalar
      const e = Math.min(bA.restitution, bB.restitution);
      const impulseScalar = -(1 + e) * velAlongNormal / ((bA.isStatic ? 0 : 1 / bA.mass) + (bB.isStatic ? 0 : 1 / bB.mass));

      // Apply impulse
      if (!bA.isStatic) {
        bA.velocity.x += (impulseScalar / bA.mass) * normal.x;
        bA.velocity.y += (impulseScalar / bA.mass) * normal.y;
        bA.velocity.z += (impulseScalar / bA.mass) * normal.z;
      }
      if (!bB.isStatic) {
        bB.velocity.x -= (impulseScalar / bB.mass) * normal.x;
        bB.velocity.y -= (impulseScalar / bB.mass) * normal.y;
        bB.velocity.z -= (impulseScalar / bB.mass) * normal.z;
      }

      eventBus.publish('physics.collision', { bodyA: bA.id, bodyB: bB.id, normal, penetration });
    }
  }
}

module.exports = { PhysicsBody, PhysicsEngine };
