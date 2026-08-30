const eventBus = require('./event_bus');

class SceneObject {
  constructor(id, type = 'generic', metadata = {}) {
    this.id = id;
    this.type = type;
    this.metadata = metadata;
    
    // Transform coordinates
    this.position = { x: 0, y: 0, z: 0 };
    this.rotation = { x: 0, y: 0, z: 0 }; // Euler angles in radians
    this.scale = { x: 1, y: 1, z: 1 };
    
    this.parent = null;
    this.children = [];
    this.components = new Map();
    
    // Three.js 3D representation binding (filled by renderer)
    this.mesh = null;
    // Physics body binding (filled by physics layer)
    this.physicsBody = null;
  }

  addComponent(name, component) {
    this.components.set(name, component);
    if (typeof component.initialize === 'function') {
      component.initialize(this);
    }
    return this;
  }

  getComponent(name) {
    return this.components.get(name);
  }

  removeComponent(name) {
    const comp = this.components.get(name);
    if (comp) {
      if (typeof comp.onDestroy === 'function') {
        comp.onDestroy();
      }
      this.components.delete(name);
    }
  }

  addChild(child) {
    if (child.parent) {
      child.parent.removeChild(child);
    }
    child.parent = this;
    this.children.push(child);
    eventBus.publish('scene.child_added', { parentId: this.id, childId: child.id });
    return this;
  }

  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index !== -1) {
      this.children.splice(index, 1);
      child.parent = null;
      eventBus.publish('scene.child_removed', { parentId: this.id, childId: child.id });
    }
  }

  update(dt) {
    // Update transform from physics body if active
    if (this.physicsBody) {
      this.position.x = this.physicsBody.position.x;
      this.position.y = this.physicsBody.position.y;
      this.position.z = this.physicsBody.position.z;
      
      this.rotation.x = this.physicsBody.rotation.x;
      this.rotation.y = this.physicsBody.rotation.y;
      this.rotation.z = this.physicsBody.rotation.z;
    }

    // Update all attached components
    for (const [name, component] of this.components.entries()) {
      if (typeof component.update === 'function') {
        try {
          component.update(dt, this);
        } catch (e) {
          console.error(`[SceneObject] Error updating component ${name} on ${this.id}:`, e);
        }
      }
    }

    // Propagate updates to children
    for (const child of this.children) {
      child.update(dt);
    }

    // Sync three.js mesh position if bound
    if (this.mesh) {
      this.mesh.position.set(this.position.x, this.position.y, this.position.z);
      this.mesh.rotation.set(this.rotation.x, this.rotation.y, this.rotation.z);
      this.mesh.scale.set(this.scale.x, this.scale.y, this.scale.z);
    }
  }

  destroy() {
    // Remove from parent
    if (this.parent) {
      this.parent.removeChild(this);
    }
    
    // Destroy children
    for (const child of [...this.children]) {
      child.destroy();
    }
    
    // Destroy components
    for (const name of this.components.keys()) {
      this.removeComponent(name);
    }
    
    eventBus.publish('scene.object_destroyed', { id: this.id });
  }
}

class SceneGraph {
  constructor() {
    this.root = new SceneObject('root', 'world');
    this.registry = new Map();
    this.registry.set('root', this.root);
  }

  addObject(obj, parentId = 'root') {
    const parent = this.registry.get(parentId);
    if (!parent) {
      console.warn(`[SceneGraph] Parent ${parentId} not found. Adding to root.`);
      this.root.addChild(obj);
    } else {
      parent.addChild(obj);
    }
    this.registerRecursively(obj);
    eventBus.publish('scene.object_added', { id: obj.id, type: obj.type, parentId: parentId });
    return obj;
  }

  registerRecursively(obj) {
    this.registry.set(obj.id, obj);
    for (const child of obj.children) {
      this.registerRecursively(child);
    }
  }

  removeObject(id) {
    const obj = this.registry.get(id);
    if (obj) {
      this.unregisterRecursively(obj);
      obj.destroy();
      return true;
    }
    return false;
  }

  unregisterRecursively(obj) {
    this.registry.delete(obj.id);
    for (const child of obj.children) {
      this.unregisterRecursively(child);
    }
  }

  getObject(id) {
    return this.registry.get(id);
  }

  getAllObjects() {
    return Array.from(this.registry.values());
  }

  clear() {
    // Destroy all children of root
    const children = [...this.root.children];
    for (const child of children) {
      this.removeObject(child.id);
    }
    this.registry.clear();
    this.registry.set('root', this.root);
    eventBus.publish('scene.cleared');
  }

  update(dt) {
    this.root.update(dt);
  }
}

module.exports = { SceneObject, SceneGraph };
