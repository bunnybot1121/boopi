/**
 * Viewport 3: True 3D Voxel & Elevation World (Three.js / WebGL).
 * Renders 120x120 multi-layer volumetric room:
 *   - TALL_SOLID_WALL (Red): Full-height 3D blocks (Z = 0 to 25cm).
 *   - LOW_STEP_RUBBLE (Yellow): Quarter-height blocks (Z = 0 to 6cm) showing open floor behind.
 *   - OVERHANG_HAZARD (Orange): Floating blocks (Z = 12 to 25cm) with open gap below.
 *   - DOORWAY_DEPTH_PORTAL (Magenta): Glowing floor boundary rings.
 *   - Robot Model + Dual 3D Ultrasonic Beams (Low Cyan + High Amber/Tilted).
 *   - A* Planned Path 3D Ribbon (Neon Green).
 */

export class VoxelWorld {
  constructor(canvasElement, containerElement) {
    this.canvas = canvasElement;
    this.container = containerElement;

    this.voxels = [];
    this.portals = [];
    this.astarPath = [];
    this.s1Ang = 90.0;
    this.s2Ang = 90.0;
    this.lastRebuildTime = 0;
    this.lastVoxelCount = -1;

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
    this.width = rect.width;
    this.height = rect.height;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x07090c);

    this.camera = new THREE.PerspectiveCamera(45, this.width / this.height, 1, 2000);
    this.camera.position.set(0, 320, 380);
    this.camera.lookAt(0, 20, 100);

