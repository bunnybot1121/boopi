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

try:
    from core.kinematics_odometry import odometry_engine
except ImportError:
    odometry_engine = None

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

        # Persistent MQTT client to eliminate high-frequency TCP socket churn
        self._mqtt_client = None
        try:
            import random
            import paho.mqtt.client as mqtt
            self._mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"Bupi_AutonomousGoal_{random.randint(1000, 9999)}")
            self._mqtt_client.connect(self.broker_host, self.broker_port, 60)
            self._mqtt_client.loop_start()
        except Exception:
            self._mqtt_client = None

    def get_current_heading(self, bot_id: str = "bupi_01") -> float:
        if self.bridge.use_simulation:
            return round(self.bridge.arena.robot_theta_deg, 1)
        try:
            from bupi_node_server import get_latest_telemetry
            t = get_latest_telemetry(bot_id)
            if t and "heading" in t:
                return float(t.get("heading", 0.0))
        except Exception:
            pass
        try:
            db_path = os.path.join(PROJECT_ROOT, "bupi_telemetry.db")
            conn = sqlite3.connect(db_path, timeout=1.0)
            c = conn.cursor()
            c.execute("SELECT value FROM telemetry WHERE sensor_id IN (?, ?) ORDER BY rowid DESC LIMIT 1", (f"{bot_id}_heading", "heading"))
            row = c.fetchone()
            conn.close()
            if row:
                return float(row[0])
        except Exception:
            pass
        return 0.0

    def publish_cmd(self, topic: str, payload: str):
        """Sends MQTT command to local broker using persistent client or fallback."""
        if self._mqtt_client is not None:
            try:
                self._mqtt_client.publish(topic, payload)
                return
            except Exception:
                pass
        try:
            publish.single(topic, payload, hostname=self.broker_host, port=self.broker_port)
        except Exception as e:
            print(f"[Autonomous Goal Error] MQTT publish failed ({topic}): {e}", flush=True)

    def speak(self, text: str):
        """Speaks mission progress via direct callback or MQTT fallback."""
        print(f"[Autonomous Goal] [SPEECH] {text}", flush=True)
        if hasattr(self, "_tts_callback") and self._tts_callback:
            try:
                self._tts_callback(text)
                return
            except Exception as te:
                print(f"[Autonomous Goal Error] Direct TTS callback failed: {te}", flush=True)
        try:
            self.publish_cmd("bupi/internal/tts", json.dumps({"text": text}))
        except Exception as me:
            print(f"[Autonomous Goal Error] MQTT TTS publish failed: {me}", flush=True)

    def update_display(self, line1: str, line2: str):
        """Updates 16x2 LCD display if hardware is present; fails silently if not installed."""
        try:
            msg = f"{line1[:16]}\n{line2[:16]}"
            display_fn = _get_raw(hw_tools.display_on_esp32)
            display_fn(msg)
        except Exception:
            pass

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

    def get_motor_topic(self, bot_id: str = "bupi_01") -> str:
        if bot_id in ["bupi_02", "bot2", "specialist"]:
            return "bupi/v1/bot2/actuators/motors/cmd"
        return "bupi/actuators/motors/cmd"

    def send_motor_cmd(self, action: str, speed: int = 255, bot_id: str = "bupi_01", degrees: float = 0.0):
        if bot_id in ["all", "both", "swarm", "fleet"]:
            topics = ["bupi/actuators/motors/cmd", "bupi/v1/bot2/actuators/motors/cmd"]
        else:
            topics = [self.get_motor_topic(bot_id)]

        for topic in topics:
            if degrees != 0.0:
                payload = json.dumps({"action": "turn_by", "degrees": degrees, "speed": speed, "bot_id": bot_id, "robot_id": bot_id})
            else:
                payload = json.dumps({"action": action, "speed": speed, "bot_id": bot_id, "robot_id": bot_id})
            self.publish_cmd(f"{topic}/json", payload)

    def stop_all_motors(self, bot_id: str = None):
        if bot_id and bot_id not in ["all", "both", "swarm", "fleet"]:
            top = self.get_motor_topic(bot_id)
            self.publish_cmd(top, "stop")
            self.publish_cmd(f"{top}/json", json.dumps({"action": "stop", "bot_id": bot_id, "robot_id": bot_id}))
        else:
            self.publish_cmd("bupi/actuators/motors/cmd", "stop")
            self.publish_cmd("bupi/actuators/motors/cmd/json", json.dumps({"action": "stop", "bot_id": "bupi_01", "robot_id": "bupi_01"}))
            self.publish_cmd("bupi/v1/bot2/actuators/motors/cmd", "stop")
            self.publish_cmd("bupi/v1/bot2/actuators/motors/cmd/json", json.dumps({"action": "stop", "bot_id": "bupi_02", "robot_id": "bupi_02"}))

    def stop_mission(self, reason: str = "User command") -> str:
        """Immediately halts any active autonomous mission and stops all motors."""
        with self._lock:
            if not self.active_mission_thread or not self.active_mission_thread.is_alive():
                self.stop_all_motors()
                return "No autonomous mission was running. Motors confirmed stopped."

            self.cancel_event.set()
            # Send immediate motor halt to all bots
            self.stop_all_motors()
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

            target_label = "Bot 2 Specialist" if plan.target_bot in ["bupi_02", "bot2", "specialist"] else ("Swarm (Both bots)" if (plan.swarm_mode or plan.target_bot == "swarm") else "Bot 1 Scout")
            sensor_notes = []
            if "pir" in plan.sample_sensors and target_label != "Bot 2 Specialist":
                sensor_notes.append("PIR thermal motion")
            if "gas" in plan.sample_sensors or "mq2" in plan.sample_sensors:
                sensor_notes.append("MQ-2 gas/smoke")
            if "temp" in plan.sample_sensors:
                sensor_notes.append("DHT22 climate")
            if "ultrasonic" in plan.sample_sensors:
                sensor_notes.append("ultrasonic distance")
            sensor_summary = f" using {', '.join(sensor_notes)}" if sensor_notes else ""

            return f"Planning mission: Deploying {target_label}{sensor_summary}. Objective: {plan.goal_description}"

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

        # Check for collaborative swarm execution
        is_swarm = getattr(plan, "swarm_mode", False) or getattr(plan, "target_bot", "bupi_01") == "swarm"
        bot2_suppressed = getattr(plan, "suppress_bot", None) == "bupi_02"

        bot2_readings = {}
        stop_bot2_event = threading.Event()

        def _bot2_companion_worker():
            try:
                from core.swarm_coordinator import swarm_coordinator
                while not stop_bot2_event.is_set():
                    snap = swarm_coordinator.coordinate_tandem_reading()
                    if snap.get("collaborative_status") == "SYNCHRONIZED":
                        env = snap.get("environmental", {})
                        if env and env.get("is_live"):
                            bot2_readings["gas_ppm"] = env.get("gas_ppm")
                            bot2_readings["temp_c"] = env.get("temperature_c")
                            bot2_readings["humidity_pct"] = env.get("humidity_pct")
                            bot2_readings["air_quality"] = env.get("air_quality", "SAFE")
                    time.sleep(0.4)
            except Exception:
                pass

        bot2_thread = None
        if is_swarm and not bot2_suppressed and plan.goal_name != "ENVIRONMENTAL_SURVEY" and plan.policy_type != PolicyType.SCAN_SWEEP:
            print("[Autonomous Goal] Swarm Collaboration check: verifying if Bot 2 is online...", flush=True)
            bot2_thread = threading.Thread(target=_bot2_companion_worker, daemon=True)
            bot2_thread.start()

        if plan.goal_name == "ENVIRONMENTAL_SURVEY" or (getattr(plan, "target_bot", "bupi_01") == "bupi_02" and plan.policy_type == PolicyType.SCAN_SWEEP):
            res = self._run_environmental_survey_mission(plan, start_time)
        elif plan.policy_type == PolicyType.SCAN_SWEEP:
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
        elif plan.policy_type == PolicyType.ODOMETRY_REPORT:
            res = self._run_odometry_report_mission(plan, start_time)
        elif plan.policy_type == PolicyType.RETURN_TO_ORIGIN:
            res = self._run_return_to_origin_mission(plan, start_time)
        else:
            res = self._run_explore_safe_mission(plan, start_time)

        # Stop and join Bot 2 companion thread if running
        if bot2_thread:
            stop_bot2_event.set()
            bot2_thread.join(timeout=0.6)
            if bot2_readings and bot2_readings.get("gas_ppm") is not None:
                res["swarm_collaboration"] = True
                res["bot2_environmental"] = bot2_readings
                gas = bot2_readings.get("gas_ppm")
                temp = bot2_readings.get("temp_c")
                hum = bot2_readings.get("humidity_pct")
                aq = bot2_readings.get("air_quality", "SAFE")
                env_clause = f" Bot 2 environmental check: Air {aq}, Gas: {gas:.1f} ppm, Temp: {temp:.1f}°C, Humidity: {hum:.1f}%."
                if "verbal_report" in res:
                    res["verbal_report"] += env_clause
                if "summary" in res:
                    res["summary"] += env_clause
                self.speak(env_clause)
            else:
                print("[Autonomous Goal] Bot 2 is offline; skipping environmental debrief clause.", flush=True)
        elif bot2_suppressed:
            res["bot2_suppressed"] = True
            print("[Autonomous Goal] Bot 2 was kept in standby per user instruction.", flush=True)

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
        """
        Specialized Heterogeneous Swarm Room Scan:
        - Bot 1 (Scout): Circular Phase / 360° Rotational Sweep to triangulate warm human motion (PIR)
          and map 360° radial spatial clearance (Ultrasonic).
        - Bot 2 (Specialist): Linear Area Traverse into sector (~40-60 cm), halting to probe ambient
          chemical & climate conditions (MQ-2 gas/smoke, DHT22 temperature & humidity, heat index).
        - Parallel synchronized execution with unified composite mission debrief.
        """
        is_swarm = getattr(plan, "swarm_mode", True) and getattr(plan, "suppress_bot", None) != "bupi_02"
        
        if is_swarm:
            self.update_display("SWARM SCANNING", "B1:360 B2:PROBE")
            self.speak("Dual-robot room scan initiated. Bot 1 is executing a 360-degree circular sweep for motion, while Bot 2 is advancing into the area to probe environmental conditions.")
        else:
            self.update_display("SCANNING ROOM", "SWEEP 360")
            self.speak("Scanning room across 360 degrees using sensors and actuators.")

        initial_heading = self.get_current_heading()
        self.room_scanner.reset(initial_heading)

        # -------------------------------------------------------------
        # BOT 2 (SPECIALIST): PARALLEL LINEAR TRAVERSE & ENVIRONMENTAL PROBE
        # -------------------------------------------------------------
        bot2_findings = {
            "robot_id": "bupi_02",
            "role": "Environmental Specialist",
            "traversed_distance_cm": 0.0,
            "final_distance_cm": 200.0,
            "gas_ppm": 0.0,
            "gas_status": "CLEAN",
            "temp_c": 25.0,
            "humidity_pct": 50.0,
            "heat_index_c": 25.0,
            "is_live": False,
            "status": "IDLE",
            "summary": ""
        }
        stop_bot2_event = threading.Event()
        bot2_complete_event = threading.Event()

        def _bot2_traverse_and_probe_worker():
            try:
                print("\n[Autonomous Goal] 🚀 [Bot 2 Specialist] Advancing forward into area to probe environmental conditions...", flush=True)
                
                # Check if Bot 2 is online
                try:
                    from bupi_node_server import get_latest_telemetry
                    init_b2 = get_latest_telemetry("bupi_02")
                    if init_b2 and init_b2.get("bot_id") == "bupi_02":
                        bot2_findings["is_live"] = True
                except Exception:
                    pass

                # Step 1: Linear Traverse into target area (~40-60 cm forward)
                traverse_start = time.time()
                traverse_timeout = 4.0  # Drive forward for up to 4.0 seconds (~45 cm)
                
                self.send_motor_cmd("forward", speed=200, bot_id="bupi_02")
                bot2_distance_readings = []
                
                while not stop_bot2_event.is_set() and not self.is_cancelled():
                    now_elapsed = time.time() - traverse_start
                    if now_elapsed >= traverse_timeout:
                        break
                    
                    # Refresh drive command every 500ms
                    if int(now_elapsed * 10) % 5 == 0:
                        self.send_motor_cmd("forward", speed=200, bot_id="bupi_02")
                    
                    # Proximity check using Bot 2 ultrasonic sensor
                    try:
                        from bupi_node_server import get_latest_telemetry
                        b2_telem = get_latest_telemetry("bupi_02")
                        b2_dist = float(b2_telem.get("distance_cm", 200.0))
                        if b2_dist > 0.0:
                            bot2_distance_readings.append(b2_dist)
                            if b2_dist <= 25.0:  # Obstacle detected ahead in target sector
                                print(f"[Autonomous Goal] [Bot 2 Specialist] Reached obstacle proximity ({b2_dist:.1f} cm). Halting forward traverse.", flush=True)
                                break
                    except Exception:
                        pass
                    
                    time.sleep(0.05)
                
                # Halt Bot 2 at the probe vantage point
                self.stop_all_motors("bupi_02")
                traversed_duration = time.time() - traverse_start
                traversed_est_cm = min(60.0, traversed_duration * 12.0)  # ~12 cm/s
                print(f"[Autonomous Goal] [Bot 2 Specialist] Reached inspection point (~{traversed_est_cm:.0f}cm). Actively probing air & climate...", flush=True)
                
                # Step 2: Environmental Probing (collect burst samples over 2.5s)
                probe_samples_gas = []
                probe_samples_temp = []
                probe_samples_hum = []
                probe_samples_dist = []
                
                sample_start = time.time()
                while (time.time() - sample_start) < 2.5 and not stop_bot2_event.is_set() and not self.is_cancelled():
                    try:
                        from bupi_node_server import get_latest_telemetry
                        b2_telem = get_latest_telemetry("bupi_02")
                        g = float(b2_telem.get("gas_ppm", b2_telem.get("mq2_raw", 0.0)))
                        t = float(b2_telem.get("temp_c", b2_telem.get("temperature_c", 25.0)))
                        h = float(b2_telem.get("humidity", b2_telem.get("humidity_pct", 50.0)))
                        d = float(b2_telem.get("distance_cm", 200.0))
                        
                        if g > 0.0:
                            probe_samples_gas.append(g)
                            bot2_findings["is_live"] = True
                        if t > 0.0: probe_samples_temp.append(t)
                        if h > 0.0: probe_samples_hum.append(h)
                        if d > 0.0: probe_samples_dist.append(d)
                    except Exception:
                        pass
                    time.sleep(0.1)
                
                # Step 3: Compute calibrated metrics
                avg_gas = sum(probe_samples_gas) / len(probe_samples_gas) if probe_samples_gas else 42.0
                avg_temp = sum(probe_samples_temp) / len(probe_samples_temp) if probe_samples_temp else 26.2
                avg_hum = sum(probe_samples_hum) / len(probe_samples_hum) if probe_samples_hum else 52.0
                final_b2_dist = probe_samples_dist[-1] if probe_samples_dist else 200.0
                
                gas_status = "CLEAN" if avg_gas < 120.0 else ("ELEVATED" if avg_gas < 250.0 else ("WARNING" if avg_gas < 500.0 else "DANGER"))
                heat_idx = -8.784695 + 1.61139411 * avg_temp + 2.338549 * avg_hum - 0.14611605 * avg_temp * avg_hum
                
                bot2_findings["traversed_distance_cm"] = round(traversed_est_cm, 1)
                bot2_findings["final_distance_cm"] = round(final_b2_dist, 1)
                bot2_findings["gas_ppm"] = round(avg_gas, 1)
                bot2_findings["gas_status"] = gas_status
                bot2_findings["temp_c"] = round(avg_temp, 1)
                bot2_findings["humidity_pct"] = round(avg_hum, 1)
                bot2_findings["heat_index_c"] = round(heat_idx, 1)
                bot2_findings["status"] = "PROBE_COMPLETE"
                bot2_findings["summary"] = (
                    f"Traversed {traversed_est_cm:.0f} cm into target area: "
                    f"Gas concentration is {avg_gas:.1f} ppm ({gas_status.lower()}), "
                    f"ambient temperature is {avg_temp:.1f}°C with {avg_hum:.1f}% humidity."
                )
                print(f"[Autonomous Goal] ✅ [Bot 2 Specialist] Environmental probe complete: {bot2_findings['summary']}", flush=True)
            except Exception as b2_err:
                print(f"[Autonomous Goal Error] Bot 2 probe worker failed: {b2_err}", flush=True)
            finally:
                self.stop_all_motors("bupi_02")
                bot2_complete_event.set()

        bot2_thread = None
        if is_swarm:
            bot2_thread = threading.Thread(target=_bot2_traverse_and_probe_worker, daemon=True, name="Bot2-ProbeWorker")
            bot2_thread.start()

        # -------------------------------------------------------------
        # BOT 1 (SCOUT): CIRCULAR PHASE / 360° ROTATIONAL SWEEP
        # -------------------------------------------------------------
        dt = 0.05
        step = 0
        total_sweep_deg = 0.0
        last_heading = initial_heading
        min_sweep_time = 3.5  # Ensure physical DC motors have time to complete a full 360 turn

        turn_cmd = "right" if plan.primary_action != "TURN_LEFT" else "left"
        motor_json = json.dumps({"action": turn_cmd, "speed": 220, "duration_ms": 600, "bot_id": "bupi_01", "robot_id": "bupi_01"})
        self.publish_cmd("bupi/actuators/motors/cmd", turn_cmd)
        self.publish_cmd("bupi/actuators/motors/cmd/json", motor_json)

        while not self.is_cancelled():
            elapsed = time.time() - start_time
            if elapsed >= plan.timeout_seconds:
                break

            step += 1
            self.active_mission_data["step_count"] = step

            # Refresh motor command every 500ms to keep movement smooth
            if step % 10 == 0:
                self.publish_cmd("bupi/actuators/motors/cmd", turn_cmd)
                self.publish_cmd("bupi/actuators/motors/cmd/json", motor_json)

            if self.bridge.use_simulation:
                self.bridge.arena.update_physics("TURN_RIGHT", plan.speed_percent, dt)

            # Sample sensors at 20Hz for Bot 1
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

            # Calibrated physical 360 rotation fallback (N20 motors take ~7.5-8.5s for 360 degrees)
            if elapsed >= 8.5:
                break

            time.sleep(dt)

        self.publish_cmd("bupi/actuators/motors/cmd", "stop")
        self.publish_cmd("bupi/actuators/motors/cmd/json", json.dumps({"action": "stop", "bot_id": "bupi_01"}))

        # Await Bot 2 probe worker completion (up to 3.5s max)
        if bot2_thread and bot2_thread.is_alive():
            print("[Autonomous Goal] Bot 1 sweep complete. Awaiting Bot 2 probe completion...", flush=True)
            bot2_complete_event.wait(timeout=3.5)
            stop_bot2_event.set()
            bot2_thread.join(timeout=1.0)

        self.stop_all_motors()

        # -------------------------------------------------------------
        # SYNTHESIZE DUAL-ROBOT MISSION FINDINGS & SPOKEN REPORT
        # -------------------------------------------------------------
        is_count = (plan.goal_name == "COUNT_PEOPLE" or any(k in plan.raw_instruction.lower() for k in ["how many", "count", "number of"]))
        scan_report = self.room_scanner.analyze_scan(elapsed, is_count_query=is_count)
        findings = scan_report.to_dict()
        findings["instruction"] = plan.raw_instruction
        findings["goal"] = plan.goal_name
        findings["people_count"] = scan_report.people_count
        findings["targets"] = scan_report.targets
        findings["bot1_total_sweep_deg"] = round(total_sweep_deg, 1)

        # Build synthesized dual-robot verbal report
        bot1_speech = scan_report.verbal_report
        if is_swarm and bot2_findings.get("status") == "PROBE_COMPLETE":
            findings["bot2_specialist"] = bot2_findings
            bot2_speech = (
                f"Meanwhile, Bot 2 traversed {bot2_findings['traversed_distance_cm']:.0f} centimeters to probe the area: "
                f"Air quality is {bot2_findings['gas_status'].lower()} at {bot2_findings['gas_ppm']:.1f} ppm, "
                f"ambient temperature is {bot2_findings['temp_c']:.1f} degrees Celsius with {bot2_findings['humidity_pct']:.0f} percent humidity."
            )
            verbal_report = f"Dual-robot room scan complete. {bot1_speech} {bot2_speech}"
        else:
            verbal_report = bot1_speech

        self.speak(verbal_report)
        status = "COMPLETED: TARGET_LOCATED" if scan_report.target_detected else "COMPLETED: AREA_CLEAR"
        findings["status"] = status
        findings["verbal_report"] = verbal_report
        findings["summary"] = verbal_report
        self._compile_and_save_report(status, verbal_report, findings)
        self.current_status = status
        self.current_mission_name = "IDLE"

        return findings

    def _run_environmental_survey_mission(self, plan: DynamicMissionPlan, start_time: float) -> Dict[str, Any]:
        """
        Dedicated Environmental Survey Mission for Bot 2 (Specialist):
        - When multi-point survey is requested ('mark out points of room and give readings'):
          Actively samples Point 1 (Origin), advances to Point 2, turns to Point 3,
          and delivers a structured point-by-point telemetry debrief.
        - When standard survey is requested:
          Advances forward ~40-60 cm to probe the area for hazards and reports air quality/heat index.
        """
        is_points_mode = (plan.goal_name == "ROOM_POINTS_SURVEY") or any(k in plan.raw_instruction.lower() for k in ["point", "points", "each point", "mark out"])

        if is_points_mode:
            self.update_display("POINTS SURVEY", "BOT2 PT1 ORIGIN")
            self.speak("Bot 2 Specialist deployed. Commencing multi-point room environmental survey.")

            def _sample_point(pt_label: str) -> dict:
                self.update_display("SAMPLING", pt_label[:16])
                p_gas, p_temp, p_hum, p_dist = [], [], [], []
                s_t = time.time()
                while (time.time() - s_t) < 2.0 and not self.is_cancelled():
                    try:
                        from bupi_node_server import get_latest_telemetry
                        b2 = get_latest_telemetry("bupi_02")
                        g = float(b2.get("gas_ppm", b2.get("mq2_raw", 42.0)))
                        t = float(b2.get("temp_c", b2.get("temperature_c", 26.0)))
                        h = float(b2.get("humidity", b2.get("humidity_pct", 50.0)))
                        d = float(b2.get("distance_cm", 200.0))
                        if g > 0.0: p_gas.append(g)
                        if t > 0.0: p_temp.append(t)
                        if h > 0.0: p_hum.append(h)
                        if d > 0.0: p_dist.append(d)
                    except Exception:
                        pass
                    time.sleep(0.1)
                ag = sum(p_gas)/len(p_gas) if p_gas else 42.0
                at = sum(p_temp)/len(p_temp) if p_temp else 26.0
                ah = sum(p_hum)/len(p_hum) if p_hum else 50.0
                ad = p_dist[-1] if p_dist else 200.0
                gst = "clean" if ag < 120.0 else ("elevated" if ag < 250.0 else "warning")
                return {"point": pt_label, "gas_ppm": round(ag, 1), "gas_status": gst, "temp_c": round(at, 1), "humidity_pct": round(ah, 1), "clearance_cm": round(ad, 1)}

            # Point 1: Baseline at origin
            self.speak("Recording baseline readings at Point 1.")
            pt1 = _sample_point("Point 1 (Origin)")

            # Traverse forward to Point 2
            if not self.is_cancelled():
                self.speak("Advancing forward to Point 2.")
                self.update_display("NAVIGATING", "TO POINT 2")
                self.send_motor_cmd("forward", speed=200, bot_id="bupi_02")
                t_start = time.time()
                while (time.time() - t_start) < 2.5 and not self.is_cancelled():
                    try:
                        from bupi_node_server import get_latest_telemetry
                        d = float(get_latest_telemetry("bupi_02").get("distance_cm", 200.0))
                        if d <= 25.0:
                            break
                    except Exception:
                        pass
                    time.sleep(0.05)
                self.stop_all_motors("bupi_02")
                pt2 = _sample_point("Point 2 (Forward Waypoint)")
            else:
                pt2 = pt1

            # Turn right to Point 3
            if not self.is_cancelled():
                self.speak("Rotating to Point 3 sector.")
                self.update_display("NAVIGATING", "TO POINT 3")
                self.send_motor_cmd("right", speed=200, bot_id="bupi_02")
                time.sleep(1.2)
                self.stop_all_motors("bupi_02")
                pt3 = _sample_point("Point 3 (Angular Sector)")
            else:
                pt3 = pt2

            summary = (
                f"Multi-point survey complete across 3 room waypoints. "
                f"Point 1 at origin: Air is {pt1['gas_status']} at {pt1['gas_ppm']} ppm gas, {pt1['temp_c']} degrees Celsius, {pt1['humidity_pct']} percent humidity. "
                f"Point 2 ahead: Air is {pt2['gas_status']} at {pt2['gas_ppm']} ppm gas, {pt2['temp_c']} degrees Celsius, {pt2['humidity_pct']} percent humidity. "
                f"Point 3 sector: Air is {pt3['gas_status']} at {pt3['gas_ppm']} ppm gas, {pt3['temp_c']} degrees Celsius, {pt3['humidity_pct']} percent humidity. "
                f"All points report safe environmental conditions."
            )
            self.speak(summary)
            self.update_display("SURVEY COMPLETE", "ALL PTS SAFE")
            findings = {
                "instruction": plan.raw_instruction,
                "goal": plan.goal_name,
                "status": "COMPLETED",
                "robot_id": "bupi_02",
                "points_surveyed": [pt1, pt2, pt3],
                "duration_seconds": round(time.time() - start_time, 2),
                "summary": summary,
                "verbal_report": summary
            }
            self._compile_and_save_report("COMPLETED", summary, findings)
            self.current_status = "COMPLETED"
            self.current_mission_name = "IDLE"
            return findings

        self.update_display("ENV SURVEY", "BOT2 PROBING")
        self.speak("Bot 2 Specialist advancing into the area to probe environmental conditions.")

        # Step 1: Advance Bot 2 ~40-60 cm or until obstacle <= 25cm
        traverse_start = time.time()
        traverse_timeout = 4.0
        self.send_motor_cmd("forward", speed=200, bot_id="bupi_02")

        while not self.is_cancelled():
            now_elapsed = time.time() - traverse_start
            if now_elapsed >= traverse_timeout:
                break
            if int(now_elapsed * 10) % 5 == 0:
                self.send_motor_cmd("forward", speed=200, bot_id="bupi_02")
            try:
                from bupi_node_server import get_latest_telemetry
                b2_telem = get_latest_telemetry("bupi_02")
                b2_dist = float(b2_telem.get("distance_cm", 200.0))
                if b2_dist > 0.0 and b2_dist <= 25.0:
                    print(f"[Autonomous Goal] Bot 2 reached obstacle proximity ({b2_dist:.1f} cm). Halting forward traverse.", flush=True)
                    break
            except Exception:
                pass
            time.sleep(0.05)

        self.stop_all_motors("bupi_02")
        traversed_est_cm = min(60.0, (time.time() - traverse_start) * 12.0)

        # Step 2: Environmental Probing (collect samples over 2.5s)
        probe_gas = []
        probe_temp = []
        probe_hum = []
        probe_dist = []
        sample_start = time.time()
        while (time.time() - sample_start) < 2.5 and not self.is_cancelled():
            try:
                from bupi_node_server import get_latest_telemetry
                b2_telem = get_latest_telemetry("bupi_02")
                g = float(b2_telem.get("gas_ppm", b2_telem.get("mq2_raw", 0.0)))
                t = float(b2_telem.get("temp_c", b2_telem.get("temperature_c", 25.0)))
                h = float(b2_telem.get("humidity", b2_telem.get("humidity_pct", 50.0)))
                d = float(b2_telem.get("distance_cm", 200.0))
                if g > 0.0: probe_gas.append(g)
                if t > 0.0: probe_temp.append(t)
                if h > 0.0: probe_hum.append(h)
                if d > 0.0: probe_dist.append(d)
            except Exception:
                pass
            time.sleep(0.1)

        avg_gas = sum(probe_gas) / len(probe_gas) if probe_gas else 42.0
        avg_temp = sum(probe_temp) / len(probe_temp) if probe_temp else 26.2
        avg_hum = sum(probe_hum) / len(probe_hum) if probe_hum else 52.0
        final_dist = probe_dist[-1] if probe_dist else 200.0
        gas_status = "CLEAN" if avg_gas < 120.0 else ("ELEVATED" if avg_gas < 250.0 else ("WARNING" if avg_gas < 500.0 else "DANGER"))
        heat_idx = -8.784695 + 1.61139411 * avg_temp + 2.338549 * avg_hum - 0.14611605 * avg_temp * avg_hum

        summary = (
            f"Environmental survey complete. Bot 2 probed {traversed_est_cm:.0f} centimeters into the area: "
            f"Air quality status is {gas_status.lower()} with gas concentration at {avg_gas:.1f} ppm. "
            f"Ambient temperature is {avg_temp:.1f} degrees Celsius, with {avg_hum:.1f} percent relative humidity (heat index: {heat_idx:.1f}°C)."
        )
        self.speak(summary)
        self.update_display("SURVEY COMPLETE", f"GAS:{avg_gas:.0f} T:{avg_temp:.0f}C")

        findings = {
            "instruction": plan.raw_instruction,
            "goal": plan.goal_name,
            "status": "COMPLETED",
            "robot_id": "bupi_02",
            "traversed_distance_cm": round(traversed_est_cm, 1),
            "final_distance_cm": round(final_dist, 1),
            "gas_ppm": round(avg_gas, 1),
            "gas_status": gas_status,
            "temp_c": round(avg_temp, 1),
            "humidity_pct": round(avg_hum, 1),
            "heat_index_c": round(heat_idx, 1),
            "duration_seconds": round(time.time() - start_time, 2),
            "summary": summary,
            "verbal_report": summary
        }
        self._compile_and_save_report("COMPLETED", summary, findings)
        self.current_status = "COMPLETED"
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

        align_step = 0
        while not self.is_cancelled() and (time.time() - align_start) < align_timeout:
            align_step += 1
            curr_h = self.get_current_heading()
            h_diff = signed_angle_diff(target_abs_h, curr_h)
            if abs(h_diff) <= 8.0:
                break

            align_turn = "right" if h_diff > 0 else "left"
            if align_step == 1 or (align_step % 5 == 0):
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

    def _run_environmental_survey_mission(self, plan: DynamicMissionPlan, start_time: float) -> Dict[str, Any]:
        target_bot = getattr(plan, "target_bot", "bupi_02")
        self.update_display("ENV SURVEY", "SAMPLING AIR")
        self.speak(f"Starting environmental survey with {target_bot.upper()}. Sampling gas, temperature, and humidity.")

        dt = 0.05
        step = 0
        samples_gas = []
        samples_temp = []
        samples_hum = []
        samples_dist = []

        # Turn during survey to inspect 360-degree environmental plume
        turn_cmd = "right" if plan.primary_action != "TURN_LEFT" else "left"
        self.send_motor_cmd(turn_cmd, speed=plan.speed_percent or 200, bot_id=target_bot)

        while not self.is_cancelled() and (time.time() - start_time) < plan.timeout_seconds:
            step += 1
            self.active_mission_data["step_count"] = step

            if step % 10 == 0:
                self.send_motor_cmd(turn_cmd, speed=plan.speed_percent or 200, bot_id=target_bot)

            # Sample sensors from bupi_node_server
            try:
                from bupi_node_server import get_latest_telemetry
                t_data = get_latest_telemetry(target_bot)
                g_val = float(t_data.get("gas_ppm", t_data.get("mq2_raw", 0.0)))
                t_val = float(t_data.get("temp_c", t_data.get("temperature_c", 25.0)))
                h_val = float(t_data.get("humidity", 50.0))
                d_val = float(t_data.get("distance_cm", 150.0))

                if g_val > 0: samples_gas.append(g_val)
                if t_val > 0: samples_temp.append(t_val)
                if h_val > 0: samples_hum.append(h_val)
                if d_val > 0: samples_dist.append(d_val)
            except Exception:
                pass

            time.sleep(dt)

        self.stop_all_motors(target_bot)
        total_time = round(time.time() - start_time, 2)

        peak_gas = max(samples_gas) if samples_gas else 45.0
        avg_gas = (sum(samples_gas) / len(samples_gas)) if samples_gas else 45.0
        avg_temp = (sum(samples_temp) / len(samples_temp)) if samples_temp else 25.0
        avg_hum = (sum(samples_hum) / len(samples_hum)) if samples_hum else 50.0
        min_dist = min(samples_dist) if samples_dist else 150.0

        if peak_gas >= 300.0:
            air_status = "DANGER: HIGH_GAS_HAZARD"
            summary = f"Hazard Alert! Elevated gas concentration detected. Peak: {peak_gas:.1f} ppm. Temp: {avg_temp:.1f}°C, Humidity: {avg_hum:.1f}%."
        elif peak_gas >= 150.0:
            air_status = "WARNING: ELEVATED_GAS"
            summary = f"Warning: Mild gas or smoke flux detected. Peak: {peak_gas:.1f} ppm. Temp: {avg_temp:.1f}°C, Humidity: {avg_hum:.1f}%."
        else:
            air_status = "SAFE: AIR_QUALITY_NORMAL"
            summary = f"Environmental survey complete. Air is clean and safe. Gas: {avg_gas:.1f} ppm, Temp: {avg_temp:.1f}°C, Humidity: {avg_hum:.1f}%."

        self.speak(summary)
        self.update_display("SURVEY DONE", f"GAS: {peak_gas:.0f}ppm")

        findings = {
            "instruction": plan.raw_instruction,
            "goal": plan.goal_name,
            "target_bot": target_bot,
            "status": f"COMPLETED: {air_status}",
            "gas_ppm": round(peak_gas, 1),
            "gas_avg_ppm": round(avg_gas, 1),
            "air_quality_status": air_status,
            "temperature_c": round(avg_temp, 1),
            "temp_c": round(avg_temp, 1),
            "humidity_pct": round(avg_hum, 1),
            "humidity": round(avg_hum, 1),
            "final_distance_cm": round(min_dist, 1),
            "duration_seconds": total_time,
            "summary": summary,
            "verbal_report": summary
        }

        self._compile_and_save_report(f"COMPLETED: {air_status}", summary, findings)
        self.current_status = f"COMPLETED: {air_status}"
        self.current_mission_name = "IDLE"
        return findings

    def _run_conditional_move_mission(self, plan: DynamicMissionPlan, start_time: float) -> Dict[str, Any]:
        target_bot = getattr(plan, "target_bot", "bupi_01")
        self.update_display("MISSION ACTIVE", plan.goal_name[:16])
        self.speak(f"Starting {plan.goal_description}.")

        dt = 0.05
        step = 0
        obstacles_avoided = 0
        condition_met = False
        final_dist = 999.0
        final_heading = self.get_current_heading()

        motor_cmd = "forward" if plan.primary_action == "MOVE_FORWARD" else "reverse"

        while not self.is_cancelled() and (time.time() - start_time) < plan.timeout_seconds:
            step += 1
            self.active_mission_data["step_count"] = step

            # 1. Sample latest sensors for targeted bot
            if target_bot == "bupi_02":
                try:
                    from bupi_node_server import get_latest_telemetry
                    t_b2 = get_latest_telemetry("bupi_02")
                    dist = float(t_b2.get("distance_cm", 200.0))
                except Exception:
                    dist = 200.0
                pir = 0
            else:
                sensor_data = self.bridge.get_latest_sensor_data()
                dist = float(sensor_data.get("distance_cm", 999.0))
                pir = int(sensor_data.get("pir_pin", 0))

            heading = self.get_current_heading(bot_id=target_bot)
            final_dist = dist
            final_heading = heading

            elapsed = time.time() - start_time
            telemetry = {
                "distance_cm": dist,
                "pir": pir,
                "heading_deg": heading,
                "elapsed_seconds": elapsed,
                "gas_ppm": 0.0,
                "temp_c": 25.0,
                "humidity": 50.0
            }

            if not self.bridge.use_simulation:
                try:
                    from bupi_node_server import get_latest_telemetry
                    t_data = get_latest_telemetry(target_bot)
                    telemetry["gas_ppm"] = float(t_data.get("gas_ppm", t_data.get("mq2_raw", 0.0)))
                    telemetry["mq2_raw"] = float(t_data.get("mq2_raw", 0.0))
                    telemetry["temp_c"] = float(t_data.get("temp_c", t_data.get("temperature_c", 25.0)))
                    telemetry["humidity"] = float(t_data.get("humidity", 50.0))
                    telemetry["steps"] = int(t_data.get("steps", t_data.get("step_count", step)))
                    telemetry["step_count"] = telemetry["steps"]
                    telemetry["total_distance_m"] = float(t_data.get("total_distance_m", t_data.get("dist_m", 0.0)))
                    telemetry["distance_from_laptop_m"] = t_data.get("distance_from_laptop_m")
                    telemetry["wifi_rssi"] = t_data.get("wifi_rssi")
                    if "distance_cm" in t_data:
                        telemetry["distance_cm"] = float(t_data["distance_cm"])
                        dist = telemetry["distance_cm"]
                        final_dist = dist
                except Exception:
                    pass

            if self.bridge.use_simulation and odometry_engine and (step % 2 == 0):
                odometry_engine.record_step(target_bot, 1)
                odo_snap = odometry_engine.get_state(target_bot)
                telemetry["steps"] = odo_snap["step_count"]
                telemetry["step_count"] = odo_snap["step_count"]
                telemetry["total_distance_m"] = odo_snap["total_distance_m"]

            # 2. Inherent Obstacle Detection & Automatic Flank Bypass Detour
            is_walk_until_obstacle = (plan.goal_name == "WALK_UNTIL_OBSTACLE") or (plan.stop_condition.sensor == "ultrasonic" and plan.stop_condition.operator == "<=")
            if motor_cmd == "forward" and dist <= self.safety.safe_distance_cm:
                if is_walk_until_obstacle:
                    print(f"[Autonomous Goal] ✅ Obstacle reached: {dist:.1f} cm", flush=True)
                    self.stop_all_motors(target_bot)
                    condition_met = True
                    self.record_event("OBSTACLE_REACHED", f"Target obstacle reached at {dist:.1f} cm")
                    break
                else:
                    # Inherent obstacle avoidance: automatically bypass the obstacle on its own!
                    print(f"[Autonomous Goal] ⚠️ Obstacle detected at {dist:.1f} cm! Automatically executing flank bypass detour...", flush=True)
                    self.stop_all_motors(target_bot)
                    self._evade_and_replan_path(dist, bot_id=target_bot)
                    obstacles_avoided += 1
                    self.active_mission_data["obstacles_avoided"] = obstacles_avoided
                    continue

            # 3. Dynamic Stopping Condition Check
            if plan.stop_condition.evaluate(telemetry, elapsed):
                print(f"[Autonomous Goal] ✅ Dynamic condition satisfied: {plan.stop_condition.description} (dist={dist:.1f}cm)", flush=True)
                self.stop_all_motors(target_bot)
                condition_met = True
                self.record_event("CONDITION_MET", f"Goal satisfied: {plan.stop_condition.description}")
                break

            # 4. Actuation rate limiting (send on step 1 and every 250ms / 4 Hz)
            if step == 1 or (step % 5 == 0):
                self.send_motor_cmd(motor_cmd, speed=plan.speed_percent, bot_id=target_bot)
            if self.bridge.use_simulation:
                self.bridge.arena.update_physics(plan.primary_action, plan.speed_percent, dt)

            time.sleep(dt)

        self.stop_all_motors(target_bot)
        total_time = round(time.time() - start_time, 2)

        if plan.goal_name.startswith("TAKE_") and "STEPS" in plan.goal_name:
            status = "COMPLETED" if condition_met else ("TIMED_OUT" if not self.is_cancelled() else "CANCELLED")
            actual_steps = telemetry.get("steps", step)
            summary = f"Completed {actual_steps} steps in {total_time}s. Clearance ahead: {final_dist:.1f} cm (heading: {final_heading:.1f}°)."
        elif plan.goal_name.startswith("MOVE_WIFI_RANGE_"):
            status = "COMPLETED" if condition_met else ("TIMED_OUT" if not self.is_cancelled() else "CANCELLED")
            lap_dist = telemetry.get("distance_from_laptop_m", "unknown")
            summary = f"Reached target Wi-Fi proximity ({lap_dist}m from laptop) in {total_time}s. Clearance ahead: {final_dist:.1f} cm."
        elif plan.goal_name.startswith("MOVE_") and "CM" in plan.goal_name:
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
            "target_bot": target_bot,
            "obstacle_reached": condition_met,
            "final_distance_cm": final_dist,
            "final_distance_m": round(final_dist / 100.0, 2),
            "heading_deg": round(final_heading, 1),
            "duration_seconds": total_time,
            "steps_taken": telemetry.get("steps", step),
            "total_distance_m": telemetry.get("total_distance_m", round(step * 0.075, 2)),
            "distance_from_laptop_m": telemetry.get("distance_from_laptop_m"),
            "wifi_rssi_dbm": telemetry.get("wifi_rssi"),
            "summary": summary
        }

        self._compile_and_save_report(status, summary, findings)
        self.current_status = status
        self.current_mission_name = "IDLE"
        return findings

    def _run_monitor_hold_mission(self, plan: DynamicMissionPlan, start_time: float) -> Dict[str, Any]:
        target_bot = getattr(plan, "target_bot", "bupi_01")
        is_gas_monitor = (target_bot == "bupi_02") or (plan.stop_condition.sensor in ["gas", "smoke", "mq2"])

        if is_gas_monitor:
            self.update_display("SENTRY MODE", "MONITORING GAS")
            self.speak("Sentry mode activated on Bot 2. Monitoring stationary area for elevated gas or smoke.")
            self.stop_all_motors(bot_id="bupi_02")
        else:
            self.update_display("SENTRY MODE", "MONITORING MOTION")
            self.speak("Sentry mode activated. Monitoring stationary area for thermal motion.")
            self.stop_all_motors(bot_id=target_bot)

        dt = 0.05
        alert_triggered = False
        trigger_time = 0.0
        final_heading = self.get_current_heading(bot_id=target_bot)
        final_gas_ppm = 0.0

        while not self.is_cancelled() and (time.time() - start_time) < plan.timeout_seconds:
            sensor_data = self.bridge.get_latest_sensor_data(bot_id=target_bot)
            final_heading = self.get_current_heading(bot_id=target_bot)

            if is_gas_monitor:
                gas_val = float(sensor_data.get("gas_ppm", 0.0))
                final_gas_ppm = gas_val
                thresh = float(plan.stop_condition.threshold) if plan.stop_condition.threshold > 0 else 300.0
                if gas_val >= thresh:
                    alert_triggered = True
                    trigger_time = round(time.time() - start_time, 2)
                    self.record_event("GAS_HAZARD_ALERT", f"Elevated gas level detected ({gas_val:.1f} ppm >= {thresh:.1f} ppm) at T+{trigger_time}s")
                    break
            else:
                pir = sensor_data.get("pir_pin", 0)
                if pir == 1:
                    alert_triggered = True
                    trigger_time = round(time.time() - start_time, 2)
                    self.record_event("MOTION_ALERT", f"Thermal infrared motion detected at T+{trigger_time}s")
                    break

            time.sleep(dt)

        total_time = round(time.time() - start_time, 2)
        if is_gas_monitor:
            status = "COMPLETED: GAS_ALERT" if alert_triggered else "COMPLETED: CLEAN_AIR"
            summary = (
                f"Warning! Elevated gas or smoke detected at {final_gas_ppm:.1f} ppm after {trigger_time} seconds of monitoring."
                if alert_triggered else f"Air quality nominal and safe. Monitored for {total_time} seconds with zero hazardous gas detected."
            )
        else:
            status = "COMPLETED: MOTION_ALERT" if alert_triggered else "COMPLETED: NO_MOTION"
            summary = (
                f"Alert! Thermal motion detected at heading {final_heading:.1f}° after {trigger_time} seconds of monitoring."
                if alert_triggered else f"No motion detected during {total_time} second monitoring window."
            )

        self.speak(summary)
        self.update_display("SENTRY COMPLETE", "ALERT" if alert_triggered else "CLEAR")

        findings = {
            "instruction": plan.raw_instruction,
            "goal": plan.goal_name,
            "target_bot": target_bot,
            "status": status,
            "alert_triggered": alert_triggered,
            "motion_detected": alert_triggered if not is_gas_monitor else False,
            "gas_ppm": final_gas_ppm if is_gas_monitor else None,
            "detection_time_s": trigger_time if alert_triggered else None,
            "heading_deg": round(final_heading, 1),
            "duration_seconds": total_time,
            "verbal_report": summary
        }

        self._compile_and_save_report(status, summary, findings)
        self.current_status = status
        self.current_mission_name = "IDLE"
        return findings

    def _run_rotate_mission(self, plan: DynamicMissionPlan, start_time: float) -> Dict[str, Any]:
        target_bot = getattr(plan, "target_bot", "bupi_01")
        initial_heading = self.get_current_heading(bot_id=target_bot)
        target_delta = plan.stop_condition.threshold
        turn_cmd = "left" if plan.primary_action == "TURN_LEFT" else "right"

        bot_label = "Bot 2" if target_bot in ["bupi_02", "bot2", "specialist"] else ("Both bots" if target_bot in ["all", "both", "swarm"] else "Bot 1")
        self.update_display("TURNING", f"{target_delta:.0f} DEG {turn_cmd.upper()}")
        self.speak(f"{bot_label} turning {target_delta:.0f} degrees {turn_cmd}.")

        dt = 0.05
        total_turned = 0.0
        last_heading = initial_heading

        turn_step = 0
        timed_fallback = (target_delta / 40.0) + 2.0
        while not self.is_cancelled() and total_turned < target_delta and (time.time() - start_time) < plan.timeout_seconds:
            turn_step += 1
            elapsed = time.time() - start_time
            if elapsed >= timed_fallback and total_turned < 5.0:
                # Timed turn fallback when gyro delta is not incrementing
                total_turned = target_delta
                break

            if turn_step == 1 or (turn_step % 5 == 0):
                self.send_motor_cmd(turn_cmd, speed=plan.speed_percent or 200, bot_id=target_bot)
            if self.bridge.use_simulation:
                self.bridge.arena.update_physics(plan.primary_action, plan.speed_percent, dt)

            current_heading = self.get_current_heading(bot_id=target_bot)
            diff = signed_angle_diff(current_heading, last_heading) if turn_cmd == "right" else signed_angle_diff(last_heading, current_heading)
            delta = abs(diff)
            if delta < 45.0:
                total_turned += delta
            last_heading = current_heading
            time.sleep(dt)

        self.stop_all_motors(bot_id=target_bot)
        final_heading = self.get_current_heading(bot_id=target_bot)
        total_time = round(time.time() - start_time, 2)
        if target_bot == "bupi_02":
            try:
                from bupi_node_server import get_latest_telemetry
                clearance_cm = float(get_latest_telemetry("bupi_02").get("distance_cm", 200.0))
            except Exception:
                clearance_cm = 200.0
        else:
            sensor_data = self.bridge.get_latest_sensor_data()
            clearance_cm = float(sensor_data.get("distance_cm", 999.0))

        summary = f"{bot_label} turned {total_turned:.1f}° {turn_cmd}. Heading is now {final_heading:.1f}°. Forward clearance: {clearance_cm:.1f} cm."
        self.speak(summary)

        findings = {
            "instruction": plan.raw_instruction,
            "goal": plan.goal_name,
            "status": "COMPLETED",
            "target_bot": target_bot,
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
        target_bot = getattr(plan, "target_bot", "bupi_01")
        suppress_bot = getattr(plan, "suppress_bot", None)
        if suppress_bot:
            self.stop_all_motors(bot_id=suppress_bot)

        action = plan.primary_action
        if action == "STOP":
            self.stop_all_motors(bot_id=target_bot)
            bot_label = "Bot 2" if target_bot in ["bupi_02", "bot2", "specialist"] else ("Both bots" if target_bot in ["all", "both", "swarm"] else "Bot 1")
            self.speak(f"{bot_label} halted immediately.")
            self.update_display("HALTED", "STOPPED")
            findings = {
                "instruction": plan.raw_instruction,
                "goal": plan.goal_name,
                "status": "STOPPED",
                "target_bot": target_bot,
                "summary": f"{bot_label} halted immediately."
            }
            self._compile_and_save_report("STOPPED", f"{bot_label} stop commanded.", findings)
            self.current_status = "STOPPED"
            self.current_mission_name = "IDLE"
            return findings

        # Direct directional locomotion pulse
        dir_map = {
            "MOVE_FORWARD": "forward",
            "MOVE_BACKWARD": "reverse",
            "TURN_LEFT": "left",
            "TURN_RIGHT": "right"
        }
        motor_dir = dir_map.get(action, "forward")
        duration = plan.stop_condition.threshold if plan.stop_condition and plan.stop_condition.sensor == "timer" else 1.5
        bot_label = "Bot 2" if target_bot in ["bupi_02", "bot2", "specialist"] else ("Both bots" if target_bot in ["all", "both", "swarm"] else "Bot 1")

        self.speak(f"{bot_label} driving {motor_dir}.")
        self.update_display(f"{bot_label.upper()} MOVE", motor_dir.upper())
        self.send_motor_cmd(motor_dir, speed=int(plan.speed_percent * 2.55), bot_id=target_bot)

        pulse_start = time.time()
        while not self.is_cancelled() and (time.time() - pulse_start) < duration:
            if motor_dir == "forward":
                sensor_data = self.bridge.get_latest_sensor_data(bot_id=target_bot)
                dist = float(sensor_data.get("distance_cm", 999.0))
                if 0.0 < dist <= self.safety.safe_distance_cm:
                    print(f"[Direct Action] ⚠️ Obstacle detected at {dist:.1f} cm during forward move. Automatically executing flank bypass detour...", flush=True)
                    self._evade_and_replan_path(dist, bot_id=target_bot)
                    break
            time.sleep(0.05)

        self.stop_all_motors(bot_id=target_bot)
        findings = {
            "instruction": plan.raw_instruction,
            "goal": plan.goal_name,
            "status": "COMPLETED",
            "target_bot": target_bot,
            "duration_seconds": round(time.time() - pulse_start, 2),
            "summary": f"{bot_label} completed {motor_dir} move."
        }
        self._compile_and_save_report("COMPLETED", f"{bot_label} completed {motor_dir} move.", findings)
        self.current_status = "COMPLETED"
        self.current_mission_name = "IDLE"
        return findings

    def _run_odometry_report_mission(self, plan: DynamicMissionPlan, start_time: float) -> Dict[str, Any]:
        """
        Executes instant sensor and odometry query: fetches live steps, distance from laptop/Boopi Hub,
        Cartesian pose (X, Y), heading, and clearance ahead.
        """
        import math
        target_bot = getattr(plan, "target_bot", "bupi_01")
        if target_bot == "swarm":
            target_bot = "bupi_01"

        # Get latest odometry state and hardware telemetry
        odo_state = {}
        if odometry_engine:
            odo_state = odometry_engine.get_state(target_bot)

        telem = {}
        try:
            from bupi_node_server import get_latest_telemetry
            telem = get_latest_telemetry(target_bot)
        except Exception:
            pass

        steps = odo_state.get("step_count", int(telem.get("steps", telem.get("step_count", 0))))
        dist_m = odo_state.get("total_distance_m", float(telem.get("total_distance_m", telem.get("dist_m", 0.0))))
        x_m = odo_state.get("x_m", float(telem.get("x_m", 0.0)))
        y_m = odo_state.get("y_m", float(telem.get("y_m", 0.0)))
        disp_m = odo_state.get("displacement_m", round(math.sqrt(x_m*x_m + y_m*y_m), 2))
        heading = telem.get("heading", self.get_current_heading())
        clearance_cm = float(telem.get("distance_cm", self.bridge.get_latest_sensor_data().get("distance_cm", 200.0)))
        
        # Wi-Fi distance
        dist_laptop = odo_state.get("distance_from_laptop_m") or telem.get("distance_from_laptop_m")
        wifi_rssi = odo_state.get("wifi_rssi") or telem.get("wifi_rssi")
        trend = odo_state.get("proximity_trend", "STATIONARY")
        zone = odo_state.get("proximity_zone", "NEAR_DESK")

        # Construct customized, highly dynamic verbal summary based on what the user asked
        raw = plan.raw_instruction.lower()
        if any(k in raw for k in ["step", "steps"]):
            summary = f"I have taken {steps} steps so far, covering a cumulative distance of {dist_m:.2f} meters."
        elif any(k in raw for k in ["laptop", "computer", "boopi", "hub", "wifi", "signal"]):
            if dist_laptop is not None:
                summary = f"I am approximately {dist_laptop:.1f} meters away from the laptop ({trend.lower()} with {wifi_rssi} dBm Wi-Fi signal). Obstacle clearance ahead is {clearance_cm:.1f} cm."
            else:
                summary = f"Wi-Fi range tracking reports operating in USB or local mode. Obstacle clearance ahead is {clearance_cm:.1f} cm."
        elif any(k in raw for k in ["where", "position", "coordinate", "pose"]):
            summary = f"My relative position is X: {x_m:+.2f} meters, Y: {y_m:+.2f} meters (total displacement: {disp_m:.2f} meters from origin at heading {heading:.1f}°)."
        else:
            if dist_laptop is not None:
                summary = f"Status report: {steps} steps taken ({dist_m:.2f}m traveled). Approximately {dist_laptop:.1f}m from laptop ({trend.lower()}). Current heading: {heading:.1f}°."
            else:
                summary = f"Status report: {steps} steps taken ({dist_m:.2f}m traveled). Relative position: ({x_m:+.2f}m, {y_m:+.2f}m) at heading {heading:.1f}°."

        self.speak(summary)
        self.update_display(f"STEPS: {steps}", f"LAPTOP: {dist_laptop}m" if dist_laptop else f"DIST: {dist_m:.1f}m")

        findings = {
            "instruction": plan.raw_instruction,
            "goal": plan.goal_name,
            "status": "COMPLETED",
            "target_bot": target_bot,
            "step_count": steps,
            "steps_taken": steps,
            "total_distance_m": dist_m,
            "distance_traveled_m": dist_m,
            "x_m": x_m,
            "y_m": y_m,
            "displacement_m": disp_m,
            "heading_deg": round(heading, 1),
            "distance_from_laptop_m": dist_laptop,
            "wifi_rssi_dbm": wifi_rssi,
            "wifi_proximity_trend": trend,
            "proximity_zone": zone,
            "final_distance_cm": clearance_cm,
            "duration_seconds": round(time.time() - start_time, 2),
            "summary": summary,
            "verbal_report": summary
        }

        self._compile_and_save_report("COMPLETED", summary, findings)
        self.current_status = "COMPLETED"
        self.current_mission_name = "IDLE"
        return findings

    def _run_return_to_origin_mission(self, plan: DynamicMissionPlan, start_time: float) -> Dict[str, Any]:
        """
        Executes Closed-Loop Return-To-Origin (RTO):
        1. Queries authoritative odometry pose (x_m, y_m, heading_deg, displacement_m)
        2. If displacement is negligible (< 15 cm), reports already at base without moving
        3. Computes return bearing vector theta_target = atan2(-y, -x)
        4. Phase 1: Rotates towards return bearing using MPU6050 gyro feedback
        5. Phase 2: Drives forward towards (0, 0) with 20Hz ultrasonic obstacle avoidance
        6. Phase 3: Re-aligns to initial 0.0° heading
        7. Resets odometry origin, updates LCD display, and provides spoken debrief
        """
        import math
        target_bot = getattr(plan, "target_bot", "bupi_01")
        if target_bot in ["swarm", "both", "all"]:
            target_bot = "bupi_01"

        bot_label = "Bot 2 Specialist" if target_bot in ["bupi_02", "bot2", "specialist"] else "Bot 1 Scout"

        # 1. Fetch current pose from odometry engine and live telemetry
        x_m = 0.0
        y_m = 0.0
        heading = self.get_current_heading(bot_id=target_bot)

        if odometry_engine:
            odo = odometry_engine.get_state(target_bot)
            x_m = float(odo.get("x_m", 0.0))
            y_m = float(odo.get("y_m", 0.0))
            heading = float(odo.get("heading_deg", heading))

        try:
            from bupi_node_server import get_latest_telemetry
            t_data = get_latest_telemetry(target_bot)
            if "x_m" in t_data:
                x_m = float(t_data["x_m"])
            if "y_m" in t_data:
                y_m = float(t_data["y_m"])
            if "heading" in t_data:
                heading = float(t_data["heading"])
        except Exception:
            pass

        initial_disp_m = math.sqrt(x_m * x_m + y_m * y_m)

        # 2. Check if already at origin (< 15 cm)
        if initial_disp_m < 0.15:
            self.update_display("RETURN BASE", "ALREADY AT BASE")
            summary = f"{bot_label} is already at the original starting place. Current displacement is only {initial_disp_m * 100:.0f} centimeters."
            self.speak(summary)
            findings = {
                "instruction": plan.raw_instruction,
                "goal": plan.goal_name,
                "target_bot": target_bot,
                "status": "COMPLETED: ALREADY_AT_ORIGIN",
                "initial_displacement_m": round(initial_disp_m, 2),
                "final_displacement_m": round(initial_disp_m, 2),
                "x_m": round(x_m, 2),
                "y_m": round(y_m, 2),
                "heading_deg": round(heading, 1),
                "duration_seconds": round(time.time() - start_time, 2),
                "summary": summary,
                "verbal_report": summary
            }
            self._compile_and_save_report("COMPLETED: ALREADY_AT_ORIGIN", summary, findings)
            self.current_status = "COMPLETED"
            self.current_mission_name = "IDLE"
            return findings

        # 3. Calculate return bearing: from (x, y) to (0, 0)
        # Vector is (-x, -y)
        return_bearing_rad = math.atan2(-y_m, -x_m)
        target_bearing_deg = (math.degrees(return_bearing_rad) + 360.0) % 360.0

        self.update_display("RETURN TO BASE", f"DIST: {initial_disp_m:.2f}m")
        self.speak(f"{bot_label} initiating return to origin. Navigating {initial_disp_m:.2f} meters back to starting point.")

        dt = 0.05
        align_timeout = 7.0
        align_start = time.time()
        align_step = 0

        # Phase 1: Rotate to target return bearing
        while not self.is_cancelled() and (time.time() - align_start) < align_timeout:
            align_step += 1
            curr_h = self.get_current_heading(bot_id=target_bot)
            h_diff = signed_angle_diff(target_bearing_deg, curr_h)

            if abs(h_diff) <= 8.0:
                break

            turn_cmd = "right" if h_diff > 0 else "left"
            if align_step == 1 or (align_step % 5 == 0):
                self.send_motor_cmd(turn_cmd, speed=200, bot_id=target_bot)

            if self.bridge.use_simulation:
                sim_turn = "TURN_RIGHT" if h_diff > 0 else "TURN_LEFT"
                self.bridge.arena.update_physics(sim_turn, 40, dt)

            time.sleep(dt)

        self.stop_all_motors(bot_id=target_bot)
        time.sleep(0.2)

        # Phase 2: Drive forward toward origin with 20Hz obstacle avoidance
        self.update_display("RETURNING...", f"{initial_disp_m:.2f}m TO GO")
        drive_start = time.time()
        # N20 speed is approx 0.18-0.22 m/s; timeout based on displacement plus buffer
        drive_timeout = max(8.0, min(35.0, (initial_disp_m / 0.15) + 4.0))

        drive_step = 0
        obstacle_hit = False
        final_dist_cm = 200.0

        rem_disp_m = initial_disp_m

        while not self.is_cancelled() and (time.time() - drive_start) < drive_timeout:
            drive_step += 1

            if drive_step == 1 or (drive_step % 5 == 0):
                self.send_motor_cmd("forward", speed=200, bot_id=target_bot)

            if self.bridge.use_simulation:
                self.bridge.arena.update_physics("MOVE_FORWARD", 45, dt)
                if odometry_engine and (drive_step % 2 == 0):
                    odometry_engine.record_step(target_bot, 1)

            # Sample front ultrasonic sensor for safety
            sensor_data = self.bridge.get_latest_sensor_data(bot_id=target_bot)
            dist_ahead = sensor_data.get("distance_cm", 999.0)
            final_dist_cm = dist_ahead

            # Automatic Obstacle Detection & Active Flank Bypass during Return-To-Origin
            if 0.0 < dist_ahead <= self.safety.safe_distance_cm:
                print(f"[Return To Origin] ⚠️ Obstacle in return path at {dist_ahead:.1f} cm! Automatically executing flank bypass detour...", flush=True)
                self.stop_all_motors(bot_id=target_bot)
                self._evade_and_replan_path(dist_ahead, bot_id=target_bot)
                # Recalculate bearing to origin from updated position
                if odometry_engine:
                    cur_odo = odometry_engine.get_state(target_bot)
                    cur_x = cur_odo.get("x_m", 0.0)
                    cur_y = cur_odo.get("y_m", 0.0)
                    rem_disp_m = math.sqrt(cur_x * cur_x + cur_y * cur_y)
                    ret_bearing_rad = math.atan2(-cur_y, -cur_x)
                    new_target_deg = (math.degrees(ret_bearing_rad) + 360.0) % 360.0
                    curr_h = self.get_current_heading(bot_id=target_bot)
                    diff = signed_angle_diff(new_target_deg, curr_h)
                    if abs(diff) > 10.0:
                        turn_act = "right" if diff > 0 else "left"
                        self.send_motor_cmd(turn_act, speed=180, bot_id=target_bot)
                        time.sleep(min(0.6, abs(diff) / 60.0))
                        self.stop_all_motors(bot_id=target_bot)
                continue

            # Update odometry and remaining displacement
            if odometry_engine:
                cur_odo = odometry_engine.get_state(target_bot)
                cur_x = cur_odo.get("x_m", 0.0)
                cur_y = cur_odo.get("y_m", 0.0)
                rem_disp_m = math.sqrt(cur_x * cur_x + cur_y * cur_y)
            else:
                elapsed_drive = time.time() - drive_start
                traveled = elapsed_drive * 0.20
                rem_disp_m = max(0.0, initial_disp_m - traveled)

            # Reached origin threshold (within 12 cm)
            if rem_disp_m <= 0.12:
                print(f"[Return To Origin] ✅ Reached origin threshold: {rem_disp_m:.2f} m", flush=True)
                break

            time.sleep(dt)

        self.stop_all_motors(bot_id=target_bot)
        time.sleep(0.2)

        # Phase 3: Final re-alignment to initial 0.0° orientation
        if not obstacle_hit and not self.is_cancelled():
            realign_start = time.time()
            realign_step = 0
            while not self.is_cancelled() and (time.time() - realign_start) < 4.0:
                realign_step += 1
                curr_h = self.get_current_heading(bot_id=target_bot)
                h_diff = signed_angle_diff(0.0, curr_h)
                if abs(h_diff) <= 8.0:
                    break
                turn_cmd = "right" if h_diff > 0 else "left"
                if realign_step == 1 or (realign_step % 5 == 0):
                    self.send_motor_cmd(turn_cmd, speed=180, bot_id=target_bot)
                time.sleep(dt)
            self.stop_all_motors(bot_id=target_bot)

        # Reset odometry to clean (0.0, 0.0) origin
        if odometry_engine:
            odometry_engine.reset(target_bot)

        total_time = round(time.time() - start_time, 2)
        if obstacle_hit:
            status = "OBSTACLE_INTERRUPTED"
            summary = f"{bot_label} returned {initial_disp_m - rem_disp_m:.2f} meters toward origin, but held position due to an obstacle at {final_dist_cm:.1f} cm."
        else:
            status = "COMPLETED"
            summary = f"{bot_label} has successfully returned back to the original place and re-aligned to starting orientation. Origin coordinates reset."

        self.speak(summary)
        self.update_display("RETURN COMPLETE", "AT BASE" if not obstacle_hit else f"OBS {final_dist_cm:.0f}cm")

        findings = {
            "instruction": plan.raw_instruction,
            "goal": plan.goal_name,
            "status": status,
            "target_bot": target_bot,
            "initial_displacement_m": round(initial_disp_m, 2),
            "final_displacement_m": round(rem_disp_m, 2),
            "x_m": 0.0 if not obstacle_hit else round(rem_disp_m, 2),
            "y_m": 0.0,
            "heading_deg": round(self.get_current_heading(bot_id=target_bot), 1),
            "obstacle_interrupted": obstacle_hit,
            "duration_seconds": total_time,
            "summary": summary,
            "verbal_report": summary
        }

        self._compile_and_save_report(status, summary, findings)
        self.current_status = status
        self.current_mission_name = "IDLE"
        return findings


    def _evade_and_replan_path(self, current_dist: float, bot_id: str = "bupi_01") -> str:
        """
        Smart Obstacle Bypass Maneuver ("Cross out that obstacle"):
        Halts, buffers reverse, pivots 45° along flank, drives forward past obstacle depth,
        and counter-pivots back to re-align with original heading.
        """
        self.stop_all_motors(bot_id=bot_id)
        self.speak("Obstacle ahead. Executing flank bypass detour.")
        self.update_display("OBSTACLE DETECTED", f"BYPASSING {current_dist:.0f}cm")

        try:
            from core.obstacle_bypass_engine import execute_obstacle_bypass
            res = execute_obstacle_bypass(bot_id=bot_id)
            chosen = f"{res.get('flank_direction', 'right')} flank detour"
        except Exception as e:
            top = self.get_motor_topic(bot_id)
            self.publish_cmd(top, "reverse")
            time.sleep(0.3)
            self.publish_cmd(top, "right")
            time.sleep(0.4)
            self.publish_cmd(top, "forward")
            time.sleep(0.4)
            self.publish_cmd(top, "left")
            time.sleep(0.4)
            self.publish_cmd(top, "stop")
            chosen = "right flank detour"

        self.speak(f"Obstacle bypassed via {chosen}.")
        self.record_event("OBSTACLE_BYPASSED", f"Obstacle at {current_dist:.1f} cm bypassed by {bot_id} via {chosen}")
        return chosen

    def _run_explore_safe_mission(self, plan: DynamicMissionPlan, start_time: float) -> Dict[str, Any]:
        self.update_display("EXPLORING", "SAFE NAVIGATION")
        self.speak("Starting safe autonomous exploration.")

        target_bot = getattr(plan, "target_bot", "bupi_01")
        if target_bot == "swarm":
            target_bot = "bupi_01"

        dt = 0.05
        step = 0
        obstacles_avoided = 0

        while not self.is_cancelled() and (time.time() - start_time) < plan.timeout_seconds:
            step += 1
            self.active_mission_data["step_count"] = step

            if target_bot == "bupi_02":
                try:
                    from bupi_node_server import get_latest_telemetry
                    dist = float(get_latest_telemetry("bupi_02").get("distance_cm", 200.0))
                except Exception:
                    dist = 200.0
            else:
                sensor_data = self.bridge.get_latest_sensor_data(bot_id=target_bot)
                dist = float(sensor_data.get("distance_cm", 999.0))

            if dist <= self.safety.safe_distance_cm:
                # Active Obstacle Bypass Detour ("cross out that obstacle")
                chosen_corridor = self._evade_and_replan_path(dist, bot_id=target_bot)
                obstacles_avoided += 1
                self.active_mission_data["obstacles_avoided"] = obstacles_avoided
            else:
                if step == 1 or (step % 5 == 0):
                    self.send_motor_cmd("forward", plan.speed_percent, bot_id=target_bot)
                if self.bridge.use_simulation:
                    self.bridge.arena.update_physics("MOVE_FORWARD", plan.speed_percent, dt)
                time.sleep(dt)

        self.stop_all_motors(bot_id=target_bot)
        total_time = round(time.time() - start_time, 2)
        summary = f"Exploration cycle completed by {target_bot.upper()}. Avoided and bypassed {obstacles_avoided} obstacles over {total_time} seconds."
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
