(() => {
if (typeof require === 'undefined') {
    window.initializeBWE = () => console.log('BWE 3D Simulator runs in Electron mode.');
    return;
}
const THREE = require('three');
const eventBus = require('./bwe/core/event_bus');
const bweEngine = require('./bwe/core/engine');
const { SceneObject } = require('./bwe/core/scene_graph');
const { PhysicsBody } = require('./bwe/core/physics');
const pluginManager = require('./bwe/plugins/plugin_manager');
const peripheralBus = require('./bwe/peripherals/peripheral_bus');
const hilBridge = require('./bwe/interface/hil_bridge');
const twinManager = require('./bwe/core/twin_manager');
const fs = require('fs');
const path = require('path');

// Load built-in component plugins
const MQ2Plugin = require('./bwe/plugins/sensors/mq2');
const HCSR04Plugin = require('./bwe/plugins/sensors/hcsr04');
const ServoPlugin = require('./bwe/plugins/actuators/servo');
const OLEDPlugin = require('./bwe/plugins/actuators/oled');

// Register them with the manager
pluginManager.registerPlugin('mq2', MQ2Plugin);
pluginManager.registerPlugin('hcsr04', HCSR04Plugin);
pluginManager.registerPlugin('servo', ServoPlugin);
pluginManager.registerPlugin('oled', OLEDPlugin);

let scene, camera, renderer;
let selectedObjectId = null;
let activeEnvironment = 'robotics_lab';
let scopeCanvas, scopeCtx;
let scopeData = [];
let obstacleCount = 0;
let lastSentVoltage = -1.0;

// 3D Camera Orbit & Viewport State Variables
let orbitTarget = new THREE.Vector3(0, 0, 0);
let cameraRadius = 9.5;
let cameraTheta = 0.0;
let cameraPhi = 1.0;
let isOrbiting = false;
let isPanning = false;
let isDraggingObject = false;
let mouseLastPos = { x: 0, y: 0 };
let activeSelectionBox = null;
let activeWire3DMeshes = new Map();

function updateCameraPosition() {
  if (!camera) return;
  const x = orbitTarget.x + cameraRadius * Math.sin(cameraPhi) * Math.sin(cameraTheta);
  const y = orbitTarget.y + cameraRadius * Math.cos(cameraPhi);
  const z = orbitTarget.z + cameraRadius * Math.sin(cameraPhi) * Math.cos(cameraTheta);
  
  camera.position.set(x, y, z);
  camera.lookAt(orbitTarget);
}

function updateSelectionHighlight() {
  if (activeSelectionBox) {
    scene.remove(activeSelectionBox);
    activeSelectionBox = null;
  }

  if (!selectedObjectId) return;
  const obj = bweEngine.sceneGraph.getObject(selectedObjectId);
  if (obj && obj.mesh) {
    const boxHelper = new THREE.BoxHelper(obj.mesh, 0xa78bfa);
    scene.add(boxHelper);
    activeSelectionBox = boxHelper;
  }
}

function update3DWires() {
  if (!scene) return;

  const activeWireIds = new Set();

  peripheralBus.wires.forEach(w => {
    activeWireIds.add(w.id);
    const startObj = bweEngine.sceneGraph.getObject(w.fromId);
    const endObj = bweEngine.sceneGraph.getObject(w.toId);

    if (startObj && endObj && startObj.mesh && endObj.mesh) {
      const p1 = new THREE.Vector3();
      const p2 = new THREE.Vector3();
      startObj.mesh.getWorldPosition(p1);
      endObj.mesh.getWorldPosition(p2);

      const dist = p1.distanceTo(p2);
      const archHeight = Math.max(0.6, dist * 0.35);

      const mid1 = p1.clone().add(new THREE.Vector3(0, archHeight, 0));
      const mid2 = p2.clone().add(new THREE.Vector3(0, archHeight, 0));

      const curve = new THREE.CubicBezierCurve3(p1, mid1, mid2, p2);
      const wireGeo = new THREE.TubeGeometry(curve, 20, 0.035, 8, false);

      let wireMesh = activeWire3DMeshes.get(w.id);
      if (!wireMesh) {
        const wireMat = new THREE.MeshStandardMaterial({
          color: new THREE.Color(w.color || 0x38bdf8),
          roughness: 0.3,
          metalness: 0.2
        });
        wireMesh = new THREE.Mesh(wireGeo, wireMat);
        scene.add(wireMesh);
        activeWire3DMeshes.set(w.id, wireMesh);
      } else {
        wireMesh.geometry.dispose();
        wireMesh.geometry = wireGeo;
      }
    }
  });

  for (const [id, mesh] of activeWire3DMeshes.entries()) {
    if (!activeWireIds.has(id)) {
      scene.remove(mesh);
      if (mesh.geometry) mesh.geometry.dispose();
      activeWire3DMeshes.delete(id);
    }
  }
}

// HIL Diagnostics Local Cache
let esp32HILStats = {
  status: "offline",
  latency: 0.0,
  tx: 0,
  rx: 0,
  errors: 0,
  port: "None"
};

// 3D GLTF Asset Loader Pipeline
let GLTFLoaderModule = null;

async function loadGLTF(url, onLoad, onError) {
  try {
    if (!GLTFLoaderModule) {
      const loaderPath = path.join(__dirname, 'node_modules', 'three', 'examples', 'jsm', 'loaders', 'GLTFLoader.js');
      GLTFLoaderModule = await import('file:///' + loaderPath.replace(/\\/g, '/'));
    }
    const loader = new GLTFLoaderModule.GLTFLoader();
    loader.load(url, onLoad, undefined, onError);
  } catch (err) {
    if (onError) onError(err);
  }
}

function getModelPath(componentName) {
  const assetsDir = path.join(__dirname, 'assets', 'models');
  const glbPath = path.join(assetsDir, `${componentName}.glb`);
  const gltfPath = path.join(assetsDir, `${componentName}.gltf`);
  
  if (fs.existsSync(glbPath)) return 'file:///' + glbPath.replace(/\\/g, '/');
  if (fs.existsSync(gltfPath)) return 'file:///' + gltfPath.replace(/\\/g, '/');
  return null;
}

function initializeBWE() {
  const container = document.getElementById('bwe-canvas-container');
  if (!container || scene) return; // Prevent double initialization

  // 1. Setup Three.js Viewport
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0f172a);
  scene.fog = new THREE.FogExp2(0x0f172a, 0.05);

  camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 100);
  updateCameraPosition();

  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  container.appendChild(renderer.domElement);

  // 2. Add Lighting with soft ambient and shadow casting
  const ambientLight = new THREE.AmbientLight(0xffffff, 0.25);
  scene.add(ambientLight);

  const dirLight = new THREE.DirectionalLight(0xffffff, 0.85);
  dirLight.position.set(5, 10, 5);
  dirLight.castShadow = true;
  dirLight.shadow.mapSize.width = 1024;
  dirLight.shadow.mapSize.height = 1024;
  scene.add(dirLight);

  // Decorative laboratory grid floor
  const gridHelper = new THREE.GridHelper(30, 30, 0x4f46e5, 0x334155);
  gridHelper.position.y = 0.01;
  gridHelper.name = 'floor';
  scene.add(gridHelper);

  // 3. Connect to the ESP32 server & HIL Bridge
  hilBridge.connect();

  // 4. Bind BWE Engine updates to Three.js Rendering
  eventBus.subscribe('engine.render', () => {
    renderer.render(scene, camera);
    updateOscilloscope();
    updateDashboardTelemetry();
    update3DWires();
    if (activeSelectionBox && selectedObjectId) {
      const obj = bweEngine.sceneGraph.getObject(selectedObjectId);
      if (obj && obj.mesh) activeSelectionBox.update();
    }
  });

  // Load Robotics Course as default
  loadEnvironment('robotics_lab');

  // Setup UI event listeners
  setupBWEUI();

  // Render initial view
  renderer.render(scene, camera);
}

