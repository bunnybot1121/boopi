const fs = require('fs');
const path = require('path');
const eventBus = require('./event_bus');

class DigitalTwinManager {
  constructor() {
    this.isRecording = false;
    this.isReplaying = false;
    
    this.recordFile = null;
    this.recordBuffer = [];
    this.replayBuffer = [];
    this.replayIndex = 0;
    
    // Live physical state cache
    this.physicalState = {
      position: { x: 0, y: 0, z: 0 },
      rotation: { x: 0, y: 0, z: 0 },
      sensorReadings: {}
    };

    // Listen to tick events to log states
    eventBus.subscribe('engine.tick_comm', () => {
      if (this.isRecording) {
        this.captureTick();
      }
    });
  }

  syncPhysicalState(statePacket) {
    // Merge incoming physical telemetry from HIL Serial/MQTT
    if (statePacket.position) this.physicalState.position = { ...statePacket.position };
    if (statePacket.rotation) this.physicalState.rotation = { ...statePacket.rotation };
    if (statePacket.sensors) {
      this.physicalState.sensorReadings = {
        ...this.physicalState.sensorReadings,
        ...statePacket.sensors
      };
    }
    
    eventBus.publish('twin.sync', this.physicalState);
    this.calculateVariance();
  }

  calculateVariance() {
    // Compare virtual robot state against physical state
    const bweEngine = require('./engine');
    const virtualRobot = bweEngine.sceneGraph.getObject('esp32-001') || bweEngine.sceneGraph.getObject('robot');
    
    if (!virtualRobot) return;

    const dx = virtualRobot.position.x - this.physicalState.position.x;
    const dy = virtualRobot.position.y - this.physicalState.position.y;
    const dz = virtualRobot.position.z - this.physicalState.position.z;
    const positionVariance = Math.sqrt(dx * dx + dy * dy + dz * dz);

    const rotVariance = Math.abs(virtualRobot.rotation.y - this.physicalState.rotation.y);

    const varianceReport = {
      timestamp: Date.now(),
      positionVariance,
      rotVariance,
      sensorDelta: {}
    };

    eventBus.publish('twin.variance_report', varianceReport);
  }

  startRecording(filepath = 'bwe_twin_log.jsonl') {
    this.recordFile = path.resolve(filepath);
    this.recordBuffer = [];
    this.isRecording = true;
    console.log(`[TwinManager] Recording telemetry to ${this.recordFile}`);
    
    // Write header
    fs.writeFileSync(this.recordFile, JSON.stringify({ type: 'header', timestamp: Date.now() }) + '\n');
  }

  captureTick() {
    const bweEngine = require('./engine');
    const tickData = {
      timestamp: Date.now(),
      simTime: bweEngine.clock.simulatedTime,
      objects: []
    };

    // Serialize all scene objects
    const objects = bweEngine.sceneGraph.getAllObjects();
    for (const obj of objects) {
      if (obj.id === 'root') continue;
      tickData.objects.push({
        id: obj.id,
        type: obj.type,
        position: { ...obj.position },
        rotation: { ...obj.rotation }
      });
    }

    // Append to file
    try {
      fs.appendFileSync(this.recordFile, JSON.stringify(tickData) + '\n');
    } catch (e) {
      console.error('[TwinManager] Write tick error:', e);
    }
  }

  stopRecording() {
    this.isRecording = false;
    console.log(`[TwinManager] Telemetry recording stopped.`);
  }

  startPlayback(filepath = 'bwe_twin_log.jsonl') {
    const target = path.resolve(filepath);
    if (!fs.existsSync(target)) {
      console.warn(`[TwinManager] Playback file ${target} not found.`);
      return false;
    }

    try {
      const data = fs.readFileSync(target, 'utf-8');
      const lines = data.split('\n').filter(l => l.trim().length > 0);
      
      this.replayBuffer = [];
      for (const line of lines) {
        const parsed = JSON.parse(line);
        if (parsed.type !== 'header') {
          this.replayBuffer.push(parsed);
        }
      }
      
      this.replayIndex = 0;
      this.isReplaying = true;
      console.log(`[TwinManager] Playback started: loaded ${this.replayBuffer.length} ticks.`);
      
      // Stop the regular simulation clock so we don't conflict
      const bweEngine = require('./engine');
      bweEngine.stop();
      
      this.playbackStep();
      return true;
    } catch (e) {
      console.error('[TwinManager] Error loading playback file:', e);
      return false;
    }
  }

  playbackStep() {
    if (!this.isReplaying || this.replayIndex >= this.replayBuffer.length) {
      this.stopPlayback();
      return;
    }

    const tick = this.replayBuffer[this.replayIndex];
    const bweEngine = require('./engine');

    // Update scene objects to matched recorded coordinates
    for (const objData of tick.objects) {
      const obj = bweEngine.sceneGraph.getObject(objData.id);
      if (obj) {
        obj.position = { ...objData.position };
        obj.rotation = { ...objData.rotation };
        
        // Sync meshes
        if (obj.mesh) {
          obj.mesh.position.set(obj.position.x, obj.position.y, obj.position.z);
          obj.mesh.rotation.set(obj.rotation.x, obj.rotation.y, obj.rotation.z);
        }
      }
    }

    eventBus.publish('engine.render', { simTime: tick.simTime });

    this.replayIndex++;
    // Step at 30 FPS target
    setTimeout(() => this.playbackStep(), 33);
  }

  stopPlayback() {
    this.isReplaying = false;
    console.log('[TwinManager] Playback finished or stopped.');
    eventBus.publish('twin.playback_stopped');
  }
}

module.exports = new DigitalTwinManager();
