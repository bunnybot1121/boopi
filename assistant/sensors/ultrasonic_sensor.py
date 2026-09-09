"""
BUPI Ultrasonic Ranging Sensor Driver & Proximity Classifier
============================================================
Interprets time-of-flight acoustic echo reflections into distance measurements.

EPISTEMIC PRINCIPLE:
Ultrasonic sensor measures distance to the nearest reflective acoustic surface in its cone (~15-30 deg).
It CANNOT identify what the object is (wall, chair leg, human leg, box, or pet).
"""

from enum import Enum
from typing import Dict, Any

class DistanceClassification(str, Enum):
    FAR = "far"
    NEAR = "near"
    VERY_NEAR = "very_near"
    OBSTACLE = "obstacle"

class UltrasonicSensor:
    def __init__(
        self,
        trig_pin: int = 5,
        echo_pin: int = 18,
        safe_distance_cm: float = 40.0,
        warning_distance_cm: float = 25.0,
        critical_distance_cm: float = 15.0,
        max_range_cm: float = 400.0,
        min_range_cm: float = 2.0
    ):
        self.trig_pin = trig_pin
        self.echo_pin = echo_pin
        self.safe_distance_cm = safe_distance_cm
        self.warning_distance_cm = warning_distance_cm
        self.critical_distance_cm = critical_distance_cm
        self.max_range_cm = max_range_cm
        self.min_range_cm = min_range_cm
        
        self.current_distance_cm: float = safe_distance_cm * 2.0
        self.classification: DistanceClassification = DistanceClassification.FAR

    def update_distance(self, distance_cm: float) -> Dict[str, Any]:
        """
        Updates the measured distance in centimeters.
        Clamps to valid sensor physical range.
        """
        if distance_cm < 0:
            distance_cm = self.max_range_cm
        self.current_distance_cm = round(max(self.min_range_cm, min(distance_cm, self.max_range_cm)), 1)
        self.classification = self._classify(self.current_distance_cm)
        return self.get_interpretation()

    def _classify(self, dist: float) -> DistanceClassification:
        if dist <= self.critical_distance_cm:
            return DistanceClassification.OBSTACLE
        elif dist <= self.warning_distance_cm:
            return DistanceClassification.VERY_NEAR
        elif dist <= self.safe_distance_cm:
            return DistanceClassification.NEAR
        else:
            return DistanceClassification.FAR

    def get_recommended_movement_behavior(self) -> str:
        """
        Translates classification to recommended control stance according to Section 6.
        """
        if self.classification == DistanceClassification.FAR:
            return "NORMAL_MOVEMENT"
        elif self.classification == DistanceClassification.NEAR:
            return "SLOW_PREPARE_TO_CHANGE_DIRECTION"
        elif self.classification == DistanceClassification.VERY_NEAR:
            return "STOP_REPLAN"
        else:  # OBSTACLE
            return "EMERGENCY_STOP"

    def get_interpretation(self) -> Dict[str, Any]:
        return {
            "sensor": "Ultrasonic_HC_SR04",
            "distance_cm": self.current_distance_cm,
            "classification": self.classification.value,
            "recommended_behavior": self.get_recommended_movement_behavior(),
            "thresholds": {
                "safe_distance_cm": self.safe_distance_cm,
                "warning_distance_cm": self.warning_distance_cm,
                "critical_distance_cm": self.critical_distance_cm
            },
            "object_identified": False,
            "epistemic_note": "Ultrasonic measures geometric proximity only. Does not identify object type or material."
        }
