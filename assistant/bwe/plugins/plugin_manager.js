const eventBus = require('../core/event_bus');

class PluginManager {
  constructor() {
    this.registeredPlugins = new Map(); // name -> class definition
    this.instances = new Map();         // id -> instantiated plugin object
    
    // Subscribe to simulation updates to step components
    eventBus.subscribe('engine.tick_sensors', ({ dt }) => {
      this.update(dt);
    });
  }

  registerPlugin(name, pluginClass) {
    if (this.registeredPlugins.has(name)) {
      console.warn(`[PluginManager] Plugin ${name} is already registered. Overwriting.`);
    }
    this.registeredPlugins.set(name, pluginClass);
    eventBus.publish('plugin.registered', { name });
    console.log(`[PluginManager] Registered plugin: ${name}`);
  }

  unregisterPlugin(name) {
    this.registeredPlugins.delete(name);
    eventBus.publish('plugin.unregistered', { name });
  }

  instantiate(pluginName, instanceId, initialConfig = {}) {
    const PluginClass = this.registeredPlugins.get(pluginName);
    if (!PluginClass) {
      console.error(`[PluginManager] Cannot instantiate: Plugin ${pluginName} not registered.`);
      return null;
    }

    try {
      const instance = new PluginClass(instanceId, initialConfig);
      this.instances.set(instanceId, instance);
      
      if (typeof instance.initialize === 'function') {
        instance.initialize();
      }
      
      eventBus.publish('plugin.instantiated', { id: instanceId, plugin: pluginName });
      return instance;
    } catch (e) {
      console.error(`[PluginManager] Error instantiating plugin ${pluginName}:`, e);
      return null;
    }
  }

  destroyInstance(instanceId) {
    const instance = this.instances.get(instanceId);
    if (instance) {
      if (typeof instance.onDestroy === 'function') {
        instance.onDestroy();
      }
      this.instances.delete(instanceId);
      eventBus.publish('plugin.destroyed', { id: instanceId });
    }
  }

  update(dt) {
    for (const [id, instance] of this.instances.entries()) {
      if (typeof instance.update === 'function') {
        try {
          // Check warm-up delays and active states
          instance.update(dt);
        } catch (e) {
          console.error(`[PluginManager] Error updating instance ${id}:`, e);
        }
      }
    }
  }

  clear() {
    for (const id of this.instances.keys()) {
      this.destroyInstance(id);
    }
    this.instances.clear();
  }
}

module.exports = new PluginManager();
