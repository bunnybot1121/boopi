import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

let scene, camera, renderer, model;
let leftEye = null;
let rightEye = null;
let mouthParts = [];
let body = null;
let originalMaterials = new Map(); // Store original colors to revert from red/angry state

let currentState = 'idle';
let stateTime = 0;
let lastTime = 0;

// Particle system for Thinking state
let thinkingParticles = null;

// Hearts system for Happy state
let activeHearts = [];

// Blinking tracking
let blinkTimer = 0;
let blinkDuration = 0;
let isBlinking = false;
let blinkFactor = 1.0;

// Audio amplitude tracking (simulated for talking lip-sync)
let talkAmplitude = 0;

// Gaze and Mouse Cursor tracking
let gazeTimer = 0;
let currentGazeX = 0;
let currentGazeY = 0;
let targetGazeX = 0;
let targetGazeY = 0;
let mouseX = 0;
let mouseY = 0;
let isMouseOver = false;

// TARGET STATES FOR SMOOTH INTERPOLATION (LERPING)
let targetModelPos = new THREE.Vector3(0, 0, 0);
let targetModelRot = new THREE.Euler(0, 0, 0);
let targetLeftEyeScale = new THREE.Vector3(1, 1, 1);
let targetRightEyeScale = new THREE.Vector3(1, 1, 1);
let targetLeftEyeRotZ = 0;
let targetRightEyeRotZ = 0;
let targetMouthScale = new THREE.Vector3(1, 1, 1);
let targetMouthPosX = 0;
let targetColorR = 1.0;
let targetColorG = 1.0;
let targetColorB = 1.0;

let currentModelPos = new THREE.Vector3(0, 0, 0);
let currentModelRot = new THREE.Euler(0, 0, 0);
let currentLeftEyeScale = new THREE.Vector3(1, 1, 1);
let currentRightEyeScale = new THREE.Vector3(1, 1, 1);
let currentLeftEyeRotZ = 0;
let currentRightEyeRotZ = 0;
let currentMouthScale = new THREE.Vector3(1, 1, 1);
let currentMouthPosX = 0;
let currentColorR = 1.0;
let currentColorG = 1.0;
let currentColorB = 1.0;

window.addEventListener('mousemove', (e) => {
  isMouseOver = true;
  mouseX = (e.clientX / window.innerWidth) - 0.5;
  mouseY = (e.clientY / window.innerHeight) - 0.5;
});

window.addEventListener('mouseleave', () => {
  isMouseOver = false;
});

export function init3D(containerId, modelPath) {
  const container = document.getElementById(containerId);
  if (!container) return;

  scene = new THREE.Scene();
  
  renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  container.appendChild(renderer.domElement);

  camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 100);
  camera.position.set(0, 0, 4.5);

  const ambientLight = new THREE.AmbientLight(0xffffff, 0.8);
  scene.add(ambientLight);

  const dirLight = new THREE.DirectionalLight(0xffffff, 1.2);
  dirLight.position.set(2, 4, 3);
  scene.add(dirLight);

  const pointLight = new THREE.PointLight(0xa78bfa, 1.5, 10);
  pointLight.position.set(0, 1, 2);
  scene.add(pointLight);

  setupThinkingParticles();

  const loader = new GLTFLoader();
  loader.load(
    modelPath,
    (gltf) => {
      model = gltf.scene;

      const box = new THREE.Box3().setFromObject(model);
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      const maxDim = Math.max(size.x, size.y, size.z);
      const scale = 2.0 / maxDim;
      model.scale.set(scale, scale, scale);
      model.position.sub(center.multiplyScalar(scale));

      model.traverse((child) => {
        if (child.isMesh) {
          child.castShadow = true;
          child.receiveShadow = true;
          
          if (child.material) {
            originalMaterials.set(child, {
              color: child.material.color ? child.material.color.clone() : null,
              emissive: child.material.emissive ? child.material.emissive.clone() : null
            });
          }

          const name = child.name.toLowerCase();
          if (name.includes('sphere')) {
            if (!leftEye) leftEye = child;
            else if (!rightEye) rightEye = child;
          } else if (name.includes('circle') || name.includes('nurbspath')) {
            mouthParts.push(child);
          } else if (name.includes('cylinder') || name.includes('cube')) {
            if (!body) body = child;
          }
        }
      });

      scene.add(model);
      requestAnimationFrame(animate);
    },
    undefined,
    (error) => {
      console.error('Error loading 3D model:', error);
    }
  );

  window.addEventListener('resize', onWindowResize);
}