function loadEnvironment(envName) {
  activeEnvironment = envName;
  bweEngine.clear();
  selectedObjectId = null;
  
  // Clear extra meshes from scene
  const toRemove = [];
  scene.traverse(child => {
    if (child.isMesh && child.name !== 'floor') {
      toRemove.push(child);
    }
  });
  toRemove.forEach(mesh => scene.remove(mesh));

  // Build Floor Ground plane
  const floorGeo = new THREE.PlaneGeometry(50, 50);
  const floorMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.8 });
  const floor = new THREE.Mesh(floorGeo, floorMat);
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  floor.name = 'floor';
  scene.add(floor);

  if (envName === 'robotics_lab') {
    scene.background = new THREE.Color(0x0a0a16);
    scene.fog.color = new THREE.Color(0x0a0a16);
    
    // Add target obstacle cubes
    spawnObstacle('wall_1', { x: -2, y: 0.5, z: -3 }, { x: 3, y: 1, z: 0.3 });
    spawnObstacle('wall_2', { x: 2, y: 0.5, z: -2 }, { x: 0.3, y: 1, z: 4 });
    
    // Add floating Gas Leak Source
    const gasSource = new SceneObject('gas_source_1', 'gas_source', { intensity: 12000 });
    gasSource.position = { x: -1.5, y: 0.5, z: -4 };
    
    // Glowing mesh for visual confirmation
    const gasGeo = new THREE.SphereGeometry(0.25, 16, 16);
    const gasMat = new THREE.MeshBasicMaterial({ color: 0x10b981, wireframe: true });
    gasSource.mesh = new THREE.Mesh(gasGeo, gasMat);
    scene.add(gasSource.mesh);
    
    bweEngine.sceneGraph.addObject(gasSource);
  } else if (envName === 'mars_base') {
    scene.background = new THREE.Color(0x2d1510);
    scene.fog.color = new THREE.Color(0x2d1510);
    floorMat.color.setHex(0x9c3d28); // Red sand
    
    // Add boulders
    spawnObstacle('crater_rock_1', { x: -4, y: 0.4, z: -1 }, { x: 1.5, y: 0.8, z: 1.5 });
    spawnObstacle('crater_rock_2', { x: 3, y: 0.5, z: -4 }, { x: 2, y: 1, z: 2 });
  } else if (envName === 'blank') {
    scene.background = new THREE.Color(0x0f172a);
    scene.fog.color = new THREE.Color(0x0f172a);
  }

  rebuildHierarchyList();
  rebuildInspector();
  rebuildWiringPanel();
  if (renderer) renderer.render(scene, camera);
}

function spawnObstacle(id, pos, size) {
  const obj = new SceneObject(id, 'obstacle');
  obj.position = { ...pos };
  
  const geo = new THREE.BoxGeometry(size.x, size.y, size.z);
  const mat = new THREE.MeshStandardMaterial({ color: 0x475569, metalness: 0.2, roughness: 0.5 });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  mesh.userData = { id: id };
  obj.mesh = mesh;
  scene.add(mesh);

  // Rigid physical body
  obj.physicsBody = new PhysicsBody(id, {
    mass: 0, // Static
    position: pos,
    halfExtents: { x: size.x / 2, y: size.y / 2, z: size.z / 2 }
  });

  bweEngine.sceneGraph.addObject(obj);
}

// -------------------------------------------------------------
// Dynamic Component Spawners (Model Pipeline & Fallbacks)
// -------------------------------------------------------------

