"""
BUPI PIR Motion Sensor Driver & Epistemic Interpreter
=====================================================
Interprets passive infrared changes caused by warm moving targets.

EPISTEMIC PRINCIPLE:
PIR detects differences in infrared radiation caused by warm bodies in motion.
It CANNOT determine size, identity, species, or confirmation of a human.
Output is strictly:
  HIGH -> MOTION_DETECTED (POSSIBLE_WARM_MOVING_TARGET)
  LOW  -> NO_MOTION_DETECTED
"""

import time
from enum import Enum
from typing import Dict, Any, Optional

class PIRState(str, Enum):
    NO_MOTION = "NO_MOTION_DETECTED"
    MOTION_DETECTED = "MOTION_DETECTED"
    POSSIBLE_WARM_TARGET = "POSSIBLE_WARM_MOVING_TARGET"

class PIRSensor:
    def __init__(self, pin: int = 19, hold_time_seconds: float = 2.0):
        self.pin = pin
        self.hold_time_seconds = hold_time_seconds
        self.raw_state: int = 0
        self.last_motion_timestamp: float = 0.0
        self.motion_detected: bool = False
        self.total_triggers: int = 0

    def update_raw(self, pin_value: int) -> Dict[str, Any]:
        """
        Updates the raw pin reading from ESP32 or Simulator.
        1 = HIGH, 0 = LOW
        """
        now = time.time()
        self.raw_state = 1 if pin_value else 0

        if self.raw_state == 1:
            self.last_motion_timestamp = now
            if not self.motion_detected:
                self.total_triggers += 1
            self.motion_detected = True
        else:
            # Check hold-off decay
            if (now - self.last_motion_timestamp) > self.hold_time_seconds:
                self.motion_detected = False

        return self.get_interpretation()

    def get_interpretation(self) -> Dict[str, Any]:
        """
        Applies epistemic constraints to output.
        Never declares HUMAN_CONFIRMED.
        """
        if self.motion_detected:
            state = PIRState.MOTION_DETECTED
            epistemic_inference = PIRState.POSSIBLE_WARM_TARGET.value
            confidence = 0.7  # Motion confidence, NOT human certainty
        else:
            state = PIRState.NO_MOTION
            epistemic_inference = "NONE"
            confidence = 0.0

        return {
            "sensor": "PIR",
            "pin": self.pin,
            "raw_value": self.raw_state,
            "motion_detected": self.motion_detected,
            "state": state.value,
            "inference": epistemic_inference,
            "confidence": confidence,
            "human_confirmed": False,  # Strict epistemic constraint: PIR can NEVER confirm a human alone!
            "epistemic_note": "PIR detects IR flux changes from warm moving objects only. PIR != Human Identification."
        }
