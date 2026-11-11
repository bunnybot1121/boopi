/**
 * Viewport 1: Dual-Beam Polar Radar Sonar Scope.
 * Dynamically scales across 100/150/200/400cm presets and renders
 * connected Sonar Contour Polylines with shaded safe/obstacle zones.
 */

import { getTacticalPalette } from './theme.js';

export class PolarScope {
  constructor(canvasElement) {
    this.canvas = canvasElement;
    this.ctx = canvasElement.getContext('2d');
    this.palette = getTacticalPalette();

    this.maxRangeCm = 200.0;
    this.s1Ang = 90.0;
    this.s2Ang = 90.0;
    this.d1Cm = 400.0;
    this.d2Cm = 400.0;
    this.valid1 = false;
    this.valid2 = false;
    this.minAng = 45.0;
    this.maxAng = 135.0;
    this.history = [];
    this.portals = [];
    this.contourScan = [];
    this.pinpointedObjects = [];
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
      const dx = (e.clientX - rect.left) - this.width / 2;
      const dy = (this.height - 28) - (e.clientY - rect.top);
      if (dy > -25 && this.onAngleAim) {
        const deg = Math.max(0.0, Math.min(180.0, (Math.atan2(dy, dx) * 180.0) / Math.PI));
        this.onAngleAim(Math.round(deg));
      }
    };
    this.canvas.addEventListener('mousedown', (e) => { this.isAimDragging = true; calcAngle(e); });
    window.addEventListener('mousemove', (e) => { if (this.isAimDragging) calcAngle(e); });
    window.addEventListener('mouseup', () => { this.isAimDragging = false; });
  }

  resize() {
    const rect = this.canvas.parentElement.getBoundingClientRect();
    this.width = rect.width;
    this.height = rect.height;
    this.canvas.width = this.width * window.devicePixelRatio;
    this.canvas.height = this.height * window.devicePixelRatio;
    this.ctx.setTransform(window.devicePixelRatio, 0, 0, window.devicePixelRatio, 0, 0);
    this.render();
  }

  getRingSteps() {
    if (this.maxRangeCm <= 105) return [25, 50, 75, 100];
    if (this.maxRangeCm <= 155) return [50, 100, 150];
    if (this.maxRangeCm <= 205) return [50, 100, 150, 200];
    return [100, 200, 300, 400];
  }

  updateState(telemetry, history, portals, pinpointedObjects = [], contourScan = [], gridMeta = null) {
    if (gridMeta && gridMeta.max_range_cm) {
      this.maxRangeCm = gridMeta.max_range_cm;
    } else if (telemetry && telemetry.max_range_cm) {
      this.maxRangeCm = telemetry.max_range_cm;
    }

    if (telemetry) {
      this.s1Ang = telemetry.s1_ang ?? telemetry.s_ang ?? 90.0;
      this.s2Ang = telemetry.s2_ang ?? this.s1Ang;
      this.d1Cm = telemetry.d1_cm ?? telemetry.d_cm ?? 400.0;
      this.d2Cm = telemetry.d2_cm ?? this.d1Cm;
      this.valid1 = (telemetry.valid1 === 1 || telemetry.valid1 === true || telemetry.valid === 1 || telemetry.valid === true);
      this.valid2 = (telemetry.valid2 === 1 || telemetry.valid2 === true);
      this.minAng = telemetry.min_ang ?? 45.0;
      this.maxAng = telemetry.max_ang ?? 135.0;
    }
    if (history) this.history = history;
    if (portals) this.portals = portals;
    if (pinpointedObjects) this.pinpointedObjects = pinpointedObjects;
    if (contourScan) this.contourScan = contourScan;
    this.render();
  }

  clear() {
    this.pinpointedObjects = [];
    this.contourScan = [];
    this.history = [];
    this.portals = [];
    this.render();
  }

  drawContourZones(ctx, ox, oy, maxRadius) {
    if (!this.contourScan || this.contourScan.length === 0) return;

    // Group continuous angular readings into connected wall segments (gap <= 8 deg & jump <= 30cm)
    const segments = [];
    let seg = [];
    for (const pt of this.contourScan) {
      if (pt.d1_cm > this.maxRangeCm || pt.d1_cm < 3.0) {
        if (seg.length > 0) { segments.push(seg); seg = []; }
        continue;
      }
      if (seg.length === 0) {
        seg.push(pt);
      } else {
        const prev = seg[seg.length - 1];
        if (Math.abs(pt.angle_deg - prev.angle_deg) <= 8.5 && Math.abs(pt.d1_cm - prev.d1_cm) <= 30.0) {
          seg.push(pt);
        } else {
          segments.push(seg);
          seg = [pt];
        }
      }
    }
    if (seg.length > 0) segments.push(seg);

    // 1. Shaded Safe Free Interior Polygon + Obstacle Backing Shadow
    segments.forEach((s) => {
      const toXY = (pt) => {
        const rad = (pt.angle_deg * Math.PI) / 180.0;
        const r = Math.min(pt.d1_cm / this.maxRangeCm, 1.0) * maxRadius;
        return { x: ox + r * Math.cos(rad), y: oy - r * Math.sin(rad), rad };
      };

      // Safe corridor interior fill (#0d3b46)
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(ox, oy);
      s.forEach((pt) => { const p = toXY(pt); ctx.lineTo(p.x, p.y); });
      ctx.closePath();
      ctx.fillStyle = 'rgba(13, 59, 70, 0.42)';
      ctx.fill();

      // Obstacle backing warning zone from hit curve out to edge
      if (s.length >= 2) {
        ctx.beginPath();
        s.forEach((pt, i) => {
          const p = toXY(pt);
          if (i === 0) ctx.moveTo(p.x, p.y);
          else ctx.lineTo(p.x, p.y);
        });
        for (let i = s.length - 1; i >= 0; i--) {
          const rad = (s[i].angle_deg * Math.PI) / 180.0;
          ctx.lineTo(ox + maxRadius * Math.cos(rad), oy - maxRadius * Math.sin(rad));
        }
        ctx.closePath();
        ctx.fillStyle = 'rgba(255, 42, 84, 0.14)';
        ctx.fill();
      }
      ctx.restore();

      // 2. Connected Sonar Contour Polyline
      ctx.save();
      ctx.beginPath();
      s.forEach((pt, idx) => {
        const p = toXY(pt);
        if (idx === 0) ctx.moveTo(p.x, p.y);
        else ctx.lineTo(p.x, p.y);
      });
      const isStep = s.some((pt) => pt.class_3d === 'LOW_STEP_RUBBLE');
      const strokeCol = isStep ? this.palette.amber : this.palette.red;
      ctx.strokeStyle = strokeCol;
      ctx.lineWidth = 2.6;
      ctx.shadowColor = strokeCol;
      ctx.shadowBlur = 6;
      ctx.stroke();

      // Small vertices along single-point returns
      if (s.length === 1) {
        const p = toXY(s[0]);
        ctx.beginPath();
        ctx.arc(p.x, p.y, 3.5, 0, Math.PI * 2);
        ctx.fillStyle = strokeCol;
        ctx.fill();
      }
      ctx.restore();
    });
  }

  render() {
    const ctx = this.ctx;
    const w = this.width;
    const h = this.height;
    if (!w || !h) return;

    const pal = this.palette;
    ctx.clearRect(0, 0, w, h);

    const ox = w / 2;
    const oy = h - 28;
    const maxRadius = Math.min(w * 0.48, h - 45);

    // 1. Dynamic Range Rings
    ctx.lineWidth = 1;
    ctx.strokeStyle = pal.borderSubtle;
    ctx.font = '10px "JetBrains Mono", monospace';
    ctx.fillStyle = pal.textDim;

    this.getRingSteps().forEach((rCm) => {
      const radius = (rCm / this.maxRangeCm) * maxRadius;
      ctx.beginPath();
      ctx.arc(ox, oy, radius, Math.PI, 0, false);
      ctx.stroke();
      ctx.fillText(`${rCm}cm`, ox + radius - 22, oy - 4);
    });

    // 2. Radial Spokes & Sector Wedge
    [0, 30, 45, 60, 90, 120, 135, 150, 180].forEach((deg) => {
      const rad = (deg * Math.PI) / 180.0;
      ctx.beginPath();
      ctx.moveTo(ox, oy);
      ctx.lineTo(ox + maxRadius * Math.cos(rad), oy - maxRadius * Math.sin(rad));
      ctx.strokeStyle = deg === 90 ? pal.borderMedium : '#1b222c';
      ctx.stroke();

      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = pal.textMuted;
      ctx.fillText(`${deg}°`, ox + (maxRadius + 14) * Math.cos(rad), oy - (maxRadius + 14) * Math.sin(rad));
    });

    const minRad = (this.minAng * Math.PI) / 180.0;
    const maxRad = (this.maxAng * Math.PI) / 180.0;
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(ox, oy);
    ctx.arc(ox, oy, maxRadius, -maxRad, -minRad, false);
    ctx.closePath();
    ctx.fillStyle = 'rgba(0, 229, 255, 0.03)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(0, 229, 255, 0.35)';
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 1.2;
    ctx.stroke();
    ctx.restore();

    // 3. Connected Sonar Contour Polyline & Shaded Zones
    this.drawContourZones(ctx, ox, oy, maxRadius);

    // 4. Live Sweeping Cones (Timeout fades cleanly to 85% maxRangeCm)
    const rad1 = (this.s1Ang * Math.PI) / 180.0;
    const coneHalf = (7.5 * Math.PI) / 180.0;
    const dispD1 = (this.valid1 && this.d1Cm < 395) ? Math.min(this.d1Cm, this.maxRangeCm) : (0.85 * this.maxRangeCm);
    const r1 = (dispD1 / this.maxRangeCm) * maxRadius;

    ctx.save();
    ctx.beginPath();
    ctx.moveTo(ox, oy);
    ctx.arc(ox, oy, r1, -rad1 - coneHalf, -rad1 + coneHalf, false);
    ctx.closePath();
    ctx.fillStyle = 'rgba(0, 229, 255, 0.16)';
    ctx.fill();
    ctx.restore();

    const rad2 = (this.s2Ang * Math.PI) / 180.0;
    const dispD2 = (this.valid2 && this.d2Cm < 395) ? Math.min(this.d2Cm, this.maxRangeCm) : (0.85 * this.maxRangeCm);
    const r2 = (dispD2 / this.maxRangeCm) * maxRadius;

    ctx.save();
    ctx.beginPath();
    ctx.moveTo(ox, oy);
    ctx.arc(ox, oy, r2, -rad2 - coneHalf * 0.7, -rad2 + coneHalf * 0.7, false);
    ctx.closePath();
    ctx.fillStyle = 'rgba(255, 183, 3, 0.11)';
    ctx.fill();
    ctx.restore();

    // Beam Needles
    ctx.beginPath();
    ctx.moveTo(ox, oy);
    ctx.lineTo(ox + maxRadius * Math.cos(rad1), oy - maxRadius * Math.sin(rad1));
    ctx.strokeStyle = pal.primary;
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // 5. Pinpointed Discrete Obstacle Reticles
    this.pinpointedObjects.forEach((obj) => {
      if (obj.distance_cm > this.maxRangeCm) return;
      const rad = (obj.angle_deg * Math.PI) / 180.0;
      const pr = (obj.distance_cm / this.maxRangeCm) * maxRadius;
      const px = ox + pr * Math.cos(rad);
      const py = oy - pr * Math.sin(rad);
      const colHex = obj.color || pal.red;

      ctx.save();
      ctx.beginPath();
      ctx.arc(px, py, 6.5, 0, Math.PI * 2);
      ctx.strokeStyle = colHex;
      ctx.lineWidth = 1.8;
      ctx.stroke();

      const tag = `${obj.id}: ${obj.distance_cm.toFixed(0)}cm @ ${obj.angle_deg.toFixed(0)}°`;
      ctx.font = '10px "JetBrains Mono", monospace';
      const tw = ctx.measureText(tag).width;
      const lx = px >= ox ? px + 10 : px - tw - 14;
      const ly = py - 8;

      ctx.fillStyle = 'rgba(11, 16, 23, 0.90)';
      ctx.fillRect(lx - 4, ly - 10, tw + 8, 15);
      ctx.strokeStyle = colHex;
      ctx.strokeRect(lx - 4, ly - 10, tw + 8, 15);
      ctx.fillStyle = colHex;
      ctx.textAlign = 'left';
      ctx.fillText(tag, lx, ly + 1);
      ctx.restore();
    });

    // 6. Live Hit Badges
    if (this.valid1 && this.d1Cm >= 3.0 && this.d1Cm <= this.maxRangeCm) {
      const hx = ox + r1 * Math.cos(rad1);
      const hy = oy - r1 * Math.sin(rad1);
      ctx.beginPath();
      ctx.arc(hx, hy, 4.5, 0, Math.PI * 2);
      ctx.fillStyle = pal.red;
      ctx.fill();
      ctx.fillStyle = pal.textBright;
      ctx.textAlign = 'left';
      ctx.fillText(`Low: ${this.d1Cm.toFixed(1)}cm`, hx + 8, hy - 6);
    }

    if (this.valid2 && this.d2Cm >= 3.0 && this.d2Cm <= this.maxRangeCm && Math.abs(this.d2Cm - this.d1Cm) > 2.0) {
      const h2x = ox + r2 * Math.cos(rad2);
      const h2y = oy - r2 * Math.sin(rad2);
      ctx.beginPath();
      ctx.arc(h2x, h2y, 4, 0, Math.PI * 2);
      ctx.fillStyle = pal.amber;
      ctx.fill();
      ctx.fillStyle = pal.amber;
      ctx.textAlign = 'left';
      ctx.fillText(`High: ${this.d2Cm.toFixed(1)}cm`, h2x + 8, h2y + 12);
    }

    // 7. Robot Origin Marker
    ctx.beginPath();
    ctx.arc(ox, oy, 4, 0, Math.PI * 2);
    ctx.fillStyle = pal.green;
    ctx.fill();
  }
}