function spawnESP32() {
  if (bweEngine.sceneGraph.getObject('esp32')) return;
  const esp32 = new SceneObject('esp32', 'mcu');
  esp32.position = { x: 0, y: 0.05, z: 0 };
  
  const modelUrl = getModelPath('esp32');
  if (modelUrl) {
    loadGLTF(modelUrl, (gltf) => {
      const model = gltf.scene;
      model.castShadow = true;
      model.receiveShadow = true;
      model.userData = { id: 'esp32' };
      esp32.mesh = model;
      scene.add(model);
      bweEngine.sceneGraph.addObject(esp32);
      rebuildHierarchyList();
      if (renderer) renderer.render(scene, camera);
    }, (err) => {
      console.error("[BWE] Failed to load ESP32 GLTF, using fallback:", err);
      createESP32Fallback(esp32);
    });
  } else {
    createESP32Fallback(esp32);
  }
}

function createESP32Fallback(esp32) {
  const espGeo = new THREE.BoxGeometry(1.6, 0.1, 2.4);
  const espMat = new THREE.MeshStandardMaterial({ color: 0x064e3b, roughness: 0.3 });
  const espMesh = new THREE.Mesh(espGeo, espMat);
  espMesh.castShadow = true;
  espMesh.userData = { id: 'esp32' };
  esp32.mesh = espMesh;
  scene.add(espMesh);
  bweEngine.sceneGraph.addObject(esp32);
  rebuildHierarchyList();
  if (renderer) renderer.render(scene, camera);
}

function spawnMQ2Sensor() {
  if (bweEngine.sceneGraph.getObject('mq2_sensor')) return;
  const mq2 = new SceneObject('mq2_sensor', 'sensor');
  mq2.position = { x: 2, y: 0.2, z: 1 };
  
  const modelUrl = getModelPath('mq2');
  if (modelUrl) {
    loadGLTF(modelUrl, (gltf) => {
      const model = gltf.scene;
      model.castShadow = true;
      model.userData = { id: 'mq2_sensor' };
      mq2.mesh = model;
      scene.add(model);
      pluginManager.instantiate('mq2', 'mq2_sensor', { pin: 34 });
      bweEngine.sceneGraph.addObject(mq2);
      rebuildHierarchyList();
      if (renderer) renderer.render(scene, camera);
    }, (err) => {
      console.error("[BWE] Failed to load MQ2 GLTF, using fallback:", err);
      createMQ2Fallback(mq2);
    });
  } else {
    createMQ2Fallback(mq2);
  }
}

function createMQ2Fallback(mq2) {
  const mq2Geo = new THREE.CylinderGeometry(0.3, 0.3, 0.4, 16);
  const mq2Mat = new THREE.MeshStandardMaterial({ color: 0x64748b, metalness: 0.8 });
  const mq2Mesh = new THREE.Mesh(mq2Geo, mq2Mat);
  mq2Mesh.castShadow = true;
  mq2Mesh.userData = { id: 'mq2_sensor' };
  mq2.mesh = mq2Mesh;
  scene.add(mq2Mesh);
  pluginManager.instantiate('mq2', 'mq2_sensor', { pin: 34 });
  bweEngine.sceneGraph.addObject(mq2);
  rebuildHierarchyList();
  if (renderer) renderer.render(scene, camera);
}

function spawnHCSR04Sensor() {
  if (bweEngine.sceneGraph.getObject('hcsr04_sensor')) return;
  const hcsr04 = new SceneObject('hcsr04_sensor', 'sensor');
  hcsr04.position = { x: -2, y: 0.2, z: 2 };
  
  const modelUrl = getModelPath('hcsr04');
  if (modelUrl) {
    loadGLTF(modelUrl, (gltf) => {
      const model = gltf.scene;
      model.castShadow = true;
      model.userData = { id: 'hcsr04_sensor' };
      hcsr04.mesh = model;
      scene.add(model);
      pluginManager.instantiate('hcsr04', 'hcsr04_sensor', { trigPin: 12, echoPin: 13 });
      bweEngine.sceneGraph.addObject(hcsr04);
      rebuildHierarchyList();
      if (renderer) renderer.render(scene, camera);
    }, (err) => {
      console.error("[BWE] Failed to load HCSR04 GLTF, using fallback:", err);
      createHCSR04Fallback(hcsr04);
    });
  } else {
    createHCSR04Fallback(hcsr04);
  }
}

function createHCSR04Fallback(hcsr04) {
  const geo = new THREE.BoxGeometry(1.2, 0.4, 0.2);
  const mat = new THREE.MeshStandardMaterial({ color: 0x1e3a8a, metalness: 0.5 });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.castShadow = true;
  mesh.userData = { id: 'hcsr04_sensor' };
  hcsr04.mesh = mesh;
  scene.add(mesh);
  pluginManager.instantiate('hcsr04', 'hcsr04_sensor', { trigPin: 12, echoPin: 13 });
  bweEngine.sceneGraph.addObject(hcsr04);
  rebuildHierarchyList();
  if (renderer) renderer.render(scene, camera);
}

function spawnServoMotor() {
  if (bweEngine.sceneGraph.getObject('servo_motor')) return;
  const servo = new SceneObject('servo_motor', 'actuator');
  servo.position = { x: 0, y: 0.2, z: -2 };
  
  const modelUrl = getModelPath('servo');
  if (modelUrl) {
    loadGLTF(modelUrl, (gltf) => {
      const model = gltf.scene;
      model.castShadow = true;
      model.userData = { id: 'servo_motor' };
      servo.mesh = model;
      scene.add(model);
      pluginManager.instantiate('servo', 'servo_motor', { pin: 18 });
      bweEngine.sceneGraph.addObject(servo);
      rebuildHierarchyList();
      if (renderer) renderer.render(scene, camera);
    }, (err) => {
      console.error("[BWE] Failed to load Servo GLTF, using fallback:", err);
      createServoFallback(servo);
    });
  } else {
    createServoFallback(servo);
  }
}