function onWindowResize() {
  const container = renderer.domElement.parentElement;
  camera.aspect = container.clientWidth / container.clientHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(container.clientWidth, container.clientHeight);
}

function setupThinkingParticles() {
  const particleCount = 40;
  const geometry = new THREE.BufferGeometry();
  const positions = new Float32Array(particleCount * 3);

  for (let i = 0; i < particleCount * 3; i += 3) {
    const angle = Math.random() * Math.PI * 2;
    const radius = 1.2 + Math.random() * 0.4;
    positions[i] = Math.cos(angle) * radius;
    positions[i + 1] = (Math.random() - 0.5) * 1.5;
    positions[i + 2] = Math.sin(angle) * radius;
  }

  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  const material = new THREE.PointsMaterial({
    color: 0x8b5cf6,
    size: 0.08,
    transparent: true,
    opacity: 0.0,
    blending: THREE.AdditiveBlending
  });

  thinkingParticles = new THREE.Points(geometry, material);
  scene.add(thinkingParticles);
}

function spawn3DHeart() {
  const heartShape = new THREE.Shape();
  heartShape.moveTo(0, 0.3);
  heartShape.bezierCurveTo(0, 0.3, -0.2, 0.7, -0.6, 0.7);
  heartShape.bezierCurveTo(-1.0, 0.7, -1.1, 0.4, -1.1, 0.15);
  heartShape.bezierCurveTo(-1.1, -0.2, -0.7, -0.6, 0, -1.0);
  heartShape.bezierCurveTo(0.7, -0.6, 1.1, -0.2, 1.1, 0.15);
  heartShape.bezierCurveTo(1.1, 0.4, 1.0, 0.7, 0.6, 0.7);
  heartShape.bezierCurveTo(0.2, 0.7, 0, 0.3, 0, 0.3);

  const extrudeSettings = {
    depth: 0.1,
    bevelEnabled: true,
    bevelSegments: 3,
    steps: 1,
    bevelSize: 0.08,
    bevelThickness: 0.08
  };

  const geometry = new THREE.ExtrudeGeometry(heartShape, extrudeSettings);
  const material = new THREE.MeshPhongMaterial({
    color: 0xff4d7d,
    emissive: 0x550011,
    shininess: 80,
    transparent: true,
    opacity: 1.0
  });

  const heart = new THREE.Mesh(geometry, material);
  
  const scaleVal = 0.08 + Math.random() * 0.06;
  heart.scale.set(scaleVal, scaleVal, scaleVal);
  heart.position.set(
    (Math.random() - 0.5) * 0.8,
    (Math.random() - 0.5) * 0.4,
    (Math.random() - 0.5) * 0.4
  );

  heart.rotation.z = Math.PI;
  heart.rotation.y = (Math.random() - 0.5) * 0.5;

  scene.add(heart);
  activeHearts.push({
    mesh: heart,
    speedY: 0.02 + Math.random() * 0.02,
    speedRot: (Math.random() - 0.5) * 0.05,
    life: 1.0
  });
}

function updateHearts() {
  for (let i = activeHearts.length - 1; i >= 0; i--) {
    const heart = activeHearts[i];
    heart.mesh.position.y += heart.speedY;
    heart.mesh.position.x += Math.sin(stateTime * 5.0 + i) * 0.005;
    heart.mesh.rotation.y += heart.speedRot;
    heart.life -= 0.015;

    if (heart.life <= 0) {
      scene.remove(heart.mesh);
      heart.mesh.geometry.dispose();
      heart.mesh.material.dispose();
      activeHearts.splice(i, 1);
    } else {
      heart.mesh.material.opacity = heart.life;
    }
  }
}