    this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true });
    this.renderer.setSize(this.width, this.height);
    this.renderer.setPixelRatio(window.devicePixelRatio);

    const ambientLight = new THREE.AmbientLight(0xffffff, 0.65);
    this.scene.add(ambientLight);

    const keyLight = new THREE.DirectionalLight(0x00e5ff, 0.7);
    keyLight.position.set(120, 350, 200);
    this.scene.add(keyLight);

    const fillLight = new THREE.DirectionalLight(0xffb300, 0.35);
    fillLight.position.set(-150, 200, -100);
    this.scene.add(fillLight);

    // Metric Room Floor Grid (4.8m x 4.8m)
    const gridHelper = new THREE.GridHelper(480, 24, 0x00e5ff, 0x1b232e);
    gridHelper.position.set(0, 0, 120);
    this.scene.add(gridHelper);

    // Groups
    this.voxelGroup = new THREE.Group();
    this.floorGroup = new THREE.Group();
    this.portalGroup = new THREE.Group();
    this.pathGroup = new THREE.Group();
    this.beamsGroup = new THREE.Group();
    this.scene.add(this.floorGroup);
    this.scene.add(this.voxelGroup);
    this.scene.add(this.portalGroup);
    this.scene.add(this.pathGroup);
    this.scene.add(this.beamsGroup);

    // Robot Chassis
    this.robotGroup = new THREE.Group();
    const botGeo = new THREE.CylinderGeometry(14, 16, 8, 18);
    const botMat = new THREE.MeshLambertMaterial({ color: 0x00e676 });
    const botBody = new THREE.Mesh(botGeo, botMat);
    botBody.position.set(0, 4, 0);
    this.robotGroup.add(botBody);

    // Low Beam Projector (Cyan)
    const b1Geo = new THREE.ConeGeometry(5, 20, 8);
    const b1Mat = new THREE.MeshBasicMaterial({ color: 0x00e5ff });
    this.beam1Mesh = new THREE.Mesh(b1Geo, b1Mat);
    this.beam1Mesh.rotation.x = Math.PI / 2;
    this.beam1Mesh.position.set(0, 6, 16);
    this.robotGroup.add(this.beam1Mesh);

    // High Tilted Beam Projector (Amber)
    const b2Geo = new THREE.ConeGeometry(4, 18, 8);
    const b2Mat = new THREE.MeshBasicMaterial({ color: 0xffb300 });
    this.beam2Mesh = new THREE.Mesh(b2Geo, b2Mat);
    this.beam2Mesh.rotation.x = (Math.PI / 2) - 0.25; // 14° upward pitch
    this.beam2Mesh.position.set(0, 14, 14);
    this.robotGroup.add(this.beam2Mesh);

    this.scene.add(this.robotGroup);

    this.setupThreeMouseControls();
    this.animateThree();
  }

  setupThreeMouseControls() {
    let isDragging = false;
    let prevMouse = { x: 0, y: 0 };
    let rotY = 0;
    let rotX = 0.65;
    let camDist = 520;

    const updateCamera = () => {
      rotX = Math.max(0.12, Math.min(1.45, rotX));
      this.camera.position.x = camDist * Math.sin(rotY) * Math.cos(rotX);
      this.camera.position.y = camDist * Math.sin(rotX);
      this.camera.position.z = camDist * Math.cos(rotY) * Math.cos(rotX) + 80;
      this.camera.lookAt(0, 20, 100);
    };

    this.canvas.addEventListener('mousedown', (e) => {
      isDragging = true;
      prevMouse = { x: e.clientX, y: e.clientY };
    });

    window.addEventListener('mouseup', () => { isDragging = false; });

    this.canvas.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      const dx = e.clientX - prevMouse.x;
      const dy = e.clientY - prevMouse.y;
      prevMouse = { x: e.clientX, y: e.clientY };

      rotY -= dx * 0.007;
      rotX += dy * 0.007;
      updateCamera();
    });

    this.canvas.addEventListener('wheel', (e) => {
      camDist = Math.max(180, Math.min(1000, camDist + e.deltaY * 0.45));
      updateCamera();
      e.preventDefault();
    }, { passive: false });

    updateCamera();
  }

  animateThree() {
    requestAnimationFrame(() => this.animateThree());
    this.renderer.render(this.scene, this.camera);
  }

  updateSnapshot(activeVoxels, portals, currentAngle, astarPath, telemetry) {
    this.voxels = activeVoxels || [];
    this.portals = portals || [];
    this.s1Ang = telemetry?.s1_ang !== undefined ? telemetry.s1_ang : (currentAngle || 90.0);
    this.s2Ang = telemetry?.s2_ang !== undefined ? telemetry.s2_ang : this.s1Ang;
    this.astarPath = astarPath || [];

    if (this.robotGroup) {
      const rad1 = ((90.0 - this.s1Ang) * Math.PI) / 180.0;
      this.robotGroup.rotation.y = rad1;
      if (this.beam2Mesh) {
        const radDiff = ((this.s1Ang - this.s2Ang) * Math.PI) / 180.0;
        this.beam2Mesh.rotation.y = radDiff;
      }
    }

    if (this.useThree) {
      const now = performance.now();
      const countChanged = this.voxels.length !== this.lastVoxelCount;
      if (countChanged || (now - this.lastRebuildTime > 300)) {
        this.lastRebuildTime = now;
        this.lastVoxelCount = this.voxels.length;
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
    this.clearGroup(this.voxelGroup);
    this.clearGroup(this.floorGroup);
    this.clearGroup(this.portalGroup);
    this.clearGroup(this.pathGroup);

    const wallGeo = new THREE.BoxGeometry(8, 70, 8);
    const wallMat = new THREE.MeshLambertMaterial({ color: 0xff3344 });

    const stepGeo = new THREE.BoxGeometry(8, 18, 8);
    const stepMat = new THREE.MeshLambertMaterial({ color: 0xffb300 });

    const overhangGeo = new THREE.BoxGeometry(8, 28, 8);
    const overhangMat = new THREE.MeshLambertMaterial({ color: 0xff6d00 });

    const floorGeo = new THREE.PlaneGeometry(16, 16);
    const floorMat = new THREE.MeshBasicMaterial({
      color: 0x00e5ff,
      transparent: true,
      opacity: 0.22,
      side: THREE.DoubleSide
    });

    this.voxels.forEach((v) => {
      if (v.type === "TALL_WALL") {
        const mesh = new THREE.Mesh(wallGeo, wallMat);
        mesh.position.set(v.x, 35, v.y);
        this.voxelGroup.add(mesh);
      } else if (v.type === "LOW_STEP") {
        const mesh = new THREE.Mesh(stepGeo, stepMat);
        mesh.position.set(v.x, 9, v.y);
        this.voxelGroup.add(mesh);
      } else if (v.type === "OVERHANG") {
        const mesh = new THREE.Mesh(overhangGeo, overhangMat);
        mesh.position.set(v.x, 50, v.y); // Floating upper block
        this.voxelGroup.add(mesh);
      } else if (v.type === "FREE_FLOOR") {
        const mesh = new THREE.Mesh(floorGeo, floorMat);
        mesh.rotation.x = -Math.PI / 2;
        mesh.position.set(v.x, 0.4, v.y);
        this.floorGroup.add(mesh);
      }
    });

    // Doorway Portals (Glowing floor rings)
    this.portals.forEach((p) => {
      const archGeo = new THREE.RingGeometry(6, 12, 16);
      const archMat = new THREE.MeshBasicMaterial({ color: 0xe040fb, side: THREE.DoubleSide });
      const ringMesh = new THREE.Mesh(archGeo, archMat);
      ringMesh.rotation.x = -Math.PI / 2;
      ringMesh.position.set(p.x_cm, 1.0, p.y_cm);
      this.portalGroup.add(ringMesh);

      const pylonGeo = new THREE.CylinderGeometry(2, 2, 10, 8);
      const pylonMat = new THREE.MeshLambertMaterial({ color: 0xe040fb });
      const pylonMesh = new THREE.Mesh(pylonGeo, pylonMat);
      pylonMesh.position.set(p.x_cm, 5.0, p.y_cm);
      this.portalGroup.add(pylonMesh);
    });

    // A* Path Ribbon
    if (this.astarPath.length >= 2) {
      const points = this.astarPath.map((wp) => {
        const wx = wp.x_cm !== undefined ? wp.x_cm : (wp.x || 0);
        const wy = wp.y_cm !== undefined ? wp.y_cm : (wp.y || 0);
        return new THREE.Vector3(wx, 2.0, wy);
      });
      const lineGeo = new THREE.BufferGeometry().setFromPoints(points);
      const lineMat = new THREE.LineBasicMaterial({ color: 0x00e676, linewidth: 3 });
      this.pathGroup.add(new THREE.Line(lineGeo, lineMat));
    }
  }

  initIsometricCanvas() {
    this.ctx = this.canvas.getContext('2d');
    this.resize();
  }

  resize() {
    const rect = this.container.getBoundingClientRect();
    this.width = rect.width;
    this.height = rect.height;

    if (this.useThree && this.renderer) {
      this.camera.aspect = this.width / this.height;
      this.camera.updateProjectionMatrix();
      this.renderer.setSize(this.width, this.height);
    } else if (this.ctx) {
      this.canvas.width = this.width * window.devicePixelRatio;
      this.canvas.height = this.height * window.devicePixelRatio;
      this.ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
      this.renderIsometricFallback();
    }
  }

  renderIsometricFallback() {
    const ctx = this.ctx;
    if (!ctx) return;
    const w = this.width;
    const h = this.height;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#07090c';
    ctx.fillRect(0, 0, w, h);

    const ox = w / 2;
    const oy = h * 0.72;
    const scale = Math.min(w, h) / 520;

    const toIso = (x, y, z = 0) => ({
      x: ox + (x - y) * Math.cos(Math.PI / 6) * scale,
      y: oy + (x + y) * Math.sin(Math.PI / 6) * scale - z * scale
    });

    this.voxels.forEach((v) => {
      const isWall = v.type === 'TALL_WALL';
      const height = isWall ? 70 : (v.type === 'LOW_STEP' ? 18 : 28);
      const base = toIso(v.x, v.y, v.type === 'OVERHANG' ? 35 : 0);
      const top = toIso(v.x, v.y, (v.type === 'OVERHANG' ? 35 : 0) + height);
      ctx.fillStyle = isWall ? '#ff3344' : (v.type === 'LOW_STEP' ? '#ffb300' : (v.type === 'OVERHANG' ? '#ff6d00' : 'rgba(0,229,255,0.2)'));
      ctx.fillRect(base.x - 3, top.y, 6, Math.max(2, base.y - top.y));
    });
  }
}