function createServoFallback(servo) {
  const group = new THREE.Group();
  
  const geo = new THREE.BoxGeometry(0.6, 0.5, 0.8);
  const mat = new THREE.MeshStandardMaterial({ color: 0x2563eb, roughness: 0.4 });
  const bodyMesh = new THREE.Mesh(geo, mat);
  bodyMesh.castShadow = true;
  group.add(bodyMesh);

  const shaftGeo = new THREE.CylinderGeometry(0.08, 0.08, 0.1, 16);
  const shaftMat = new THREE.MeshStandardMaterial({ color: 0x1e293b });
  const shaftMesh = new THREE.Mesh(shaftGeo, shaftMat);
  shaftMesh.position.set(0, 0.28, 0.2);
  group.add(shaftMesh);

  const hornGroup = new THREE.Group();
  hornGroup.position.set(0, 0.33, 0.2);

  const hornGeo = new THREE.BoxGeometry(0.12, 0.04, 0.6);
  const hornMat = new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.2 });
  const hornArm = new THREE.Mesh(hornGeo, hornMat);
  hornArm.position.set(0, 0, 0.25);
  hornGroup.add(hornArm);

  group.add(hornGroup);

  group.userData = { id: 'servo_motor' };
  servo.mesh = group;
  servo.hornMesh = hornGroup;
  
  scene.add(group);
  pluginManager.instantiate('servo', 'servo_motor', { pin: 18 });
  bweEngine.sceneGraph.addObject(servo);
  rebuildHierarchyList();
  if (renderer) renderer.render(scene, camera);
}

function updateServoAngle(servoId, angleDeg) {
  const obj = bweEngine.sceneGraph.getObject(servoId);
  if (obj && obj.hornMesh) {
    const angleRad = (angleDeg * Math.PI) / 180.0;
    obj.hornMesh.rotation.y = angleRad;
  }
}

function spawnIRSensor() {
  if (bweEngine.sceneGraph.getObject('ir_sensor')) return;
  const ir = new SceneObject('ir_sensor', 'sensor');
  ir.position = { x: 1.5, y: 0.2, z: -1 };

  const group = new THREE.Group();

  const boardGeo = new THREE.BoxGeometry(0.8, 0.1, 1.4);
  const boardMat = new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.4 });
  const boardMesh = new THREE.Mesh(boardGeo, boardMat);
  group.add(boardMesh);

  const emitGeo = new THREE.CylinderGeometry(0.08, 0.08, 0.25, 16);
  const emitMat = new THREE.MeshStandardMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.8 });
  const emitMesh = new THREE.Mesh(emitGeo, emitMat);
  emitMesh.rotation.x = Math.PI / 2;
  emitMesh.position.set(-0.2, 0.1, -0.6);
  group.add(emitMesh);

  const recvGeo = new THREE.CylinderGeometry(0.08, 0.08, 0.25, 16);
  const recvMat = new THREE.MeshStandardMaterial({ color: 0x020617 });
  const recvMesh = new THREE.Mesh(recvGeo, recvMat);
  recvMesh.rotation.x = Math.PI / 2;
  recvMesh.position.set(0.2, 0.1, -0.6);
  group.add(recvMesh);

  group.userData = { id: 'ir_sensor' };
  ir.mesh = group;

  scene.add(group);
  bweEngine.sceneGraph.addObject(ir);
  rebuildHierarchyList();
  if (renderer) renderer.render(scene, camera);
}

function spawnCameraModule() {
  if (bweEngine.sceneGraph.getObject('camera_module')) return;
  const cam = new SceneObject('camera_module', 'sensor');
  cam.position = { x: -1.5, y: 0.25, z: 0 };

  const group = new THREE.Group();

  const pcbGeo = new THREE.BoxGeometry(1.0, 0.1, 1.2);
  const pcbMat = new THREE.MeshStandardMaterial({ color: 0x78350f, roughness: 0.5 });
  const pcbMesh = new THREE.Mesh(pcbGeo, pcbMat);
  group.add(pcbMesh);

  const camGeo = new THREE.BoxGeometry(0.4, 0.3, 0.4);
  const camMat = new THREE.MeshStandardMaterial({ color: 0x18181b, roughness: 0.3 });
  const camMesh = new THREE.Mesh(camGeo, camMat);
  camMesh.position.set(0, 0.18, 0);
  group.add(camMesh);

  const lensGeo = new THREE.CylinderGeometry(0.12, 0.12, 0.1, 16);
  const lensMat = new THREE.MeshStandardMaterial({ color: 0x0284c7, metalness: 0.8, roughness: 0.1 });
  const lensMesh = new THREE.Mesh(lensGeo, lensMat);
  lensMesh.rotation.x = Math.PI / 2;
  lensMesh.position.set(0, 0.18, -0.22);
  group.add(lensMesh);

  group.userData = { id: 'camera_module' };
  cam.mesh = group;

  scene.add(group);
  bweEngine.sceneGraph.addObject(cam);
  rebuildHierarchyList();
  if (renderer) renderer.render(scene, camera);
}

function spawnOLEDDisplay() {
  if (bweEngine.sceneGraph.getObject('oled_display')) return;
  const oled = new SceneObject('oled_display', 'actuator');
  oled.position = { x: -2, y: 0.3, z: -1 };
  
  const modelUrl = getModelPath('oled');
  if (modelUrl) {
    loadGLTF(modelUrl, (gltf) => {
      const model = gltf.scene;
      model.castShadow = true;
      model.userData = { id: 'oled_display' };
      oled.mesh = model;
      scene.add(model);
      pluginManager.instantiate('oled', 'oled_display', { address: 0x3C });
      bweEngine.sceneGraph.addObject(oled);
      rebuildHierarchyList();
      if (renderer) renderer.render(scene, camera);
    }, (err) => {
      console.error("[BWE] Failed to load OLED GLTF, using fallback:", err);
      createOLEDFallback(oled);
    });
  } else {
    createOLEDFallback(oled);
  }
}