export function set3DState(state) {
  if (currentState === state) return;
  currentState = state;
  stateTime = 0;

  console.log(`[3D Router] Activating state: ${state}`);

  // Base state defaults
  targetModelPos.set(0, 0, 0);
  targetModelRot.set(0, 0, 0);
  targetLeftEyeScale.set(1, 1, 1);
  targetRightEyeScale.set(1, 1, 1);
  targetLeftEyeRotZ = 0;
  targetRightEyeRotZ = 0;
  targetMouthScale.set(1, 1, 1);
  targetMouthPosX = 0;
  
  targetColorR = 1.0;
  targetColorG = 1.0;
  targetColorB = 1.0;

  if (state === 'angry' || state === 'error') {
     targetColorR = 0.85;
     targetColorG = 0.1;
     targetColorB = 0.1;
  }
}

function handleBlinking(delta) {
  if (!leftEye || !rightEye) return;

  blinkTimer -= delta;
  if (blinkTimer <= 0) {
    if (!isBlinking) {
      isBlinking = true;
      blinkDuration = 0.15; // 150ms blink
    }
  }

  if (isBlinking) {
    blinkDuration -= delta;
    if (blinkDuration <= 0) {
      isBlinking = false;
      blinkTimer = 3.0 + Math.random() * 4.0;
      blinkFactor = 1.0;
    } else {
      blinkFactor = Math.abs(Math.sin((blinkDuration / 0.15) * Math.PI)) * 0.9 + 0.1;
    }
  } else {
    blinkFactor = 1.0;
  }
}

