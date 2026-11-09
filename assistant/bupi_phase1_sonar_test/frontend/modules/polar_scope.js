/**
 * Viewport 1: Dual-Beam Polar Radar Sonar Scope.
 * Renders real-time sweep beams for both Sensor 1 (Low) and Sensor 2 (High),
 * sector boundaries, depth jump portals, and phosphor fading trails.
 */

export class PolarScope {
  constructor(canvasElement) {
    this.canvas = canvasElement;
    this.ctx = canvasElement.getContext('2d');

    this.maxRangeCm = 400.0;
    this.currentAngle = 90.0;
    this.s1Ang = 90.0;
    this.s2Ang = 90.0;
    this.d1Cm = 400.0;
    this.d2Cm = 400.0;
    this.valid1 = false;
    this.valid2 = false;
    this.deltaD = 0.0;
    this.class3d = "OPEN_CORRIDOR";
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
      if (this.isAimDragging) calcAngle(e);
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
      this.s1Ang = telemetry.s1_ang !== undefined ? telemetry.s1_ang : (telemetry.s_ang || 90.0);
      this.s2Ang = telemetry.s2_ang !== undefined ? telemetry.s2_ang : this.s1Ang;
      this.currentAngle = this.s1Ang;

      this.d1Cm = telemetry.d1_cm !== undefined ? telemetry.d1_cm : (telemetry.d_cm || 400.0);
      this.d2Cm = telemetry.d2_cm !== undefined ? telemetry.d2_cm : this.d1Cm;

      this.valid1 = telemetry.valid1 !== undefined ? (telemetry.valid1 === 1) : (telemetry.valid === 1);
      this.valid2 = telemetry.valid2 !== undefined ? (telemetry.valid2 === 1) : this.valid1;

      this.deltaD = telemetry.delta_d !== undefined ? telemetry.delta_d : (this.d2Cm - this.d1Cm);
      this.class3d = telemetry.class_3d || "OPEN_CORRIDOR";

      this.minAng = telemetry.min_ang !== undefined ? telemetry.min_ang : 45.0;
      this.maxAng = telemetry.max_ang !== undefined ? telemetry.max_ang : 135.0;
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

    const ox = w / 2;
    const oy = h - 28;
    const maxRadius = Math.min(w * 0.48, h - 45);

    // 1. Range Rings (100cm, 200cm, 300cm, 400cm)
    const rings = [100, 200, 300, 400];
    ctx.lineWidth = 1;
    ctx.strokeStyle = '#21262d';
    ctx.font = '10px "JetBrains Mono", monospace';
    ctx.fillStyle = '#545d68';

    rings.forEach((rCm) => {
      const radius = (rCm / this.maxRangeCm) * maxRadius;
      ctx.beginPath();
      ctx.arc(ox, oy, radius, Math.PI, 0, false);
      ctx.stroke();
      ctx.fillText(`${rCm}cm`, ox + radius - 18, oy - 4);
    });

    // 2. Radial Spokes (0, 30, 45, 60, 90, 120, 135, 150, 180)
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

      const lx = ox + (maxRadius + 14) * Math.cos(rad);
      const ly = oy - (maxRadius + 14) * Math.sin(rad);
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = '#8b949e';
      ctx.fillText(`${deg}°`, lx, ly);
    });

    // 2b. Sweep Sector Wedge
    if (this.minAng !== undefined && this.maxAng !== undefined) {
      const minRad = (this.minAng * Math.PI) / 180.0;
      const maxRad = (this.maxAng * Math.PI) / 180.0;
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(ox, oy);
      ctx.arc(ox, oy, maxRadius, -maxRad, -minRad, false);
      ctx.closePath();
      ctx.fillStyle = 'rgba(0, 229, 255, 0.04)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(0, 229, 255, 0.40)';
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.restore();
    }

    // 3. Beam 1: Low Ground Plane (Cyan)
    const rad1 = (this.s1Ang * Math.PI) / 180.0;
    const r1 = Math.min(this.d1Cm / this.maxRangeCm, 1.0) * maxRadius;
    const coneHalf = (7.5 * Math.PI) / 180.0;

    ctx.save();
    ctx.beginPath();
    ctx.moveTo(ox, oy);
    ctx.arc(ox, oy, r1, -rad1 - coneHalf, -rad1 + coneHalf, false);
    ctx.closePath();
    ctx.fillStyle = 'rgba(0, 229, 255, 0.15)';
    ctx.fill();
    ctx.restore();

    // 4. Beam 2: High / Tilted Plane (Amber / Green)
    const rad2 = (this.s2Ang * Math.PI) / 180.0;
    const r2 = Math.min(this.d2Cm / this.maxRangeCm, 1.0) * maxRadius;

    ctx.save();
    ctx.beginPath();
    ctx.moveTo(ox, oy);
    ctx.arc(ox, oy, r2, -rad2 - coneHalf * 0.7, -rad2 + coneHalf * 0.7, false);
    ctx.closePath();
    ctx.fillStyle = 'rgba(255, 179, 0, 0.12)';
    ctx.fill();
    ctx.restore();

    // 5. Differential Bridge (If Upper beam shoots past Low Step)
    if (this.valid1 && this.valid2 && this.d2Cm > this.d1Cm + 25.0) {
      ctx.save();
      ctx.beginPath();
      const p1x = ox + r1 * Math.cos(rad1);
      const p1y = oy - r1 * Math.sin(rad1);
      const p2x = ox + r2 * Math.cos(rad2);
      const p2y = oy - r2 * Math.sin(rad2);
      ctx.moveTo(p1x, p1y);
      ctx.lineTo(p2x, p2y);
      ctx.strokeStyle = '#00e5ff';
      ctx.lineWidth = 2;
      ctx.setLineDash([2, 3]);
      ctx.stroke();
      ctx.restore();
    }

    // 6. Needle Rays
    // Beam 1 Needle
    ctx.beginPath();
    ctx.moveTo(ox, oy);
    ctx.lineTo(ox + maxRadius * Math.cos(rad1), oy - maxRadius * Math.sin(rad1));
    ctx.strokeStyle = '#00e5ff';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Beam 2 Needle (Dashed Amber)
    ctx.save();
    ctx.beginPath();
    ctx.setLineDash([3, 3]);
    ctx.moveTo(ox, oy);
    ctx.lineTo(ox + maxRadius * Math.cos(rad2), oy - maxRadius * Math.sin(rad2));
    ctx.strokeStyle = '#ffb300';
    ctx.lineWidth = 1.2;
    ctx.stroke();
    ctx.restore();

    // 7. Endpoints & History
    this.history.forEach((pt, idx) => {
      const age = idx / this.history.length;
      if (pt.d1_cm && pt.d1_cm < 395) {
        const pRad = (pt.angle_deg * Math.PI) / 180.0;
        const pr = (pt.d1_cm / this.maxRangeCm) * maxRadius;
        ctx.beginPath();
        ctx.arc(ox + pr * Math.cos(pRad), oy - pr * Math.sin(pRad), pt.is_portal ? 4 : 2, 0, Math.PI * 2);
        ctx.fillStyle = pt.is_portal ? `rgba(224, 64, 251, ${0.4 + age * 0.6})` : `rgba(0, 229, 255, ${0.3 + age * 0.7})`;
        ctx.fill();
      }
      if (pt.d2_cm && pt.d2_cm < 395 && pt.d2_cm !== pt.d1_cm) {
        const pRad2 = (pt.angle_deg * Math.PI) / 180.0;
        const pr2 = (pt.d2_cm / this.maxRangeCm) * maxRadius;
        ctx.beginPath();
        ctx.arc(ox + pr2 * Math.cos(pRad2), oy - pr2 * Math.sin(pRad2), 2, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(255, 179, 0, ${0.3 + age * 0.7})`;
        ctx.fill();
      }
    });

    // 8. Live Hit Badges
    if (this.valid1 && this.d1Cm < 395) {
      const h1x = ox + r1 * Math.cos(rad1);
      const h1y = oy - r1 * Math.sin(rad1);
      ctx.beginPath();
      ctx.arc(h1x, h1y, 5, 0, Math.PI * 2);
      ctx.fillStyle = '#ff3344';
      ctx.fill();
      ctx.fillStyle = '#ffffff';
      ctx.font = '10px "JetBrains Mono", monospace';
      ctx.fillText(`Low: ${this.d1Cm.toFixed(1)}cm`, h1x + 8, h1y - 6);
    }

    if (this.valid2 && this.d2Cm < 395) {
      const h2x = ox + r2 * Math.cos(rad2);
      const h2y = oy - r2 * Math.sin(rad2);
      ctx.beginPath();
      ctx.arc(h2x, h2y, 4, 0, Math.PI * 2);
      ctx.fillStyle = '#ffb300';
      ctx.fill();
      ctx.fillStyle = '#ffb300';
      ctx.font = '10px "JetBrains Mono", monospace';
      ctx.fillText(`High: ${this.d2Cm.toFixed(1)}cm`, h2x + 8, h2y + 12);
    }

    // 9. Sensor Origin
    ctx.beginPath();
    ctx.arc(ox, oy, 4, 0, Math.PI * 2);
    ctx.fillStyle = '#00e676';
    ctx.fill();
  }
}
