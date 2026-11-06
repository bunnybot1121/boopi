/**
 * API and WebSocket client for BUPI Sonar Vision Testbed.
 */

export class SonarAPI {
  constructor() {
    this.ws = null;
    this.reconnectTimer = null;
    this.onSnapshotCallback = null;
    this.onConnectionChange = null;
  }

  async getPorts() {
    try {
      const res = await fetch('/api/ports');
      return await res.json();
    } catch (err) {
      return { ports: [] };
    }
  }

  async connectPort(port, baud = 115200) {
    const res = await fetch('/api/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ port, baud: parseInt(baud, 10) })
    });
    return await res.json();
  }

  async disconnectPort() {
    const res = await fetch('/api/disconnect', { method: 'POST' });
    return await res.json();
  }

  async setActivePass(passName) {
    const res = await fetch('/api/pass', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pass_name: passName })
    });
    return await res.json();
  }

  async setManualAngle(angleDeg) {
    try {
      await fetch('/api/angle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ angle_deg: angleDeg })
      });
    } catch (_) {}
  }

  async resetMap() {
    const res = await fetch('/api/reset', { method: 'POST' });
    return await res.json();
  }

  async exportJson() {
    const res = await fetch('/api/export');
    return await res.json();
  }

  initWebSocket(onSnapshot, onConnection) {
    this.onSnapshotCallback = onSnapshot;
    this.onConnectionChange = onConnection;
    this.connectWs();
  }

  connectWs() {
    if (this.ws) {
      try { this.ws.close(); } catch (_) {}
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/sonar`;

    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      if (this.onConnectionChange) this.onConnectionChange(true);
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (this.onSnapshotCallback) this.onSnapshotCallback(data);
      } catch (_) {}
    };

    this.ws.onclose = () => {
      if (this.onConnectionChange) this.onConnectionChange(false);
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = setTimeout(() => this.connectWs(), 1500);
    };

    this.ws.onerror = () => {
      if (this.onConnectionChange) this.onConnectionChange(false);
    };
  }

  sendWs(payload) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    }
  }
}

