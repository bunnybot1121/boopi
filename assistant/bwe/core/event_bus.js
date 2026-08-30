class EventBus {
  constructor() {
    this.listeners = new Map();
  }

  subscribe(event, callback) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, []);
    }
    this.listeners.get(event).push(callback);
    return () => this.unsubscribe(event, callback);
  }

  unsubscribe(event, callback) {
    if (!this.listeners.has(event)) return;
    const callbacks = this.listeners.get(event).filter(cb => cb !== callback);
    this.listeners.set(event, callbacks);
  }

  publish(event, data) {
    // Exact match
    if (this.listeners.has(event)) {
      this.listeners.get(event).forEach(callback => {
        try {
          callback(data);
        } catch (e) {
          console.error(`[EventBus] Error in callback for ${event}:`, e);
        }
      });
    }
    // Wildcard matches (e.g. "sensor.*" matches "sensor.mq2")
    for (const [key, callbacks] of this.listeners.entries()) {
      if (key.includes('*')) {
        const regex = new RegExp('^' + key.split('.').map(part => part === '*' ? '.*' : part).join('\\.') + '$');
        if (regex.test(event)) {
          callbacks.forEach(callback => {
            try {
              callback(data, event);
            } catch (e) {
              console.error(`[EventBus] Error in wildcard callback for ${key}:`, e);
            }
          });
        }
      }
    }
  }
}

module.exports = new EventBus();
