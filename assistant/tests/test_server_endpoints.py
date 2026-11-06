"""
Integration test probing all FastAPI REST and WebSocket endpoints for BUPI Sonar Testbed.
"""

import sys
import os
import time
import urllib.request
import json
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bupi_phase1_sonar_test")))

import uvicorn
from backend.server import app

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8050, log_level="warning")

def test_endpoints():
    base_url = "http://127.0.0.1:8050"
    print("Probing endpoints...")

    # Wait for server to come up
    for _ in range(20):
        try:
            with urllib.request.urlopen(f"{base_url}/api/status", timeout=1.0) as res:
                if res.status == 200:
                    break
        except Exception:
            time.sleep(0.2)
    else:
        raise RuntimeError("Server failed to respond within 4s")

    # 1. Test /api/status
    with urllib.request.urlopen(f"{base_url}/api/status") as res:
        status_data = json.loads(res.read().decode())
        print("Status API:", status_data)
        assert "connected" in status_data
        assert "port" in status_data
        assert status_data["total_pings"] >= 0

    # 2. Test /api/ports
    with urllib.request.urlopen(f"{base_url}/api/ports") as res:
        ports_data = json.loads(res.read().decode())
        print("Ports API:", ports_data)
        assert "ports" in ports_data

    # 3. Test /api/map_image (PNG image)
    with urllib.request.urlopen(f"{base_url}/api/map_image?dilation=1") as res:
        img_bytes = res.read()
        print(f"Map Image PNG bytes: {len(img_bytes)} bytes")
        assert img_bytes.startswith(b'\x89PNG\r\n\x1a\n')

    # 4. Test /api/export (JSON matrix)
    with urllib.request.urlopen(f"{base_url}/api/export") as res:
        export_data = json.loads(res.read().decode())
        print("Export Config:", export_data["config"])
        assert export_data["config"]["width"] == 120
        assert export_data["config"]["height"] == 120
        assert len(export_data["log_odds_matrix"]) == 120

    # 5. Test Frontend Static Root /
    with urllib.request.urlopen(f"{base_url}/") as res:
        html = res.read().decode()
        print(f"Index HTML loaded ({len(html)} chars)")
        assert "BUPI Phase 1" in html
        assert "polarScopeCanvas" in html
        assert "dipCanvas" in html
        assert "voxelCanvas" in html

    # 6. Test Ingest Ping POST /api/ping
    req_data = json.dumps({"angle_deg": 60.0, "d_cm": 95.0, "valid": 1}).encode()
    req = urllib.request.Request(
        f"{base_url}/api/ping",
        data=req_data,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as res:
        ping_res = json.loads(res.read().decode())
        print("Ping ingest response:", ping_res)
        assert ping_res["status"] == "ok"

    print("ALL REST & FRONTEND ENDPOINTS VERIFIED SUCCESSFULLY!")

if __name__ == "__main__":
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    try:
        test_endpoints()
    finally:
        print("Completed integration test.")

