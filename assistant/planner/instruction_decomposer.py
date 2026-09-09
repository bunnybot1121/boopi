"""
BUPI Dynamic Instruction Decomposer
===================================
Translates ANY arbitrary natural language instruction into a structured,
executable robotic mission plan with dynamic stopping conditions, sensory
requirements, and data reporting specifications.

Does NOT rely on rigid if/else trees:
1. Analyzes the semantics of the user's intent.
2. Extracts directional action, target sensors, and dynamic stopping criteria
   (e.g., distance <= threshold, motion detected, target angle, or timeout).
3. Uses LLM Gateway (Gemini / Groq / Local) with an intelligent, multi-pattern
   semantic parser fallback.
"""

import re
import os
import json
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum

class PolicyType(str, Enum):
    CONDITIONAL_MOVE = "CONDITIONAL_MOVE"       # Move until a sensor threshold is met (e.g. walk until obstacle)
    SCAN_SWEEP = "SCAN_SWEEP"                   # Rotate/sweep sensors across sectors (e.g. find humans / map room)
    MONITOR_HOLD = "MONITOR_HOLD"               # Stay stationary and alert on sensor changes (e.g. sentry mode)
    ROTATE_TO = "ROTATE_TO"                     # Turn to specific relative or absolute heading
    EXPLORE_SAFE = "EXPLORE_SAFE"               # Continuous navigation with reactive obstacle avoidance
    PATROL = "PATROL"                           # Perimeter / looping inspection
    DIRECT_ACTION = "DIRECT_ACTION"             # Immediate atomic action (e.g. halt, brake)
    APPROACH_TARGET = "APPROACH_TARGET"         # Locate target via scan, rotate to bearing, and approach to safe distance

@dataclass
class DynamicStopCondition:
    sensor: str          # "ultrasonic", "pir", "imu_heading", "timer", "none"
    operator: str        # "<=", ">=", "==", "!=", "detect", "timeout"
    threshold: float     # e.g. 25.0 cm, 360.0 deg, 10.0 sec
    description: str     # e.g. "Obstacle within 25.0 cm"

    def evaluate(self, telemetry: Dict[str, Any], elapsed_time: float) -> bool:
        """
        Evaluates whether this dynamic stopping condition has been satisfied.
        """
        if self.sensor == "ultrasonic":
            dist = telemetry.get("distance_cm", 999.0)
            if self.operator == "<=":
                return dist <= self.threshold
            elif self.operator == ">=":
                return dist >= self.threshold

        elif self.sensor == "pir":
            pir_val = telemetry.get("pir", 0)
            if self.operator in ["==", "detect"]:
                return pir_val == 1

        elif self.sensor == "imu_heading":
            delta_angle = abs(telemetry.get("heading_delta_deg", 0.0))
            if self.operator == ">=":
                return delta_angle >= self.threshold

        elif self.sensor == "timer":
            return elapsed_time >= self.threshold

        return False

@dataclass
class DynamicMissionPlan:
    raw_instruction: str
    goal_name: str
    goal_description: str
    policy_type: PolicyType
    primary_action: str                 # "MOVE_FORWARD", "MOVE_BACKWARD", "TURN_LEFT", "TURN_RIGHT", "STOP"
    speed_percent: int                  # 0 to 100
    stop_condition: DynamicStopCondition
    timeout_seconds: float = 30.0
    sample_sensors: List[str] = field(default_factory=lambda: ["ultrasonic", "pir", "imu"])
    report_fields: List[str] = field(default_factory=lambda: ["final_distance_cm", "heading_deg", "status", "duration_seconds"])
    next_plan: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "raw_instruction": self.raw_instruction,
            "goal_name": self.goal_name,
            "goal_description": self.goal_description,
            "policy_type": self.policy_type.value,
            "primary_action": self.primary_action,
            "speed_percent": self.speed_percent,
            "stop_condition": asdict(self.stop_condition) if hasattr(self.stop_condition, "__dataclass_fields__") else self.stop_condition,
            "timeout_seconds": self.timeout_seconds,
            "sample_sensors": list(self.sample_sensors),
            "report_fields": list(self.report_fields),
            "next_plan": self.next_plan.to_dict() if (self.next_plan and hasattr(self.next_plan, "to_dict")) else None
        }
        return d