function animate(timestamp) {
  requestAnimationFrame(animate);

  const delta = (timestamp - lastTime) / 1000;
  lastTime = timestamp;
  stateTime += delta;

  if (!model) return;

  // LERP FACTOR (smoothness)
  const lerpSpeed = 12.0 * delta; // Adjust multiplier for transition speed

  // 1. Process Thinking Particles
  if (thinkingParticles) {
    const targetParticleOpacity = (currentState === 'thinking') ? 0.8 : 0.0;
    thinkingParticles.material.opacity += (targetParticleOpacity - thinkingParticles.material.opacity) * lerpSpeed;
    if (thinkingParticles.material.opacity > 0.01) {
      thinkingParticles.rotation.y = -stateTime * 0.3;
      thinkingParticles.position.y = Math.sin(stateTime * 1.5) * 0.03;
    }
  }

  // 2. State-Specific Overrides (Continuous procedural motions)
  let extraPosY = 0;
  let extraPosX = 0;
  let extraPosZ = 0;
  let extraRotX = 0;
  let extraRotY = 0;
  let extraRotZ = 0;
  
  // Fast-fluctuating overrides applied outside of the lerp
  let extraMouthScaleX = 0;
  let extraMouthScaleY = 0;
  let extraEyeScale = 0;

  switch (currentState) {
    case 'idle':
    case 'chilling':
    case 'waiting':
      extraPosY = Math.sin(stateTime * 1.5) * 0.04; // Gentle breathing/floating
      extraRotY = Math.sin(stateTime * 0.8) * 0.05;
      extraRotZ = Math.sin(stateTime * 0.5) * 0.02; // Subtle natural swaying
      break;

    case 'listening':
      // Attentive tilt forward, active listening movements
      targetModelPos.z = 0.15; // Lean closer
      targetModelRot.x = 0.1; // Look slightly down
      targetModelRot.y = Math.sin(stateTime * 2.0) * 0.08; // Small shakes/nods of attention
      
      extraPosY = Math.sin(stateTime * 3.0) * 0.02;
      
      const pulse = 1.15 + Math.sin(stateTime * 6.0) * 0.05;
      targetLeftEyeScale.set(pulse, pulse, pulse);
      targetRightEyeScale.set(pulse, pulse, pulse);
      targetMouthScale.set(0.9, 0.9, 1.0);
      break;

    case 'thinking':
      // Highly dynamic pondering animation
      targetModelRot.z = Math.sin(stateTime * 3.0) * 0.12; // Head bobbing side to side
      targetModelRot.x = -0.05 + Math.sin(stateTime * 2.0) * 0.05; // Nodding slightly while thinking
      targetModelRot.y = Math.cos(stateTime * 2.5) * 0.15; // Looking around

      extraPosY = Math.sin(stateTime * 4.0) * 0.04; // Faster hover to show mental activity

      // Squint eyes dynamically
      const squint = 0.6 + Math.sin(stateTime * 5.0) * 0.2;
      targetLeftEyeScale.set(1.0, squint, 1.0);
      targetRightEyeScale.set(1.1, 1.1, 1.1);

      // Mouth moves slightly as if muttering
      targetMouthScale.set(0.8, 0.8 + Math.sin(stateTime * 10.0) * 0.2, 1.0);
      targetMouthPosX = 0.06 + Math.sin(stateTime * 4.0) * 0.03;
      break;

    case 'talking':
      extraPosY = Math.sin(stateTime * 12.0) * 0.04;
      // Energetic head bobbing while speaking
      extraRotX = Math.sin(stateTime * 8.0) * 0.05;
      extraRotZ = Math.sin(stateTime * 5.0) * 0.03;
      
      talkAmplitude = Math.abs(Math.sin(stateTime * 18.0) * Math.cos(stateTime * 7.0));
      
      extraMouthScaleX = -talkAmplitude * 0.18;
      extraMouthScaleY = talkAmplitude * 0.85;
      extraEyeScale = talkAmplitude * 0.08;
      break;

    case 'happy':
    case 'excited':
    case 'praise':
      extraPosY = Math.abs(Math.sin(stateTime * 8.0)) * 0.3; // Very bouncy
      extraRotY = Math.sin(stateTime * 12.0) * 0.2; // Wiggling happily
      extraRotZ = Math.sin(stateTime * 10.0) * 0.1; // Wiggle rotation

      targetLeftEyeScale.set(1.3, 0.5, 1.25); // "Smiling" eyes
      targetRightEyeScale.set(1.3, 0.5, 1.25);
      targetMouthScale.set(1.4, 0.6, 1.0); // Big wide smile

      if (Math.random() < 0.08 && activeHearts.length < 15) {
        spawn3DHeart();
      }
      break;

    case 'angry':
    case 'error':
      extraPosX = (Math.random() - 0.5) * 0.015;
      extraPosY = (Math.sin(stateTime * 8.0) * 0.03) + (Math.random() - 0.5) * 0.015;
      
      targetLeftEyeRotZ = -0.26;
      targetRightEyeRotZ = 0.26;
      targetLeftEyeScale.set(1.0, 0.5, 1.0);
      targetRightEyeScale.set(1.0, 0.5, 1.0);
      targetMouthScale.set(0.7, 1.35, 1.0);
      break;

    case 'sleeping':
      // Gentle, slow, deep breathing
      extraPosY = Math.sin(stateTime * 0.8) * 0.06 - 0.05; // Lowered posture
      targetModelRot.x = 0.15; // Head nodded forward
      
      // Eyes completely closed
      targetLeftEyeScale.set(1.0, 0.1, 1.0);
      targetRightEyeScale.set(1.0, 0.1, 1.0);
      
      // Tiny relaxed mouth
      targetMouthScale.set(0.5, 0.5, 1.0);
      break;

    case 'confused':
      // Tilted head, one eye big, one eye small
      targetModelRot.z = 0.2; 
      targetModelRot.x = -0.05;
      extraPosY = Math.sin(stateTime * 2.0) * 0.02;

      targetLeftEyeScale.set(1.3, 1.3, 1.3);
      targetRightEyeScale.set(0.6, 0.6, 1.0);
      
      targetMouthScale.set(0.6, 0.6, 1.0);
      targetMouthPosX = -0.05; // Mouth shifted to side
      break;

    case 'surprised':
      // Jump back slightly, look up, wide eyes and mouth
      targetModelPos.z = -0.2;
      targetModelRot.x = -0.15;
      extraPosY = Math.abs(Math.sin(stateTime * 15.0)) * 0.05 + 0.1; // Sudden jolt up
      
      targetLeftEyeScale.set(1.6, 1.6, 1.6);
      targetRightEyeScale.set(1.6, 1.6, 1.6);
      
      targetMouthScale.set(0.4, 1.8, 1.0); // Tall narrow 'O' shape mouth
      break;
  }

  // 3. Update Targets with Gaze
  if (isMouseOver) {
    targetGazeX = mouseX * 0.45;
    targetGazeY = mouseY * 0.35;
  } else if (currentState === 'thinking') {
    targetGazeX = 0.16;
    targetGazeY = -0.14;
  } else {
    gazeTimer -= delta;
    if (gazeTimer <= 0) {
      gazeTimer = 2.0 + Math.random() * 3.5;
      if (Math.random() < 0.75) {
        targetGazeX = (Math.random() - 0.5) * 0.22;
        targetGazeY = (Math.random() - 0.5) * 0.16;
      } else {
        targetGazeX = 0;
        targetGazeY = 0;
      }
    }
  }

  currentGazeX += (targetGazeX - currentGazeX) * 0.08;
  currentGazeY += (targetGazeY - currentGazeY) * 0.08;

  if (currentState !== 'angry' && currentState !== 'error') {
    handleBlinking(delta);
  }

  // 4. Perform Lerping
  currentModelPos.lerp(targetModelPos, lerpSpeed);
  currentModelRot.x += (targetModelRot.x - currentModelRot.x) * lerpSpeed;
  currentModelRot.y += (targetModelRot.y - currentModelRot.y) * lerpSpeed;
  currentModelRot.z += (targetModelRot.z - currentModelRot.z) * lerpSpeed;

  currentLeftEyeScale.lerp(targetLeftEyeScale, lerpSpeed);
  currentRightEyeScale.lerp(targetRightEyeScale, lerpSpeed);
  
  currentLeftEyeRotZ += (targetLeftEyeRotZ - currentLeftEyeRotZ) * lerpSpeed;
  currentRightEyeRotZ += (targetRightEyeRotZ - currentRightEyeRotZ) * lerpSpeed;

  currentMouthScale.lerp(targetMouthScale, lerpSpeed);
  currentMouthPosX += (targetMouthPosX - currentMouthPosX) * lerpSpeed;

  currentColorR += (targetColorR - currentColorR) * lerpSpeed;
  currentColorG += (targetColorG - currentColorG) * lerpSpeed;
  currentColorB += (targetColorB - currentColorB) * lerpSpeed;

  // 5. Apply Values to Meshes
  model.position.set(
    currentModelPos.x + extraPosX, 
    currentModelPos.y + extraPosY, 
    currentModelPos.z + extraPosZ
  );
  model.rotation.set(
    currentModelRot.x + extraRotX,
    currentModelRot.y + extraRotY,
    currentModelRot.z + extraRotZ
  );

  if (leftEye && rightEye) {
    leftEye.scale.set(
        currentLeftEyeScale.x + extraEyeScale, 
        (currentLeftEyeScale.y + extraEyeScale) * blinkFactor, 
        currentLeftEyeScale.z + extraEyeScale
    );
    rightEye.scale.set(
        currentRightEyeScale.x + extraEyeScale, 
        (currentRightEyeScale.y + extraEyeScale) * blinkFactor, 
        currentRightEyeScale.z + extraEyeScale
    );
    leftEye.rotation.set(-currentGazeY, currentGazeX, currentLeftEyeRotZ);
    rightEye.rotation.set(-currentGazeY, currentGazeX, currentRightEyeRotZ);
  }

  mouthParts.forEach(part => {
    part.scale.set(
        currentMouthScale.x + extraMouthScaleX,
        currentMouthScale.y + extraMouthScaleY,
        currentMouthScale.z
    );
    part.position.x = currentMouthPosX;
  });

  // Apply colors (with lerping for smooth red/angry transitions)
  originalMaterials.forEach((original, mesh) => {
    if (mesh.material && mesh.material.color && original.color) {
      if (currentColorR === 1.0 && currentColorG === 1.0 && currentColorB === 1.0) {
        mesh.material.color.copy(original.color);
        if (mesh.material.emissive && original.emissive) mesh.material.emissive.copy(original.emissive);
      } else {
        // Simple blend towards target color (usually red)
        mesh.material.color.setRGB(
          original.color.r * currentColorR,
          original.color.g * currentColorG,
          original.color.b * currentColorB
        );
      }
    }
  });

  updateHearts();
  renderer.render(scene, camera);
}
