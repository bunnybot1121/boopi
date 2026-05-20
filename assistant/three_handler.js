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

window.addEventListener('mousemove', (e) => {
  isMouseOver = true;
  // Convert client coordinates to normalized coordinates relative to center (-0.5 to 0.5)
  mouseX = (e.clientX / window.innerWidth) - 0.5;
  mouseY = (e.clientY / window.innerHeight) - 0.5;
});

window.addEventListener('mouseleave', () => {
  isMouseOver = false;
});

export function init3D(containerId, modelPath) {
  const container = document.getElementById(containerId);
  if (!container) return;

  // 1. Create Scene & Transparent Renderer
  scene = new THREE.Scene();
  
  renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  container.appendChild(renderer.domElement);

  // 2. Setup Camera
  camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 100);
  camera.position.set(0, 0, 4.5);

  // 3. Lighting Setup
  const ambientLight = new THREE.AmbientLight(0xffffff, 0.8);
  scene.add(ambientLight);

  const dirLight = new THREE.DirectionalLight(0xffffff, 1.2);
  dirLight.position.set(2, 4, 3);
  scene.add(dirLight);

  const pointLight = new THREE.PointLight(0xa78bfa, 1.5, 10);
  pointLight.position.set(0, 1, 2);
  scene.add(pointLight);

  // 4. Setup Thinking Particles (Invisible initially)
  setupThinkingParticles();

  // 5. Load GLB Model
  const loader = new GLTFLoader();
  loader.load(
    modelPath,
    (gltf) => {
      model = gltf.scene;

      // Automatically center and scale the model to fit a standard 2x2x2 bounding box
      const box = new THREE.Box3().setFromObject(model);
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      const maxDim = Math.max(size.x, size.y, size.z);
      const scale = 2.0 / maxDim;
      model.scale.set(scale, scale, scale);
      model.position.sub(center.multiplyScalar(scale));

      // Traverse meshes to bind animations to specific parts
      model.traverse((child) => {
        if (child.isMesh) {
          child.castShadow = true;
          child.receiveShadow = true;
          
          // Store original materials to allow dynamic color shifting (for angry/error states)
          if (child.material) {
            originalMaterials.set(child, {
              color: child.material.color ? child.material.color.clone() : null,
              emissive: child.material.emissive ? child.material.emissive.clone() : null
            });
          }

          // Identify components based on node names
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
      const meshNames = [];
      model.traverse((c) => { if (c.isMesh) meshNames.push(c.name); });
      console.log('3D Model loaded successfully! Mesh names inside model:', JSON.stringify(meshNames));
      console.log('Bound components:', JSON.stringify({
        leftEye: leftEye ? leftEye.name : null,
        rightEye: rightEye ? rightEye.name : null,
        mouthParts: mouthParts.map(m => m.name),
        body: body ? body.name : null
      }));
      
      // Start the animation loop
      requestAnimationFrame(animate);
    },
    undefined,
    (error) => {
      console.error('Error loading 3D model:', error);
    }
  );

  // Handle window resizing
  window.addEventListener('resize', onWindowResize);
}

function onWindowResize() {
  const container = renderer.domElement.parentElement;
  camera.aspect = container.clientWidth / container.clientHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(container.clientWidth, container.clientHeight);
}

// -------------------------------------------------------------
// Procedural Effects (Thinking Particles & Extruded Hearts)
// -------------------------------------------------------------
function setupThinkingParticles() {
  const particleCount = 40;
  const geometry = new THREE.BufferGeometry();
  const positions = new Float32Array(particleCount * 3);

  for (let i = 0; i < particleCount * 3; i += 3) {
    // Generate initial orbital shell positions
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
  // Drawing a smooth 2D heart path
  heartShape.moveTo(0, 0.3);
  heartShape.bezierCurveTo(0, 0.3, -0.2, 0.7, -0.6, 0.7);
  heartShape.bezierCurveTo(-1.0, 0.7, -1.1, 0.4, -1.1, 0.15);
  heartShape.bezierCurveTo(-1.1, -0.2, -0.7, -0.6, 0, -1.0);
  heartShape.bezierCurveTo(0.7, -0.6, 1.1, -0.2, 1.1, 0.15);
  heartShape.bezierCurveTo(1.1, 0.4, 1.0, 0.7, 0.6, 0.7);
  heartShape.bezierCurveTo(0.2, 0.7, 0, 0.3, 0, 0.3);

  // Extrude the 2D path into a 3D bubble heart
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
  
  // Start position near the character with some random offset
  const scaleVal = 0.08 + Math.random() * 0.06;
  heart.scale.set(scaleVal, scaleVal, scaleVal);
  heart.position.set(
    (Math.random() - 0.5) * 0.8,
    (Math.random() - 0.5) * 0.4,
    (Math.random() - 0.5) * 0.4
  );

  // Random rotation for variety
  heart.rotation.z = Math.PI; // Face upright
  heart.rotation.y = (Math.random() - 0.5) * 0.5;

  scene.add(heart);
  activeHearts.push({
    mesh: heart,
    speedY: 0.02 + Math.random() * 0.02,
    speedRot: (Math.random() - 0.5) * 0.05,
    life: 1.0 // opacity factor
  });
}

function updateHearts() {
  for (let i = activeHearts.length - 1; i >= 0; i--) {
    const heart = activeHearts[i];
    heart.mesh.position.y += heart.speedY;
    heart.mesh.position.x += Math.sin(stateTime * 5.0 + i) * 0.005;
    heart.mesh.rotation.y += heart.speedRot;
    heart.life -= 0.015; // fade out life

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

// -------------------------------------------------------------
// Core Animation Loop & State Engine
// -------------------------------------------------------------
export function set3DState(state) {
  if (currentState === state) return;
  currentState = state;
  stateTime = 0;

  console.log(`[3D Router] Activating state: ${state}`);

  // 1. Reset mesh colors/scales from previous state transitions
  if (model) {
    model.position.set(0, 0, 0);
    model.rotation.set(0, 0, 0);
    
    // Restore original materials (for angry/error red tints)
    originalMaterials.forEach((original, mesh) => {
      if (original.color) mesh.material.color.copy(original.color);
      if (original.emissive) mesh.material.emissive.copy(original.emissive);
    });

    // Reset eyes
    if (leftEye) {
      leftEye.scale.set(1, 1, 1);
      leftEye.rotation.set(0, 0, 0);
    }
    if (rightEye) {
      rightEye.scale.set(1, 1, 1);
      rightEye.rotation.set(0, 0, 0);
    }
    mouthParts.forEach(part => {
      part.scale.set(1, 1, 1);
      part.position.set(0, 0, 0);
    });
  }

  // 2. Adjust State-specific elements
  if (thinkingParticles) {
    thinkingParticles.material.opacity = (state === 'thinking') ? 0.8 : 0.0;
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
      blinkTimer = 3.0 + Math.random() * 4.0; // blink again in 3-7s
      leftEye.scale.y = 1.0;
      rightEye.scale.y = 1.0;
    } else {
      // Smooth close and open
      const factor = Math.abs(Math.sin((blinkDuration / 0.15) * Math.PI));
      leftEye.scale.y = factor * 0.9 + 0.1;
      rightEye.scale.y = factor * 0.9 + 0.1;
    }
  }
}

function animate(timestamp) {
  requestAnimationFrame(animate);

  const delta = (timestamp - lastTime) / 1000;
  lastTime = timestamp;
  stateTime += delta;

  if (!model) return;

  // A. Gaze Tracking logic
  if (isMouseOver) {
    // Follow mouse cursor (subtle limits to avoid extreme rotation)
    targetGazeX = mouseX * 0.45;
    targetGazeY = mouseY * 0.35;
  } else if (currentState === 'thinking') {
    // Thinking: gaze drifts up and right
    targetGazeX = 0.16;
    targetGazeY = -0.14;
  } else {
    // Natural look-around gaze drift when idle or waiting
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

  // Smoothly interpolate gaze
  currentGazeX += (targetGazeX - currentGazeX) * 0.08;
  currentGazeY += (targetGazeY - currentGazeY) * 0.08;

  // Apply gaze rotations to left and right eyes
  if (leftEye && rightEye && currentState !== 'angry' && currentState !== 'error') {
    leftEye.rotation.y = currentGazeX;
    leftEye.rotation.x = -currentGazeY;
    rightEye.rotation.y = currentGazeX;
    rightEye.rotation.x = -currentGazeY;
  }

  // B. Process blinking
  if (currentState !== 'angry' && currentState !== 'error') {
    handleBlinking(delta);
  }

  // C. Process Hearts
  updateHearts();

  // D. Execute State-Specific Pose & Mesh Manipulations
  switch (currentState) {
    case 'idle':
    case 'chilling':
    case 'waiting':
      // Gentle breathing/floating
      model.position.y = Math.sin(stateTime * 1.5) * 0.04;
      model.rotation.y = Math.sin(stateTime * 0.8) * 0.05;
      mouthParts.forEach(part => part.scale.set(1.0, 1.0, 1.0));
      break;

    case 'listening':
      // Attentive tilt forward, subtle rapid breathing pulse
      model.position.z = 0.12;
      model.rotation.x = 0.08;
      model.position.y = Math.sin(stateTime * 3.0) * 0.02;
      
      // Make eyes slightly wider to look alert and attentive
      if (leftEye && rightEye) {
        const pulse = 1.15 + Math.sin(stateTime * 6.0) * 0.05;
        leftEye.scale.set(pulse, pulse, pulse);
        rightEye.scale.set(pulse, pulse, pulse);
      }
      mouthParts.forEach(part => part.scale.set(0.9, 0.9, 1.0));
      break;

    case 'thinking':
      // Hover and rotate body slowly, rotate thinking particles
      model.position.y = Math.sin(stateTime * 2.0) * 0.03;
      model.rotation.y = stateTime * 0.4;

      if (thinkingParticles) {
        thinkingParticles.rotation.y = -stateTime * 0.6;
        thinkingParticles.position.y = Math.sin(stateTime * 2.0) * 0.03;
      }
      
      // Smirk/thinking mouth shape offset to the side
      mouthParts.forEach(part => {
        part.scale.set(0.9, 0.8, 1.0);
        part.position.x = 0.05;
      });
      break;

    case 'talking':
      // Bouncing in sync with talking
      model.position.y = Math.sin(stateTime * 12.0) * 0.06;
      
      // Simulate mouth opening and closing (lip-sync)
      if (mouthParts.length > 0) {
        talkAmplitude = Math.abs(Math.sin(stateTime * 18.0) * Math.cos(stateTime * 7.0));
        mouthParts.forEach(part => {
          part.scale.y = 1.0 + talkAmplitude * 0.85;
          part.scale.x = 1.0 - talkAmplitude * 0.18;
        });

        // Make eyes react to the speech amplitude for expressive talk
        if (leftEye && rightEye) {
          const eyePulse = 1.0 + talkAmplitude * 0.12;
          leftEye.scale.set(eyePulse, eyePulse, eyePulse);
          rightEye.scale.set(eyePulse, eyePulse, eyePulse);
        }
      }
      break;

    case 'happy':
    case 'excited':
    case 'praise':
      // Bounce high
      model.position.y = Math.abs(Math.sin(stateTime * 7.0)) * 0.28;
      model.rotation.y = Math.sin(stateTime * 10.0) * 0.15;

      // Squint/happy eyes
      if (leftEye && rightEye) {
        leftEye.scale.set(1.25, 0.6, 1.25);
        rightEye.scale.set(1.25, 0.6, 1.25);
      }

      // Wide flat smile
      mouthParts.forEach(part => part.scale.set(1.35, 0.55, 1.0));

      // Spawning hearts on a timer
      if (Math.random() < 0.08 && activeHearts.length < 15) {
        spawn3DHeart();
      }
      break;

    case 'angry':
    case 'error':
      // Glitchy shaking
      model.position.x = (Math.random() - 0.5) * 0.015;
      model.position.y = (Math.sin(stateTime * 8.0) * 0.03) + (Math.random() - 0.5) * 0.015;
      
      // Tilt eyes inward and narrow them for angry look
      if (leftEye && rightEye) {
        leftEye.rotation.z = -0.26;
        rightEye.rotation.z = 0.26;
        leftEye.scale.set(1.0, 0.5, 1.0);
        rightEye.scale.set(1.0, 0.5, 1.0);
      }

      // Frowning shape
      mouthParts.forEach(part => part.scale.set(0.7, 1.35, 1.0));

      // Glow Red
      originalMaterials.forEach((original, mesh) => {
        if (mesh.material && mesh.material.color) {
          mesh.material.color.setRGB(0.85, 0.1, 0.1);
          if (mesh.material.emissive) {
            mesh.material.emissive.setRGB(0.3, 0.0, 0.0);
          }
        }
      });
      break;
  }

  // Render Scene
  renderer.render(scene, camera);
}
