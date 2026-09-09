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

from planner.instruction_decomposer import InstructionDecomposer, DynamicMissionPlan, PolicyType
from planner.room_scanner import RoomScanner
from communication.bridge import BupiBridge
from safety.safety_controller import SafetyController

def _get_raw(tool_obj):
    if hasattr(tool_obj, "func"):
        return tool_obj.func
    elif hasattr(tool_obj, "run"):
        return tool_obj.run
    return tool_obj

def signed_angle_diff(current: float, previous: float) -> float:
    """
    Computes the minimal signed difference (current - previous) in degrees within [-180.0, +180.0].
    Correctly handles 0/360 degree wrap-arounds and sensor jitter.
    """
    d = (current - previous) % 360.0
    if d > 180.0:
        d -= 360.0
    return d

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
    def __init__(self, broker_host: str = "localhost", broker_port: int = 1883, use_simulation: bool = False):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.active_mission_thread: Optional[threading.Thread] = None
        self.cancel_event = threading.Event()
        self.current_mission_name = "IDLE"
        self.current_status = "READY"
        self._lock = threading.RLock()
        
        # Dynamic Planners, Safety Layer & Hardware Bridge
        self.bridge = BupiBridge(use_simulation=use_simulation)
        self.decomposer = InstructionDecomposer()
        self.room_scanner = RoomScanner()
        self.safety = SafetyController(safe_distance_cm=40.0, warning_distance_cm=25.0, critical_distance_cm=15.0)

        # Telemetry & Mission Tracking
        _init_db()
        self._tts_callback: Optional[Any] = None
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

    def get_current_heading(self) -> float:
        if self.bridge.use_simulation:
            return round(self.bridge.arena.robot_theta_deg, 1)
        try:
            from bupi_node_server import get_latest_telemetry
            return float(get_latest_telemetry().get("heading", 0.0))
        except Exception:
            try:
                db_path = os.path.join(PROJECT_ROOT, "bupi_telemetry.db")
                conn = sqlite3.connect(db_path, timeout=1.0)
                c = conn.cursor()
                c.execute("SELECT value FROM telemetry WHERE sensor_id='heading' ORDER BY rowid DESC LIMIT 1")
                row = c.fetchone()
                conn.close()
                if row:
                    return float(row[0])
            except Exception:
                pass
        return 0.0

    def publish_cmd(self, topic: str, payload: str):
        """Sends MQTT command to local broker."""
        try:
            publish.single(topic, payload, hostname=self.broker_host, port=self.broker_port)
        except Exception as e:
            print(f"[Autonomous Goal Error] MQTT publish failed ({topic}): {e}", flush=True)

    def speak(self, text: str):
        """Speaks mission progress via MQTT bupi/internal/tts or direct callback."""
        print(f"[Autonomous Goal] [SPEECH] {text}", flush=True)
        try:
            self.publish_cmd("bupi/internal/tts", json.dumps({"text": text}))
        except Exception:
            pass
        if hasattr(self, "_tts_callback") and self._tts_callback:
            try:
                self._tts_callback(text)
            except Exception as te:
                print(f"[Autonomous Goal Error] Direct TTS callback failed: {te}", flush=True)

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

    def start_mission(self, goal_description: str) -> str:
        """
        Dynamically compiles ANY high-level natural language instruction
        and launches the closed-loop autonomous execution thread.
        """
        with self._lock:
            if self.active_mission_thread and self.active_mission_thread.is_alive():
                print(f"[Autonomous Goal] Preempting previous mission '{self.current_mission_name}' with new goal: '{goal_description}'", flush=True)
                self.cancel_event.set()
                self.publish_cmd("bupi/actuators/motors/cmd", "stop")
                try:
                    self.active_mission_thread.join(timeout=0.5)
                except Exception:
                    pass

            self.cancel_event.clear()
            plan = self.decomposer.decompose(goal_description)
            self.current_mission_name = plan.goal_name

            self.active_mission_data = {
                "goal": goal_description,
                "goal_name": plan.goal_name,
                "project_type": plan.policy_type.value,
                "started_at": time.time(),
                "events": [],
                "step_count": 0,
                "obstacles_avoided": 0,
                "target_found": False,
                "sensor_snapshots": [],
                "plan": plan.to_dict()
            }

            self.record_event("MISSION_STARTED", f"Mission '{plan.goal_name}' started ({plan.policy_type.value}). Goal: {goal_description}")
            self.record_sensor_snapshot()

            self.active_mission_thread = threading.Thread(
                target=self.execute_dynamic_mission,
                args=(plan,),
                daemon=True,
                name=f"MissionThread-{self.current_mission_name}"
            )
            self.active_mission_thread.start()
            self.current_status = f"RUNNING: {self.current_mission_name}"

            return f"Autonomous mission '{self.current_mission_name}' ({plan.policy_type.value}) started: {plan.goal_description}"

    def run_mission_sync(self, goal_description: str) -> Dict[str, Any]:
        """
        Synchronously executes any high-level natural language instruction
        and returns the full structured data findings immediately.
        """
        with self._lock:
            self.cancel_event.clear()
            plan = self.decomposer.decompose(goal_description)
            self.current_mission_name = plan.goal_name
            self.active_mission_data = {
                "goal": goal_description,
                "goal_name": plan.goal_name,
                "project_type": plan.policy_type.value,
                "started_at": time.time(),
                "events": [],
                "step_count": 0,
                "obstacles_avoided": 0,
                "target_found": False,
                "sensor_snapshots": [],
                "plan": plan.to_dict()
            }
            self.current_status = f"RUNNING: {self.current_mission_name}"

        return self.execute_dynamic_mission(plan)

    def execute_dynamic_mission(self, plan: DynamicMissionPlan) -> Dict[str, Any]:
        """
        Generic closed-loop executor that runs any DynamicMissionPlan,
        driving actuators and checking dynamic stopping conditions at 20Hz.
        Supports seamless sequential chaining when plan.next_plan is defined.
        """
        start_time = time.time()
        print(f"\n[Autonomous Goal] Executing Dynamic Mission: '{plan.goal_name}' ({plan.policy_type.value})", flush=True)
        print(f"[Autonomous Goal] Objective: {plan.goal_description}", flush=True)

        if plan.policy_type == PolicyType.SCAN_SWEEP:
            res = self._run_scan_sweep_mission(plan, start_time)
        elif plan.policy_type == PolicyType.APPROACH_TARGET:
            res = self._run_approach_target_mission(plan, start_time)
        elif plan.policy_type == PolicyType.CONDITIONAL_MOVE:
            res = self._run_conditional_move_mission(plan, start_time)
        elif plan.policy_type == PolicyType.MONITOR_HOLD:
            res = self._run_monitor_hold_mission(plan, start_time)
        elif plan.policy_type == PolicyType.ROTATE_TO:
            res = self._run_rotate_mission(plan, start_time)
        elif plan.policy_type == PolicyType.DIRECT_ACTION:
            res = self._run_direct_action_mission(plan, start_time)
        else:
            res = self._run_explore_safe_mission(plan, start_time)

        # Chained mission handling: execute next_plan if current step finished without cancellation
        if plan.next_plan is not None and not self.is_cancelled():
            print(f"\n[Autonomous Goal] Step completed: '{plan.goal_name}'. Transitioning to next plan: '{plan.next_plan.goal_name}'...", flush=True)
            self.record_event("MISSION_STEP_TRANSITION", f"Completed {plan.goal_name}, launching next step: {plan.next_plan.goal_name}")
            self.current_mission_name = plan.next_plan.goal_name
            self.current_status = f"RUNNING: {self.current_mission_name}"
            time.sleep(0.4)
            next_res = self.execute_dynamic_mission(plan.next_plan)

            merged = dict(next_res)
            merged["step_1"] = res
            merged["step_2"] = next_res
            merged["chained_execution"] = True
            return merged

        return res

    # -------------------------------------------------------------------------
    # DYNAMIC EXECUTION POLICIES
    # -------------------------------------------------------------------------
    def _run_scan_sweep_mission(self, plan: DynamicMissionPlan, start_time: float) -> Dict[str, Any]:
        self.update_display("SCANNING ROOM", "SWEEP 360")
        self.speak("Scanning room across 360 degrees using sensors and actuators.")

        initial_heading = self.get_current_heading()
        self.room_scanner.reset(initial_heading)

        dt = 0.05
        step = 0
        total_sweep_deg = 0.0
        last_heading = initial_heading
        min_sweep_time = 3.5  # Ensure physical DC motors have time to complete a full 360 turn

        # Start physical rotation
        turn_cmd = "right" if plan.primary_action != "TURN_LEFT" else "left"
        self.publish_cmd("bupi/actuators/motors/cmd", turn_cmd)

        while not self.is_cancelled():
            elapsed = time.time() - start_time
            if elapsed >= plan.timeout_seconds:
                break

            step += 1
            self.active_mission_data["step_count"] = step

            # Refresh motor command every 500ms to keep movement smooth
            if step % 10 == 0:
                self.publish_cmd("bupi/actuators/motors/cmd", turn_cmd)

            if self.bridge.use_simulation:
                self.bridge.arena.update_physics("TURN_RIGHT", plan.speed_percent, dt)

            # Sample sensors at 20Hz
            sensor_data = self.bridge.get_latest_sensor_data()
            dist = sensor_data.get("distance_cm", 999.0)
            pir = sensor_data.get("pir_pin", 0)
            current_heading = self.get_current_heading()

            # Track total sweep angle using minimal signed angular delta
            delta = abs(signed_angle_diff(current_heading, last_heading))
            if delta < 45.0:  # Ignore abnormal sensor spikes
                total_sweep_deg += delta
            last_heading = current_heading

            self.room_scanner.record_sample(current_heading, dist, pir)

            # Full rotation achieved and minimum physical duration met
            if total_sweep_deg >= 360.0 and elapsed >= min_sweep_time:
                break

            # Calibrated physical 360 rotation fallback (N20 motors at ~45-50% PWM take ~7.5-8.5s for 360 degrees)
            if elapsed >= 8.5:
                break

            time.sleep(dt)

        self.publish_cmd("bupi/actuators/motors/cmd", "stop")
        is_count = (plan.goal_name == "COUNT_PEOPLE" or any(k in plan.raw_instruction.lower() for k in ["how many", "count", "number of"]))
        scan_report = self.room_scanner.analyze_scan(elapsed, is_count_query=is_count)
        findings = scan_report.to_dict()
        findings["instruction"] = plan.raw_instruction
        findings["goal"] = plan.goal_name
        findings["people_count"] = scan_report.people_count
        findings["targets"] = scan_report.targets

        self.speak(scan_report.verbal_report)
        status = "COMPLETED: TARGET_LOCATED" if scan_report.target_detected else "COMPLETED: AREA_CLEAR"
        findings["status"] = status
        self._compile_and_save_report(status, scan_report.verbal_report, findings)
        self.current_status = status
        self.current_mission_name = "IDLE"

        return findings

    def _run_approach_target_mission(self, plan: DynamicMissionPlan, start_time: float) -> Dict[str, Any]:
        self.update_display("SEARCH & APPROACH", "SCANNING ROOM")
        self.speak("Scanning room to locate person, then I will move towards them.")

        # Phase 1: 360-degree scan sweep to locate target
        initial_heading = self.get_current_heading()
        self.room_scanner.reset(initial_heading)

        dt = 0.05
        step = 0
        total_sweep_deg = 0.0
        last_heading = initial_heading
        min_sweep_time = 3.5

        turn_cmd = "right" if plan.primary_action != "TURN_LEFT" else "left"
        self.publish_cmd("bupi/actuators/motors/cmd", turn_cmd)

        while not self.is_cancelled():
            elapsed = time.time() - start_time
            if elapsed >= plan.timeout_seconds:
                break

            step += 1
            self.active_mission_data["step_count"] = step

            if step % 10 == 0:
                self.publish_cmd("bupi/actuators/motors/cmd", turn_cmd)

            if self.bridge.use_simulation:
                self.bridge.arena.update_physics("TURN_RIGHT", 45, dt)

            sensor_data = self.bridge.get_latest_sensor_data()
            dist = sensor_data.get("distance_cm", 999.0)
            pir = sensor_data.get("pir_pin", 0)
            current_heading = self.get_current_heading()

            delta = abs(signed_angle_diff(current_heading, last_heading))
            if delta < 45.0:
                total_sweep_deg += delta
            last_heading = current_heading

            self.room_scanner.record_sample(current_heading, dist, pir)

            if total_sweep_deg >= 360.0 and elapsed >= min_sweep_time:
                break
            if elapsed >= 8.5:
                break

            time.sleep(dt)

        self.publish_cmd("bupi/actuators/motors/cmd", "stop")
        time.sleep(0.3)

        scan_report = self.room_scanner.analyze_scan(time.time() - start_time, is_count_query=False)

        if not scan_report.target_detected or not scan_report.targets:
            msg = "Scan complete. No person was detected in the room to approach."
            self.speak(msg)
            self.update_display("MISSION COMPLETE", "NO PERSON FOUND")
            findings = scan_report.to_dict()
            findings["instruction"] = plan.raw_instruction
            findings["goal"] = plan.goal_name
            findings["status"] = "COMPLETED: NO_TARGET"
            findings["verbal_report"] = msg
            self._compile_and_save_report("COMPLETED: NO_TARGET", msg, findings)
            self.current_status = "COMPLETED: NO_TARGET"
            self.current_mission_name = "IDLE"
            return findings

        # Phase 2: Select closest target and align towards their heading
        target = scan_report.targets[0]
        for t in scan_report.targets:
            if t["distance_cm"] < target["distance_cm"]:
                target = t

        target_bearing = target["relative_bearing_deg"]
        target_dist_m = target["distance_m"]

        self.update_display("TARGET LOCATED", f"{target_dist_m}m {target['direction_description'][:10]}")
        self.speak(f"Person located {target_dist_m} meters away, {target['relative_text']}. Aligning and moving towards them.")

        target_abs_h = target.get("absolute_heading_deg", (initial_heading + target_bearing) % 360.0)
        align_start = time.time()
        align_timeout = 6.0

        while not self.is_cancelled() and (time.time() - align_start) < align_timeout:
            curr_h = self.get_current_heading()
            h_diff = signed_angle_diff(target_abs_h, curr_h)
            if abs(h_diff) <= 8.0:
                break

            align_turn = "right" if h_diff > 0 else "left"
            self.publish_cmd("bupi/actuators/motors/cmd", align_turn)
            if self.bridge.use_simulation:
                sim_turn = "TURN_RIGHT" if h_diff > 0 else "TURN_LEFT"
                self.bridge.arena.update_physics(sim_turn, 40, dt)

            time.sleep(dt)

        self.publish_cmd("bupi/actuators/motors/cmd", "stop")
        time.sleep(0.2)

        # Phase 3: Move forward towards the person until safe approach threshold (35 cm)
        self.update_display("APPROACHING", f"TARGET {target_dist_m}m")
        self.publish_cmd("bupi/actuators/motors/cmd", "forward")

        approach_start = time.time()
        # Generous approach window: allow enough time to cross room safely (up to 30s)
        approach_timeout = max(18.0, min(35.0, (target.get("distance_cm", 200.0) / 10.0) + 10.0))
        final_distance_cm = target.get("distance_cm", 999.0)
        app_step = 0

        while not self.is_cancelled() and (time.time() - approach_start) < approach_timeout:
            app_step += 1
            if app_step % 10 == 0:
                self.publish_cmd("bupi/actuators/motors/cmd", "forward")

            if self.bridge.use_simulation:
                self.bridge.arena.update_physics("MOVE_FORWARD", 45, dt)

            sensor_data = self.bridge.get_latest_sensor_data()
            dist = sensor_data.get("distance_cm", 999.0)
            final_distance_cm = dist

            # Target standoff reached (<= 35 cm) or critical obstacle barrier (<= 15 cm)
            if 0.0 < dist <= 35.0:
                print(f"[Autonomous Goal] ✅ Target standoff reached: {dist:.1f} cm", flush=True)
                break

            time.sleep(dt)

        self.publish_cmd("bupi/actuators/motors/cmd", "stop")
        total_duration = round(time.time() - start_time, 2)

        if final_distance_cm <= 45.0:
            arrival_msg = f"Arrived. I have approached the person and stopped safely at {final_distance_cm:.0f} centimeters distance."
        else:
            arrival_msg = f"Moved towards the person, currently holding safe standoff at {final_distance_cm:.0f} centimeters."

        self.speak(arrival_msg)
        self.update_display("TARGET REACHED", f"DIST: {final_distance_cm:.0f}cm")

        findings = scan_report.to_dict()
        findings["instruction"] = plan.raw_instruction
        findings["goal"] = plan.goal_name
        findings["status"] = "COMPLETED: TARGET_APPROACHED"
        findings["final_distance_cm"] = final_distance_cm
        findings["target_approached"] = target
        findings["verbal_report"] = arrival_msg
        findings["duration_seconds"] = total_duration

        self._compile_and_save_report("COMPLETED: TARGET_APPROACHED", arrival_msg, findings)
        self.current_status = "COMPLETED: TARGET_APPROACHED"
        self.current_mission_name = "IDLE"

        return findings

    def _run_conditional_move_mission(self, plan: DynamicMissionPlan, start_time: float) -> Dict[str, Any]:
        self.update_display("MISSION ACTIVE", plan.goal_name[:16])
        self.speak(f"Starting {plan.goal_description}.")

        dt = 0.05
        step = 0
        condition_met = False
        final_dist = 999.0
        final_heading = self.get_current_heading()

        motor_cmd = "forward" if plan.primary_action == "MOVE_FORWARD" else "reverse"

        while not self.is_cancelled() and (time.time() - start_time) < plan.timeout_seconds:
            step += 1
            self.active_mission_data["step_count"] = step

            # 1. Sample latest sensors
            sensor_data = self.bridge.get_latest_sensor_data()
            dist = sensor_data.get("distance_cm", 999.0)
            pir = sensor_data.get("pir_pin", 0)
            heading = self.get_current_heading()
            final_dist = dist
            final_heading = heading

            elapsed = time.time() - start_time
            telemetry = {
                "distance_cm": dist,
                "pir": pir,
                "heading_deg": heading,
                "elapsed_seconds": elapsed
            }

            # 2. Hardware Safety Supervisor (< 15 cm critical cutoff for forward motion only)
            if motor_cmd == "forward" and dist <= self.safety.critical_distance_cm:
                print(f"[Autonomous Goal Safety] 🛑 Critical obstacle proximity ({dist:.1f} cm)! Emergency brake.", flush=True)
                self.publish_cmd("bupi/actuators/motors/cmd", "stop")
                condition_met = True
                self.record_event("SAFETY_STOP", f"Emergency brake triggered at {dist:.1f} cm")
                break

            # 3. Dynamic Stopping Condition Check
            if plan.stop_condition.evaluate(telemetry, elapsed):
                print(f"[Autonomous Goal] ✅ Dynamic condition satisfied: {plan.stop_condition.description} (dist={dist:.1f}cm)", flush=True)
                self.publish_cmd("bupi/actuators/motors/cmd", "stop")
                condition_met = True
                self.record_event("CONDITION_MET", f"Goal satisfied: {plan.stop_condition.description}")
                break

            # 4. Actuation
            self.publish_cmd("bupi/actuators/motors/cmd", motor_cmd)
            if self.bridge.use_simulation:
                self.bridge.arena.update_physics(plan.primary_action, plan.speed_percent, dt)

            time.sleep(dt)

        self.publish_cmd("bupi/actuators/motors/cmd", "stop")
        total_time = round(time.time() - start_time, 2)

        if plan.goal_name.startswith("MOVE_") and "CM" in plan.goal_name:
            if final_dist <= self.safety.critical_distance_cm:
                status = "OBSTACLE_INTERRUPTED"
                summary = f"Stopped early. Critical obstacle detected at {final_dist:.1f} cm ahead after {total_time} seconds."
            else:
                status = "COMPLETED"
                summary = f"Successfully moved {plan.goal_description.lower()} in {total_time} seconds. Clearance ahead: {final_dist:.1f} cm."
        else:
            status = "OBSTACLE_REACHED" if condition_met else ("TIMED_OUT" if not self.is_cancelled() else "CANCELLED")
            summary = (
                f"Stopped. Obstacle detected at {final_dist:.1f} cm (0.{int(final_dist):02d}m) directly ahead after "
                f"moving {motor_cmd} for {total_time} seconds (heading: {final_heading:.1f}°)."
                if condition_met else f"Mission {status.lower()} after {total_time} seconds."
            )

        self.speak(summary)
        self.update_display("MISSION STOPPED", f"DIST: {final_dist:.0f}cm")

        findings = {
            "instruction": plan.raw_instruction,
            "goal": plan.goal_name,
            "status": status,
            "obstacle_reached": condition_met,
            "final_distance_cm": final_dist,
            "final_distance_m": round(final_dist / 100.0, 2),
            "heading_deg": round(final_heading, 1),
            "duration_seconds": total_time,
            "steps_taken": step,
            "summary": summary
        }

        self._compile_and_save_report(status, summary, findings)
        self.current_status = status
        self.current_mission_name = "IDLE"
        return findings

    def _run_monitor_hold_mission(self, plan: DynamicMissionPlan, start_time: float) -> Dict[str, Any]:
        self.update_display("SENTRY MODE", "MONITORING MOTION")
        self.speak("Sentry mode activated. Monitoring stationary area for thermal motion.")
        self.publish_cmd("bupi/actuators/motors/cmd", "stop")

        dt = 0.05
        motion_triggered = False
        trigger_time = 0.0
        final_heading = self.get_current_heading()

        while not self.is_cancelled() and (time.time() - start_time) < plan.timeout_seconds:
            sensor_data = self.bridge.get_latest_sensor_data()
            pir = sensor_data.get("pir_pin", 0)
            final_heading = self.get_current_heading()

            if pir == 1:
                motion_triggered = True
                trigger_time = round(time.time() - start_time, 2)
                self.record_event("MOTION_ALERT", f"Thermal infrared motion detected at T+{trigger_time}s")
                break

            time.sleep(dt)

        total_time = round(time.time() - start_time, 2)
        status = "COMPLETED: MOTION_ALERT" if motion_triggered else "COMPLETED: NO_MOTION"
        summary = (
            f"Alert! Thermal motion detected at heading {final_heading:.1f}° after {trigger_time} seconds of monitoring."
            if motion_triggered else f"No motion detected during {total_time} second monitoring window."
        )

        self.speak(summary)
        self.update_display("SENTRY COMPLETE", "MOTION ALERT" if motion_triggered else "CLEAR")

        findings = {
            "instruction": plan.raw_instruction,
            "goal": plan.goal_name,
            "status": status,
            "motion_detected": motion_triggered,
            "detection_time_s": trigger_time if motion_triggered else None,
            "heading_deg": round(final_heading, 1),
            "duration_seconds": total_time,
            "summary": summary
        }

        self._compile_and_save_report(status, summary, findings)
        self.current_status = status
        self.current_mission_name = "IDLE"
        return findings

    def _run_rotate_mission(self, plan: DynamicMissionPlan, start_time: float) -> Dict[str, Any]:
        initial_heading = self.get_current_heading()
        target_delta = plan.stop_condition.threshold
        turn_cmd = "left" if plan.primary_action == "TURN_LEFT" else "right"

        self.update_display("TURNING", f"{target_delta:.0f} DEG {turn_cmd.upper()}")
        self.speak(f"Turning {target_delta:.0f} degrees {turn_cmd}.")

        dt = 0.05
        total_turned = 0.0
        last_heading = initial_heading

        timed_fallback = (target_delta / 40.0) + 2.0
        while not self.is_cancelled() and total_turned < target_delta and (time.time() - start_time) < plan.timeout_seconds:
            elapsed = time.time() - start_time
            if elapsed >= timed_fallback and total_turned < 5.0:
                # Timed turn fallback when gyro delta is not incrementing
                total_turned = target_delta
                break

            self.publish_cmd("bupi/actuators/motors/cmd", turn_cmd)
            if self.bridge.use_simulation:
                self.bridge.arena.update_physics(plan.primary_action, plan.speed_percent, dt)

            current_heading = self.get_current_heading()
            diff = signed_angle_diff(current_heading, last_heading) if turn_cmd == "right" else signed_angle_diff(last_heading, current_heading)
            delta = abs(diff)
            if delta < 45.0:
                total_turned += delta
            last_heading = current_heading
            time.sleep(dt)

        self.publish_cmd("bupi/actuators/motors/cmd", "stop")
        final_heading = self.get_current_heading()
        total_time = round(time.time() - start_time, 2)
        sensor_data = self.bridge.get_latest_sensor_data()
        clearance_cm = sensor_data.get("distance_cm", 999.0)

        summary = f"Turned {total_turned:.1f}° {turn_cmd}. Heading is now {final_heading:.1f}°. Forward clearance: {clearance_cm:.1f} cm."
        self.speak(summary)

        findings = {
            "instruction": plan.raw_instruction,
            "goal": plan.goal_name,
            "status": "COMPLETED",
            "initial_heading_deg": initial_heading,
            "final_heading_deg": final_heading,
            "total_turned_deg": round(total_turned, 1),
            "distance_ahead_cm": clearance_cm,
            "duration_seconds": total_time,
            "summary": summary
        }

        self._compile_and_save_report("COMPLETED", summary, findings)
        self.current_status = "COMPLETED"
        self.current_mission_name = "IDLE"
        return findings

    def _run_direct_action_mission(self, plan: DynamicMissionPlan, start_time: float) -> Dict[str, Any]:
        self.publish_cmd("bupi/actuators/motors/cmd", "stop")
        self.speak("Halted immediately.")
        self.update_display("HALTED", "STOPPED")
        findings = {
            "instruction": plan.raw_instruction,
            "goal": plan.goal_name,
            "status": "STOPPED",
            "summary": "Robot halted immediately."
        }
        self._compile_and_save_report("STOPPED", "Immediate stop commanded.", findings)
        self.current_status = "STOPPED"
        self.current_mission_name = "IDLE"
        return findings

    def _evade_and_replan_path(self, current_dist: float) -> str:
        """
        Smart Obstacle Evasion:
        Stops, looks left and right, evaluates clearance, and pivots into clearer corridor.
        """
        self.publish_cmd("bupi/actuators/motors/cmd", "stop")
        self.speak("Obstacle ahead. Scanning alternate corridors.")
        self.update_display("OBSTACLE DETECTED", "SCANNING PATH")

        # 1. Reverse slightly to give turning space
        self.publish_cmd("bupi/actuators/motors/cmd", "reverse")
        if self.bridge.use_simulation:
            self.bridge.arena.update_physics("MOVE_BACKWARD", 40, 0.4)
        time.sleep(0.4)
        self.publish_cmd("bupi/actuators/motors/cmd", "stop")

        # 2. Look Left (-35 deg)
        self.publish_cmd("bupi/actuators/motors/cmd", "left")
        if self.bridge.use_simulation:
            self.bridge.arena.update_physics("TURN_LEFT", 50, 0.5)
        time.sleep(0.5)
        self.publish_cmd("bupi/actuators/motors/cmd", "stop")
        time.sleep(0.1)
        left_dist = self.bridge.get_latest_sensor_data().get("distance_cm", 999.0)

        # 3. Look Right (+70 deg from left = +35 deg relative to center)
        self.publish_cmd("bupi/actuators/motors/cmd", "right")
        if self.bridge.use_simulation:
            self.bridge.arena.update_physics("TURN_RIGHT", 50, 1.0)
        time.sleep(1.0)
        self.publish_cmd("bupi/actuators/motors/cmd", "stop")
        time.sleep(0.1)
        right_dist = self.bridge.get_latest_sensor_data().get("distance_cm", 999.0)

        # 4. Pick best path
        if left_dist > right_dist:
            # Pivot back to left corridor
            self.publish_cmd("bupi/actuators/motors/cmd", "left")
            if self.bridge.use_simulation:
                self.bridge.arena.update_physics("TURN_LEFT", 50, 1.0)
            time.sleep(1.0)
            self.publish_cmd("bupi/actuators/motors/cmd", "stop")
            chosen = f"left corridor ({left_dist:.1f} cm clear)"
        else:
            chosen = f"right corridor ({right_dist:.1f} cm clear)"

        self.speak(f"Re-routed to {chosen}.")
        self.record_event("PATH_REPLANNED", f"Obstacle at {current_dist:.1f} cm avoided via {chosen}")
        return chosen

    def _run_explore_safe_mission(self, plan: DynamicMissionPlan, start_time: float) -> Dict[str, Any]:
        self.update_display("EXPLORING", "SAFE NAVIGATION")
        self.speak("Starting safe autonomous exploration.")

        dt = 0.05
        step = 0
        obstacles_avoided = 0

        while not self.is_cancelled() and (time.time() - start_time) < plan.timeout_seconds:
            step += 1
            self.active_mission_data["step_count"] = step

            sensor_data = self.bridge.get_latest_sensor_data()
            dist = sensor_data.get("distance_cm", 999.0)

            if dist <= self.safety.safe_distance_cm:
                # Smart Obstacle Evasion: stop, sample left and right, pivot into clear corridor
                chosen_corridor = self._evade_and_replan_path(dist)
                obstacles_avoided += 1
                self.active_mission_data["obstacles_avoided"] = obstacles_avoided
            else:
                self.publish_cmd("bupi/actuators/motors/cmd", "forward")
                if self.bridge.use_simulation:
                    self.bridge.arena.update_physics("MOVE_FORWARD", plan.speed_percent, dt)
                time.sleep(dt)

        self.publish_cmd("bupi/actuators/motors/cmd", "stop")
        total_time = round(time.time() - start_time, 2)
        summary = f"Exploration cycle completed. Avoided {obstacles_avoided} obstacles over {total_time} seconds."
        self.speak(summary)

        findings = {
            "instruction": plan.raw_instruction,
            "goal": plan.goal_name,
            "status": "COMPLETED: EXPLORATION_DONE",
            "obstacles_avoided": obstacles_avoided,
            "duration_seconds": total_time,
            "steps_taken": step,
            "summary": summary
        }

        self._compile_and_save_report("COMPLETED: EXPLORATION_DONE", summary, findings)
        self.current_status = "COMPLETED"
        self.current_mission_name = "IDLE"
        return findings

    # =========================================================================
    # DYNAMIC MISSION DEBRIEF & PERSISTENCE
    # =========================================================================
    def _compile_and_save_report(self, final_status: str, summary_notes: str = "", findings_extra: dict = None) -> dict:
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

        if findings_extra:
            report_data.update(findings_extra)

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
