"""
BUPI Autonomous Closed-Loop Planner (Sections 3, 4, 9, 10)
==========================================================
Produces structured actions based on continuous feedback from sensor fusion,
epistemic state, and active goal objectives.

Does NOT use static hardcoded sequences. Movement and decisions dynamically
adapt to real-time PIR and Ultrasonic measurements.
"""

import time
import random
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from intent.intent_parser import HighLevelIntent
from sensors.ultrasonic_sensor import DistanceClassification
from .state_manager import StateManager, BupiState
from .goal_manager import GoalManager, GoalStatus

@dataclass
class StructuredAction:
    action: str
    speed: int = 0
    duration_ms: int = 500
    reason: str = ""
    safety_required: bool = True
    event: Optional[str] = None
    distance_cm: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Prune None keys for clean serialization
        return {k: v for k, v in d.items() if v is not None}

class AutonomousPlanner:
    def __init__(self, state_manager: StateManager, goal_manager: GoalManager):
        self.state_mgr = state_manager
        self.goal_mgr = goal_manager

        # Search state variables
        self.consecutive_forward_ticks = 0
        self.turn_direction_bias = "TURN_RIGHT"
        self.verification_timer_start: Optional[float] = None
        self.last_reported_presence_time: float = 0.0
        self.presence_cooldown_seconds: float = 5.0
        self.pause_and_hold_after_report: bool = True

    def plan_next_action(self, fusion_result: Dict[str, Any]) -> StructuredAction:
        """
        Executes one decision cycle of the closed-loop planner.
        Returns a StructuredAction.
        """
        state = self.state_mgr.get_state()
        active_mission = self.goal_mgr.active_mission

        if not active_mission or active_mission.goal.intent == HighLevelIntent.STOP_AND_WAIT:
            self.state_mgr.set_decision_and_action("STOP", "STOP", "No active goal or Stop commanded")
            return StructuredAction(
                action="STOP",
                speed=0,
                duration_ms=0,
                reason="Robot idle / Stop commanded",
                safety_required=False
            )

        intent = active_mission.goal.intent

        # Dispatch based on high-level intent
        if intent == HighLevelIntent.SEARCH_FOR_PRESENCE:
            return self._plan_search_for_presence(state, fusion_result)
        elif intent == HighLevelIntent.EXPLORE_SAFE:
            return self._plan_explore_safe(state, fusion_result)
        elif intent == HighLevelIntent.MONITOR_MOTION:
            return self._plan_monitor_motion(state, fusion_result)
        elif intent == HighLevelIntent.PATROL:
            return self._plan_patrol(state, fusion_result)
        elif intent == HighLevelIntent.OBSERVE_SURROUNDINGS:
            return self._plan_observe(state, fusion_result)
        elif intent == HighLevelIntent.APPROACH_TARGET:
            return self._plan_approach(state, fusion_result)
        else:
            return StructuredAction(action="STOP", speed=0, duration_ms=0, reason="Default fallback")

    def _plan_search_for_presence(self, state: BupiState, fusion_result: Dict[str, Any]) -> StructuredAction:
        """
        Implements Section 4 & 5 Search Behavior:
        1. Start search mode.
        2. Move through available area.
        3. Continuously monitor ultrasonic & PIR.
        4. Track orientation with MPU6050.
        5. Avoid obstacles.
        6. When PIR detects motion: slow down or temporarily stop, check distance.
        7. If both motion + nearby object: classify POSSIBLE_HUMAN_PRESENCE.
        8. Report approximate distance.
        9. Decide whether to continue searching or hold.
        """
        now = time.time()
        dist_info = fusion_result.get("ultrasonic", {})
        pir_info = fusion_result.get("pir", {})
        inference = fusion_result.get("inference", {})

        distance_cm = dist_info.get("distance_cm", 125.0)
        dist_class = dist_info.get("classification", DistanceClassification.FAR.value)
        motion_detected = pir_info.get("motion_detected", False)
        possible_human = inference.get("possible_human_presence", False)

        # Step 7 & 8: If both motion and nearby object detected
        if possible_human:
            # Check if this is a fresh detection or already recently reported
            if (now - self.last_reported_presence_time) > self.presence_cooldown_seconds:
                self.last_reported_presence_time = now
                self.goal_mgr.record_detection(inference.get("report_message", ""))
                self.state_mgr.set_goal("SEARCH_FOR_PRESENCE", mode="REPORTING")
                self.state_mgr.set_decision_and_action(
                    decision="STOP_AND_REPORT",
                    action="REPORT",
                    reason="Possible warm moving human target in sensing corridor"
                )

                return StructuredAction(
                    action="REPORT",
                    speed=0,
                    duration_ms=2000,
                    reason="Target detected; stopping to confirm and alert operator",
                    safety_required=True,
                    event="POSSIBLE_HUMAN_PRESENCE",
                    distance_cm=distance_cm
                )

        # Step 7: Motion detected by PIR, but distance check is in progress
        if motion_detected and not possible_human:
            # Temporarily stop/slow down to align and verify ultrasonic distance
            self.state_mgr.set_goal("SEARCH_FOR_PRESENCE", mode="VERIFYING")
            self.state_mgr.set_decision_and_action(
                decision="SLOW_CHECK_SURROUNDINGS",
                action="CHECK_DISTANCE",
                reason="PIR infrared trigger; slowing down to correlate acoustic echo"
            )
            return StructuredAction(
                action="CHECK_DISTANCE",
                speed=25,
                duration_ms=600,
                reason="PIR motion detected; pausing to verify acoustic range",
                safety_required=True,
                event="VERIFYING_MOTION",
                distance_cm=distance_cm
            )

        # Step 5 & 6: Obstacle avoidance based on Ultrasonic feedback
        if dist_class == DistanceClassification.OBSTACLE.value:
            # Critical obstacle (< 15cm)
            self.state_mgr.set_goal("SEARCH_FOR_PRESENCE", mode="OBSTACLE_AVOIDING")
            self.state_mgr.set_decision_and_action("EMERGENCY_AVOID", "MOVE_BACKWARD", "Critical proximity")
            return StructuredAction(
                action="MOVE_BACKWARD",
                speed=40,
                duration_ms=600,
                reason="Obstacle detected in critical zone; backing away",
                safety_required=True,
                distance_cm=distance_cm
            )

        if dist_class == DistanceClassification.VERY_NEAR.value:
            # Warning-to-critical zone (15-25cm): Stop and turn away
            self.state_mgr.set_goal("SEARCH_FOR_PRESENCE", mode="OBSTACLE_AVOIDING")
            # Alternate turn bias to explore open space
            turn_action = self.turn_direction_bias
            self.turn_direction_bias = "TURN_LEFT" if turn_action == "TURN_RIGHT" else "TURN_RIGHT"
            
            self.state_mgr.set_decision_and_action("AVOID_OBSTACLE", turn_action, "Path blocked")
            return StructuredAction(
                action=turn_action,
                speed=50,
                duration_ms=750,
                reason="Obstacle near forward path; pivoting to clear corridor",
                safety_required=True,
                distance_cm=distance_cm
            )

        if dist_class == DistanceClassification.NEAR.value:
            # Warning zone (25-40cm): Slow down and bias turn
            self.state_mgr.set_goal("SEARCH_FOR_PRESENCE", mode="SEARCHING")
            self.state_mgr.set_decision_and_action("SLOW_APPROACH", "MOVE_FORWARD", "Approaching boundary")
            return StructuredAction(
                action="MOVE_FORWARD",
                speed=35,
                duration_ms=600,
                reason="Approaching potential boundary; navigating at cautious speed",
                safety_required=True,
                distance_cm=distance_cm
            )

        # Step 2: Clear path (> 40cm safe distance) -> Advance and sweep search
        self.consecutive_forward_ticks += 1
        self.state_mgr.set_goal("SEARCH_FOR_PRESENCE", mode="SEARCHING")

        # Periodically execute dynamic exploratory sweep instead of fixed straight lines
        if self.consecutive_forward_ticks > 6:
            self.consecutive_forward_ticks = 0
            turn_choice = "TURN_LEFT" if random.random() > 0.5 else "TURN_RIGHT"
            self.state_mgr.set_decision_and_action("SCAN_AREA", turn_choice, "Exploratory sweep")
            return StructuredAction(
                action=turn_choice,
                speed=45,
                duration_ms=500,
                reason="Exploratory search sweep to expand PIR sensor field of view",
                safety_required=True,
                distance_cm=distance_cm
            )

        self.state_mgr.set_decision_and_action("ADVANCE_SEARCH", "MOVE_FORWARD", "Corridor clear")
        return StructuredAction(
            action="MOVE_FORWARD",
            speed=60,
            duration_ms=1000,
            reason="Corridor clear; advancing search for presence",
            safety_required=True,
            distance_cm=distance_cm
        )

    def _plan_explore_safe(self, state: BupiState, fusion_result: Dict[str, Any]) -> StructuredAction:
        dist_info = fusion_result.get("ultrasonic", {})
        dist_class = dist_info.get("classification", DistanceClassification.FAR.value)
        dist_cm = dist_info.get("distance_cm", 125.0)

        if dist_class in [DistanceClassification.OBSTACLE.value, DistanceClassification.VERY_NEAR.value]:
            return StructuredAction(
                action="TURN_RIGHT",
                speed=50,
                duration_ms=700,
                reason="Safe exploration avoidance",
                distance_cm=dist_cm
            )
        return StructuredAction(
            action="MOVE_FORWARD",
            speed=50,
            duration_ms=800,
            reason="Exploring safe open path",
            distance_cm=dist_cm
        )

    def _plan_monitor_motion(self, state: BupiState, fusion_result: Dict[str, Any]) -> StructuredAction:
        pir_info = fusion_result.get("pir", {})
        if pir_info.get("motion_detected"):
            return StructuredAction(
                action="REPORT",
                speed=0,
                duration_ms=1000,
                reason="Motion alert triggered while stationary",
                event="MOTION_DETECTED"
            )
        return StructuredAction(
            action="STOP",
            speed=0,
            duration_ms=500,
            reason="Monitoring stationary position for IR flux changes"
        )

    def _plan_patrol(self, state: BupiState, fusion_result: Dict[str, Any]) -> StructuredAction:
        # Alternating forward and perimeter turning
        dist_info = fusion_result.get("ultrasonic", {})
        if dist_info.get("classification") in ["obstacle", "very_near"]:
            return StructuredAction(action="TURN_LEFT", speed=50, duration_ms=800, reason="Patrol waypoint turn")
        return StructuredAction(action="MOVE_FORWARD", speed=55, duration_ms=1000, reason="Patrol pace")

    def _plan_observe(self, state: BupiState, fusion_result: Dict[str, Any]) -> StructuredAction:
        return StructuredAction(action="TURN_RIGHT", speed=40, duration_ms=500, reason="Surroundings 360 scan")

    def _plan_approach(self, state: BupiState, fusion_result: Dict[str, Any]) -> StructuredAction:
        dist_info = fusion_result.get("ultrasonic", {})
        dist = dist_info.get("distance_cm", 125.0)
        if dist <= 30.0:
            return StructuredAction(action="STOP", speed=0, duration_ms=0, reason="Approach distance reached")
        return StructuredAction(action="MOVE_FORWARD", speed=30, duration_ms=500, reason="Cautious approach")
