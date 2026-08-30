const eventBus = require('../core/event_bus');

class Actuator {
  constructor(id, type, metadata = {}) {
    this.id = id;
    this.type = type;
    this.metadata = metadata;
    this.state = {};
    this.isActive = false;
  }

  initialize() {
    this.isActive = true;
    eventBus.publish('actuator.initialized', { id: this.id, type: this.type });
  }

  execute(command) {
    eventBus.publish('actuator.command', { id: this.id, command });
  }

  stop() {
    this.isActive = false;
    eventBus.publish('actuator.stopped', { id: this.id });
  }

  reset() {
    this.state = {};
    eventBus.publish('actuator.reset', { id: this.id });
  }

  update(dt) {
    // Actuator physics/rotation animation step in simulation
  }

  onDestroy() {
    this.stop();
  }
}

module.exports = Actuator;
