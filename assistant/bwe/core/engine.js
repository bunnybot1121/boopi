const { SceneGraph } = require('./scene_graph');
const { PhysicsEngine } = require('./physics');
const eventBus = require('./event_bus');

class SimulationClock {
  constructor() {
    this.timeScale = 1.0;
    this.simulatedTime = 0.0; // Total accumulated simulation seconds
    this.realTimeElapsed = 0.0;
    
    // Configurable update frequencies (in Hz)
    this.frequencies = {
      physics: 120,    // Physics steps at 120 Hz (fixed time step)
      render: 60,      // Visual updates (60 Hz target)
      sensors: 20,     // Sensor scanning rate
      gpio: 50,        // Peripheral bus syncing rate
      comm: 10         // MQTT/Serial communication output updates
    };
    
    // Accumulators for individual frequency steps
    this.accumulators = {
      physics: 0,
      render: 0,
      sensors: 0,
      gpio: 0,
      comm: 0
    };
  }

  setFrequency(type, hz) {
    if (this.frequencies[type] !== undefined) {
      this.frequencies[type] = hz;
    }
  }
}

class BWEEngine {
  constructor() {
    this.clock = new SimulationClock();
    this.sceneGraph = new SceneGraph();
    this.physicsEngine = new PhysicsEngine();
    
    this.isRunning = false;
    this.lastRealTime = 0;
    this.frameId = null;
    
    // Handle global scene-to-physics bindings
    eventBus.subscribe('scene.object_added', ({ id }) => {
      const obj = this.sceneGraph.getObject(id);
      if (obj && obj.physicsBody) {
        this.physicsEngine.addBody(obj.physicsBody);
      }
    });

    eventBus.subscribe('scene.object_destroyed', ({ id }) => {
      this.physicsEngine.removeBody(id);
    });
  }

  start() {
    if (this.isRunning) return;
    this.isRunning = true;
    this.lastRealTime = performance.now();
    
    const loop = (timestamp) => {
      if (!this.isRunning) return;
      
      const realDt = (timestamp - this.lastRealTime) / 1000.0;
      this.lastRealTime = timestamp;
      
      // Cap dt to prevent "spiral of death" during heavy lag spikes
      const cappedDt = Math.min(realDt, 0.1);
      
      this.step(cappedDt);
      
      this.frameId = requestAnimationFrame(loop);
    };
    
    this.frameId = requestAnimationFrame(loop);
    eventBus.publish('engine.started');
    console.log("[BWE Engine] Simulator running.");
  }

  stop() {
    if (!this.isRunning) return;
    this.isRunning = false;
    if (this.frameId) {
      cancelAnimationFrame(this.frameId);
      this.frameId = null;
    }
    eventBus.publish('engine.stopped');
    console.log("[BWE Engine] Simulator stopped.");
  }

  step(realDt) {
    const simDt = realDt * this.clock.timeScale;
    this.clock.realTimeElapsed += realDt;
    this.clock.simulatedTime += simDt;

    // Accumulate delta times for each subsystem
    for (const key in this.clock.accumulators) {
      this.clock.accumulators[key] += simDt;
    }

    // 1. Step Physics (Fixed timestep at e.g. 120 Hz = 0.00833s)
    const physicsStepSize = 1.0 / this.clock.frequencies.physics;
    let physicsUpdatesCount = 0;
    while (this.clock.accumulators.physics >= physicsStepSize) {
      this.physicsEngine.update(physicsStepSize);
      this.clock.accumulators.physics -= physicsStepSize;
      
      physicsUpdatesCount++;
      if (physicsUpdatesCount > 10) {
        // Break to avoid freezing the tab under severe lag
        this.clock.accumulators.physics = 0;
        break;
      }
    }

    // 2. Step GPIO Bus manager (e.g. 50 Hz)
    const gpioStepSize = 1.0 / this.clock.frequencies.gpio;
    if (this.clock.accumulators.gpio >= gpioStepSize) {
      eventBus.publish('engine.tick_gpio', { dt: gpioStepSize });
      this.clock.accumulators.gpio %= gpioStepSize;
    }

    // 3. Step Sensors (e.g. 20 Hz)
    const sensorStepSize = 1.0 / this.clock.frequencies.sensors;
    if (this.clock.accumulators.sensors >= sensorStepSize) {
      eventBus.publish('engine.tick_sensors', { dt: sensorStepSize });
      this.clock.accumulators.sensors %= sensorStepSize;
    }

    // 4. Step Communication Bridge output rates (e.g. 10 Hz)
    const commStepSize = 1.0 / this.clock.frequencies.comm;
    if (this.clock.accumulators.comm >= commStepSize) {
      eventBus.publish('engine.tick_comm', { dt: commStepSize });
      this.clock.accumulators.comm %= commStepSize;
    }

    // 5. Update Scene Graph hierarchy (e.g. sync meshes and evaluate joints)
    this.sceneGraph.update(simDt);

    // 6. Step Render Trigger
    const renderStepSize = 1.0 / this.clock.frequencies.render;
    if (this.clock.accumulators.render >= renderStepSize) {
      eventBus.publish('engine.render', { simTime: this.clock.simulatedTime });
      this.clock.accumulators.render %= renderStepSize;
    }
  }

  clear() {
    this.sceneGraph.clear();
    this.physicsEngine.clear();
  }
}

module.exports = new BWEEngine();
