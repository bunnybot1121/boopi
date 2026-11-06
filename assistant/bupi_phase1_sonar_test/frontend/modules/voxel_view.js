/**
 * Viewport 3: Interactive 3D Voxel Extrusion World.
 * Renders every cell in the 120x120 matrix:
 *   - Tall Wall (Red): Solid full-height 3D wall blocks (100% height) with crisp lighting and edges.
 *   - Low Step (Yellow): Quarter-height 3D blocks (25% height) showing open depth behind.
 *   - Open Corridor (Cyan): Flat floor tiles on the ground plane showing scanned floor.
 *   - Doorway Portal (Magenta): Low glowing doorway ground markers (NOT giant pink sticks).
 *   - Robot Origin (Green): 3D robot chassis + live aiming cone + green A* Planned Path line.
 */

export class VoxelWorld {
  constructor(canvasElement, containerElement) {
    this.canvas = canvasElement;
    this.container = containerElement;

    this.voxels = [];
    this.portals = [];
    this.astarPath = [];
    this.currentAngle = 90.0;

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

    // Scene & Camera setup
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x07090c);

    this.camera = new THREE.PerspectiveCamera(45, this.width / this.height, 1, 2000);
    this.camera.position.set(0, 320, 380);
    this.camera.lookAt(0, 20, 100);

