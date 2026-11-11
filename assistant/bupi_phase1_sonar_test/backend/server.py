"""
FastAPI Server & Real-Time WebSocket Bridge for BUPI Sonar Vision.
Receives real ultrasonic telemetry over USB Serial (115200 baud) or MQTT.
Zero dummy/simulator data. Starts 100% empty.
"""

import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response, Query
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import CONFIG
from .sonar_imaging_engine import SonarImagingEngine
from .serial_manager import SerialManager

engine = SonarImagingEngine(CONFIG)
serial_mgr = SerialManager(engine)
active_websockets: List[WebSocket] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Attempt auto-connection to an attached ESP32 port (specifically COM3 or auto-detected USB)
    connected = serial_mgr.connect("COM3", 115200)
    if connected:
        print("[STARTUP] Auto-connected to ESP32 on COM3 at 115200 baud")
    else:
        ports = SerialManager.list_ports()
        for p in ports:
            dev = p["device"]
            desc = p.get("description", "").lower()
            if "usb" in desc or "ch340" in desc or "cp210" in desc or "uart" in desc:
                if serial_mgr.connect(dev, 115200):
                    print(f"[STARTUP] Auto-connected to ESP32 on {dev} at 115200 baud")
                    break
    b_task = asyncio.create_task(broadcast_loop())
    yield
    b_task.cancel()
    serial_mgr.stop_all()


