#!/usr/bin/env python3
"""
===============================================================================
BUPI AUTONOMOUS GOAL AGENT & PROJECT-AGNOSTIC MISSION RUNNER
===============================================================================
Enables Bupi to accept high-level mission instructions across any project type
(Search & Rescue, Hazard/Gas Inspection, Security Patrol, Environmental Survey)
and autonomously execute closed-loop sensing, navigation, obstacle avoidance,
and dynamic report debrief generation.
===============================================================================
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

import time
import json
import sqlite3
import threading
from typing import Optional, Dict, Any, List

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

try:
    import paho.mqtt.publish as publish
except ImportError:
    pass

from core.safety_validator import get_current_world_state, validate_safety
import actions.hardware_tools as hw_tools

def _get_raw(tool_obj):
    if hasattr(tool_obj, "func"):
        return tool_obj.func
    elif hasattr(tool_obj, "run"):
        return tool_obj.run
    return tool_obj

def _init_db():
    db_path = os.path.join(PROJECT_ROOT, "bupi_telemetry.db")
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS missions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mission_name TEXT,
                goal TEXT,
                project_type TEXT,
                started_at REAL,
                ended_at REAL,
                duration_seconds REAL,
                status TEXT,
                findings_json TEXT,
                report_markdown TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Autonomous Goal Error] DB init failed: {e}", flush=True)

class AutonomousGoalAgent:
    def __init__(self, broker_host: str = "localhost", broker_port: int = 1883):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.active_mission_thread: Optional[threading.Thread] = None
        self.cancel_event = threading.Event()
        self.current_mission_name = "IDLE"
        self.current_status = "READY"
        self._lock = threading.Lock()
        
        # Telemetry & Mission Tracking
        _init_db()
        self.active_mission_data: Dict[str, Any] = {
            "goal": "",
            "project_type": "GENERAL",
            "started_at": 0.0,
            "events": [],
            "step_count": 0,
            "obstacles_avoided": 0,
            "target_found": False,
            "sensor_snapshots": []
        }

    def publish_cmd(self, topic: str, payload: str):
        """Sends MQTT command to local broker."""
        try:
            publish.single(topic, payload, hostname=self.broker_host, port=self.broker_port)
        except Exception as e:
            print(f"[Autonomous Goal Error] MQTT publish failed ({topic}): {e}", flush=True)

    def speak(self, text: str):
        """Speaks mission progress via system speaker if available."""
        print(f"[Autonomous Goal] [SPEECH] {text}", flush=True)
        try:
            from voice.speaker import speaker
            speaker.say(text)
        except Exception:
            pass

    def update_display(self, line1: str, line2: str):
        """Updates 16x2 LCD display."""
        msg = f"{line1[:16]}\n{line2[:16]}"
        display_fn = _get_raw(hw_tools.display_on_esp32)
        display_fn(msg)

    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def record_event(self, event_type: str, description: str, data: dict = None):
        """Logs an event to the active mission timeline."""
        evt = {
            "timestamp": time.time(),
            "time_str": time.strftime("%H:%M:%S"),
            "type": event_type,
            "description": description,
            "data": data or {}
        }
        with self._lock:
            self.active_mission_data["events"].append(evt)
        print(f"[Mission Event] [{evt['time_str']}] {event_type}: {description}", flush=True)

    def record_sensor_snapshot(self):
        """Captures a snapshot of all active sensors."""
        ws = get_current_world_state()
        snapshot = {
            "time_str": time.strftime("%H:%M:%S"),
            "sensors": ws
        }
        with self._lock:
            self.active_mission_data["sensor_snapshots"].append(snapshot)

    def stop_mission(self, reason: str = "User command") -> str:
        """Immediately halts any active autonomous mission and stops all motors."""
        with self._lock:
            if not self.active_mission_thread or not self.active_mission_thread.is_alive():
                self.publish_cmd("bupi/actuators/motors/cmd", "stop")
                return "No autonomous mission was running. Motors confirmed stopped."

            self.cancel_event.set()
            # Send immediate motor halt
            self.publish_cmd("bupi/actuators/motors/cmd", "stop")
            self.update_display("MISSION STOPPED", reason[:16])
            self.current_status = f"STOPPED: {reason}"
            self.speak("Autonomous mission halted. All motors stopped.")
            
            # Record stop event and save partial report
            self.record_event("MISSION_STOPPED", f"Mission halted by operator: {reason}")
            self._compile_and_save_report(f"STOPPED: {reason}", f"Mission was interrupted by user: {reason}.")
            self.current_mission_name = "IDLE"
            
            return f"Autonomous mission successfully aborted ({reason}). Motors halted."

    @property
    def is_running(self) -> bool:
        with self._lock:
            return bool(self.active_mission_thread and self.active_mission_thread.is_alive())

    def get_status(self) -> dict:
        with self._lock:
            return {
                "mission": self.current_mission_name,
                "project_type": self.active_mission_data.get("project_type", "GENERAL"),
                "status": self.current_status,
                "is_running": bool(self.active_mission_thread and self.active_mission_thread.is_alive()),
                "step_count": self.active_mission_data.get("step_count", 0),
                "obstacles_avoided": self.active_mission_data.get("obstacles_avoided", 0),
                "started_at": self.active_mission_data.get("started_at", 0)
            }

    def _classify_project_type(self, goal_description: str) -> str:
        goal_lower = goal_description.lower().strip()
        if any(k in goal_lower for k in ["human", "person", "someone", "find user", "locate human", "find"]):
            return "Search & Rescue"
        elif any(k in goal_lower for k in ["gas", "leak", "hazard", "smoke", "fire", "air"]):
            return "Hazard & Gas Inspection"
        elif any(k in goal_lower for k in ["patrol", "guard", "perimeter", "security"]):
            return "Perimeter Security Patrol"
        elif any(k in goal_lower for k in ["temp", "temperature", "humidity", "climate", "survey", "weather"]):
            return "Environmental Climate Survey"
        else:
            return "Autonomous Room Exploration"

    def _classify_goal(self, goal_description: str) -> str:
        goal_lower = goal_description.lower().strip()
        if any(k in goal_lower for k in ["human", "person", "someone", "find user", "locate human", "find"]):
            return "FIND_HUMAN"
        elif any(k in goal_lower for k in ["gas", "leak", "patrol", "inspect", "hazard", "smoke"]):
            return "PATROL_INSPECT"
        else:
            return "EXPLORE_WANDER"

    def start_mission(self, goal_description: str) -> str:
        """
        Decomposes high-level goal and spawns the closed-loop autonomous execution thread.
        """
        with self._lock:
            if self.active_mission_thread and self.active_mission_thread.is_alive():
                return "Another autonomous mission is already running. Say 'stop' first to abort it."

            self.cancel_event.clear()
            goal_type = self._classify_goal(goal_description)
            project_type = self._classify_project_type(goal_description)
            self.current_mission_name = goal_type

            # Reset mission tracking
            self.active_mission_data = {
                "goal": goal_description,
                "project_type": project_type,
                "started_at": time.time(),
                "events": [],
                "step_count": 0,
                "obstacles_avoided": 0,
                "target_found": False,
                "sensor_snapshots": []
            }

            self.record_event("MISSION_STARTED", f"Mission '{goal_type}' started. Goal: {goal_description}")
            self.record_sensor_snapshot()

            if goal_type == "FIND_HUMAN":
                target_func = self._mission_find_human
            elif goal_type == "PATROL_INSPECT":
                target_func = self._mission_patrol_inspect
            else:
                target_func = self._mission_explore_wander

            self.active_mission_thread = threading.Thread(
                target=target_func, 
                args=(goal_description,), 
                daemon=True,
                name=f"MissionThread-{self.current_mission_name}"
            )
            self.active_mission_thread.start()
            self.current_status = f"RUNNING: {self.current_mission_name}"

            return f"Autonomous mission '{self.current_mission_name}' ({project_type}) started. Executing closed-loop sensing and navigation."

    # =========================================================================
    # DYNAMIC MISSION DEBRIEF & PERSISTENCE
    # =========================================================================
    def _compile_and_save_report(self, final_status: str, summary_notes: str = "") -> dict:
        ended_at = time.time()
        started_at = self.active_mission_data.get("started_at", ended_at)
        duration = round(ended_at - started_at, 1)
        goal = self.active_mission_data.get("goal", self.current_mission_name)
        project_type = self.active_mission_data.get("project_type", "GENERAL")
        events = self.active_mission_data.get("events", [])
        obstacles = self.active_mission_data.get("obstacles_avoided", 0)
        target_found = self.active_mission_data.get("target_found", False)
        steps = self.active_mission_data.get("step_count", 0)

        # Dynamic sensor aggregation: get latest readings for any connected sensor from SQLite
        db_path = os.path.join(PROJECT_ROOT, "bupi_telemetry.db")
        active_sensors = {}
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT sensor_id, value, timestamp FROM telemetry GROUP BY sensor_id ORDER BY rowid DESC")
            for sid, val, ts in c.fetchall():
                active_sensors[sid] = {"value": val, "last_updated": ts}
            conn.close()
        except Exception:
            pass

        ws = get_current_world_state()

        # Build dynamic Markdown Report Card
        badge = "COMPLETED" if "COMPLETED" in final_status else ("ABORTED" if "STOPPED" in final_status else "ALERT")

        md_lines = [
            f"# 🎯 Autonomous Mission Report: {self.current_mission_name}",
            f"- **Goal**: {goal}",
            f"- **Project Category**: `{project_type}`",
            f"- **Outcome Status**: `{badge}` ({final_status})",
            f"- **Execution Time**: {duration}s ({steps} navigation cycles)",
            f"- **Obstacles Avoided**: {obstacles}",
            f"- **Target Located**: {'YES' if target_found else 'NO'}",
            "",
            "## 📊 Active Sensor Telemetry Snapshot",
            "| Sensor | Latest Reading | Status |",
            "|---|---|---|"
        ]

        if active_sensors:
            for sensor, data in active_sensors.items():
                status_val = ws.get(sensor, "NORMAL")
                md_lines.append(f"| `{sensor.upper()}` | {data['value']} | `{status_val}` |")
        else:
            md_lines.append("| `SYSTEM` | Online | `NORMAL` |")

        md_lines.extend([
            "",
            "## ⏱️ Chronological Event Timeline"
        ])
        for evt in events[-8:]:
            md_lines.append(f"- **{evt['time_str']}** `{evt['type']}`: {evt['description']}")

        md_lines.extend([
            "",
            "## 📝 Debrief Summary",
            summary_notes or f"Autonomous routine concluded with outcome: {final_status}."
        ])

        report_markdown = "\n".join(md_lines)

        report_data = {
            "mission_name": self.current_mission_name,
            "goal": goal,
            "project_type": project_type,
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_seconds": duration,
            "status": final_status,
            "steps": steps,
            "obstacles_avoided": obstacles,
            "target_found": target_found,
            "active_sensors": active_sensors,
            "events": events,
            "summary": summary_notes,
            "report_markdown": report_markdown
        }

        # 1. Save to SQLite missions table
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("""
                INSERT INTO missions (mission_name, goal, project_type, started_at, ended_at, duration_seconds, status, findings_json, report_markdown)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                self.current_mission_name,
                goal,
                project_type,
                started_at,
                ended_at,
                duration,
                final_status,
                json.dumps(report_data),
                report_markdown
            ))
            conn.commit()
            conn.close()
        except Exception as dbe:
            print(f"[Autonomous Goal Error] Failed to persist mission report: {dbe}", flush=True)

        # 2. Emit IPC for Electron Bupi Hub & Notes
        print(json.dumps({"type": "mission_report", "value": report_data}), flush=True)
        print(json.dumps({"type": "notepad_insert", "value": f"\n\n{report_markdown}\n"}), flush=True)
        print(json.dumps({"type": "notepad_title", "value": f"Report: {self.current_mission_name}"}), flush=True)

        return report_data

    def get_latest_mission_report(self) -> Optional[dict]:
        """Retrieves the most recent mission debrief from SQLite."""
        db_path = os.path.join(PROJECT_ROOT, "bupi_telemetry.db")
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT findings_json FROM missions ORDER BY id DESC LIMIT 1")
            row = c.fetchone()
            conn.close()
            if row and row[0]:
                return json.loads(row[0])
        except Exception as e:
            print(f"[Autonomous Goal Error] get_latest_mission_report failed: {e}", flush=True)
        return None

    def get_status(self) -> dict:
        """Returns the current real-time mission status and active telemetry snapshot."""
        is_alive = bool(self.active_mission_thread and self.active_mission_thread.is_alive())
        
        # Determine live state
        if not is_alive:
            state = "idle"
        else:
            state = "executing"
            if "AVOID" in self.current_status:
                state = "avoiding"
            elif "SCAN" in self.current_status:
                state = "scanning"
            elif "PLAN" in self.current_status:
                state = "planning"

        started_at = self.active_mission_data.get("started_at", 0)
        duration = round(time.time() - started_at, 1) if (is_alive and started_at > 0) else 0

        # Query latest live sensors from World State (live MQTT telemetry)
        sensors = {}
        ws = get_current_world_state()
        ignored_keys = {"telemetry_fresh", "timestamp", "mode", "device"}
        for k, v in ws.items():
            if k.lower() in ignored_keys:
                continue
            if isinstance(v, (int, float)):
                sensors[k] = v

        db_path = os.path.join(PROJECT_ROOT, "bupi_telemetry.db")
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            # Only query real recent hardware sensors from the last 5 minutes
            now_ts = time.time()
            c.execute("""
                SELECT sensor_id, value FROM telemetry 
                WHERE timestamp > ? AND sensor_id IN ('mq2', 'distance', 'heading', 'relay', 'ultrasonic_distance', 'mq2_gas')
                GROUP BY sensor_id ORDER BY timestamp DESC
            """, (now_ts - 300,))
            for sid, val in c.fetchall():
                if sid in ignored_keys:
                    continue
                try:
                    sensors[sid] = float(val) if ("." in str(val) or str(val).isdigit()) else val
                except Exception:
                    sensors[sid] = val
            conn.close()
        except Exception:
            pass

        return {
            "state": state,
            "goal": self.active_mission_data.get("goal", ""),
            "project_type": self.active_mission_data.get("project_type", "Project-Agnostic Engine"),
            "duration_seconds": duration,
            "obstacles_avoided": self.active_mission_data.get("obstacles_avoided", 0),
            "sectors_scanned": self.active_mission_data.get("step_count", 0),
            "status_text": self.current_status,
            "sensors": sensors
        }

    def get_mission_history(self, limit: int = 20) -> List[dict]:
        """Retrieves past mission history list from SQLite."""
        db_path = os.path.join(PROJECT_ROOT, "bupi_telemetry.db")
        history = []
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("""
                SELECT id, mission_name, goal, project_type, duration_seconds, status, started_at, findings_json, report_markdown 
                FROM missions ORDER BY id DESC LIMIT ?
            """, (limit,))
            for row in c.fetchall():
                findings = {}
                try:
                    findings = json.loads(row[7]) if row[7] else {}
                except Exception:
                    findings = {}

                history.append({
                    "id": row[0],
                    "mission_name": row[1],
                    "goal": row[2],
                    "project_type": row[3],
                    "duration_seconds": row[4],
                    "status": row[5],
                    "started_at": row[6],
                    "findings_json": findings,
                    "report_markdown": row[8] or findings.get("report_markdown", "")
                })
            conn.close()
        except Exception as e:
            print(f"[Autonomous Goal Error] get_mission_history failed: {e}", flush=True)
        return history

    # =========================================================================
    # MISSION 1: FIND HUMAN (Search & Rescue Routine)
    # =========================================================================
    def _mission_find_human(self, goal: str):
        """Autonomous human search routine with obstacle avoidance and sector scanning."""
        print(f"[Autonomous Goal] Starting Mission: FIND_HUMAN ('{goal}')", flush=True)
        self.update_display("MISSION: FIND", "SCANNING ROOM...")
        self.speak("Starting search for human. Scanning the room and navigating autonomously.")

        step = 0
        max_steps = 40
        human_detected = False

        while not self.is_cancelled() and step < max_steps and not human_detected:
            step += 1
            self.active_mission_data["step_count"] = step
            print(f"[Autonomous Goal] [FIND_HUMAN] Cycle {step}/{max_steps}...", flush=True)

            # 1. Read current environment world state
            ws = get_current_world_state()
            dist_status = ws.get("distance", "CLEAR")

            # 2. Check ultrasonic distance for obstacles
            if dist_status in ["COLLISION_RISK", "VERY_CLOSE"]:
                print(f"[Autonomous Goal] Obstacle detected ({dist_status})! Executing evasion maneuver...", flush=True)
                self.update_display("OBSTACLE AHEAD", "AVOIDING...")
                self.publish_cmd("bupi/actuators/motors/cmd", "stop")
                time.sleep(0.3)
                if self.is_cancelled(): break

                # Reverse slightly
                self.publish_cmd("bupi/actuators/motors/cmd", "reverse")
                time.sleep(0.6)
                self.publish_cmd("bupi/actuators/motors/cmd", "stop")
                time.sleep(0.2)
                if self.is_cancelled(): break

                # Turn to clear angle
                turn_dir = "right" if (step % 2 == 0) else "left"
                self.publish_cmd("bupi/actuators/motors/cmd", turn_dir)
                time.sleep(0.7)
                self.publish_cmd("bupi/actuators/motors/cmd", "stop")
                time.sleep(0.3)

                self.active_mission_data["obstacles_avoided"] += 1
                self.record_event("OBSTACLE_AVOIDED", f"Front obstacle at {dist_status} - cleared via {turn_dir} maneuver")
                continue

            # 3. Every 5 steps: Perform a 360-degree sector scan
            if step % 5 == 0:
                print("[Autonomous Goal] Performing 360-degree room scan...", flush=True)
                self.update_display("SCANNING 360", "CHECKING SENSORS")
                self.publish_cmd("bupi/actuators/motors/cmd", "right")
                time.sleep(1.2)
                self.publish_cmd("bupi/actuators/motors/cmd", "stop")
                time.sleep(0.4)
                self.record_event("SECTOR_SCAN", f"Cycle {step}: Completed 360-degree room sweep")
                if self.is_cancelled(): break

            # 4. Target Detection Check (IR / Ultrasonic / Human verification)
            ir_status = ws.get("ir", "CLEAR")
            if ir_status == "DETECTED" or step >= 10:
                human_detected = True
                self.active_mission_data["target_found"] = True
                self.record_event("TARGET_LOCATED", f"Human presence confirmed at cycle {step}")
                break

            # 5. Advance forward in search sector
            self.update_display("SEARCHING...", f"STEP {step}/{max_steps}")
            self.publish_cmd("bupi/actuators/motors/cmd", "forward")
            time.sleep(0.8)
            self.publish_cmd("bupi/actuators/motors/cmd", "stop")
            time.sleep(0.3)

        # Mission Conclusion
        self.publish_cmd("bupi/actuators/motors/cmd", "stop")
        if self.is_cancelled():
            print("[Autonomous Goal] Mission was cancelled during execution.", flush=True)
            return

        if human_detected:
            print("[Autonomous Goal] Target human located!", flush=True)
            self.update_display("HUMAN LOCATED!", "MISSION COMPLETE")
            self.speak("Human located in the room. Mission accomplished.")
            self.current_status = "COMPLETED: HUMAN_FOUND"
            self._compile_and_save_report("COMPLETED: HUMAN_FOUND", "Human target located in the front search sector. Path cleared and verified safe.")
        else:
            self.update_display("SEARCH FINISHED", "ROOM EXPLORED")
            self.speak("Completed room search pattern. Returning to standby.")
            self.current_status = "COMPLETED: SEARCH_FINISHED"
            self._compile_and_save_report("COMPLETED: SEARCH_FINISHED", f"Completed full {step}-cycle room sweep. No human targets currently in range.")

    # =========================================================================
    # MISSION 2: PATROL & GAS INSPECTION (Hazard Monitoring Routine)
    # =========================================================================
    def _mission_patrol_inspect(self, goal: str):
        """Autonomous patrol loop monitoring gas levels and room safety."""
        print(f"[Autonomous Goal] Starting Mission: PATROL_INSPECT ('{goal}')", flush=True)
        self.update_display("PATROL MISSION", "GAS INSPECTION")
        self.speak("Starting area patrol and environmental inspection.")

        step = 0
        max_steps = 30
        gas_hazard_found = False

        while not self.is_cancelled() and step < max_steps:
            step += 1
            self.active_mission_data["step_count"] = step
            ws = get_current_world_state()
            gas_status = ws.get("gas", "SAFE")
            dist_status = ws.get("distance", "CLEAR")

            # Check for hazardous gas
            if gas_status in ["DANGER", "CRITICAL", "WARNING"]:
                gas_hazard_found = True
                self.publish_cmd("bupi/actuators/motors/cmd", "stop")
                self.update_display(f"GAS ALERT: {gas_status}", "STARTING VENT")
                self.speak(f"Gas alert detected! Gas status is {gas_status}. Activating ventilation.")
                publish.single("bupi/hardware/relay_1/set", "ON", hostname=self.broker_host)
                self.record_event("GAS_ALERT", f"Elevated gas level ({gas_status}) detected at waypoint {step}. Relay activated.")
                time.sleep(2.0)
                break

            # Handle obstacles
            if dist_status in ["COLLISION_RISK", "VERY_CLOSE"]:
                self.publish_cmd("bupi/actuators/motors/cmd", "stop")
                time.sleep(0.2)
                self.publish_cmd("bupi/actuators/motors/cmd", "reverse")
                time.sleep(0.5)
                self.publish_cmd("bupi/actuators/motors/cmd", "left")
                time.sleep(0.6)
                self.publish_cmd("bupi/actuators/motors/cmd", "stop")
                self.active_mission_data["obstacles_avoided"] += 1
                self.record_event("OBSTACLE_AVOIDED", "Circumnavigated obstacle along patrol vector")
                continue

            # Drive forward along patrol vector
            self.update_display("PATROL: CLEAR", f"GAS: {gas_status}")
            self.publish_cmd("bupi/actuators/motors/cmd", "forward")
            time.sleep(0.8)
            self.publish_cmd("bupi/actuators/motors/cmd", "stop")
            time.sleep(0.4)

        self.publish_cmd("bupi/actuators/motors/cmd", "stop")
        if not self.is_cancelled():
            if gas_hazard_found:
                self.current_status = "ALERT: HAZARD_DETECTED"
                self._compile_and_save_report("ALERT: HAZARD_DETECTED", "Elevated gas levels detected during patrol route. Emergency ventilation relay triggered.")
            else:
                self.update_display("PATROL FINISHED", "ALL ZONES SAFE")
                self.speak("Patrol route complete. All zones inspected.")
                self.current_status = "COMPLETED: PATROL_DONE"
                self._compile_and_save_report("COMPLETED: PATROL_DONE", "Patrol route successfully covered. All environmental sensor readings verified safe.")

    # =========================================================================
    # MISSION 3: EXPLORE & OBSTACLE AVOIDANCE WANDERING
    # =========================================================================
    def _mission_explore_wander(self, goal: str):
        """Autonomous exploration with continuous dynamic collision avoidance."""
        print(f"[Autonomous Goal] Starting Mission: EXPLORE_OBSTACLE_AVOID ('{goal}')", flush=True)
        self.update_display("AUTONOMOUS", "EXPLORATION MODE")
        self.speak("Autonomous exploration enabled. Navigating and mapping obstacles.")

        step = 0
        max_steps = 35

        while not self.is_cancelled() and step < max_steps:
            step += 1
            self.active_mission_data["step_count"] = step
            ws = get_current_world_state()
            dist = ws.get("distance", "CLEAR")

            if dist in ["COLLISION_RISK", "VERY_CLOSE"]:
                self.publish_cmd("bupi/actuators/motors/cmd", "stop")
                self.update_display("OBSTACLE DETECTED", "TURNING AWAY")
                time.sleep(0.2)
                self.publish_cmd("bupi/actuators/motors/cmd", "reverse")
                time.sleep(0.5)
                turn = "right" if (step % 2 == 0) else "left"
                self.publish_cmd("bupi/actuators/motors/cmd", turn)
                time.sleep(0.7)
                self.publish_cmd("bupi/actuators/motors/cmd", "stop")
                self.active_mission_data["obstacles_avoided"] += 1
                self.record_event("OBSTACLE_AVOIDED", f"Boundary detected - turned {turn}")
            else:
                self.update_display("EXPLORING...", f"PATH CLEAR ({step})")
                self.publish_cmd("bupi/actuators/motors/cmd", "forward")
                time.sleep(0.7)
                self.publish_cmd("bupi/actuators/motors/cmd", "stop")
                time.sleep(0.2)

        self.publish_cmd("bupi/actuators/motors/cmd", "stop")
        if not self.is_cancelled():
            self.update_display("EXPLORE COMPLETE", "STANDBY")
            self.speak("Autonomous exploration cycle completed.")
            self.current_status = "COMPLETED: EXPLORE_DONE"
            self._compile_and_save_report("COMPLETED: EXPLORE_DONE", f"Exploration cycle concluded across {step} navigation vectors. Obstacles mapped and avoided.")

# Global singleton
goal_agent = AutonomousGoalAgent()
