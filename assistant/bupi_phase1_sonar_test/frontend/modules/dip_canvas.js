/**
 * Viewport 2: 2D DIP Occupancy Grid Canvas.
 * Dynamically scales across 100/150/200/400cm presets using gap-free colors
 * and renders crisp rectangular tactical bounding boxes around objects.
 */

import { getTacticalPalette } from './theme.js';

export class DIPCanvas {
  constructor(canvasElement, coordsElement) {
    this.canvas = canvasElement;
    this.coordsEl = coordsElement;
    this.ctx = canvasElement.getContext('2d');
    this.palette = getTacticalPalette();

    this.gridWidth = 200;
    this.gridHeight = 200;
    this.resCm = 2.0;
    this.originX = 100;
    this.originY = 100;
    this.maxRangeCm = 200.0;

    this.image = new Image();
    this.image.onload = () => this.render();

    this.astarPath = [];
    this.telemetry = null;
    this.pinpointedObjects = [];
    this.isHovering = false;

    this.setupMouseEvents();
    this.resize();
    window.addEventListener('resize', () => this.resize());
  }

  resize() {
    const rect = this.canvas.parentElement.getBoundingClientRect();
    const size = Math.min(rect.width, rect.height) - 16;
    this.size = Math.max(260, size);
    this.canvas.width = this.size * window.devicePixelRatio;
    this.canvas.height = this.size * window.devicePixelRatio;
    this.canvas.style.width = `${this.size}px`;
    this.canvas.style.height = `${this.size}px`;
    this.ctx.imageSmoothingEnabled = false;
    this.render();
  }

  getRingSteps() {
    if (this.maxRangeCm <= 105) return [25, 50, 75, 100];
    if (this.maxRangeCm <= 155) return [50, 100, 150];
    if (this.maxRangeCm <= 205) return [50, 100, 150, 200];
    return [100, 200, 300, 400];
  }

  updateSnapshot(imageB64, astarPath, _points3d, telemetry, pinpointedObjects = [], gridMeta = null) {
    if (gridMeta) {
      this.gridWidth = gridMeta.width || 200;
      this.gridHeight = gridMeta.height || 200;
      this.resCm = gridMeta.res_cm || 2.0;
      this.originX = gridMeta.origin_x || 100;
      this.originY = gridMeta.origin_y || 100;
      this.maxRangeCm = gridMeta.max_range_cm || 200.0;
      if (this.coordsEl && !this.isHovering) {
        this.coordsEl.textContent = `Grid: ${this.gridWidth}x${this.gridHeight} | Res: ${this.resCm.toFixed(1)}cm | Range: ${this.maxRangeCm.toFixed(0)}cm`;
      }
    }
    if (astarPath) this.astarPath = astarPath;
    if (telemetry) this.telemetry = telemetry;
    if (pinpointedObjects) this.pinpointedObjects = pinpointedObjects;

    if (imageB64 && imageB64 !== this.image.src) {
      this.image.src = imageB64;
    } else {
      this.render();
    }
  }

  worldToCanvasPx(wxCm, wyCm, pxPerCell) {
    return {
      px: (this.originX + (wxCm / this.resCm)) * pxPerCell,
      py: (this.originY - (wyCm / this.resCm)) * pxPerCell
    };
  }