app = FastAPI(title="BUPI Sonar Vision System", version="2.5.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConnectRequest(BaseModel):
    port: str
    baud: int = 115200


class PassRequest(BaseModel):
    pass_name: str


class AngleRequest(BaseModel):
    angle_deg: float


class RangeScaleRequest(BaseModel):
    max_range_cm: float = 200.0


class ServoConfigRequest(BaseModel):
    min_ang: int = 45
    max_ang: int = 135
    step: int = 3
    sweep_en: int = 1
    hold_ang: int = 90


class ScanConfigRequest(BaseModel):
    mode: str = "STACKED_3D"  # 'STACKED_3D', 'OPPOSED_360', 'PITCH_TILT_3D'
    min_ang: int = 45
    max_ang: int = 135
    step: int = 3
    sweep_en: int = 1
    center_90: int = 0


class IngestPingRequest(BaseModel):
    angle_deg: float = 90.0
    d_cm: float = 400.0
    d1_cm: Optional[float] = None
    d2_cm: Optional[float] = None
    s1_ang: Optional[float] = None
    s2_ang: Optional[float] = None
    mode: str = "STACKED_3D"
    valid: int = 1
    valid1: Optional[int] = None
    valid2: Optional[int] = None
    safety_stop: int = 0
    imu: bool = False
    yaw: Optional[float] = None
    pitch: Optional[float] = None
    s_ang: Optional[float] = None
    min_ang: float = 45.0
    max_ang: float = 135.0
    sweep_dir: str = "STEADY"


broadcast_count: int = 0


async def broadcast_loop():
    """Broadcast state snapshots to all connected WebSockets at 20 FPS."""
    global broadcast_count
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
                    except Exception as e:
                        print(f"[WS ERROR] send_json failed: {type(e).__name__}: {e}")
                        disconnected.append(ws)

                for dead_ws in disconnected:
                    if dead_ws in active_websockets:
                        active_websockets.remove(dead_ws)

                broadcast_count += 1
                if broadcast_count % 50 == 0:
                    tel = snapshot.get("telemetry", {})
                    s1 = tel.get("s1_ang", 90.0)
                    d1 = tel.get("d1_cm", 400.0)
                    d2 = tel.get("d2_cm", 400.0)
                    print(f"[WS BROADCAST] Pushed snapshot #{broadcast_count} to {len(active_websockets)} client(s): s1={s1:.1f}°, d1={d1:.1f}cm, d2={d2:.1f}cm")
        except Exception:
            pass
        await asyncio.sleep(0.05)


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


@app.post("/api/range_scale")
def set_range_scale(req: RangeScaleRequest):
    engine.set_max_range(req.max_range_cm)
    return {
        "status": "ok",
        "max_range_cm": engine.engine_3d.max_range_cm,
        "res_cm": engine.engine_3d.res
    }


@app.post("/api/scan_cfg")
def configure_scan(req: ScanConfigRequest):
    cmd = {
        "cmd": "SCAN_CFG",
        "mode": req.mode,
        "min_ang": req.min_ang,
        "max_ang": req.max_ang,
        "step": req.step,
        "sweep_en": req.sweep_en,
        "center_90": req.center_90
    }
    success = serial_mgr.send_command(cmd)
    return {"status": "ok" if success else "error", "config": cmd, "sent_to_serial": success}


@app.post("/api/center_both_90")
def center_both_servos():
    cmd = {"cmd": "SCAN_CFG", "center_90": 1, "sweep_en": 0}
    success = serial_mgr.send_command(cmd)
    return {"status": "ok" if success else "error", "action": "center_90", "sent_to_serial": success}


@app.post("/api/servo_cfg")
def configure_servo(req: ServoConfigRequest):
    cmd = {
        "cmd": "SERVO_CFG",
        "min_ang": req.min_ang,
        "max_ang": req.max_ang,
        "step": req.step,
        "sweep_en": req.sweep_en,
        "hold_ang": req.hold_ang
    }
    success = serial_mgr.send_command(cmd)
    return {"status": "ok" if success else "error", "config": cmd, "sent_to_serial": success}


@app.post("/api/ping")
def ingest_ping(req: IngestPingRequest):
    """Direct HTTP/MQTT ingest endpoint for live wireless ESP32 or MQTT bridge."""
    d1 = req.d1_cm if req.d1_cm is not None else req.d_cm
    d2 = req.d2_cm if req.d2_cm is not None else d1
    v1 = bool(req.valid1 == 1) if req.valid1 is not None else bool(req.valid == 1)
    v2 = bool(req.valid2 == 1) if req.valid2 is not None else v1
    s1 = req.s1_ang if req.s1_ang is not None else req.s_ang
    s2 = req.s2_ang if req.s2_ang is not None else s1

    telemetry = engine.ingest_dual_ping(
        theta_deg=req.angle_deg,
        d1_cm=d1,
        d2_cm=d2,
        valid1=v1,
        valid2=v2,
        s1_ang=s1,
        s2_ang=s2,
        mode=req.mode,
        safety_stop=req.safety_stop,
        imu_detected=req.imu,
        yaw=req.yaw,
        pitch=req.pitch,
        min_ang=req.min_ang,
        max_ang=req.max_ang,
        sweep_dir=req.sweep_dir
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
    # Immediately send current state snapshot so the client renders at once
    try:
        init_snapshot = engine.get_state_snapshot(include_image=True)
        init_snapshot["connection"] = {
            "connected": serial_mgr.is_connected,
            "port": serial_mgr.current_port,
            "is_busy": serial_mgr.is_port_busy,
            "busy_port": serial_mgr.busy_port_name
        }
        await websocket.send_json(init_snapshot)
    except Exception:
        pass

    active_websockets.append(websocket)
    try:
        while True:
            msg = await websocket.receive_json()
            cmd = msg.get("action")
            if cmd == "set_angle":
                serial_mgr.update_pacer_angle(float(msg.get("angle", 90.0)))
            elif cmd == "set_range":
                engine.set_max_range(float(msg.get("max_range_cm", 200.0)))
            elif cmd == "set_pass":
                engine.set_active_pass(msg.get("pass", "pass1"))
            elif cmd == "step_ping":
                ang = float(msg.get("angle", 90.0))
                d = float(msg.get("d_cm", 400.0))
                engine.ingest_ping(ang, d, is_valid=True)
            elif cmd == "scan_cfg":
                cfg = {
                    "cmd": "SCAN_CFG",
                    "mode": msg.get("mode", "STACKED_3D"),
                    "min_ang": int(msg.get("min_ang", 45)),
                    "max_ang": int(msg.get("max_ang", 135)),
                    "step": int(msg.get("step", 3)),
                    "sweep_en": int(msg.get("sweep_en", 1)),
                    "center_90": int(msg.get("center_90", 0))
                }
                serial_mgr.send_command(cfg)
            elif cmd == "center_both_90":
                serial_mgr.send_command({"cmd": "SCAN_CFG", "center_90": 1, "sweep_en": 0})
            elif cmd == "servo_cfg":
                cfg = {
                    "cmd": "SERVO_CFG",
                    "min_ang": int(msg.get("min_ang", 45)),
                    "max_ang": int(msg.get("max_ang", 135)),
                    "step": int(msg.get("step", 3)),
                    "sweep_en": int(msg.get("sweep_en", 1)),
                    "hold_ang": int(msg.get("hold_ang", 90))
                }
                serial_mgr.send_command(cfg)
            elif cmd == "center_servo":
                cfg = {
                    "cmd": "SERVO_CFG",
                    "min_ang": 45,
                    "max_ang": 135,
                    "step": 3,
                    "sweep_en": 0,
                    "hold_ang": 90
                }
                serial_mgr.send_command(cfg)
            elif cmd == "resume_sweep":
                cfg = {
                    "cmd": "SERVO_CFG",
                    "min_ang": int(msg.get("min_ang", 45)),
                    "max_ang": int(msg.get("max_ang", 135)),
                    "step": int(msg.get("step", 3)),
                    "sweep_en": 1,
                    "hold_ang": 90
                }
                serial_mgr.send_command(cfg)
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("bupi_phase1_sonar_test.backend.server:app", host="0.0.0.0", port=8050, reload=False)

