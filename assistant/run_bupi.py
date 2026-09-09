#!/usr/bin/env python3
"""
BUPI Autonomous Sensor-Fusion System — Central Orchestrator & UI Server
========================================================================
Runs the 20Hz closed-loop goal execution pipeline:
User Command -> Intent Parser -> Goal Manager -> Planner -> Sensor Fusion -> Safety Layer -> Motors

Serves the interactive Demo Dashboard and 2D Arena Simulation at http://localhost:8080
"""

import os
import sys
import json
import time
import asyncio
import logging
from typing import Set

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from sensors import PIRSensor, UltrasonicSensor, MPU6050Sensor, SensorFusion
from motion import DifferentialDrive, MotorPins
from intent import IntentParser, HighLevelIntent
from planner import StateManager, GoalManager, AutonomousPlanner, StructuredAction
from safety import SafetyController
from communication import BupiBridge

import websockets
from http.server import SimpleHTTPRequestHandler
import socketserver
import threading

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("BUPI_MASTER")

class BupiEngine:
    def __init__(self):
        # 1. Sensors
        self.pir = PIRSensor(pin=19)
        self.ultrasonic = UltrasonicSensor(trig_pin=5, echo_pin=18)
        self.imu = MPU6050Sensor(sda_pin=21, scl_pin=22)
        self.sensor_fusion = SensorFusion(self.pir, self.ultrasonic, self.imu)

        # 2. Motion & Actuation
        self.drive = DifferentialDrive(MotorPins())

        # 3. Intent & Goals
        self.intent_parser = IntentParser()
        self.goal_mgr = GoalManager()

        # 4. State & Planner
        self.state_mgr = StateManager()
        self.planner = AutonomousPlanner(self.state_mgr, self.goal_mgr)

        # 5. Safety Controller (unconditional override gate)
        self.safety = SafetyController(
            safe_distance_cm=40.0,
            warning_distance_cm=25.0,
            critical_distance_cm=15.0
        )

        # 6. Communication & Arena Simulator
        self.bridge = BupiBridge(use_simulation=True)

        self.is_running = True
        self.active_action: Optional[StructuredAction] = None
        self.last_pipeline_snapshot = {}
        self.connected_clients: Set[websockets.WebSocketServerProtocol] = set()

    def process_command(self, natural_language_text: str) -> Dict[str, Any]:
        """
        Accepts single high-level user command and activates autonomous goal.
        """
        logger.info(f"Received high-level command: '{natural_language_text}'")
        goal = self.intent_parser.parse(natural_language_text)
        mission = self.goal_mgr.start_mission(goal)
        self.state_mgr.set_goal(goal.intent.value, mode="SEARCHING" if goal.intent == HighLevelIntent.SEARCH_FOR_PRESENCE else "ACTIVE")

        logger.info(f"Identified Intent: {goal.intent.value} (Confidence: {goal.confidence:.2f})")
        logger.info(f"Required Capabilities: {goal.relevant_capabilities}")

        return {
            "intent": goal.intent.value,
            "goal": goal.goal_description,
            "confidence": goal.confidence,
            "capabilities": goal.relevant_capabilities
        }

    async def step_cycle(self, dt: float):
        """
        One complete 50ms tick of the Closed-Loop Pipeline.
        """
        # 1. READ RAW SENSORS (from Arena Sim or Physical ESP32)
        raw_data = self.bridge.get_latest_sensor_data()
        self.pir.update_raw(raw_data["pir_pin"])
        self.ultrasonic.update_distance(raw_data["distance_cm"])
        imu_d = raw_data["imu"]
        self.imu.update_telemetry(
            imu_d["ax"], imu_d["ay"], imu_d["az"],
            imu_d["gx"], imu_d["gy"], imu_d["gz"]
        )

        # 2. SENSOR FUSION & EPISTEMIC LADDER
        fusion_res = self.sensor_fusion.evaluate()
        self.state_mgr.update_from_fusion(fusion_res)

        # 3. PLANNER DECISION
        raw_planned_action = self.planner.plan_next_action(fusion_res)

        # 4. HARDWARE SAFETY SUPERVISOR (Override Gatekeeper)
        safe_action = self.safety.validate_and_filter(raw_planned_action, fusion_res)
        self.active_action = safe_action

        # 5. MOTOR ACTUATION
        motor_sig = self.drive.execute_action(
            action=safe_action.action,
            speed_percent=safe_action.speed,
            duration_ms=safe_action.duration_ms,
            reason=safe_action.reason
        )

        # 6. UPDATE SIMULATION PHYSICS (if in sim mode)
        if self.bridge.use_simulation:
            self.bridge.arena.update_physics(
                motor_action=safe_action.action,
                speed_percent=safe_action.speed,
                dt=dt
            )

        # Build telemetry snapshot for UI
        self.last_pipeline_snapshot = {
            "type": "telemetry_update",
            "timestamp": time.time(),
            "goal": self.goal_mgr.get_mission_info(),
            "state": self.state_mgr.get_state().to_dict(),
            "epistemic_ladder": fusion_res["epistemic_ladder"],
            "fusion_inference": fusion_res["inference"],
            "planner_action": raw_planned_action.to_dict(),
            "safe_action": safe_action.to_dict(),
            "safety_status": self.safety.get_status(),
            "arena": self.bridge.arena.get_arena_state() if self.bridge.use_simulation else None,
            "simulation_mode": self.bridge.use_simulation
        }

    async def broadcast_telemetry(self):
        if not self.connected_clients or not self.last_pipeline_snapshot:
            return
        payload = json.dumps(self.last_pipeline_snapshot)
        disconnected = set()
        for ws in list(self.connected_clients):
            try:
                await ws.send(payload)
            except Exception:
                disconnected.add(ws)
        if disconnected:
            self.connected_clients.difference_update(disconnected)