function createOLEDFallback(oled) {
  const geo = new THREE.BoxGeometry(1.2, 0.7, 0.08);
  const mat = new THREE.MeshStandardMaterial({ color: 0x18181b, roughness: 0.6 });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.castShadow = true;
  mesh.userData = { id: 'oled_display' };
  oled.mesh = mesh;
  scene.add(mesh);
  pluginManager.instantiate('oled', 'oled_display', { address: 0x3C });
  bweEngine.sceneGraph.addObject(oled);
  rebuildHierarchyList();
  if (renderer) renderer.render(scene, camera);
}

function spawnDynamicObstacle() {
  obstacleCount++;
  const id = `obstacle_${obstacleCount}`;
  const pos = { x: 0, y: 0.5, z: 0 };
  const size = { x: 1, y: 1, z: 1 };
  
  const obj = new SceneObject(id, 'obstacle');
  obj.position = { ...pos };
  
  const geo = new THREE.BoxGeometry(size.x, size.y, size.z);
  const mat = new THREE.MeshStandardMaterial({ color: 0x4b5563, metalness: 0.1, roughness: 0.6 });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  mesh.userData = { id: id };
  obj.mesh = mesh;
  scene.add(mesh);

  obj.physicsBody = new PhysicsBody(id, {
    mass: 1.0, 
    position: pos,
    halfExtents: { x: size.x / 2, y: size.y / 2, z: size.z / 2 }
  });

  bweEngine.sceneGraph.addObject(obj);
  rebuildHierarchyList();
  if (renderer) renderer.render(scene, camera);
}

function selectObject(id) {
  selectedObjectId = id;
  
  // Highlight selected mesh
  bweEngine.sceneGraph.getAllObjects().forEach(obj => {
    if (obj.mesh) {
      obj.mesh.traverse(child => {
        if (child.isMesh && child.material) {
          if (obj.id === id) {
            if (!child.userData.originalColor) {
              child.userData.originalColor = child.material.color ? child.material.color.getHex() : 0x475569;
            }
            if (child.material.color) child.material.color.setHex(0xa78bfa);
          } else if (child.userData.originalColor) {
            if (child.material.color) child.material.color.setHex(child.userData.originalColor);
          }
        }
      });
    }
  });

  updateSelectionHighlight();
  rebuildInspector();
  rebuildWiringPanel();
  rebuildHierarchyList();
  if (renderer) renderer.render(scene, camera);
}

function updateObjectPosition(id, axis, value) {
  const obj = bweEngine.sceneGraph.getObject(id);
  if (obj) {
    const val = parseFloat(value);
    if (!isNaN(val)) {
      obj.position[axis] = val;
      if (obj.mesh) {
        obj.mesh.position[axis] = val;
      }
      if (obj.physicsBody) {
        obj.physicsBody.position[axis] = val;
      }
      if (renderer) renderer.render(scene, camera);
    }
  }
}
window.updateObjectPosition = updateObjectPosition;

function rebuildHierarchyList() {
  const tree = document.querySelector('.bwe-tree-list');
  if (!tree) return;

  tree.innerHTML = '';
  const objects = bweEngine.sceneGraph.getAllObjects();

  objects.forEach(obj => {
    if (obj.id === 'root') return;

    const el = document.createElement('div');
    el.className = `bwe-tree-item ${obj.id === selectedObjectId ? 'selected' : ''}`;
    el.innerHTML = `
      <span>📦 ${obj.id} <small style="color:var(--text-light)">(${obj.type})</small></span>
      <button class="bwe-nav-btn" style="padding: 2px 6px; font-size: 10px;">Inspect</button>
    `;
    el.addEventListener('click', () => selectObject(obj.id));
    tree.appendChild(el);
  });
}

