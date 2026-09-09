"""
BUPI Differential Drive Motor Controller & TB6612FNG Driver Model
=================================================================
Controls dual N20 micro metal gear DC motors via TB6612FNG H-Bridge.

PIN CONFIGURATION (ESP32 Dev Module):
- PWMA: GPIO 25 (Left PWM)
- AIN1: GPIO 26 (Left Dir 1)
- AIN2: GPIO 27 (Left Dir 2)
- PWMB: GPIO 14 (Right PWM)
- BIN1: GPIO 33 (Right Dir 1 - Note: GPIO33 verified fix)
- BIN2: GPIO 32 (Right Dir 2)
- STBY: GPIO 4  (Standby - Active HIGH)
"""

from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict

class MovementAction(str, Enum):
    MOVE_FORWARD = "MOVE_FORWARD"
    MOVE_BACKWARD = "MOVE_BACKWARD"
    TURN_LEFT = "TURN_LEFT"
    TURN_RIGHT = "TURN_RIGHT"
    STOP = "STOP"

@dataclass
class MotorPins:
    PWMA: int = 25
    AIN1: int = 26
    AIN2: int = 27
    PWMB: int = 14
    BIN1: int = 33
    BIN2: int = 32
    STBY: int = 4

@dataclass
class MotorState:
    action: MovementAction
    left_pwm: int      # 0 to 255
    right_pwm: int     # 0 to 255
    speed_percent: int # 0 to 100
    duration_ms: int
    is_active: bool
    reason: str

class DifferentialDrive:
    def __init__(self, pins: Optional[MotorPins] = None, max_speed_percent: int = 80):
        self.pins = pins or MotorPins()
        self.max_speed_percent = max(20, min(max_speed_percent, 100))
        self.current_state = MotorState(
            action=MovementAction.STOP,
            left_pwm=0,
            right_pwm=0,
            speed_percent=0,
            duration_ms=0,
            is_active=False,
            reason="Initialized"
        )
        
        # Dead-reckoning kinematic parameters
        self.wheel_base_cm: float = 10.5
        self.wheel_diameter_cm: float = 4.3
        self.max_linear_velocity_cm_s: float = 22.0  # at 100% speed

    def execute_action(
        self,
        action: str,
        speed_percent: int = 60,
        duration_ms: int = 500,
        reason: str = "Commanded movement"
    ) -> Dict[str, Any]:
        """
        Translates high-level structured action into motor PWM and pin states.
        """
        act = MovementAction(action) if action in MovementAction._value2member_map_ else MovementAction.STOP
        speed = max(0, min(speed_percent, self.max_speed_percent))
        pwm = int((speed / 100.0) * 255)

        if act == MovementAction.MOVE_FORWARD:
            left_pwm, right_pwm = pwm, pwm
            left_dir = (1, 0)
            right_dir = (1, 0)
            is_active = True
        elif act == MovementAction.MOVE_BACKWARD:
            left_pwm, right_pwm = pwm, pwm
            left_dir = (0, 1)
            right_dir = (0, 1)
            is_active = True
        elif act == MovementAction.TURN_LEFT:
            # Turn in place: Left reverse, Right forward
            left_pwm, right_pwm = pwm, pwm
            left_dir = (0, 1)
            right_dir = (1, 0)
            is_active = True
        elif act == MovementAction.TURN_RIGHT:
            # Turn in place: Left forward, Right reverse
            left_pwm, right_pwm = pwm, pwm
            left_dir = (1, 0)
            right_dir = (0, 1)
            is_active = True
        else:  # STOP
            left_pwm, right_pwm = 0, 0
            left_dir = (0, 0)
            right_dir = (0, 0)
            is_active = False

        self.current_state = MotorState(
            action=act,
            left_pwm=left_pwm,
            right_pwm=right_pwm,
            speed_percent=speed if is_active else 0,
            duration_ms=duration_ms,
            is_active=is_active,
            reason=reason
        )

        return {
            "motor_state": asdict(self.current_state),
            "hardware_signal": {
                "STBY": 1 if is_active else 0,
                "PWMA": left_pwm,
                "AIN1": left_dir[0],
                "AIN2": left_dir[1],
                "PWMB": right_pwm,
                "BIN1": right_dir[0],
                "BIN2": right_dir[1],
            },
            "pins": asdict(self.pins)
        }

    def emergency_stop(self, reason: str = "Safety override") -> Dict[str, Any]:
        return self.execute_action(MovementAction.STOP.value, speed_percent=0, duration_ms=0, reason=reason)
