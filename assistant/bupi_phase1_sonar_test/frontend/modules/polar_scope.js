/**
 * Viewport 1: Polar Radar Sonar Scope.
 * Displays real-time sweep beam cone, range rings, endpoint history, and depth jumps.
 */

export class PolarScope {
  constructor(canvasElement) {
    this.canvas = canvasElement;
    this.ctx = canvasElement.getContext('2d');

    this.maxRangeCm = 400.0;
    this.currentAngle = 90.0;
    this.currentDist = 400.0;
    this.currentValid = false;
    this.history = [];
    this.portals = [];
    this.onAngleAim = null;
    this.isAimDragging = false;

    this.initAimEvents();
    this.resize();
    window.addEventListener('resize', () => this.resize());
  }

  initAimEvents() {
    this.canvas.style.cursor = 'crosshair';

    const calcAngle = (e) => {
      const rect = this.canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const ox = this.width / 2;
      const oy = this.height - 28;
      const dx = mx - ox;
      const dy = oy - my;
      if (dy > -25) {
        let rad = Math.atan2(dy, dx);
        let deg = (rad * 180.0) / Math.PI;
        deg = Math.max(0.0, Math.min(180.0, deg));
        if (this.onAngleAim) {
          this.onAngleAim(Math.round(deg));
        }
      }
    };

    this.canvas.addEventListener('mousedown', (e) => {
      this.isAimDragging = true;
      calcAngle(e);
    });

    window.addEventListener('mousemove', (e) => {
      if (this.isAimDragging) {
        calcAngle(e);
      }
    });

    window.addEventListener('mouseup', () => {
      this.isAimDragging = false;
    });
  }

  resize() {
    const rect = this.canvas.parentElement.getBoundingClientRect();
    this.width = rect.width;
    this.height = rect.height;
    this.canvas.width = this.width * window.devicePixelRatio;
    this.canvas.height = this.height * window.devicePixelRatio;
    this.ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
    this.render();
  }

  updateState(telemetry, history, portals) {
    if (telemetry) {
      this.currentAngle = telemetry.angle_deg || 90.0;
      this.currentDist = telemetry.d_cm || 400.0;
      this.currentValid = telemetry.valid === 1;
    }
    if (history) this.history = history;
    if (portals) this.portals = portals;
    this.render();
  }

