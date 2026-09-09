"""
BUPI Safety Controller & Actuator Protection Layer (Section 6 & 7)
==================================================================
The safety layer intercepts every StructuredAction output by the Planner
and verifies environmental conditions against physical constraints before
forwarding commands to the motor driver / ESP32.

RULE:
Safety decisions unconditionally supersede AI decisions.
"""

import time
from enum import Enum
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from planner.autonomous_planner import StructuredAction
from sensors.ultrasonic_sensor import DistanceClassification

class SafetyVerdict(str, Enum):
    APPROVED = "APPROVED"
    MODIFIED = "MODIFIED"
    OVERRIDDEN = "OVERRIDDEN_FORCED_STOP"

@dataclass
class SafetyOverrideEvent:
    timestamp: float
    original_action: str
    safe_action: str
    reason: str
    distance_cm: float
    tilt_deg: float
    verdict: SafetyVerdict

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["verdict"] = self.verdict.value
        return d

class SafetyController:
    def __init__(
        self,
        safe_distance_cm: float = 40.0,
        warning_distance_cm: float = 25.0,
        critical_distance_cm: float = 15.0,
        max_allowed_tilt_deg: float = 35.0,
        enable_strict_overrides: bool = True
    ):
        self.safe_distance_cm = safe_distance_cm
        self.warning_distance_cm = warning_distance_cm
        self.critical_distance_cm = critical_distance_cm
        self.max_allowed_tilt_deg = max_allowed_tilt_deg
        self.enable_strict_overrides = enable_strict_overrides
        
        self.override_history: List[SafetyOverrideEvent] = []
        self.total_overrides: int = 0
        self.last_verdict: SafetyVerdict = SafetyVerdict.APPROVED
        self.last_status_message: str = "Safety layer nominal. No overrides active."

    def validate_and_filter(
        self,
        action: StructuredAction,
        sensor_fusion_result: Dict[str, Any]
    ) -> StructuredAction:
        """
        Interception point between Planner and Motors.
        Returns the safe action (either original or overridden).
        """
        now = time.time()
        dist_info = sensor_fusion_result.get("ultrasonic", {})
        imu_info = sensor_fusion_result.get("imu", {})

        distance_cm = dist_info.get("distance_cm", 100.0)
        pitch_deg = abs(imu_info.get("pitch_deg", 0.0))
        roll_deg = abs(imu_info.get("roll_deg", 0.0))
        max_tilt = max(pitch_deg, roll_deg)

        # 1. HARD CONSTRAINT: Tilt Hazard / Rollover / Picked up
        if max_tilt > self.max_allowed_tilt_deg:
            self._record_override(
                action.action, "STOP",
                f"TILT_HAZARD detected ({max_tilt}° > {self.max_allowed_tilt_deg}°)",
                distance_cm, max_tilt, SafetyVerdict.OVERRIDDEN
            )
            return StructuredAction(
                action="STOP",
                speed=0,
                duration_ms=0,
                reason=f"SAFETY OVERRIDE: Robot tilted excessively ({max_tilt}°)",
                safety_required=False
            )

        # 2. HARD CONSTRAINT: Critical Collision Distance (distance <= critical_distance_cm)
        if distance_cm <= self.critical_distance_cm:
            # If robot is trying to move forward, force immediate STOP
            if action.action in ["MOVE_FORWARD", "APPROACH_TARGET"]:
                self._record_override(
                    action.action, "STOP",
                    f"CRITICAL OBSTACLE distance ({distance_cm} cm <= {self.critical_distance_cm} cm)",
                    distance_cm, max_tilt, SafetyVerdict.OVERRIDDEN
                )
                return StructuredAction(
                    action="STOP",
                    speed=0,
                    duration_ms=0,
                    reason=f"SAFETY OVERRIDE: Emergency obstacle barrier at {distance_cm} cm",
                    safety_required=False,
                    event="EMERGENCY_STOP",
                    distance_cm=distance_cm
                )

        # 3. WARNING CONSTRAINT: Warning Distance (critical < distance <= warning)
        if self.critical_distance_cm < distance_cm <= self.warning_distance_cm:
            if action.action == "MOVE_FORWARD":
                # Clamp speed or force turn / stop
                safe_speed = min(action.speed, 25)
                self._record_override(
                    action.action, "STOP",
                    f"Warning obstacle boundary ({distance_cm} cm <= {self.warning_distance_cm} cm)",
                    distance_cm, max_tilt, SafetyVerdict.MODIFIED
                )
                return StructuredAction(
                    action="STOP",
                    speed=0,
                    duration_ms=0,
                    reason=f"SAFETY OVERRIDE: Boundary caution at {distance_cm} cm (forced stop to replan)",
                    safety_required=False,
                    distance_cm=distance_cm
                )

        # 4. APPROVED
        self.last_verdict = SafetyVerdict.APPROVED
        self.last_status_message = "Action approved by Safety Layer."
        return action

    def _record_override(
        self,
        orig: str,
        safe: str,
        reason: str,
        dist: float,
        tilt: float,
        verdict: SafetyVerdict
    ):
        self.total_overrides += 1
        self.last_verdict = verdict
        self.last_status_message = f"{verdict.value}: {reason}"
        event = SafetyOverrideEvent(
            timestamp=time.time(),
            original_action=orig,
            safe_action=safe,
            reason=reason,
            distance_cm=dist,
            tilt_deg=tilt,
            verdict=verdict
        )
        self.override_history.append(event)
        # Keep recent 50
        if len(self.override_history) > 50:
            self.override_history.pop(0)

    def get_status(self) -> Dict[str, Any]:
        return {
            "verdict": self.last_verdict.value,
            "status_message": self.last_status_message,
            "total_overrides": self.total_overrides,
            "recent_overrides": [ev.to_dict() for ev in self.override_history[-5:]],
            "thresholds": {
                "safe_distance_cm": self.safe_distance_cm,
                "warning_distance_cm": self.warning_distance_cm,
                "critical_distance_cm": self.critical_distance_cm,
                "max_allowed_tilt_deg": self.max_allowed_tilt_deg
            }
        }
