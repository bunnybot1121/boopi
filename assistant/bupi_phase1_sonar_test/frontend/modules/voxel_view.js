/**
 * Viewport 3: True 3D Voxel & Elevation World (Three.js / WebGL).
 * Renders verified short-range floor (<150cm) without max-range timeout floods,
 * extrudes clustered obstacle volumes with directional lighting, and outlines
 * detected objects in 3D space.
 */

import { getTacticalPalette } from './theme.js';

export class VoxelWorld {
  constructor(canvasElement, containerElement) {
    this.canvas = canvasElement;
    this.container = containerElement;
    this.palette = getTacticalPalette();

    this.voxels = [];
    this.portals = [];
    this.astarPath = [];
    this.pinpointedObjects = [];
    this.maxRangeCm = 200.0;
    this.resCm = 2.0;
    this.s1Ang = 90.0;
    this.s2Ang = 90.0;
    this.lastRebuildTime = 0;
    this.lastVoxelHash = '';

    this.useThree = typeof window.THREE !== 'undefined';
    if (this.useThree) {
      this.initThreeJS();
    } else {
      this.initIsometricCanvas();
    }

    window.addEventListener('resize', () => this.resize());
  }

  initThreeJS() {
    const THREE = window.THREE;
    const rect = this.container.getBoundingClientRect();
    this.width = rect.width || 360;
    this.height = rect.height || 360;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(this.palette.bgBase);

    this.camera = new THREE.PerspectiveCamera(45, this.width / this.height, 1, 2200);
    this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true });
    this.renderer.setSize(this.width, this.height);
    this.renderer.setPixelRatio(window.devicePixelRatio);

    // Three-point tactical lighting for crisp 3D depth separation
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const keyLight = new THREE.DirectionalLight(0x00e5ff, 0.95);
    keyLight.position.set(140, 320, 180);
    this.scene.add(keyLight);

    const rimLight = new THREE.DirectionalLight(0xffb703, 0.45);
    rimLight.position.set(-160, 220, -120);
    this.scene.add(rimLight);

    this.gridHelper = null;
    this.rebuildGridHelper(this.maxRangeCm);

    this.voxelGroup = new THREE.Group();
    this.floorGroup = new THREE.Group();
    this.bboxGroup = new THREE.Group();
    this.portalGroup = new THREE.Group();
    this.pathGroup = new THREE.Group();
    this.scene.add(this.floorGroup, this.voxelGroup, this.bboxGroup, this.portalGroup, this.pathGroup);

    // Robot Chassis + Dual Beam Cones
    this.robotGroup = new THREE.Group();
    const botBody = new THREE.Mesh(
      new THREE.CylinderGeometry(8, 10, 6, 18),
      new THREE.MeshStandardMaterial({ color: this.palette.green, roughness: 0.4 })
    );
    botBody.position.set(0, 3, 0);
    this.robotGroup.add(botBody);

    this.beam1Mesh = new THREE.Mesh(
      new THREE.ConeGeometry(3.5, 16, 10),
      new THREE.MeshBasicMaterial({ color: this.palette.primary })
    );
    this.beam1Mesh.rotation.x = Math.PI / 2;
    this.beam1Mesh.position.set(0, 4, 12);
    this.robotGroup.add(this.beam1Mesh);

    this.beam2Mesh = new THREE.Mesh(
      new THREE.ConeGeometry(3, 14, 10),
      new THREE.MeshBasicMaterial({ color: this.palette.amber })
    );
    this.beam2Mesh.rotation.x = (Math.PI / 2) - 0.25;
    this.beam2Mesh.position.set(0, 10, 10);
    this.robotGroup.add(this.beam2Mesh);

    this.scene.add(this.robotGroup);
    this.setupThreeMouseControls();
    this.animateThree();
  }

  rebuildGridHelper(rangeCm) {
    const THREE = window.THREE;
    if (!this.scene) return;
    if (this.gridHelper) {
      this.scene.remove(this.gridHelper);
      this.gridHelper.geometry.dispose();
      this.gridHelper.material.dispose();
    }
    const span = rangeCm * 2;
    this.gridHelper = new THREE.GridHelper(span, 20, this.palette.primary, '#1b232e');
    this.gridHelper.position.set(0, 0, rangeCm * 0.4);
    this.scene.add(this.gridHelper);
  }

  setupThreeMouseControls() {
    let isDragging = false;
    let prevMouse = { x: 0, y: 0 };
    let rotY = 0.0;
    let rotX = 0.72;
    this.camDist = this.maxRangeCm * 1.65;

    this.updateCamera = () => {
      rotX = Math.max(0.15, Math.min(1.45, rotX));
      const focusZ = this.maxRangeCm * 0.42;
      this.camera.position.x = this.camDist * Math.sin(rotY) * Math.cos(rotX);
      this.camera.position.y = this.camDist * Math.sin(rotX);
      this.camera.position.z = this.camDist * Math.cos(rotY) * Math.cos(rotX) + focusZ;
      this.camera.lookAt(0, 10, focusZ);
    };

    this.canvas.addEventListener('mousedown', (e) => {
      isDragging = true;
      prevMouse = { x: e.clientX, y: e.clientY };
    });
    window.addEventListener('mouseup', () => { isDragging = false; });
    this.canvas.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      rotY -= (e.clientX - prevMouse.x) * 0.007;
      rotX += (e.clientY - prevMouse.y) * 0.007;
      prevMouse = { x: e.clientX, y: e.clientY };
      this.updateCamera();
    });
    this.canvas.addEventListener('wheel', (e) => {
      this.camDist = Math.max(90, Math.min(900, this.camDist + e.deltaY * 0.35));
      this.updateCamera();
      e.preventDefault();
    }, { passive: false });

    this.updateCamera();
  }

  animateThree() {
    requestAnimationFrame(() => this.animateThree());
    if (this.renderer && this.scene && this.camera) {
      this.renderer.render(this.scene, this.camera);
    }
  }

  updateSnapshot(activeVoxels, portals, currentAngle, astarPath, telemetry, pinpointedObjects = [], gridMeta = null) {
    this.voxels = activeVoxels || [];
    this.portals = portals || [];
    this.pinpointedObjects = pinpointedObjects || [];
    this.astarPath = astarPath || [];
    this.s1Ang = telemetry?.s1_ang ?? currentAngle ?? 90.0;
    this.s2Ang = telemetry?.s2_ang ?? this.s1Ang;

    if (gridMeta) {
      const rangeChanged = Math.abs(gridMeta.max_range_cm - this.maxRangeCm) > 0.5;
      this.maxRangeCm = gridMeta.max_range_cm || 200.0;
      this.resCm = gridMeta.res_cm || 2.0;
      if (rangeChanged && this.useThree) {
        this.rebuildGridHelper(this.maxRangeCm);
        this.camDist = this.maxRangeCm * 1.65;
        if (this.updateCamera) this.updateCamera();
      }
    }

    if (this.robotGroup) {
      this.robotGroup.rotation.y = ((90.0 - this.s1Ang) * Math.PI) / 180.0;
      if (this.beam2Mesh) {
        this.beam2Mesh.rotation.y = ((this.s1Ang - this.s2Ang) * Math.PI) / 180.0;
      }
    }

    if (this.useThree) {
      const now = performance.now();
      const vHash = `${this.voxels.length}:${this.pinpointedObjects.length}:${this.maxRangeCm}`;
      if (vHash !== this.lastVoxelHash || (now - this.lastRebuildTime > 300)) {
        this.lastRebuildTime = now;
        this.lastVoxelHash = vHash;
        this.rebuildThreeScene();
      }
    } else {
      this.renderIsometricFallback();
    }
  }

  clearGroup(grp) {
    while (grp.children.length > 0) {
      const obj = grp.children[0];
      grp.remove(obj);
      if (obj.geometry) obj.geometry.dispose();
      if (obj.material) obj.material.dispose();
    }
  }

  rebuildThreeScene() {
    const THREE = window.THREE;
    const pal = this.palette;
    this.clearGroup(this.voxelGroup);
    this.clearGroup(this.floorGroup);
    this.clearGroup(this.bboxGroup);
    this.clearGroup(this.portalGroup);
    this.clearGroup(this.pathGroup);

    const cellSpan = Math.max(2.5, this.resCm * 1.35);
    const wallGeo = new THREE.BoxGeometry(cellSpan, 36, cellSpan);
    const wallMat = new THREE.MeshStandardMaterial({ color: pal.red, roughness: 0.45, metalness: 0.12 });

    const stepGeo = new THREE.BoxGeometry(cellSpan, 10, cellSpan);
    const stepMat = new THREE.MeshStandardMaterial({ color: pal.amber, roughness: 0.5, metalness: 0.1 });

    const overhangGeo = new THREE.BoxGeometry(cellSpan, 16, cellSpan);
    const overhangMat = new THREE.MeshStandardMaterial({ color: pal.orange, roughness: 0.45, metalness: 0.1 });

    const floorGeo = new THREE.PlaneGeometry(8, 8);
    const floorMat = new THREE.MeshBasicMaterial({
      color: pal.mapFree,
      transparent: true,
      opacity: 0.52,
      side: THREE.DoubleSide
    });

    this.voxels.forEach((v) => {
      if (v.type === 'TALL_WALL') {
        const mesh = new THREE.Mesh(wallGeo, wallMat);
        mesh.position.set(v.x, 18, v.y);
        this.voxelGroup.add(mesh);
      } else if (v.type === 'LOW_STEP') {
        const mesh = new THREE.Mesh(stepGeo, stepMat);
        mesh.position.set(v.x, 5, v.y);
        this.voxelGroup.add(mesh);
      } else if (v.type === 'OVERHANG') {
        const mesh = new THREE.Mesh(overhangGeo, overhangMat);
        mesh.position.set(v.x, 28, v.y);
        this.voxelGroup.add(mesh);
      } else if (v.type === 'FREE_FLOOR') {
        const mesh = new THREE.Mesh(floorGeo, floorMat);
        mesh.rotation.x = -Math.PI / 2;
        mesh.position.set(v.x, 0.3, v.y);
        this.floorGroup.add(mesh);
      }
    });

    // 3D Clustered Object Wireframe Hulls
    this.pinpointedObjects.forEach((obj) => {
      const b = obj.bbox_world;
      if (!b) return;
      const bw = Math.max(8, b.x_max - b.x_min);
      const bd = Math.max(8, b.y_max - b.y_min);
      const bh = obj.class === 'LOW_STEP_RUBBLE' ? 12 : 40;
      const hullGeo = new THREE.EdgesGeometry(new THREE.BoxGeometry(bw, bh, bd));
      const hullMat = new THREE.LineBasicMaterial({ color: obj.color || pal.red });
      const lines = new THREE.LineSegments(hullGeo, hullMat);
      lines.position.set((b.x_min + b.x_max) / 2, bh / 2, (b.y_min + b.y_max) / 2);
      this.bboxGroup.add(lines);
    });

    // Doorway Portals
    this.portals.forEach((p) => {
      const ringMesh = new THREE.Mesh(
        new THREE.RingGeometry(5, 9, 16),
        new THREE.MeshBasicMaterial({ color: pal.magenta, side: THREE.DoubleSide })
      );
      ringMesh.rotation.x = -Math.PI / 2;
      ringMesh.position.set(p.x_cm, 1.0, p.y_cm);
      this.portalGroup.add(ringMesh);
    });

    // A* Path Ribbon
    if (this.astarPath.length >= 2) {
      const points = this.astarPath.map((wp) => new THREE.Vector3(wp.x_cm ?? wp.x ?? 0, 2.0, wp.y_cm ?? wp.y ?? 0));
      const lineGeo = new THREE.BufferGeometry().setFromPoints(points);
      this.pathGroup.add(new THREE.Line(lineGeo, new THREE.LineBasicMaterial({ color: pal.green })));
    }
  }

  initIsometricCanvas() {
    this.ctx = this.canvas.getContext('2d');
    this.resize();
  }

  resize() {
    const rect = this.container.getBoundingClientRect();
    this.width = rect.width || 360;
    this.height = rect.height || 360;

    if (this.useThree && this.renderer) {
      this.camera.aspect = this.width / this.height;
      this.camera.updateProjectionMatrix();
      this.renderer.setSize(this.width, this.height);
    } else if (this.ctx) {
      this.canvas.width = this.width * window.devicePixelRatio;
      this.canvas.height = this.height * window.devicePixelRatio;
      this.ctx.setTransform(window.devicePixelRatio, 0, 0, window.devicePixelRatio, 0, 0);
      this.renderIsometricFallback();
    }
  }

  renderIsometricFallback() {
    const ctx = this.ctx;
    if (!ctx) return;
    const w = this.width;
    const h = this.height;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = this.palette.bgBase;
    ctx.fillRect(0, 0, w, h);
  }
}