class InstructionDecomposer:
    def __init__(self, use_llm: bool = True):
        self.use_llm = use_llm
        self._llm_gateway = None

    def _get_llm_gateway(self):
        if self._llm_gateway is None:
            try:
                from services.llm_gateway import LLMGateway
                self._llm_gateway = LLMGateway()
            except Exception:
                self._llm_gateway = None
            return self._llm_gateway

    def decompose(self, instruction: str) -> DynamicMissionPlan:
        """
        Decomposes ANY free-form user instruction into a DynamicMissionPlan.
        """
        cleaned = instruction.strip()

        # 1. Try Fast Semantic Decomposition (dynamic regex/pattern analyzer)
        fast_plan = self._semantic_decompose(cleaned)
        if fast_plan is not None:
            return fast_plan

        # 2. If semantic parsing needs deeper reasoning, use LLM Gateway
        if self.use_llm:
            llm_plan = self._llm_decompose(cleaned)
            if llm_plan is not None:
                return llm_plan

        # 3. Default Safe Fallback: Cautious Exploration
        return DynamicMissionPlan(
            raw_instruction=instruction,
            goal_name="EXPLORE_CAUTIOUS",
            goal_description=f"Execute cautious autonomous action for: {instruction}",
            policy_type=PolicyType.EXPLORE_SAFE,
            primary_action="MOVE_FORWARD",
            speed_percent=40,
            stop_condition=DynamicStopCondition(
                sensor="timer",
                operator="timeout",
                threshold=15.0,
                description="Default 15-second exploratory timeout"
            ),
            timeout_seconds=15.0
        )

    def _semantic_decompose(self, text: str) -> Optional[DynamicMissionPlan]:
        """
        Dynamic semantic analyzer that parses condition, direction, distance,
        and objectives from natural language text.
        Supports compound instruction chaining (e.g. 'move 10 cm, scan the room').
        """
        compound_plan = self._check_compound_instruction(text)
        if compound_plan is not None:
            return compound_plan
        return self._semantic_decompose_single(text)

    def _check_compound_instruction(self, text: str) -> Optional[DynamicMissionPlan]:
        """
        Detects and chains multi-step instructions (e.g. 'move 10 cm, scan the room').
        Ensures both sub-parts are valid autonomous goals before forming a sequence.
        """
        lower = text.lower().strip()
        # Avoid splitting conditional/subordinate triggers (e.g. 'if you find a person, move towards him')
        if lower.startswith(("if ", "when ", "whenever ", "while ", "as soon as ")):
            return None

        # Split on sequence connectors: ';', ', then', ' then ', ', and then', ' and then ', ', and ', or ', '
        split_patterns = [
            r";\s*",
            r"\s*,\s*(?:and\s+)?then\s+",
            r"\s+(?:and\s+)?then\s+",
            r"\s*,\s*and\s+",
            r"\s*,\s*"
        ]

        for pattern in split_patterns:
            parts = re.split(pattern, text, maxsplit=1, flags=re.IGNORECASE)
            if len(parts) == 2:
                p1_text = parts[0].strip()
                p2_text = parts[1].strip()
                if len(p1_text) < 3 or len(p2_text) < 3:
                    continue
                # Clean leading conversational conjunctions from p2
                p2_clean = re.sub(r"^(then|and|so|that|please|also)\s+", "", p2_text, flags=re.IGNORECASE).strip()
                if not p2_clean:
                    continue

                plan1 = self._semantic_decompose_single(p1_text)
                if plan1 is not None:
                    # p2 may itself be compound
                    plan2 = self._semantic_decompose(p2_clean)
                    if plan2 is not None:
                        plan1.next_plan = plan2
                        plan1.raw_instruction = text
                        plan1.goal_name = f"{plan1.goal_name}_THEN_{plan2.goal_name}"
                        plan1.goal_description = f"{plan1.goal_description}, then {plan2.goal_description}"
                        return plan1
        return None

    def _semantic_decompose_single(self, text: str) -> Optional[DynamicMissionPlan]:
        """
        Dynamic semantic analyzer that parses condition, direction, distance,
        and objectives from natural language text for an atomic step.
        """
        try:
            from agents.router_agent import normalize_stt_command
            lower = normalize_stt_command(text)
        except Exception:
            lower = text.lower()

        # Stop / Halt Commands (only if not a sentry / monitoring instruction)
        is_monitor = bool(re.search(r"\b(monitor|watch|alert|motion|movement|moves|listen)\b", lower))
        if not is_monitor and re.search(r"\b(stop|halt|freeze|pause|brake|stay still|cancel|emergency stop)\b", lower):
            return DynamicMissionPlan(
                raw_instruction=text,
                goal_name="EMERGENCY_STOP",
                goal_description="Immediately halt all motors and remain stationary",
                policy_type=PolicyType.DIRECT_ACTION,
                primary_action="STOP",
                speed_percent=0,
                stop_condition=DynamicStopCondition(
                    sensor="none",
                    operator="==",
                    threshold=0,
                    description="Immediate halt requested"
                ),
                timeout_seconds=0.1
            )

        # Relative Distance Moves (Dynamic: any distance value and unit)
        # e.g., "move the bot 10 cm", "move 12 cm", "cover that 15 centimeter distance", "drive forward 20 cm", "move back 10 cm", "step 0.5 meters"
        dist_match = re.search(r"(\d+(?:\.\d+)?)\s*(cm|centimeter|centimeters|cms|m|meter|meters|inch|inches|mm|millimeters)\b", lower)
        is_move = bool(re.search(r"\b(move|drive|walk|go|cover|advance|step|reverse|back|forward|ahead|crawl|bot|robot)\b", lower))
        if dist_match and is_move and not re.search(r"\buntil\b", lower):
            val = float(dist_match.group(1))
            unit = dist_match.group(2).lower()
            if unit in ["m", "meter", "meters"]:
                target_cm = val * 100.0
            elif unit in ["inch", "inches"]:
                target_cm = val * 2.54
            elif unit in ["mm", "millimeters"]:
                target_cm = val / 10.0
            else:
                target_cm = val

            is_reverse = bool(re.search(r"\b(back|backward|backwards|reverse)\b", lower))
            primary_action = "MOVE_BACKWARD" if is_reverse else "MOVE_FORWARD"
            
            # Calibrated physical speed: travels ~20 cm/sec at 50% PWM
            SPEED_CM_PER_SEC = 20.0
            duration_s = max(0.15, round(target_cm / SPEED_CM_PER_SEC, 2))
            
            return DynamicMissionPlan(
                raw_instruction=text,
                goal_name=f"MOVE_{int(target_cm)}_CM",
                goal_description=f"Move {target_cm:.1f} cm {'backward' if is_reverse else 'forward'}",
                policy_type=PolicyType.CONDITIONAL_MOVE,
                primary_action=primary_action,
                speed_percent=50,
                stop_condition=DynamicStopCondition(
                    sensor="timer",
                    operator="timeout",
                    threshold=duration_s,
                    description=f"Covered {target_cm:.1f} cm target distance"
                ),
                timeout_seconds=duration_s + 3.0,
                sample_sensors=["ultrasonic", "imu"],
                report_fields=["target_distance_cm", "final_distance_cm", "heading_deg", "duration_seconds"]
            )

        # Walk / Drive until Obstacle
        # e.g., "walk until an obstacle comes in front of you", "drive forward until you hit something",
        # "move ahead until wall", "go forward until obstacle is 30cm away"
        if re.search(r"\b(walk|drive|move|go|run|crawl)\b.*?\buntil\b.*?\b(obstacle|wall|something|object|barrier|block|front)\b", lower) or \
           re.search(r"\buntil\b.*?\b(obstacle|wall|something|object)\b", lower) or \
           re.search(r"\b(drive|move|walk)\b.*?\btoward(s)?\b.*?\b(obstacle|wall)\b", lower):
            
            # Extract target distance threshold if specified (e.g., "until 30cm away")
            dist_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:cm|centimeter|centimeters)", lower)
            if dist_match:
                threshold_cm = float(dist_match.group(1))
            else:
                m_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|meter|meters)", lower)
                if m_match:
                    threshold_cm = float(m_match.group(1)) * 100.0
                else:
                    threshold_cm = 25.0  # Standard safe obstacle threshold

            return DynamicMissionPlan(
                raw_instruction=text,
                goal_name="WALK_UNTIL_OBSTACLE",
                goal_description=f"Drive forward until an obstacle is detected within {threshold_cm} cm",
                policy_type=PolicyType.CONDITIONAL_MOVE,
                primary_action="MOVE_FORWARD",
                speed_percent=50,
                stop_condition=DynamicStopCondition(
                    sensor="ultrasonic",
                    operator="<=",
                    threshold=threshold_cm,
                    description=f"Obstacle detected at or below {threshold_cm} cm"
                ),
                timeout_seconds=40.0,
                sample_sensors=["ultrasonic", "imu"],
                report_fields=["final_distance_cm", "heading_deg", "obstacle_reached", "duration_seconds"]
            )

        # Target Approach & Move Towards Commands (Search, Align, and Move Towards)
        # e.g. "whenever you find any person, just move towards him in the room",
        # "scan the room and if you find any person, move towards it",
        # "find any person and move towards him", "move towards the person", "approach the person", "go towards the person"
        if re.search(r"\b(move towards|go towards|drive towards|walk towards|approach|get closer to|move to|go to|reach)\b.*?\b(him|her|them|it|person|human|someone|target)\b", lower) or \
           re.search(r"\b(whenever|if|when)\b.*?\b(find|detect|see|locate)\b.*?\b(person|human|someone|target)\b.*?\b(move|go|drive|walk|approach)\b", lower) or \
           re.search(r"\b(find|locate|search)\b.*?\b(person|human|someone)\b.*?\b(move towards|approach|go towards|move to)\b", lower):
            return DynamicMissionPlan(
                raw_instruction=text,
                goal_name="APPROACH_TARGET",
                goal_description="Scan 360 degrees to locate human target, rotate to target bearing, and drive forward to safe approach distance",
                policy_type=PolicyType.APPROACH_TARGET,
                primary_action="MOVE_FORWARD",
                speed_percent=45,
                stop_condition=DynamicStopCondition(
                    sensor="ultrasonic",
                    operator="<=",
                    threshold=35.0,
                    description="Safe standoff distance (35 cm) reached"
                ),
                timeout_seconds=35.0,
                sample_sensors=["pir", "ultrasonic", "imu"],
                report_fields=["target_detected", "distance_m", "relative_bearing_deg", "final_distance_cm", "status", "verbal_report"]
            )

        # Headcount & People Counting Commands
        # e.g. "find the number of people in the room", "how many people are in the room?", "count people", "how many humans", "count the people"
        if re.search(r"\b(how many|number of|count|count the|total number of)\b.*?\b(people|persons|humans|someone|individuals|bodies|occupants)\b", lower) or \
           re.search(r"\b(people count|headcount|occupancy count)\b", lower):
            return DynamicMissionPlan(
                raw_instruction=text,
                goal_name="COUNT_PEOPLE",
                goal_description="Perform 360-degree rotational scan to cluster spatial targets and count the number of people in the room",
                policy_type=PolicyType.SCAN_SWEEP,
                primary_action="TURN_RIGHT",
                speed_percent=45,
                stop_condition=DynamicStopCondition(
                    sensor="imu_heading",
                    operator=">=",
                    threshold=360.0,
                    description="Full 360-degree scan sweep completed"
                ),
                timeout_seconds=30.0,
                sample_sensors=["pir", "ultrasonic", "imu"],
                report_fields=["people_count", "targets", "target_detected", "distance_m", "heading_deg", "confidence", "direction_description"]
            )

        # Presence / Human / Room Search Commands
        # e.g. "are there any humans in the room?", "is anyone here?", "find person", "search room for people", "scan the room", "scan"
        if not re.search(r"\b(what did you find|show findings|last mission|mission report|tell me what you found)\b", lower) and (
            re.search(r"\b(human|humans|person|people|someone|anyone|anybody|presence|body)\b", lower) or \
            re.search(r"\b(find|search|locate|detect)\b.*?\b(human|person|people|someone|anyone|occupant|intruder)\b", lower) or \
            re.search(r"\b(scan|sweep)\b.*?\b(room|area|surroundings|around|environment|space)\b", lower) or \
            re.search(r"^(scan|sweep|scan room|scan area)$", lower.strip())
        ):
            return DynamicMissionPlan(
                raw_instruction=text,
                goal_name="SEARCH_HUMAN_PRESENCE",
                goal_description="Perform 360-degree room scan correlating PIR thermal flux and ultrasonic distance",
                policy_type=PolicyType.SCAN_SWEEP,
                primary_action="TURN_RIGHT",
                speed_percent=45,
                stop_condition=DynamicStopCondition(
                    sensor="imu_heading",
                    operator=">=",
                    threshold=360.0,
                    description="Full 360-degree scan sweep completed"
                ),
                timeout_seconds=30.0,
                sample_sensors=["pir", "ultrasonic", "imu"],
                report_fields=["target_detected", "distance_m", "relative_bearing_deg", "heading_deg", "confidence", "direction_description"]
            )

        # Sentry / Motion Monitoring Commands
        # e.g. "watch this area and alert me if anything moves", "stay still and detect motion", "monitor for movement"
        if re.search(r"\b(monitor|watch|alert|sentry|listen)\b.*?\b(motion|movement|move)\b", lower) or \
           re.search(r"\balert\b.*?\bif\b.*?\bmoves\b", lower):
            return DynamicMissionPlan(
                raw_instruction=text,
                goal_name="MONITOR_MOTION_SENTRY",
                goal_description="Hold stationary position and monitor PIR sensor for thermal motion events",
                policy_type=PolicyType.MONITOR_HOLD,
                primary_action="STOP",
                speed_percent=0,
                stop_condition=DynamicStopCondition(
                    sensor="pir",
                    operator="==",
                    threshold=1.0,
                    description="Thermal motion flux detected"
                ),
                timeout_seconds=60.0,
                sample_sensors=["pir", "imu"],
                report_fields=["motion_detected", "detection_time_s", "heading_deg", "raw_pir"]
            )

        # Rotation / Turn to Angle Commands
        # e.g. "turn 90 degrees left", "spin 180 degrees", "turn around", "rotate 90 degrees"
        deg_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:deg|degree|degrees)", lower)
        is_turn_around = bool(re.search(r"\b(turn around|spin around|rotate around|about face)\b", lower))
        turn_action_match = re.search(r"\b(turn|spin|rotate)\b", lower)

        if is_turn_around or (turn_action_match and deg_match) or (turn_action_match and re.search(r"\b(left|right)\b", lower)):
            if is_turn_around:
                target_deg = 180.0
                turn_dir = "TURN_RIGHT"
                dir_label = "right"
            else:
                target_deg = float(deg_match.group(1)) if deg_match else 90.0
                turn_dir = "TURN_LEFT" if "left" in lower else "TURN_RIGHT"
                dir_label = "left" if "left" in lower else "right"

            return DynamicMissionPlan(
                raw_instruction=text,
                goal_name=f"ROTATE_{int(target_deg)}_DEG",
                goal_description=f"Rotate {target_deg} degrees {dir_label}",
                policy_type=PolicyType.ROTATE_TO,
                primary_action=turn_dir,
                speed_percent=50,
                stop_condition=DynamicStopCondition(
                    sensor="imu_heading",
                    operator=">=",
                    threshold=target_deg,
                    description=f"Completed {target_deg} degree rotation"
                ),
                timeout_seconds=15.0,
                sample_sensors=["imu", "ultrasonic"],
                report_fields=["initial_heading_deg", "final_heading_deg", "distance_ahead_cm"]
            )

        # Perimeter Patrol / Inspection
        if re.search(r"\b(patrol|guard|perimeter|loop|inspect room)\b", lower):
            return DynamicMissionPlan(
                raw_instruction=text,
                goal_name="PATROL_PERIMETER",
                goal_description="Autonomous perimeter patrol monitoring environmental obstacles",
                policy_type=PolicyType.PATROL,
                primary_action="MOVE_FORWARD",
                speed_percent=50,
                stop_condition=DynamicStopCondition(
                    sensor="timer",
                    operator="timeout",
                    threshold=45.0,
                    description="Patrol routine duration expired"
                ),
                timeout_seconds=45.0,
                sample_sensors=["ultrasonic", "imu", "pir"],
                report_fields=["laps_completed", "obstacles_avoided", "average_clearance_cm"]
            )

        # Autonomous Safe Exploration
        if re.search(r"\b(explore|wander|roam|navigate|navigate room)\b", lower):
            return DynamicMissionPlan(
                raw_instruction=text,
                goal_name="EXPLORE_SAFE",
                goal_description="Explore available open spaces while avoiding obstacles",
                policy_type=PolicyType.EXPLORE_SAFE,
                primary_action="MOVE_FORWARD",
                speed_percent=50,
                stop_condition=DynamicStopCondition(
                    sensor="timer",
                    operator="timeout",
                    threshold=30.0,
                    description="Exploration session complete"
                ),
                timeout_seconds=30.0,
                sample_sensors=["ultrasonic", "imu"],
                report_fields=["distance_traveled_cm", "obstacles_avoided", "room_coverage_estimate"]
            )

        return None

    def _llm_decompose(self, text: str) -> Optional[DynamicMissionPlan]:
        """
        Invokes LLM to decompose zero-shot novel instructions into a DynamicMissionPlan.
        """
        gateway = self._get_llm_gateway()
        if not gateway:
            return None

        prompt = f"""
You are BUPI's Autonomous Robotic Mission Compiler.
Decompose the following user instruction into an executable robotic mission plan.

Instruction: "{text}"

Respond with ONLY a JSON object matching this schema:
{{
  "goal_name": "SHORT_IDENTIFIER",
  "goal_description": "Brief description of the objective",
  "policy_type": "CONDITIONAL_MOVE" | "SCAN_SWEEP" | "MONITOR_HOLD" | "ROTATE_TO" | "EXPLORE_SAFE" | "PATROL" | "DIRECT_ACTION",
  "primary_action": "MOVE_FORWARD" | "MOVE_BACKWARD" | "TURN_LEFT" | "TURN_RIGHT" | "STOP",
  "speed_percent": 0-100,
  "stop_condition": {{
    "sensor": "ultrasonic" | "pir" | "imu_heading" | "timer" | "none",
    "operator": "<=" | ">=" | "==" | "timeout" | "detect",
    "threshold": float,
    "description": "Condition description"
  }},
  "timeout_seconds": float,
  "sample_sensors": ["ultrasonic", "pir", "imu"],
  "report_fields": ["field1", "field2"]
}}
"""
        try:
            import asyncio
            if asyncio.get_event_loop().is_running():
                return None
            loop = asyncio.new_event_loop()
            res_json = loop.run_until_complete(gateway.classify_intent(prompt))
            loop.close()
            if isinstance(res_json, dict) and "policy_type" in res_json:
                sc = res_json.get("stop_condition", {})
                return DynamicMissionPlan(
                    raw_instruction=text,
                    goal_name=res_json.get("goal_name", "CUSTOM_MISSION"),
                    goal_description=res_json.get("goal_description", text),
                    policy_type=PolicyType(res_json.get("policy_type", "CONDITIONAL_MOVE")),
                    primary_action=res_json.get("primary_action", "MOVE_FORWARD"),
                    speed_percent=int(res_json.get("speed_percent", 50)),
                    stop_condition=DynamicStopCondition(
                        sensor=sc.get("sensor", "timer"),
                        operator=sc.get("operator", "timeout"),
                        threshold=float(sc.get("threshold", 15.0)),
                        description=sc.get("description", "Timeout")
                    ),
                    timeout_seconds=float(res_json.get("timeout_seconds", 30.0)),
                    sample_sensors=res_json.get("sample_sensors", ["ultrasonic", "pir", "imu"]),
                    report_fields=res_json.get("report_fields", ["final_distance_cm", "status"])
                )
        except Exception:
            pass

        return None