  render() {
    const ctx = this.ctx;
    const s = this.size;
    if (!s) return;

    const pal = this.palette;
    ctx.save();
    ctx.setTransform(window.devicePixelRatio, 0, 0, window.devicePixelRatio, 0, 0);
    ctx.clearRect(0, 0, s, s);

    // 1. Gap-free OpenCV semantic matrix base (#0b1017 unknown canvas)
    if (this.image.complete && this.image.naturalWidth > 0) {
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(this.image, 0, 0, s, s);
    } else {
      ctx.fillStyle = pal.mapUnknown;
      ctx.fillRect(0, 0, s, s);
    }

    const pxPerCell = s / this.gridWidth;
    const oxPx = this.originX * pxPerCell;
    const oyPx = this.originY * pxPerCell;

    // 2. Metric Axes
    ctx.strokeStyle = 'rgba(0, 229, 255, 0.22)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, oyPx); ctx.lineTo(s, oyPx);
    ctx.moveTo(oxPx, 0); ctx.lineTo(oxPx, s);
    ctx.stroke();

    // 3. Scaled Metric Range Rings
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.09)';
    ctx.fillStyle = 'rgba(255, 255, 255, 0.45)';
    ctx.font = '9px "JetBrains Mono", monospace';
    this.getRingSteps().forEach((rCm) => {
      const rPx = (rCm / this.resCm) * pxPerCell;
      ctx.beginPath();
      ctx.arc(oxPx, oyPx, rPx, 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillText(`${rCm}cm`, oxPx + rPx - 24, oyPx - 4);
    });

    // 4. Live Sweeping Radar Ray (Capped at 85% max_range on timeout)
    if (this.telemetry) {
      const s1 = this.telemetry.s1_ang ?? this.telemetry.s_ang ?? 90.0;
      const rad = (s1 * Math.PI) / 180.0;
      const v1 = (this.telemetry.valid1 === 1 || this.telemetry.valid === 1);
      const d1 = this.telemetry.d1_cm ?? this.telemetry.d_cm ?? 400.0;
      const rayCm = (v1 && d1 < 395) ? Math.min(d1, this.maxRangeCm) : (0.85 * this.maxRangeCm);
      const rayPx = (rayCm / this.resCm) * pxPerCell;

      ctx.save();
      ctx.beginPath();
      ctx.moveTo(oxPx, oyPx);
      ctx.lineTo(oxPx + rayPx * Math.cos(rad), oyPx - rayPx * Math.sin(rad));
      ctx.strokeStyle = 'rgba(0, 229, 255, 0.65)';
      ctx.lineWidth = 1.5;
      ctx.stroke();

      if (v1 && d1 >= 3.0 && d1 <= this.maxRangeCm) {
        const hp = this.worldToCanvasPx(d1 * Math.cos(rad), d1 * Math.sin(rad), pxPerCell);
        ctx.beginPath();
        ctx.arc(hp.px, hp.py, 4, 0, Math.PI * 2);
        ctx.fillStyle = pal.primary;
        ctx.fill();
      }
      ctx.restore();
    }

    // 5. A* Planned Path Ribbon
    if (this.astarPath && this.astarPath.length >= 2) {
      ctx.save();
      ctx.strokeStyle = pal.green;
      ctx.lineWidth = 2.0;
      ctx.beginPath();
      this.astarPath.forEach((wp, idx) => {
        const pt = this.worldToCanvasPx(wp.x_cm ?? wp.x ?? 0, wp.y_cm ?? wp.y ?? 0, pxPerCell);
        if (idx === 0) ctx.moveTo(pt.px, pt.py);
        else ctx.lineTo(pt.px, pt.py);
      });
      ctx.stroke();
      ctx.restore();
    }

    // 6. Clustered Object Bounding Boxes [OBJ-01: XXcm]
    this.pinpointedObjects.forEach((obj) => {
      const box = obj.bbox_world;
      if (!box) return;
      const p1 = this.worldToCanvasPx(box.x_min, box.y_max, pxPerCell);
      const p2 = this.worldToCanvasPx(box.x_max, box.y_min, pxPerCell);
      const bx = p1.px - 3;
      const by = p1.py - 3;
      const bw = Math.max(10, (p2.px - p1.px) + 6);
      const bh = Math.max(10, (p2.py - p1.py) + 6);
      const colHex = obj.color || pal.red;

      ctx.save();
      ctx.strokeStyle = colHex;
      ctx.lineWidth = 1.4;
      ctx.strokeRect(bx, by, bw, bh);

      // Centroid marker
      const cp = this.worldToCanvasPx(obj.x_cm, obj.y_cm, pxPerCell);
      ctx.beginPath();
      ctx.arc(cp.px, cp.py, 2.5, 0, Math.PI * 2);
      ctx.fillStyle = colHex;
      ctx.fill();

      // Label tag [OBJ-01: 48cm]
      const tag = `[${obj.id}: ${obj.distance_cm.toFixed(0)}cm]`;
      ctx.font = 'bold 9px "JetBrains Mono", monospace';
      const tw = ctx.measureText(tag).width;
      const lx = Math.min(s - tw - 10, Math.max(4, bx));
      const ly = Math.max(15, by - 4);

      ctx.fillStyle = 'rgba(11, 16, 23, 0.90)';
      ctx.fillRect(lx - 2, ly - 11, tw + 6, 13);
      ctx.strokeStyle = colHex;
      ctx.lineWidth = 1;
      ctx.strokeRect(lx - 2, ly - 11, tw + 6, 13);
      ctx.fillStyle = colHex;
      ctx.fillText(tag, lx + 1, ly - 1);
      ctx.restore();
    });

    // 7. Robot Origin Marker
    ctx.beginPath();
    ctx.arc(oxPx, oyPx, 4, 0, Math.PI * 2);
    ctx.fillStyle = pal.green;
    ctx.fill();

    ctx.restore();
  }

  setupMouseEvents() {
    this.canvas.addEventListener('mousemove', (e) => {
      this.isHovering = true;
      const rect = this.canvas.getBoundingClientRect();
      const col = Math.floor(((e.clientX - rect.left) / rect.width) * this.gridWidth);
      const row = Math.floor(((e.clientY - rect.top) / rect.height) * this.gridHeight);

      if (col >= 0 && col < this.gridWidth && row >= 0 && row < this.gridHeight) {
        const xCm = (col - this.originX) * this.resCm;
        const yCm = (this.originY - row) * this.resCm;
        const dist = Math.hypot(xCm, yCm);
        const angle = ((Math.atan2(yCm, xCm) * 180.0) / Math.PI + 360) % 360;
        if (this.coordsEl) {
          this.coordsEl.textContent = `X: ${xCm.toFixed(0)}cm | Y: ${yCm.toFixed(0)}cm | D: ${dist.toFixed(0)}cm @ ${angle.toFixed(0)}°`;
        }
      }
    });

    this.canvas.addEventListener('mouseleave', () => {
      this.isHovering = false;
      if (this.coordsEl) {
        this.coordsEl.textContent = `Grid: ${this.gridWidth}x${this.gridHeight} | Res: ${this.resCm.toFixed(1)}cm | Range: ${this.maxRangeCm.toFixed(0)}cm`;
      }
    });
  }
}
