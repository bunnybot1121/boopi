/**
 * Viewport 2: 2D DIP Occupancy Grid Canvas.
 * Displays the 120x120 Bayesian Log-Odds tensor, OpenCV safety dilation buffer,
 * and mouse hover coordinates.
 */

export class DIPCanvas {
  constructor(canvasElement, coordsElement) {
    this.canvas = canvasElement;
    this.coordsEl = coordsElement;
    this.ctx = canvasElement.getContext('2d');

    this.gridWidth = 120;
    this.gridHeight = 120;
    this.resCm = 4.0;
    this.originX = 60;
    this.originY = 60;

    this.image = new Image();
    this.image.onload = () => this.render();

    this.astarPath = [];
    this.points3d = [];
    this.telemetry = null;
    this.pinpointedObjects = [];

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

  updateSnapshot(imageB64, astarPath, points3d, telemetry, pinpointedObjects = []) {
    if (astarPath) this.astarPath = astarPath;
    if (points3d) this.points3d = points3d;
    if (telemetry) this.telemetry = telemetry;
    if (pinpointedObjects) this.pinpointedObjects = pinpointedObjects;

    if (imageB64 && imageB64 !== this.image.src) {
      this.image.src = imageB64;
    } else {
      this.render();
    }
  }

  render() {
    const ctx = this.ctx;
    const s = this.size;
    if (!s) return;

    ctx.save();
    ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
    ctx.clearRect(0, 0, s, s);

    // 1. Render OpenCV generated semantic image base
    if (this.image.complete && this.image.naturalWidth > 0) {
      ctx.drawImage(this.image, 0, 0, s, s);
    } else {
      ctx.fillStyle = '#0b0f14';
      ctx.fillRect(0, 0, s, s);
    }

    const pxPerCell = s / this.gridWidth;
    const oxPx = this.originX * pxPerCell;
    const oyPx = this.originY * pxPerCell;

    // 2. Metric Coordinate Axes (X-axis & Y-axis in cm)
    ctx.strokeStyle = 'rgba(0, 229, 255, 0.25)';
    ctx.lineWidth = 1;
    // X Axis (Horizontal line through origin)
    ctx.beginPath();
    ctx.moveTo(0, oyPx);
    ctx.lineTo(s, oyPx);
    ctx.stroke();
    // Y Axis (Vertical line through origin)
    ctx.beginPath();
    ctx.moveTo(oxPx, 0);
    ctx.lineTo(oxPx, s);
    ctx.stroke();

    // 3. Concentric Metric Range Rings (100cm, 200cm, 300cm)
    const rings = [100, 200, 300];
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
    ctx.fillStyle = 'rgba(255, 255, 255, 0.40)';
    ctx.font = '9px "JetBrains Mono", monospace';
    rings.forEach((rCm) => {
      const rPx = (rCm / this.resCm) * pxPerCell;
      ctx.beginPath();
      ctx.arc(oxPx, oyPx, rPx, 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillText(`${rCm}cm`, oxPx + rPx - 14, oyPx - 4);
    });

    // 4. Exact 2D Obstacle Points from 3D Engine
    if (this.points3d && this.points3d.length > 0) {
      this.points3d.forEach((pt) => {
        const wx = pt.x !== undefined ? pt.x : 0;
        const wy = pt.y !== undefined ? pt.y : 0;
        const px = (this.originX + (wx / this.resCm)) * pxPerCell;
        const py = (this.originY - (wy / this.resCm)) * pxPerCell;
        if (px >= 0 && px <= s && py >= 0 && py <= s) {
          ctx.beginPath();
          ctx.arc(px, py, pt.beam === 'high' ? 2.5 : 3.0, 0, Math.PI * 2);
          ctx.fillStyle = pt.beam === 'high' ? '#ffb300' : '#ff3344';
          ctx.shadowColor = pt.beam === 'high' ? '#ffb300' : '#ff3344';
          ctx.shadowBlur = 4;
          ctx.fill();
          ctx.shadowBlur = 0;
        }
      });
    }

    // 5. Live Sweeping Radar Ray
    if (this.telemetry) {
      const s1 = this.telemetry.s1_ang !== undefined ? this.telemetry.s1_ang : (this.telemetry.s_ang || 90.0);
      const rad = (s1 * Math.PI) / 180.0;
      const rayLenPx = (380 / this.resCm) * pxPerCell;
      const rx = oxPx + rayLenPx * Math.cos(rad);
      const ry = oyPx - rayLenPx * Math.sin(rad);

      ctx.save();
      ctx.beginPath();
      ctx.moveTo(oxPx, oyPx);
      ctx.lineTo(rx, ry);
      ctx.strokeStyle = 'rgba(0, 229, 255, 0.65)';
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Live hit dot along current ray
      const d1 = this.telemetry.d1_cm !== undefined ? this.telemetry.d1_cm : this.telemetry.d_cm;
      if (d1 && d1 > 2 && d1 < 390) {
        const hPx = (d1 / this.resCm) * pxPerCell;
        const hx = oxPx + hPx * Math.cos(rad);
        const hy = oyPx - hPx * Math.sin(rad);
        ctx.beginPath();
        ctx.arc(hx, hy, 4.5, 0, Math.PI * 2);
        ctx.fillStyle = '#00e5ff';
        ctx.shadowColor = '#00e5ff';
        ctx.shadowBlur = 8;
        ctx.fill();
      }
      ctx.restore();
    }

    // 6. Draw A* Planned Path Line (Neon Green)
    if (this.astarPath && this.astarPath.length >= 2) {
      ctx.save();
      ctx.strokeStyle = '#00e676';
      ctx.lineWidth = 2.0;
      ctx.shadowColor = '#00e676';
      ctx.shadowBlur = 6;
      ctx.beginPath();

      this.astarPath.forEach((wp, idx) => {
        const wx = wp.x_cm !== undefined ? wp.x_cm : (wp.x || 0);
        const wy = wp.y_cm !== undefined ? wp.y_cm : (wp.y || 0);
        const col = this.originX + (wx / this.resCm);
        const row = this.originY - (wy / this.resCm);
        const px = col * pxPerCell;
        const py = row * pxPerCell;
        if (idx === 0) {
          ctx.moveTo(px, py);
        } else {
          ctx.lineTo(px, py);
        }
      });
      ctx.stroke();
      ctx.restore();
    }

    // 6b. Pinpointed Discrete Obstacles & Metric Tags
    if (this.pinpointedObjects && this.pinpointedObjects.length > 0) {
      this.pinpointedObjects.forEach((obj) => {
        const col = this.originX + (obj.x_cm / this.resCm);
        const row = this.originY - (obj.y_cm / this.resCm);
        const px = col * pxPerCell;
        const py = row * pxPerCell;

        if (px >= 0 && px <= s && py >= 0 && py <= s) {
          const colHex = obj.color || '#ff3344';
          const rPx = Math.max(8, (obj.width_cm / 2 / this.resCm) * pxPerCell);

          ctx.save();
          // Obstacle bounding circle / zone
          ctx.beginPath();
          ctx.arc(px, py, rPx, 0, Math.PI * 2);
          ctx.strokeStyle = colHex;
          ctx.lineWidth = 1.5;
          ctx.setLineDash([3, 2]);
          ctx.stroke();

          // Center target reticle
          ctx.setLineDash([]);
          ctx.beginPath();
          ctx.arc(px, py, 4, 0, Math.PI * 2);
          ctx.fillStyle = colHex;
          ctx.fill();

          // Tactical Coordinate Label
          const tag = `${obj.id} [${obj.x_cm > 0 ? '+' : ''}${obj.x_cm}, ${obj.y_cm > 0 ? '+' : ''}${obj.y_cm}]`;
          ctx.font = '9px "JetBrains Mono", monospace';
          const tw = ctx.measureText(tag).width;

          ctx.fillStyle = 'rgba(11, 15, 20, 0.85)';
          ctx.fillRect(px + 6, py - 14, tw + 8, 14);
          ctx.strokeStyle = colHex;
          ctx.lineWidth = 1;
          ctx.strokeRect(px + 6, py - 14, tw + 8, 14);

          ctx.fillStyle = colHex;
          ctx.fillText(tag, px + 10, py - 3);
          ctx.restore();
        }
      });
    }

    // 7. Robot Origin Marker at Center (60, 60)
    ctx.beginPath();
    ctx.arc(oxPx, oyPx, 4, 0, Math.PI * 2);
    ctx.fillStyle = '#00e676';
    ctx.fill();

    ctx.restore();
  }

  setupMouseEvents() {
    this.canvas.addEventListener('mousemove', (e) => {
      const rect = this.canvas.getBoundingClientRect();
      const normX = (e.clientX - rect.left) / rect.width;
      const normY = (e.clientY - rect.top) / rect.height;

      const col = Math.floor(normX * this.gridWidth);
      const row = Math.floor(normY * this.gridHeight);

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
      if (this.coordsEl) {
        this.coordsEl.textContent = `Grid: 120x120 | Res: 4.0cm | 4.8m x 4.8m`;
      }
    });
  }
}