    this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true });
    this.renderer.setSize(this.width, this.height);
    this.renderer.setPixelRatio(window.devicePixelRatio);

    // Directional & Ambient Lighting for realistic block shading
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.65);
    this.scene.add(ambientLight);

    const keyLight = new THREE.DirectionalLight(0x00e5ff, 0.7);
    keyLight.position.set(120, 350, 200);
    this.scene.add(keyLight);

    const fillLight = new THREE.DirectionalLight(0xffb300, 0.3);
    fillLight.position.set(-150, 200, -100);
    this.scene.add(fillLight);

    // Metric Ground Grid (480cm x 480cm = 4.8m x 4.8m room)
    const gridHelper = new THREE.GridHelper(480, 24, 0x00e5ff, 0x1b232e);
    gridHelper.position.set(0, 0, 120);
    this.scene.add(gridHelper);

    // Dynamic Groups
    this.voxelGroup = new THREE.Group();
    this.floorGroup = new THREE.Group();
    this.portalGroup = new THREE.Group();
    this.pathGroup = new THREE.Group();
    this.scene.add(this.floorGroup);
    this.scene.add(this.voxelGroup);
    this.scene.add(this.portalGroup);
    this.scene.add(this.pathGroup);

    // Robot Origin Marker (Chassis + Live Aiming Cone)
    this.robotGroup = new THREE.Group();
    const botGeo = new THREE.CylinderGeometry(14, 16, 8, 18);
    const botMat = new THREE.MeshLambertMaterial({ color: 0x00e676 });
    const botBody = new THREE.Mesh(botGeo, botMat);
    botBody.position.set(0, 4, 0);
    this.robotGroup.add(botBody);

    // Live Aiming Pointer on Robot
    const coneGeo = new THREE.ConeGeometry(5, 18, 8);
    const coneMat = new THREE.MeshBasicMaterial({ color: 0x00e5ff });
    this.aimCone = new THREE.Mesh(coneGeo, coneMat);
    this.aimCone.rotation.x = Math.PI / 2;
    this.aimCone.position.set(0, 7, 16);
    this.robotGroup.add(this.aimCone);

    this.scene.add(this.robotGroup);

    // Mouse Interaction
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

  updateSnapshot(activeVoxels, portals, currentAngle, astarPath) {
    this.voxels = activeVoxels || [];
    this.portals = portals || [];
    this.currentAngle = currentAngle || 90.0;
    this.astarPath = astarPath || [];

    // Orient Robot Aiming Cone
    if (this.robotGroup) {
      const rad = ((90.0 - this.currentAngle) * Math.PI) / 180.0;
      this.robotGroup.rotation.y = rad;
    }

    if (this.useThree) {
      this.rebuildThreeScene();
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

    // Shared Materials for Performance
    const wallGeo = new THREE.BoxGeometry(8, 70, 8); // 100% height solid wall
    const wallMat = new THREE.MeshLambertMaterial({ color: 0xff3344 });

    const stepGeo = new THREE.BoxGeometry(8, 18, 8); // 25% height low step
    const stepMat = new THREE.MeshLambertMaterial({ color: 0xffb300 });

    const floorGeo = new THREE.PlaneGeometry(16, 16);
    const floorMat = new THREE.MeshBasicMaterial({
      color: 0x00e5ff,
      transparent: true,
      opacity: 0.22,
      side: THREE.DoubleSide
    });

    // 1. Render All Voxel Matrix Cells
    this.voxels.forEach((v) => {
      if (v.type === "TALL_WALL") {
        const mesh = new THREE.Mesh(wallGeo, wallMat);
        mesh.position.set(v.x, 35, v.y);
        this.voxelGroup.add(mesh);
      } else if (v.type === "LOW_STEP") {
        const mesh = new THREE.Mesh(stepGeo, stepMat);
        mesh.position.set(v.x, 9, v.y);
        this.voxelGroup.add(mesh);
      } else if (v.type === "FREE_FLOOR") {
        const mesh = new THREE.Mesh(floorGeo, floorMat);
        mesh.rotation.x = -Math.PI / 2;
        mesh.position.set(v.x, 0.4, v.y);
        this.floorGroup.add(mesh);
      }
    });

    // 2. Render Doorway Portals (Low glowing ground markers, NOT giant pink sticks)
    this.portals.forEach((p) => {
      const archGeo = new THREE.RingGeometry(6, 12, 16);
      const archMat = new THREE.MeshBasicMaterial({
        color: 0xe040fb,
        side: THREE.DoubleSide
      });
      const ringMesh = new THREE.Mesh(archGeo, archMat);
      ringMesh.rotation.x = -Math.PI / 2;
      ringMesh.position.set(p.x_cm, 1.0, p.y_cm);
      this.portalGroup.add(ringMesh);

      // Low Ground Marker Pylon (height = 12cm)
      const pylonGeo = new THREE.CylinderGeometry(2, 2, 12, 8);
      const pylonMat = new THREE.MeshLambertMaterial({ color: 0xe040fb });
      const pylonMesh = new THREE.Mesh(pylonGeo, pylonMat);
      pylonMesh.position.set(p.x_cm, 6.0, p.y_cm);
      this.portalGroup.add(pylonMesh);
    });

    // 3. Render A* Planned Path Line (Green glowing line from robot)
    if (this.astarPath.length >= 2) {
      const points = this.astarPath.map((wp) => new THREE.Vector3(wp.x, 2.0, wp.y));
      const lineGeo = new THREE.BufferGeometry().setFromPoints(points);
      const lineMat = new THREE.LineBasicMaterial({ color: 0x00e676, linewidth: 3 });
      const lineMesh = new THREE.Line(lineGeo, lineMat);
      this.pathGroup.add(lineMesh);
    }
  }

  // Resilient 2.5D Isometric Fallback
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

    const toIso = (x, y, z = 0) => {
      const isoX = ox + (x - y) * Math.cos(Math.PI / 6) * scale;
      const isoY = oy + (x + y) * Math.sin(Math.PI / 6) * scale - z * scale;
      return { x: isoX, y: isoY };
    };

    // Draw Grid
    ctx.strokeStyle = '#1b232e';
    ctx.lineWidth = 1;
    for (let i = -200; i <= 200; i += 40) {
      const p1 = toIso(i, 0);
      const p2 = toIso(i, 350);
      ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.stroke();
    }

    // Render Voxels
    this.voxels.forEach((v) => {
      const isWall = v.type === 'TALL_WALL';
      const height = isWall ? 70 : 18;
      const base = toIso(v.x, v.y, 0);
      const top = toIso(v.x, v.y, height);

      ctx.fillStyle = isWall ? '#ff3344' : (v.type === 'LOW_STEP' ? '#ffb300' : 'rgba(0,229,255,0.2)');
      ctx.fillRect(base.x - 3, top.y, 6, Math.max(2, base.y - top.y));
    });

    // Render Portals
    this.portals.forEach((p) => {
      const pt = toIso(p.x_cm, p.y_cm, 0);
      ctx.fillStyle = '#e040fb';
      ctx.beginPath(); ctx.arc(pt.x, pt.y, 4, 0, Math.PI * 2); ctx.fill();
    });

    // Render Robot
    const bot = toIso(0, 0, 0);
    ctx.fillStyle = '#00e676';
    ctx.beginPath(); ctx.arc(bot.x, bot.y, 6, 0, Math.PI * 2); ctx.fill();
  }
}
