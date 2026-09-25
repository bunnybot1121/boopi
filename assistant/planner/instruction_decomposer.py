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
    SWARM_COOPERATIVE = "SWARM_COOPERATIVE"     # Synchronized dual-robot mission (Scout + Specialist in tandem)
    ODOMETRY_REPORT = "ODOMETRY_REPORT"         # Instant status report of steps, distance from laptop/boopi, and Cartesian pose
    RETURN_TO_ORIGIN = "RETURN_TO_ORIGIN"       # Closed-loop return to starting point using odometry & gyro

@dataclass
class DynamicStopCondition:
    sensor: str          # "ultrasonic", "pir", "imu_heading", "timer", "gas", "temp", "humidity", "none"
    operator: str        # "<=", ">=", "==", "!=", "detect", "timeout", "hazard"
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

        elif self.sensor in ["gas", "mq2"]:
            val = telemetry.get("gas_ppm", telemetry.get("bupi_02_mq2", telemetry.get("mq2", 0.0)))
            if self.operator in [">=", ">"]:
                return val >= self.threshold
            elif self.operator == "hazard":
                return val >= self.threshold

        elif self.sensor in ["temp", "temperature"]:
            val = telemetry.get("temp_c", telemetry.get("bupi_02_temp", 25.0))
            if self.operator in [">=", ">"]:
                return val >= self.threshold

        elif self.sensor == "humidity":
            val = telemetry.get("humidity", telemetry.get("humidity_pct", 50.0))
            if self.operator in [">=", ">"]:
                return val >= self.threshold

        elif self.sensor == "pir":
            val = telemetry.get("pir", 0)
            return bool(val == self.threshold)

        elif self.sensor == "imu_heading":
            val = telemetry.get("heading_deg", telemetry.get("heading", 0.0))
            return val >= self.threshold

        elif self.sensor in ["steps", "step_count"]:
            val = telemetry.get("steps", telemetry.get("step_count", 0))
            return val >= self.threshold

        elif self.sensor in ["wifi_distance", "laptop_distance", "distance_from_laptop"]:
            val = telemetry.get("distance_from_laptop_m")
            if val is not None:
                if self.operator in ["<=", "<"]:
                    return val <= self.threshold
                elif self.operator in [">=", ">"]:
                    return val >= self.threshold

        elif self.sensor in ["dist_traveled", "distance_traveled", "meters_traveled"]:
            val = telemetry.get("total_distance_m", telemetry.get("dist_m", 0.0))
            if self.operator in [">=", ">"]:
                return val >= self.threshold
            elif self.operator in ["<=", "<"]:
                return val <= self.threshold

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
    target_bot: str = "bupi_01"         # "bupi_01" (Scout), "bupi_02" (Specialist), or "swarm" (Both)
    swarm_mode: bool = False            # True when both bots collaborate
    suppress_bot: Optional[str] = None  # e.g. "bupi_02" if excluded
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
            "target_bot": self.target_bot,
            "swarm_mode": self.swarm_mode,
            "suppress_bot": self.suppress_bot,
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
        fallback_target = "bupi_02" if any(k in cleaned.lower() for k in ["bot 2", "bot2", "bupi 2", "bupi2", "bupi_02", "specialist", "hazard bot", "gas", "smoke", "temperature", "climate", "air quality"]) else "bupi_01"
        return DynamicMissionPlan(
            raw_instruction=instruction,
            goal_name="EXPLORE_CAUTIOUS",
            goal_description=f"Execute cautious autonomous action for: {instruction}",
            policy_type=PolicyType.EXPLORE_SAFE,
            primary_action="MOVE_FORWARD",
            speed_percent=40,
            target_bot=fallback_target,
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
        # Avoid splitting conditional/subordinate triggers (e.g. 'if you find a person, move towards him' or 'scan the room and if you find any person move towards him')
        if lower.startswith(("if ", "when ", "whenever ", "while ", "as soon as ")) or \
           re.search(r"\b(whenever|if|when)\b.*?\b(find|detect|see|locate)\b.*?\b(person|human|someone|target)\b.*?\b(move|go|drive|walk|approach)\b", lower):
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

        # Target Robot & Collaborative Swarm Resolution
        raw_lower = text.lower()
        
        # 1. Explicit Bot Designations
        only_bot1 = bool(re.search(r"\b(?:only\s+(?:the\s+)?(?:bot|robot|bupi)\s*1|(?:the\s+)?(?:bot|robot|bupi)\s*1\s+only|just\s+(?:the\s+)?(?:bot|robot|bupi)\s*1|single\s+bot\s*1)\b", raw_lower))
        only_bot2 = bool(re.search(r"\b(?:only\s+(?:the\s+)?(?:bot|robot|bupi)\s*2|(?:the\s+)?(?:bot|robot|bupi)\s*2\s+only|just\s+(?:the\s+)?(?:bot|robot|bupi)\s*2|single\s+bot\s*2)\b", raw_lower))
        bot1_explicit = bool(
            only_bot1 or
            re.search(r"\b(bot\s*1|bot1|bupi\s*1|bupi1|bupi_01|scout|bot one|first bot|robot 1|robot one|number 1|number one)\b", raw_lower)
        )
        bot2_explicit = bool(
            only_bot2 or
            re.search(r"\b(bot\s*2|bot2|bupi\s*2|bupi2|bupi_02|specialist|bot two|second bot|robot 2|robot two|number 2|number two|hazard bot|environmental bot)\b", raw_lower)
        )

        # 2. Explicit Swarm / Fleet Designations
        swarm_explicit = bool(
            re.search(r"\b(both|all|fleet|swarm|team|both bots|the two bots|both the bots|both robots|together)\b", raw_lower)
        )
        single_bot_mode = bool(
            re.search(r"\b(single bot|single robot|one bot|only one bot|single bot mode)\b", raw_lower)
        )

        # 3. Suppression / Single-bot exclusion
        # Strictly suppress the opposite bot when single-bot designation is requested or explicit exclusion is stated
        bot2_suppressed = bool(
            only_bot1 or
            (bot1_explicit and not bot2_explicit and not swarm_explicit) or
            (bot1_explicit and re.search(r"\b(bot\s*2|bot2|specialist|hazard bot)\b.*?\b(don'?t|do not|stay|stop|ignore|hold|leave|idle|standby|sit)\b", raw_lower)) or
            re.search(r"\b(don'?t|do not)\s+(use|move|run|drive)\s+(bot\s*2|bot2|specialist)\b", raw_lower) or
            re.search(r"\b(without|excluding)\s+(bot\s*2|bot2|specialist)\b", raw_lower)
        )
        bot1_suppressed = bool(
            only_bot2 or
            (bot2_explicit and not bot1_explicit and not swarm_explicit) or
            (bot2_explicit and re.search(r"\b(bot\s*1|bot1|scout)\b.*?\b(don'?t|do not|stay|stop|ignore|hold|leave|idle|standby|sit)\b", raw_lower)) or
            re.search(r"\b(don'?t|do not)\s+(use|move|run|drive)\s+(bot\s*1|bot1|scout)\b", raw_lower) or
            re.search(r"\b(without|excluding)\s+(bot\s*1|bot1|scout)\b", raw_lower)
        )

        # 4. Capability-Driven Inference (Boopi knows what Bot 1 and Bot 2 can do!)
        # Bot 2 Specialist capability: gas, smoke, air quality, climate, temp, humidity, point readings, room environmental survey
        is_env_capability = bool(
            re.search(r"\b(gas|smoke|air quality|air\s*quality|lpg|fumes|leak|temperature|temp|heat|warmth|humidity|humid|climate)\b", raw_lower) or
            re.search(r"\b(points?\s+of\s+the\s+room|each\s+point|different\s+points|mark\s+out\s+(?:the\s+)?points?|survey\s+points?|record\s+readings?|give\s+(?:the\s+)?readings?|take\s+readings?|probe\s+points?|probe\s+the\s+room|sample\s+the\s+room|environmental\s+survey)\b", raw_lower)
        )
        # Bot 1 Scout capability: motion, PIR, person, people, human tracking, approach person
        is_recon_capability = bool(
            re.search(r"\b(human|person|someone|people|occupant|body|pir|thermal motion|motion|intruder|movement)\b", raw_lower) or
            re.search(r"\b(move towards him|move towards her|approach him|approach her|go towards him|find him|find her)\b", raw_lower)
        )
        # Collaborative room scan operations
        is_collaborative_scan = bool(re.search(r"\b(scan the room|sweep the room|map the room|scan room|search room|patrol together)\b", raw_lower))

        if bot2_suppressed:
            target_bot = "bupi_01"
            swarm_mode = False
            suppress_bot = "bupi_02"
        elif bot1_suppressed:
            target_bot = "bupi_02"
            swarm_mode = False
            suppress_bot = "bupi_01"
        elif bot1_explicit and not bot2_explicit:
            target_bot = "bupi_01"
            swarm_mode = False
            suppress_bot = "bupi_02"
        elif bot2_explicit and not bot1_explicit:
            target_bot = "bupi_02"
            swarm_mode = False
            suppress_bot = "bupi_01"
        elif swarm_explicit:
            target_bot = "swarm"
            swarm_mode = True
            suppress_bot = None
        elif is_env_capability and not is_recon_capability:
            # Route directly to Bot 2 Environmental Specialist
            target_bot = "bupi_02"
            swarm_mode = False
            suppress_bot = "bupi_01"
        elif is_recon_capability and not is_env_capability:
            # Route directly to Bot 1 Scout
            target_bot = "bupi_01"
            swarm_mode = False
            suppress_bot = "bupi_02"
        elif is_collaborative_scan and not single_bot_mode:
            # Default collaborative swarm mode for full room scans
            target_bot = "swarm"
            swarm_mode = True
            suppress_bot = None
        else:
            # Default single bot operation! (Default primary active bot is Bot 1 Scout)
            target_bot = "bupi_01"
            swarm_mode = False
            suppress_bot = "bupi_02"

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
                target_bot=target_bot,
                swarm_mode=swarm_mode,
                suppress_bot=suppress_bot,
                stop_condition=DynamicStopCondition(
                    sensor="none",
                    operator="==",
                    threshold=0,
                    description="Immediate halt requested"
                ),
                timeout_seconds=0.1
            )

        # Return to Origin / Starting Place (Closed-Loop Odometry & Heading Navigation)
        # e.g., "return back to the original place", "return to original place", "go back to where you started",
        # "come back to base", "return to base", "return to origin", "return home", "go back to starting position",
        # "head back to start", "come back to origin", "drive back to start"
        is_return_to_origin = bool(
            re.search(r"\b(return|go\s+back|come\s+back|head\s+back|drive\s+back|navigate\s+back)\b.*?\b(original\s+(?:place|position|spot|location|point)|origin|base|home|starting\s+(?:place|position|point|spot)|where\s+(?:you|it|they)\s+started|start)\b", lower) or
            re.search(r"\b(return\s+back|return\s+home|return\s+to\s+base|return\s+to\s+origin)\b", lower) or
            re.search(r"\b(go\s+back\s+home|come\s+back\s+home|back\s+to\s+origin|back\s+to\s+(?:the\s+)?original\s+(?:place|position))\b", lower)
        )
        if is_return_to_origin:
            return DynamicMissionPlan(
                raw_instruction=text,
                goal_name="RETURN_TO_ORIGIN",
                goal_description="Navigate back to initial starting coordinates (0.0, 0.0) using closed-loop odometry and heading alignment",
                policy_type=PolicyType.RETURN_TO_ORIGIN,
                primary_action="MOVE_FORWARD",
                speed_percent=45,
                target_bot=target_bot,
                swarm_mode=swarm_mode,
                suppress_bot=suppress_bot,
                stop_condition=DynamicStopCondition(
                    sensor="odometry",
                    operator="<=",
                    threshold=0.15,
                    description="Reached origin within 15 cm standoff"
                ),
                timeout_seconds=35.0,
                sample_sensors=["imu", "odometry", "ultrasonic"],
                report_fields=["initial_displacement_m", "final_displacement_m", "x_m", "y_m", "heading_deg", "duration_seconds"]
            )

        # Dynamic Odometry, Step Count & Wi-Fi Proximity Metric Queries
        # e.g. "how many steps did you take?", "how far are you from my laptop?", "what is your distance from boopi?",
        # "where are you located?", "what are your coordinates?", "are you getting closer to the laptop?", "what is the wi-fi signal?"
        is_step_query = bool(re.search(r"\b(how many|count|number of|tell me|what (is|are))\b.*?\b(steps|step count)\b", lower) or re.search(r"\b(steps taken|how many steps)\b", lower))
        is_wifi_range_query = bool(re.search(r"\b(how far|distance|range|signal|proximity|meters? away)\b.*?\b(laptop|computer|boopi|hub|pc|wifi|wi-fi|hotspot|you)\b", lower) or
                                  re.search(r"\b(laptop|computer|boopi|hub|wifi|wi-fi)\b.*?\b(distance|range|far|away|signal)\b", lower) or
                                  re.search(r"\b(closer to|moving away from|approaching)\b.*?\b(laptop|computer|boopi|hub|me)\b", lower))
        is_pose_query = bool(re.search(r"\b(where are you|current position|coordinates|current pose|displacement|distance traveled|how far (have you|did you) (travel|go|move))\b", lower))

        if is_step_query or is_wifi_range_query or is_pose_query:
            report_name = "ODOMETRY_AND_RANGE_REPORT"
            if is_step_query:
                report_name = "STEP_COUNT_REPORT"
            elif is_wifi_range_query:
                report_name = "WIFI_PROXIMITY_REPORT"
            elif is_pose_query:
                report_name = "CARTESIAN_POSE_REPORT"

            return DynamicMissionPlan(
                raw_instruction=text,
                goal_name=report_name,
                goal_description="Capture and report live MPU6050 step count, Cartesian coordinates, and Wi-Fi RSSI distance from laptop/Boopi Hub",
                policy_type=PolicyType.ODOMETRY_REPORT,
                primary_action="STOP",
                speed_percent=0,
                target_bot=target_bot,
                swarm_mode=swarm_mode,
                suppress_bot=suppress_bot,
                stop_condition=DynamicStopCondition(
                    sensor="none",
                    operator="==",
                    threshold=0,
                    description="Instant odometry and RF range reading"
                ),
                timeout_seconds=0.5,
                sample_sensors=["imu", "wifi", "odometry"],
                report_fields=["step_count", "total_distance_m", "distance_from_laptop_m", "wifi_rssi", "proximity_trend", "x_m", "y_m"]
            )

        # Environmental Survey, Room Point Probing & Gas/Climate Inspection (Bot 2 Specialist)
        # e.g., "mark out the points of the room and give the readings of each points", "check the environment",
        # "survey room air quality", "sniff for gas leaks", "measure temperature and humidity", "take readings at points of the room"
        if re.search(r"\b(check|survey|inspect|measure|monitor|sniff|test|probe|sample|record|give|read|mark out)\b.*?\b(environment|gas|smoke|temperature|temp|climate|air quality|humidity|hazard|hazards|points?|readings?)\b", lower) or \
           re.search(r"\b(points?\s+of\s+the\s+room|each\s+point|different\s+points|mark\s+out\s+(?:the\s+)?points?|readings?\s+of\s+each\s+point|readings?\s+of\s+points?)\b", lower) or \
           re.search(r"\b(gas|smoke|air quality|temperature|climate|environmental)\b.*?\b(survey|inspection|check|status|reading|readings|probe)\b", lower):
            is_mon = bool(re.search(r"\b(monitor|alert|watch|guard)\b", lower))
            is_points = bool(re.search(r"\b(points?|mark out|each point|different points|probe points)\b", lower))
            policy = PolicyType.MONITOR_HOLD if is_mon else PolicyType.SCAN_SWEEP
            goal_name = "ROOM_POINTS_SURVEY" if is_points else "ENVIRONMENTAL_SURVEY"
            goal_desc = "Traverse room waypoints and record environmental telemetry (MQ-2 gas, DHT22 temperature and humidity, obstacle clearance) at each point" if is_points else "Perform environmental survey measuring MQ-2 gas concentration, ambient temperature, humidity, and obstacle clearance"
            return DynamicMissionPlan(
                raw_instruction=text,
                goal_name=goal_name,
                goal_description=goal_desc,
                policy_type=policy,
                primary_action="MOVE_FORWARD" if is_points else ("TURN_RIGHT" if policy == PolicyType.SCAN_SWEEP else "STOP"),
                speed_percent=45 if policy == PolicyType.SCAN_SWEEP else 0,
                target_bot="bupi_02",
                swarm_mode=False,
                suppress_bot="bupi_01",
                stop_condition=DynamicStopCondition(
                    sensor="gas" if is_mon else "timer",
                    operator="hazard" if is_mon else "timeout",
                    threshold=300.0 if is_mon else 15.0,
                    description="Hazardous gas detected (>300 ppm)" if is_mon else "Room points environmental survey complete"
                ),
                timeout_seconds=30.0 if is_mon else 18.0,
                sample_sensors=["gas", "temp", "humidity", "ultrasonic", "imu"],
                report_fields=["point_readings", "gas_ppm", "temp_c", "humidity_pct", "air_quality_status", "final_distance_cm", "heading_deg"]
            )

        # Walk / Move until Gas / Smoke detected (Bot 2 Specialist)
        # e.g., "walk until you detect gas", "move forward until smoke or gas leak"
        if re.search(r"\b(walk|drive|move|go|crawl)\b.*?\buntil\b.*?\b(gas|smoke|leak|hazard|fume|fumes)\b", lower):
            thresh_ppm = 250.0
            return DynamicMissionPlan(
                raw_instruction=text,
                goal_name="WALK_UNTIL_GAS",
                goal_description=f"Drive forward until elevated gas concentration is detected (>= {thresh_ppm} ppm)",
                policy_type=PolicyType.CONDITIONAL_MOVE,
                primary_action="MOVE_FORWARD",
                speed_percent=45,
                target_bot="bupi_02",
                stop_condition=DynamicStopCondition(
                    sensor="gas",
                    operator=">=",
                    threshold=thresh_ppm,
                    description=f"Gas concentration reached {thresh_ppm} ppm threshold"
                ),
                timeout_seconds=40.0,
                sample_sensors=["gas", "ultrasonic", "imu"],
                report_fields=["final_gas_ppm", "final_distance_cm", "heading_deg", "duration_seconds"]
            )

        # Step-Gated Dynamic Moves (MPU6050 Peak Acceleration Step Counting)
        # e.g., "walk 5 steps forward", "take 10 steps", "move 3 steps back", "advance 8 steps"
        step_match = re.search(r"\b(?:take|walk|move|advance|drive|step|crawl)\s+(\d+)\s+steps?\b", lower) or \
                     re.search(r"(\d+)\s+steps?\b.*?\b(?:forward|ahead|advance|back|backward|reverse)\b", lower) or \
                     re.search(r"\b(?:take|walk|move)\s+(\d+)\s+steps?\b", lower)
        if step_match and not re.search(r"\b(how many|count|tell me|number)\b", lower):
            num_steps = int(step_match.group(1))
            is_reverse = bool(re.search(r"\b(back|backward|backwards|reverse)\b", lower))
            primary_act = "MOVE_BACKWARD" if is_reverse else "MOVE_FORWARD"
            timeout = max(5.0, num_steps * 1.8)

            return DynamicMissionPlan(
                raw_instruction=text,
                goal_name=f"TAKE_{num_steps}_STEPS",
                goal_description=f"Move {num_steps} steps {'backward' if is_reverse else 'forward'} using MPU6050 peak-acceleration gait detection",
                policy_type=PolicyType.CONDITIONAL_MOVE,
                primary_action=primary_act,
                speed_percent=50,
                target_bot=target_bot,
                swarm_mode=swarm_mode,
                suppress_bot=suppress_bot,
                stop_condition=DynamicStopCondition(
                    sensor="steps",
                    operator=">=",
                    threshold=float(num_steps),
                    description=f"Completed {num_steps} steps"
                ),
                timeout_seconds=timeout,
                sample_sensors=["imu", "odometry", "ultrasonic"],
                report_fields=["steps_taken", "total_distance_m", "final_distance_cm", "heading_deg", "duration_seconds"]
            )

        # Wi-Fi RSSI Distance-Gated Moves (Move relative to Host Laptop / Boopi Hub)
        # e.g., "move until you are 2 meters from the laptop", "walk toward laptop until 1 meter", "move away from laptop until 3 meters"
        wifi_move_match = re.search(r"\buntil\b.*?\b(\d+(?:\.\d+)?)\s*(?:m|meter|meters)\b.*?\b(?:from|to|away from)?\s*(?:the\s*)?(?:laptop|computer|boopi|hub|wifi|hotspot)\b", lower) or \
                          re.search(r"\b(?:laptop|computer|boopi|hub)\b.*?\buntil\b.*?\b(\d+(?:\.\d+)?)\s*(?:m|meter|meters)\b", lower)
        if wifi_move_match:
            target_wifi_m = float(wifi_move_match.group(1))
            is_approach = bool(re.search(r"\b(closer|towards?|near|approach)\b", lower))
            is_recede = bool(re.search(r"\b(away|back|reverse|farther)\b", lower))
            operator = "<=" if (is_approach or not is_recede) else ">="
            action = "MOVE_BACKWARD" if is_recede else "MOVE_FORWARD"

            return DynamicMissionPlan(
                raw_instruction=text,
                goal_name=f"MOVE_WIFI_RANGE_{target_wifi_m}M",
                goal_description=f"Drive {action.lower()} until distance from laptop is {operator} {target_wifi_m:.1f} meters",
                policy_type=PolicyType.CONDITIONAL_MOVE,
                primary_action=action,
                speed_percent=45,
                target_bot=target_bot,
                swarm_mode=swarm_mode,
                suppress_bot=suppress_bot,
                stop_condition=DynamicStopCondition(
                    sensor="wifi_distance",
                    operator=operator,
                    threshold=target_wifi_m,
                    description=f"Distance from laptop reached {operator} {target_wifi_m:.1f} m"
                ),
                timeout_seconds=35.0,
                sample_sensors=["wifi", "imu", "ultrasonic"],
                report_fields=["distance_from_laptop_m", "wifi_rssi", "proximity_trend", "duration_seconds"]
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
                target_bot=target_bot,
                swarm_mode=swarm_mode,
                suppress_bot=suppress_bot,
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
                target_bot=target_bot,
                swarm_mode=swarm_mode,
                suppress_bot=suppress_bot,
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
                target_bot=target_bot,
                swarm_mode=swarm_mode,
                suppress_bot=suppress_bot,
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
                target_bot=target_bot,
                swarm_mode=swarm_mode,
                suppress_bot=suppress_bot,
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
            is_explicit_human = bool(re.search(r"\b(human|person|someone|anyone|people|occupant)\b", lower))
            g_name = "SEARCH_HUMAN_PRESENCE" if is_explicit_human else "SWARM_ROOM_SCAN"
            g_desc = "Perform 360-degree room scan correlating PIR thermal flux and ultrasonic distance" if not swarm_mode else "Perform collaborative dual-robot room scan: Bot 1 circular 360 sweep and Bot 2 linear environmental probe"
            return DynamicMissionPlan(
                raw_instruction=text,
                goal_name=g_name,
                goal_description=g_desc,
                policy_type=PolicyType.SCAN_SWEEP,
                primary_action="TURN_RIGHT",
                speed_percent=45,
                target_bot=target_bot,
                swarm_mode=swarm_mode,
                suppress_bot=suppress_bot,
                stop_condition=DynamicStopCondition(
                    sensor="imu_heading",
                    operator=">=",
                    threshold=360.0,
                    description="Full 360-degree scan sweep completed"
                ),
                timeout_seconds=30.0,
                sample_sensors=["pir", "ultrasonic", "imu", "gas", "temp", "humidity"],
                report_fields=["target_detected", "distance_m", "relative_bearing_deg", "heading_deg", "gas_ppm", "temp_c", "humidity_pct", "confidence", "direction_description"]
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
                target_bot=target_bot,
                swarm_mode=swarm_mode,
                suppress_bot=suppress_bot,
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

        if is_turn_around or (turn_action_match and deg_match):
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
                target_bot=target_bot,
                swarm_mode=swarm_mode,
                suppress_bot=suppress_bot,
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
                target_bot=target_bot,
                swarm_mode=swarm_mode,
                suppress_bot=suppress_bot,
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

        # Dynamic Obstacle Avoidance & Path Bypass Maneuver
        # e.g., "if any obstacle comes in the between, avoid that by taking another path", "avoid obstacles by taking another path",
        # "bypass the obstacle", "take another path if obstacle comes", "avoid obstacles", "bypass obstacles", "cross out that obstacle"
        is_bypass_request = bool(
            re.search(r"\b(avoid|bypass|detour|dodge|evade|cross\s+out)\b.*?\b(obstacle|obstacles|barrier|blockage|wall|object)\b", lower) or
            re.search(r"\b(obstacle|obstacles|barrier)\b.*?\b(avoid|bypass|detour|dodge|another\s+path|different\s+path|alternate\s+path|take\s+another|take\s+a\s+different)\b", lower) or
            re.search(r"\b(taking\s+another\s+path|take\s+another\s+path|take\s+a\s+different\s+path|another\s+path|different\s+path|alternate\s+path)\b", lower) or
            re.search(r"\b(bypass\s+the\s+obstacle|bypass\s+obstacle|cross\s+out\s+(?:the\s+)?obstacle)\b", lower)
        )
        if is_bypass_request:
            return DynamicMissionPlan(
                raw_instruction=text,
                goal_name="DYNAMIC_OBSTACLE_BYPASS",
                goal_description="Drive forward and dynamically bypass any obstacle by executing flank and detour maneuvers",
                policy_type=PolicyType.EXPLORE_SAFE,
                primary_action="MOVE_FORWARD",
                speed_percent=45,
                target_bot=target_bot,
                swarm_mode=swarm_mode,
                suppress_bot=suppress_bot,
                stop_condition=DynamicStopCondition(
                    sensor="timer",
                    operator="timeout",
                    threshold=35.0,
                    description="Autonomous obstacle avoidance session complete"
                ),
                timeout_seconds=35.0,
                sample_sensors=["ultrasonic", "imu"],
                report_fields=["distance_traveled_cm", "obstacles_avoided", "summary"]
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
                target_bot=target_bot,
                swarm_mode=swarm_mode,
                suppress_bot=suppress_bot,
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

        # Direct Directional Locomotion Commands
        # e.g., "move the bot 1 only", "move bot 1 forward", "bot 1 turn left", "bot 2 move forward"
        is_reverse_cmd = bool(re.search(r"\b(move backward|move backwards|move back|drive backward|drive backwards|drive back|drive reverse|go backward|go backwards|go back|backward|backwards|reverse|back up|backup|step back)\b", lower))
        is_left_cmd = bool(re.search(r"\b(turn left|spin left|rotate left|go left|take a left|turn to the left)\b", lower))
        is_right_cmd = bool(re.search(r"\b(turn right|spin right|rotate right|go right|take a right|turn to the right)\b", lower))
        is_forward_cmd = bool(
            re.search(r"\b(move forward|drive forward|go forward|step forward|drive ahead|go ahead|advance|move ahead)\b", lower) or
            (bot1_explicit and re.search(r"\b(move|drive|go)\b", lower) and not (is_reverse_cmd or is_left_cmd or is_right_cmd)) or
            (bot2_explicit and re.search(r"\b(move|drive|go)\b", lower) and not (is_reverse_cmd or is_left_cmd or is_right_cmd))
        )

        if is_reverse_cmd or is_left_cmd or is_right_cmd or is_forward_cmd:
            if is_reverse_cmd:
                act = "MOVE_BACKWARD"
                gname = "DIRECT_MOVE_BACKWARD"
            elif is_left_cmd:
                act = "TURN_LEFT"
                gname = "DIRECT_TURN_LEFT"
            elif is_right_cmd:
                act = "TURN_RIGHT"
                gname = "DIRECT_TURN_RIGHT"
            else:
                act = "MOVE_FORWARD"
                gname = "DIRECT_MOVE_FORWARD"

            return DynamicMissionPlan(
                raw_instruction=text,
                goal_name=gname,
                goal_description=f"Execute direct motor action {act} for {target_bot}",
                policy_type=PolicyType.DIRECT_ACTION,
                primary_action=act,
                speed_percent=60,
                target_bot=target_bot,
                swarm_mode=swarm_mode,
                suppress_bot=suppress_bot,
                stop_condition=DynamicStopCondition(
                    sensor="timer",
                    operator="timeout",
                    threshold=1.5,
                    description="1.5-second direct action pulse"
                ),
                timeout_seconds=2.0
            )

        return None

    def _llm_decompose(self, text: str) -> Optional[DynamicMissionPlan]:
        """
        Invokes LLM to decompose zero-shot novel instructions into a DynamicMissionPlan.
        Equipped with the complete Bot 1 & Bot 2 heterogeneous hardware capability matrix.
        """
        gateway = self._get_llm_gateway()
        if not gateway:
            return None

        prompt = f"""You are BUPI's Autonomous Robotic Mission Compiler.
Decompose the following user instruction into an executable robotic mission plan.

ROBOT FLEET HARDWARE CAPABILITIES:
1. Bot 1 ("bupi_01", Scout):
   - Sensors: HC-SR04 Ultrasonic Distance, PIR Passive Infrared Motion (detects warm moving humans/occupants), MPU6050 6-Axis IMU (gyro heading, pitch/roll, accelerometer step counter).
   - Actuators: Differential drive DC motors (TB6612FNG).
   - Specialization: Human tracking, motion detection, spatial reconnaissance, obstacle navigation, fast scouting.
2. Bot 2 ("bupi_02", Specialist):
   - Sensors: MQ-2 Gas & Smoke (0-1000 ppm), DHT22 Temperature & Humidity, HC-SR04 Ultrasonic Distance, MPU6050 IMU.
   - Actuators: Differential drive DC motors (TB6612FNG).
   - Specialization: Gas leak detection, smoke analysis, air quality, room climate, temperature/heat index monitoring.
3. Swarm ("swarm"):
   - Collaborative tandem mission: Both robots operate simultaneously. Use when operator specifies "both", "all", "fleet", "swarm", or collaborative room scans.

TARGET SELECTION RULES:
- If operator specifies Bot 1 / Scout -> target_bot = "bupi_01", swarm_mode = false.
- If operator specifies Bot 2 / Specialist -> target_bot = "bupi_02", swarm_mode = false.
- If instruction requires gas, smoke, temperature, or humidity -> target_bot = "bupi_02", swarm_mode = false.
- If instruction requires PIR, human motion, or person tracking -> target_bot = "bupi_01", swarm_mode = false.
- If operator specifies "both", "all", "swarm", or asks to scan/map room -> target_bot = "swarm", swarm_mode = true.
- For simple atomic movements without robot designation -> target_bot = "bupi_01", swarm_mode = false.

Instruction: "{text}"

Respond with ONLY a JSON object matching this schema:
{{
  "goal_name": "SHORT_IDENTIFIER",
  "goal_description": "Brief description of the objective",
  "policy_type": "CONDITIONAL_MOVE" | "SCAN_SWEEP" | "MONITOR_HOLD" | "ROTATE_TO" | "EXPLORE_SAFE" | "PATROL" | "DIRECT_ACTION" | "ODOMETRY_REPORT",
  "primary_action": "MOVE_FORWARD" | "MOVE_BACKWARD" | "TURN_LEFT" | "TURN_RIGHT" | "STOP",
  "speed_percent": 0-100,
  "target_bot": "bupi_01" | "bupi_02" | "swarm",
  "swarm_mode": true | false,
  "stop_condition": {{
    "sensor": "ultrasonic" | "pir" | "imu_heading" | "steps" | "wifi_distance" | "dist_traveled" | "gas" | "temp" | "timer" | "none",
    "operator": "<=" | ">=" | "==" | "timeout" | "detect",
    "threshold": float,
    "description": "Condition description"
  }},
  "timeout_seconds": float,
  "sample_sensors": ["ultrasonic", "pir", "imu", "wifi", "odometry"],
  "report_fields": ["field1", "field2"]
}}
"""
        try:
            import asyncio
            import concurrent.futures

            def _call_gateway():
                new_l = asyncio.new_event_loop()
                ans = new_l.run_until_complete(gateway.classify_intent(prompt))
                new_l.close()
                return ans

            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None

            if running_loop and running_loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    res_json = pool.submit(_call_gateway).result(timeout=10.0)
            else:
                res_json = _call_gateway()

            if isinstance(res_json, dict) and "policy_type" in res_json:
                sc = res_json.get("stop_condition", {})
                llm_target = res_json.get("target_bot")
                if not llm_target:
                    if any(k in text.lower() for k in ["bot 2", "bot2", "bupi 2", "bupi2", "bupi_02", "specialist", "hazard bot", "gas", "smoke", "temperature", "climate", "air quality"]):
                        llm_target = "bupi_02"
                    elif any(k in text.lower() for k in ["both", "all", "swarm", "fleet", "two bots"]):
                        llm_target = "swarm"
                    else:
                        llm_target = "bupi_01"

                is_swarm = bool(res_json.get("swarm_mode", llm_target == "swarm"))
                return DynamicMissionPlan(
                    raw_instruction=text,
                    goal_name=res_json.get("goal_name", "CUSTOM_MISSION"),
                    goal_description=res_json.get("goal_description", text),
                    policy_type=PolicyType(res_json.get("policy_type", "CONDITIONAL_MOVE")),
                    primary_action=res_json.get("primary_action", "MOVE_FORWARD"),
                    speed_percent=int(res_json.get("speed_percent", 50)),
                    target_bot=llm_target,
                    swarm_mode=is_swarm,
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
        except Exception as e:
            print(f"[Instruction Decomposer] LLM fallback error: {e}", flush=True)

        return None