  render() {
    const ctx = this.ctx;
    const w = this.width;
    const h = this.height;
    if (!w || !h) return;

    ctx.clearRect(0, 0, w, h);

    // Origin is at bottom center (leaving 24px bottom margin)
    const ox = w / 2;
    const oy = h - 28;
    const maxRadius = Math.min(w * 0.48, h - 45);

    // 1. Draw Range Rings (100cm, 200cm, 300cm, 400cm)
    const rings = [100, 200, 300, 400];
    ctx.lineWidth = 1;
    ctx.strokeStyle = '#21262d';
    ctx.font = '10px "JetBrains Mono", monospace';
    ctx.fillStyle = '#545d68';

    rings.forEach((rCm) => {
      const radius = (rCm / this.maxRangeCm) * maxRadius;
      ctx.beginPath();
      // Draw semicircle from 0 to PI (in canvas coords: from 0 (right) to Math.PI (left))
      ctx.arc(ox, oy, radius, Math.PI, 0, false);
      ctx.stroke();

      // Range label
      ctx.fillText(`${rCm}cm`, ox + radius - 18, oy - 4);
    });

    // 2. Draw Radial Angle Spokes (0, 30, 45, 60, 90, 120, 135, 150, 180 deg)
    const angles = [0, 30, 45, 60, 90, 120, 135, 150, 180];
    angles.forEach((deg) => {
      const rad = (deg * Math.PI) / 180.0;
      const ex = ox + maxRadius * Math.cos(rad);
      const ey = oy - maxRadius * Math.sin(rad);

      ctx.beginPath();
      ctx.moveTo(ox, oy);
      ctx.lineTo(ex, ey);
      ctx.strokeStyle = deg === 90 ? '#30363d' : '#1b222c';
      ctx.stroke();

      // Label
      const lx = ox + (maxRadius + 14) * Math.cos(rad);
      const ly = oy - (maxRadius + 14) * Math.sin(rad);
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = '#8b949e';
      ctx.fillText(`${deg}°`, lx, ly);
    });

    // 3. Draw 15-degree Acoustic Beam Cone
    const curRad = (this.currentAngle * Math.PI) / 180.0;
    const coneHalfRad = (7.5 * Math.PI) / 180.0;
    const beamRadius = Math.min(this.currentDist / this.maxRangeCm, 1.0) * maxRadius;

    ctx.save();
    ctx.beginPath();
    ctx.moveTo(ox, oy);
    ctx.arc(ox, oy, beamRadius, -curRad - coneHalfRad, -curRad + coneHalfRad, false);
    ctx.closePath();
    const coneGrad = ctx.createRadialGradient(ox, oy, 10, ox, oy, maxRadius);
    coneGrad.addColorStop(0, 'rgba(0, 229, 255, 0.25)');
    coneGrad.addColorStop(1, 'rgba(0, 229, 255, 0.03)');
    ctx.fillStyle = coneGrad;
    ctx.fill();
    ctx.restore();

    // 4. Draw Center Pacer Needle
    const needleX = ox + maxRadius * Math.cos(curRad);
    const needleY = oy - maxRadius * Math.sin(curRad);
    ctx.beginPath();
    ctx.moveTo(ox, oy);
    ctx.lineTo(needleX, needleY);
    ctx.strokeStyle = '#00e5ff';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // 5. Draw Historical Sonar Endpoints (Phosphor fading trail)
    const now = Date.now();
    this.history.forEach((pt, idx) => {
      if (pt.d_cm >= 400 || !pt.valid) return;
      const ptRad = (pt.angle_deg * Math.PI) / 180.0;
      const r = (pt.d_cm / this.maxRangeCm) * maxRadius;
      const px = ox + r * Math.cos(ptRad);
      const py = oy - r * Math.sin(ptRad);

      const ageRatio = idx / this.history.length; // 0 (old) to 1 (new)
      ctx.beginPath();
      ctx.arc(px, py, pt.is_portal ? 4 : 2.5, 0, Math.PI * 2);
      ctx.fillStyle = pt.is_portal
        ? `rgba(224, 64, 251, ${0.4 + ageRatio * 0.6})`  // Magenta portal
        : (pt.pass === 'pass2'
          ? `rgba(255, 179, 0, ${0.3 + ageRatio * 0.7})` // Amber high pass
          : `rgba(0, 229, 255, ${0.3 + ageRatio * 0.7})`);// Cyan low pass
      ctx.fill();
    });

    // 6. Draw Current Target Hit Point
    if (this.currentValid && this.currentDist < 395) {
      const hx = ox + beamRadius * Math.cos(curRad);
      const hy = oy - beamRadius * Math.sin(curRad);

      ctx.beginPath();
      ctx.arc(hx, hy, 5, 0, Math.PI * 2);
      ctx.fillStyle = '#ff3344';
      ctx.shadowColor = '#ff3344';
      ctx.shadowBlur = 8;
      ctx.fill();
      ctx.shadowBlur = 0;

      // Echo distance tag
      ctx.fillStyle = '#ffffff';
      ctx.font = '11px "JetBrains Mono", monospace';
      ctx.fillText(`${this.currentDist.toFixed(1)}cm`, hx + 10, hy - 6);
    }

    // 7. Sensor Origin Crosshair at (ox, oy)
    ctx.beginPath();
    ctx.arc(ox, oy, 4, 0, Math.PI * 2);
    ctx.fillStyle = '#00e676';
    ctx.fill();
  }
}

