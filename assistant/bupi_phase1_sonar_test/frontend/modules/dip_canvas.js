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

  updateSnapshot(imageB64, astarPath) {
    if (astarPath) this.astarPath = astarPath;
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

    // Render OpenCV generated semantic image
    if (this.image.complete && this.image.naturalWidth > 0) {
      ctx.drawImage(this.image, 0, 0, s, s);
    } else {
      // Empty background
      ctx.fillStyle = '#0b0f14';
      ctx.fillRect(0, 0, s, s);
    }

    // Draw Subtle 100cm Metric Grid Lines (every 25 cells = 100cm)
    const pxPerCell = s / this.gridWidth;
    const pxPer100cm = 25 * pxPerCell;

    ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
    ctx.lineWidth = 1;

    for (let c = 0; c <= this.gridWidth; c += 25) {
      const x = c * pxPerCell;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, s);
      ctx.stroke();
    }
    for (let r = 0; r <= this.gridHeight; r += 25) {
      const y = r * pxPerCell;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(s, y);
      ctx.stroke();
    }

    // Draw A* Planned Path Line (Neon Green)
    if (this.astarPath && this.astarPath.length >= 2) {
      ctx.save();
      ctx.strokeStyle = '#00e676';
      ctx.lineWidth = 2.0;
      ctx.shadowColor = '#00e676';
      ctx.shadowBlur = 6;
      ctx.beginPath();

      this.astarPath.forEach((wp, idx) => {
        const col = this.originX + (wp.x / this.resCm);
        const row = this.originY - (wp.y / this.resCm);
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

