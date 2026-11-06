"""
FastAPI Server & Real-Time WebSocket Bridge for BUPI Sonar Vision.
Receives real ultrasonic telemetry over USB Serial (115200 baud) or MQTT.
Zero dummy/simulator data. Starts 100% empty.
"""

import asyncio
from pathlib import Path
from typing import Dict, Any, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response, Query
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import CONFIG
from .sonar_imaging_engine import SonarImagingEngine
from .serial_manager import SerialManager

app = FastAPI(title="BUPI Sonar Vision System", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = SonarImagingEngine(CONFIG)
serial_mgr = SerialManager(engine)

active_websockets: List[WebSocket] = []


class ConnectRequest(BaseModel):
    port: str
    baud: int = 115200


class PassRequest(BaseModel):
    pass_name: str


class AngleRequest(BaseModel):
    angle_deg: float


class IngestPingRequest(BaseModel):
    angle_deg: float
    d_cm: float
    valid: int = 1
    safety_stop: int = 0
    imu: bool = False
    yaw: float = None
    pitch: float = None


@app.on_event("startup")
async def startup_event():
    # Attempt auto-connection to an attached ESP32 port (e.g. COM3 or first detected USB port)
    ports = SerialManager.list_ports()
    for p in ports:
        dev = p["device"]
        desc = p.get("description", "").lower()
        if "usb" in desc or "ch340" in desc or "cp210" in desc or "uart" in desc or dev == "COM3":
            if serial_mgr.connect(dev, 115200):
                break

    # Start broadcasting loop
    asyncio.create_task(broadcast_loop())


@app.on_event("shutdown")
async def shutdown_event():
    serial_mgr.stop_all()


async def broadcast_loop():
    """Broadcast state snapshots to all connected WebSockets at ~15 FPS."""
    while True:
        try:
            if active_websockets:
                snapshot = engine.get_state_snapshot(include_image=True)
                snapshot["connection"] = {
                    "connected": serial_mgr.is_connected,
                    "port": serial_mgr.current_port,
                    "is_busy": serial_mgr.is_port_busy,
                    "busy_port": serial_mgr.busy_port_name
                }
                disconnected = []
                for ws in list(active_websockets):
                    try:
                        await ws.send_json(snapshot)
                    except Exception:
                        disconnected.append(ws)

                for dead_ws in disconnected:
                    if dead_ws in active_websockets:
                        active_websockets.remove(dead_ws)
        except Exception:
            pass
        await asyncio.sleep(0.066)


@app.get("/api/ports")
def get_ports():
    return {"ports": SerialManager.list_ports()}


@app.get("/api/status")
def get_status():
    return {
        "connected": serial_mgr.is_connected,
        "port": serial_mgr.current_port,
        "is_busy": serial_mgr.is_port_busy,
        "busy_port": serial_mgr.busy_port_name,
        "baud": serial_mgr.baud_rate,
        "active_pass": engine.profiler.active_pass,
        "total_pings": engine.total_pings,
        "hit_count": engine.hit_count
    }


@app.post("/api/connect")
def connect_port(req: ConnectRequest):
    success = serial_mgr.connect(req.port, req.baud)
    return {"status": "ok" if success else "error", "connected": success, "port": req.port}


@app.post("/api/disconnect")
def disconnect_port():
    serial_mgr.disconnect()
    return {"status": "ok", "connected": False}


@app.post("/api/pass")
def set_pass(req: PassRequest):
    engine.set_active_pass(req.pass_name)
    return {"status": "ok", "active_pass": engine.profiler.active_pass}


@app.post("/api/angle")
def set_angle(req: AngleRequest):
    serial_mgr.update_pacer_angle(req.angle_deg)
    return {"status": "ok", "angle": req.angle_deg}


@app.post("/api/ping")
def ingest_ping(req: IngestPingRequest):
    """Direct HTTP/MQTT ingest endpoint for live wireless ESP32 or MQTT bridge."""
    telemetry = engine.ingest_ping(
        angle_deg=req.angle_deg,
        distance_cm=req.d_cm,
        is_valid=bool(req.valid == 1),
        safety_stop=req.safety_stop,
        imu_detected=req.imu,
        yaw=req.yaw,
        pitch=req.pitch
    )
    return {"status": "ok", "telemetry": telemetry}


@app.post("/api/reset")
def reset_map():
    engine.reset()
    return {"status": "ok", "message": "Map and buffers reset successfully"}


@app.get("/api/map_image")
def get_map_image(dilation: bool = Query(True)):
    png_bytes = engine.get_map_png(show_dilation=dilation)
    return Response(content=png_bytes, media_type="image/png")


@app.get("/api/export")
def export_matrix():
    return engine.export_full_matrix_json()


@app.websocket("/ws/sonar")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        while True:
            msg = await websocket.receive_json()
            cmd = msg.get("action")
            if cmd == "set_angle":
                serial_mgr.update_pacer_angle(float(msg.get("angle", 90.0)))
            elif cmd == "set_pass":
                engine.set_active_pass(msg.get("pass", "pass1"))
            elif cmd == "step_ping":
                ang = float(msg.get("angle", 90.0))
                d = float(msg.get("d_cm", 400.0))
                engine.ingest_ping(ang, d, is_valid=True)
            elif cmd == "reset":
                engine.reset()
    except WebSocketDisconnect:
        if websocket in active_websockets:
            active_websockets.remove(websocket)
    except Exception:
        if websocket in active_websockets:
            active_websockets.remove(websocket)


@app.get("/devlog", response_class=HTMLResponse)
def view_devlog():
    import json
    devlog_path = Path(__file__).resolve().parent.parent.parent / "devlog" / "2026-11-06_phase1_sonar_vision_breakthrough.md"
    if not devlog_path.exists():
        return HTMLResponse("<h1>DevLog file not found</h1>")
    md_content = devlog_path.read_text(encoding="utf-8")
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>BUPI Engineering DevLog</title>
  <link rel="stylesheet" href="/tokens.css">
  <link rel="stylesheet" href="/styles.css">
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <style>
    body {{ background: #0b0e14; color: #c9d1d9; padding: 2.5rem 1.5rem; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace; line-height: 1.6; max-width: 960px; margin: 0 auto; }}
    h1, h2, h3 {{ color: #00e5ff; border-bottom: 1px solid #21262d; padding-bottom: 0.3em; margin-top: 1.8rem; }}
    pre {{ background: #161b22; padding: 1.2rem; border-radius: 6px; overflow-x: auto; border: 1px solid #30363d; }}
    code {{ color: #58a6ff; font-family: "JetBrains Mono", monospace; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1.2rem 0; font-size: 13.5px; }}
    th, td {{ border: 1px solid #30363d; padding: 8px 12px; text-align: left; }}
    th {{ background: #161b22; color: #f0f6fc; }}
    a {{ color: #00e5ff; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .back-btn {{ display: inline-flex; align-items: center; gap: 6px; margin-bottom: 1.5rem; padding: 8px 16px; background: #21262d; color: #00e5ff; border-radius: 6px; border: 1px solid #30363d; text-decoration: none; font-size: 13px; font-weight: 600; }}
    .back-btn:hover {{ background: #30363d; color: #fff; }}
  </style>
</head>
<body>
  <a href="/" class="back-btn">← Back to Sonar Testbed</a>
  <div id="content"></div>
  <script>
    const md = {json.dumps(md_content)};
    document.getElementById('content').innerHTML = marked.parse(md);
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)


# Mount static frontend
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