function rebuildInspector() {
  const table = document.getElementById('bwe-inspector-table');
  if (!table) return;

  table.innerHTML = '';
  if (!selectedObjectId) {
    table.innerHTML = '<tr><td colspan="2" style="text-align:center; color:var(--text-light);">Select an object.</td></tr>';
    return;
  }

  const obj = bweEngine.sceneGraph.getObject(selectedObjectId);
  if (!obj) return;

  let rows = [];
  
  if (selectedObjectId === 'esp32') {
    const statusText = esp32HILStats.status === 'online' 
      ? '<span style="color:#10b981; font-weight:700;">ACTIVE ✅</span>' 
      : '<span style="color:#ef4444; font-weight:700;">DISCONNECTED ❌</span>';
      
    rows = [
      { key: 'ID', val: obj.id },
      { key: 'Device Type', val: 'Physical ESP32 MCU' },
      { key: 'HIL Link Status', val: statusText },
      { key: 'Serial COM Port', val: esp32HILStats.port },
      { key: 'Bridge Latency', val: `<span style="color:#a78bfa; font-weight:700;">${esp32HILStats.latency.toFixed(1)} ms</span>` },
      { key: 'Sent (TX)', val: `${esp32HILStats.tx} packets` },
      { key: 'Received (RX)', val: `${esp32HILStats.rx} packets` },
      { key: 'Frame Errors', val: esp32HILStats.errors > 0 ? `<span style="color:#ef4444; font-weight:bold;">${esp32HILStats.errors}</span>` : '0' }
    ];

    const servoAngle = (peripheralBus.pwm.getPWM(18).duty * 180.0).toFixed(0);
    const mq2Voltage = peripheralBus.analog.getPinVoltage(34).toFixed(2);
    
    rows.push({
      key: 'Peripheral Map',
      val: `
        <table style="width:100%; border-collapse:collapse; margin-top:5px; font-size:11px;">
          <tr style="border-bottom:1px solid rgba(255,255,255,0.1); text-align:left; color:var(--text-light); font-weight:700;">
            <th style="padding:4px 0;">Pin</th>
            <th style="padding:4px 0;">Direction</th>
            <th style="padding:4px 0;">Value / State</th>
          </tr>
          <tr>
            <td style="padding:4px 0; color:#38bdf8;">GP18</td>
            <td style="padding:4px 0;">PWM Out (Servo)</td>
            <td style="padding:4px 0; font-family:monospace; color:#a78bfa;">${servoAngle}°</td>
          </tr>
          <tr>
            <td style="padding:4px 0; color:#38bdf8;">GP34</td>
            <td style="padding:4px 0;">ADC In (MQ2)</td>
            <td style="padding:4px 0; font-family:monospace; color:#10b981;">${mq2Voltage} V</td>
          </tr>
        </table>
      `
    });
  } else {
    rows = [
      { key: 'ID', val: obj.id },
      { key: 'Type', val: obj.type },
      { 
        key: 'Position', 
        val: `
          X: <input type="number" step="0.1" class="bwe-inspector-input" value="${obj.position.x.toFixed(1)}" oninput="updateObjectPosition('${obj.id}', 'x', this.value)">
          Y: <input type="number" step="0.1" class="bwe-inspector-input" value="${obj.position.y.toFixed(1)}" oninput="updateObjectPosition('${obj.id}', 'y', this.value)">
          Z: <input type="number" step="0.1" class="bwe-inspector-input" value="${obj.position.z.toFixed(1)}" oninput="updateObjectPosition('${obj.id}', 'z', this.value)">
        ` 
      },
      { key: 'Rotation', val: `Y: ${(obj.rotation.y * 180 / Math.PI).toFixed(1)}°` }
    ];

    const plugin = pluginManager.instances.get(obj.id);
    if (plugin) {
      rows.push({ key: 'Update Rate', val: `${plugin.metadata.updateRate} Hz` });
      rows.push({ key: 'Warmup State', val: plugin.isWarmingUp ? `Warming up (${Math.round(plugin.warmupTimer)}s)` : 'Ready ✅' });
      rows.push({ key: 'Drift Offset', val: `${plugin.driftAccumulator.toFixed(4)}` });
      rows.push({ key: 'Telemetry Reading', val: `${plugin.rawValue.toFixed(1)} PPM` });
    }
  }

  rows.forEach(r => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td style="padding:8px; font-weight:600; color:var(--text-light); font-size:12px; vertical-align:top; white-space:nowrap;">${r.key}</td>
      <td style="padding:8px; font-family:monospace; font-size:12px;">${r.val}</td>
    `;
    table.appendChild(tr);
  });
}

function rebuildWiringPanel() {
  const grid = document.querySelector('.bwe-wiring-grid');
  if (!grid) return;

  grid.innerHTML = '';
  if (!selectedObjectId || selectedObjectId === 'esp32') {
    grid.innerHTML = '<div style="text-align:center; color:var(--text-light); font-size:12px; padding:25px;">Select a peripheral sensor/actuator to configure pin wiring connections.</div>';
    return;
  }

  const obj = bweEngine.sceneGraph.getObject(selectedObjectId);
  const plugin = pluginManager.instances.get(obj.id);
  
  if (plugin && plugin.analogPin !== undefined) {
    const el = document.createElement('div');
    el.className = 'bwe-wiring-node';
    
    const wireId = `esp32_34_to_${obj.id}_${plugin.analogPin}`;
    const isWired = peripheralBus.wires.some(w => w.id.includes(obj.id));
    
    el.innerHTML = `
      <span>ADC Pin ${plugin.analogPin} (Analog Out)</span>
      <div style="display:flex; align-items:center; gap:8px;">
        <span style="font-size:10px; color:${isWired ? '#48bb78' : '#cbd5e0'}">${isWired ? 'Connected to ESP32:34' : 'Disconnected'}</span>
        <div class="bwe-pin-circle ${isWired ? 'selected' : ''}" id="wire-trigger-btn"></div>
      </div>
    `;

    el.querySelector('#wire-trigger-btn').addEventListener('click', () => {
      if (isWired) {
        const found = peripheralBus.wires.find(w => w.id.includes(obj.id));
        if (found) peripheralBus.removeWire(found.id);
      } else {
        peripheralBus.addWire('esp32', 34, obj.id, plugin.analogPin, '#e28743');
      }
      rebuildWiringPanel();
    });
    
    grid.appendChild(el);
  }
}

function setupBWEUI() {
  const { ipcRenderer } = require('electron');

  // Dynamic window resizing to fit Three.js camera viewport to container aspect ratio
  const container = document.getElementById('bwe-canvas-container');
  window.addEventListener('resize', () => {
    if (renderer && camera && container) {
      const w = container.clientWidth;
      const h = container.clientHeight;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    }
  });

  // Handle panel visibility toggling to maximize environment view area
  const toggleUiBtn = document.getElementById('bwe-btn-toggle-ui');
  if (toggleUiBtn) {
    toggleUiBtn.addEventListener('click', () => {
      const leftBar = document.querySelector('.bwe-left-bar');
      const rightBar = document.querySelector('.bwe-right-bar');
      const telemetryPanel = document.querySelector('.bwe-telemetry-panel');
      
      const isHidden = leftBar.style.display === 'none';
      leftBar.style.display = isHidden ? '' : 'none';
      rightBar.style.display = isHidden ? '' : 'none';
      telemetryPanel.style.display = isHidden ? '' : 'none';
      
      toggleUiBtn.style.color = isHidden ? '#38bdf8' : '#e2e8f0';
      toggleUiBtn.style.borderColor = isHidden ? '#38bdf8' : 'rgba(255,255,255,0.1)';
      
      // Trigger size updates on next tick
      setTimeout(() => {
        if (renderer && camera && container) {
          const w = container.clientWidth;
          const h = container.clientHeight;
          renderer.setSize(w, h);
          camera.aspect = w / h;
          camera.updateProjectionMatrix();
        }
      }, 30);
    });
  }

  // Handle incoming pin writes from physical ESP32 routed via MQTT
  ipcRenderer.on('bwe-pin-write', (event, data) => {
    if (data.pin === 18) {
      const duty = data.val / 180.0;
      peripheralBus.pwm.setPWM(18, 50, duty);
      updateServoAngle('servo_motor', data.val);
    } else {
      peripheralBus.gpio.writePin(data.pin, data.val);
    }
  });

  // Handle real-time bridge diagnostics packet updates
  ipcRenderer.on('bwe-esp32-stats', (event, stats) => {
    esp32HILStats = { ...esp32HILStats, ...stats };
    
    // 1. Update the latency value indicator
    const latencyVal = document.getElementById('bwe-val-latency');
    if (latencyVal) {
      latencyVal.textContent = Math.round(esp32HILStats.latency) + ' ms';
      if (esp32HILStats.latency > 120) {
        latencyVal.style.color = '#ef4444'; // Red (High latency warning)
      } else {
        latencyVal.style.color = '#a78bfa'; // Violet (Low latency normal)
      }
    }

    // 2. Update the HIL Active status overlay badge
    const badge = document.getElementById('bwe-badge-hil-status');
    if (badge) {
      if (esp32HILStats.status === 'online') {
        badge.textContent = 'HIL Active';
        badge.className = 'bwe-badge-status online';
      } else {
        badge.textContent = 'HIL Offline';
        badge.className = 'bwe-badge-status offline';
      }
    }

    // 3. Re-render Inspector properties dynamically if the physical board is selected
    if (selectedObjectId === 'esp32') {
      rebuildInspector();
    }
  });

  // Play/Pause simulation toggle
  const playBtn = document.getElementById('bwe-btn-play');
  if (playBtn) {
    playBtn.addEventListener('click', () => {
      if (bweEngine.isRunning) {
        bweEngine.stop();
        playBtn.innerHTML = '▶️ Run';
        playBtn.style.color = '#e2e8f0';
        playBtn.style.borderColor = 'rgba(255,255,255,0.1)';
      } else {
        bweEngine.start();
        playBtn.innerHTML = '⏸️ Pause';
        playBtn.style.color = '#10b981';
        playBtn.style.borderColor = 'rgba(16,185,129,0.4)';
      }
    });
  }

  // Spawn Library Bindings
  const btnEsp32 = document.getElementById('bwe-spawn-esp32');
  const btnMq2 = document.getElementById('bwe-spawn-mq2');
  const btnHcsr04 = document.getElementById('bwe-spawn-hcsr04');
  const btnServo = document.getElementById('bwe-spawn-servo');
  const btnIr = document.getElementById('bwe-spawn-ir');
  const btnCam = document.getElementById('bwe-spawn-cam');
  const btnOled = document.getElementById('bwe-spawn-oled');
  const btnObstacle = document.getElementById('bwe-spawn-obstacle');

  if (btnEsp32) btnEsp32.addEventListener('click', spawnESP32);
  if (btnMq2) btnMq2.addEventListener('click', spawnMQ2Sensor);
  if (btnHcsr04) btnHcsr04.addEventListener('click', spawnHCSR04Sensor);
  if (btnServo) btnServo.addEventListener('click', spawnServoMotor);
  if (btnIr) btnIr.addEventListener('click', spawnIRSensor);
  if (btnCam) btnCam.addEventListener('click', spawnCameraModule);
  if (btnOled) btnOled.addEventListener('click', spawnOLEDDisplay);
  if (btnObstacle) btnObstacle.addEventListener('click', spawnDynamicObstacle);

  // Environment Selector Hooks
  const roboticsBtn = document.getElementById('bwe-btn-robotics');
  const marsBtn = document.getElementById('bwe-btn-mars');
  const blankBtn = document.getElementById('bwe-btn-blank');
  
  if (roboticsBtn) roboticsBtn.addEventListener('click', () => loadEnvironment('robotics_lab'));
  if (marsBtn) marsBtn.addEventListener('click', () => loadEnvironment('mars_base'));
  if (blankBtn) blankBtn.addEventListener('click', () => loadEnvironment('blank'));

  // Guide modal triggers
  const guideBtn = document.getElementById('bwe-btn-guide');
  const closeGuideBtn = document.getElementById('bwe-btn-close-guide');
  const guideCard = document.getElementById('bwe-guide-card');

  if (guideBtn && guideCard) {
    guideBtn.addEventListener('click', () => {
      guideCard.classList.toggle('hidden');
    });
  }
  if (closeGuideBtn && guideCard) {
    closeGuideBtn.addEventListener('click', () => {
      guideCard.classList.add('hidden');
    });
  }

  // Twin Control Hooks
  const recBtn = document.getElementById('bwe-btn-rec');
  if (recBtn) {
    recBtn.addEventListener('click', () => {
      if (twinManager.isRecording) {
        twinManager.stopRecording();
        recBtn.textContent = '🔴 Record Twin';
        recBtn.style.color = '';
      } else {
        twinManager.startRecording();
        recBtn.textContent = '⏹️ Stop Recording';
        recBtn.style.color = '#ff5f56';
      }
    });
  }

  // Setup Oscilloscope Canvas
  scopeCanvas = document.getElementById('bwe-scope-canvas');
  if (scopeCanvas) {
    scopeCtx = scopeCanvas.getContext('2d');
  }

  // Interactive Viewport Mouse Navigation (Orbit 360°, Pan, Zoom, 3D Object Drag)
  if (container) {
    container.addEventListener('contextmenu', (e) => e.preventDefault());

    container.addEventListener('mousedown', (e) => {
      mouseLastPos = { x: e.clientX, y: e.clientY };

      const rect = renderer.domElement.getBoundingClientRect();
      const mouse = new THREE.Vector2(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        -((e.clientY - rect.top) / rect.height) * 2 + 1
      );

      const raycaster = new THREE.Raycaster();
      raycaster.setFromCamera(mouse, camera);

      const intersects = raycaster.intersectObjects(scene.children, true);
      let clickedId = null;

      for (let i = 0; i < intersects.length; i++) {
        let cur = intersects[i].object;
        while (cur && cur !== scene) {
          if (cur.userData && cur.userData.id && cur.name !== 'floor') {
            clickedId = cur.userData.id;
            break;
          }
          cur = cur.parent;
        }
        if (clickedId) break;
      }

      if (e.button === 0) { // Left-click
        if (clickedId) {
          selectObject(clickedId);
          isDraggingObject = true;
        } else {
          isOrbiting = true;
        }
      } else if (e.button === 2) { // Right-click
        isPanning = true;
      }
    });

    window.addEventListener('mousemove', (e) => {
      const deltaX = e.clientX - mouseLastPos.x;
      const deltaY = e.clientY - mouseLastPos.y;
      mouseLastPos = { x: e.clientX, y: e.clientY };

      if (isDraggingObject && selectedObjectId) {
        const rect = renderer.domElement.getBoundingClientRect();
        const mouse = new THREE.Vector2(
          ((e.clientX - rect.left) / rect.width) * 2 - 1,
          -((e.clientY - rect.top) / rect.height) * 2 + 1
        );
        const raycaster = new THREE.Raycaster();
        raycaster.setFromCamera(mouse, camera);

        const floorPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
        const intersectPoint = new THREE.Vector3();
        raycaster.ray.intersectPlane(floorPlane, intersectPoint);

        if (intersectPoint) {
          const obj = bweEngine.sceneGraph.getObject(selectedObjectId);
          if (obj) {
            obj.position.x = Math.round(intersectPoint.x * 10) / 10;
            obj.position.z = Math.round(intersectPoint.z * 10) / 10;
            if (obj.mesh) {
              obj.mesh.position.x = obj.position.x;
              obj.mesh.position.z = obj.position.z;
            }
            if (obj.physicsBody) {
              obj.physicsBody.position.x = obj.position.x;
              obj.physicsBody.position.z = obj.position.z;
            }
            rebuildInspector();
          }
        }
      } else if (isOrbiting) {
        cameraTheta -= deltaX * 0.008;
        cameraPhi -= deltaY * 0.008;
        cameraPhi = Math.max(0.05, Math.min(Math.PI / 2 - 0.05, cameraPhi));
        updateCameraPosition();
      } else if (isPanning) {
        const panSpeed = cameraRadius * 0.0012;
        const forward = new THREE.Vector3(Math.sin(cameraTheta), 0, Math.cos(cameraTheta));
        const right = new THREE.Vector3(Math.cos(cameraTheta), 0, -Math.sin(cameraTheta));

        orbitTarget.addScaledVector(right, -deltaX * panSpeed);
        orbitTarget.addScaledVector(forward, deltaY * panSpeed);
        updateCameraPosition();
      }
    });

    window.addEventListener('mouseup', () => {
      isOrbiting = false;
      isPanning = false;
      isDraggingObject = false;
    });

    container.addEventListener('wheel', (e) => {
      e.preventDefault();
      cameraRadius += e.deltaY * 0.008;
      cameraRadius = Math.max(2.0, Math.min(35.0, cameraRadius));
      updateCameraPosition();
    });
  }
}

function updateOscilloscope() {
  if (!scopeCtx || !scopeCanvas) return;

  const voltage = peripheralBus.analog.getPinVoltage(34);

  // Forward to physical ESP32 over MQTT/Serial with change throttling
  if (Math.abs(voltage - lastSentVoltage) > 0.02) {
    lastSentVoltage = voltage;
    const { ipcRenderer } = require('electron');
    ipcRenderer.send('bwe-pin-update', { pin: 34, val: voltage });
  }

  scopeData.push(voltage);
  if (scopeData.length > scopeCanvas.width) {
    scopeData.shift();
  }

  scopeCtx.fillStyle = '#090d16';
  scopeCtx.fillRect(0, 0, scopeCanvas.width, scopeCanvas.height);

  scopeCtx.strokeStyle = 'rgba(167, 139, 250, 0.08)';
  scopeCtx.lineWidth = 1;
  for (let x = 0; x < scopeCanvas.width; x += 40) {
    scopeCtx.beginPath();
    scopeCtx.moveTo(x, 0);
    scopeCtx.lineTo(x, scopeCanvas.height);
    scopeCtx.stroke();
  }
  for (let y = 0; y < scopeCanvas.height; y += 30) {
    scopeCtx.beginPath();
    scopeCtx.moveTo(0, y);
    scopeCtx.lineTo(scopeCanvas.width, y);
    scopeCtx.stroke();
  }

  scopeCtx.strokeStyle = '#10b981';
  scopeCtx.lineWidth = 2;
  scopeCtx.beginPath();

  for (let i = 0; i < scopeData.length; i++) {
    const x = i;
    const y = scopeCanvas.height - (scopeData[i] / 3.3) * (scopeCanvas.height - 10) - 5;
    if (i === 0) scopeCtx.moveTo(x, y);
    else scopeCtx.lineTo(x, y);
  }
  scopeCtx.stroke();
}

function updateDashboardTelemetry() {
  const ppmVal = document.getElementById('bwe-val-ppm');
  const voltVal = document.getElementById('bwe-val-volts');
  const latencyVal = document.getElementById('bwe-val-latency');

  if (ppmVal) {
    const plugin = pluginManager.instances.get('mq2_sensor');
    ppmVal.textContent = plugin ? Math.round(plugin.read()) : '0';
  }

  if (voltVal) {
    const volts = peripheralBus.analog.getPinVoltage(34);
    voltVal.textContent = volts.toFixed(2);
  }

  // Update latency values in dashboard card fallback if HIL stats are present
  if (latencyVal && esp32HILStats.status === 'online') {
    latencyVal.textContent = Math.round(esp32HILStats.latency) + ' ms';
  }
}

module.exports = { initializeBWE, selectObject, loadEnvironment };
if (typeof window !== 'undefined') {
  window.initializeBWE = initializeBWE;
  window.selectObject = selectObject;
  window.loadEnvironment = loadEnvironment;
}
})();