async def handle_websocket(websocket, engine: BupiEngine):
    engine.connected_clients.add(websocket)
    logger.info(f"Client connected. Total clients: {len(engine.connected_clients)}")
    try:
        async for message in websocket:
            try:
                msg = json.loads(message)
                msg_type = msg.get("type")

                if msg_type == "command":
                    text = msg.get("text", "")
                    engine.process_command(text)

                elif msg_type == "move_human":
                    h_id = msg.get("id", "person_1")
                    x = float(msg.get("x", 250))
                    y = float(msg.get("y", 200))
                    engine.bridge.arena.set_human_position(h_id, x, y)

                elif msg_type == "move_obstacle":
                    obs_id = msg.get("id", "box_1")
                    x = float(msg.get("x", 200))
                    y = float(msg.get("y", 150))
                    engine.bridge.arena.set_obstacle_position(obs_id, x, y)

                elif msg_type == "inject_obstacle":
                    dist = float(msg.get("distance_cm", 12.0))
                    engine.bridge.arena.spawn_obstacle_in_front(dist)
                    engine.ultrasonic.update_distance(dist)

                elif msg_type == "toggle_mode":
                    mode = msg.get("mode", "simulation")
                    engine.bridge.use_simulation = (mode == "simulation")
                    logger.info(f"Switched mode to: {mode}")

            except Exception as e:
                logger.error(f"Error handling message: {e}")
    except Exception as err:
        logger.debug(f"Websocket connection ended: {err}")
    finally:
        engine.connected_clients.discard(websocket)
        logger.info("Client disconnected.")

def start_http_server(port=8080):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=PROJECT_ROOT, **kwargs)
        def do_GET(self):
            if self.path in ["/", "/index.html"]:
                self.path = "/notepad.html"
            return super().do_GET()
        def log_message(self, format, *args):
            pass # suppress verbose logs

    socketserver.TCPServer.allow_reuse_address = True
    server = socketserver.TCPServer(("", port), Handler)
    logger.info(f"Bupi Hub Dashboard HTTP Server running at http://localhost:{port}")
    server.serve_forever()

async def main():
    engine = BupiEngine()
    
    # Start HTTP static file server in background thread
    http_thread = threading.Thread(target=start_http_server, args=(8080,), daemon=True)
    http_thread.start()

    # WebSocket server on port 8767
    ws_server = await websockets.serve(
        lambda ws: handle_websocket(ws, engine),
        "0.0.0.0",
        8767
    )
    logger.info("BUPI Telemetry WebSocket Server listening on ws://localhost:8767")

    # Initial default command
    engine.process_command("BUPI, find a person in this room.")

    last_tick = time.time()
    while engine.is_running:
        now = time.time()
        dt = max(0.01, min(now - last_tick, 0.1))
        last_tick = now

        await engine.step_cycle(dt)
        await engine.broadcast_telemetry()
        await asyncio.sleep(0.05) # 20 Hz loop

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown requested.")
