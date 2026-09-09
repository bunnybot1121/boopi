"""
BUPI MPU6050 6-Axis Motion Tracking IMU & Dynamics Interpreter
==============================================================
Tracks the robot's own internal kinematics, tilt, and rotational dynamics.

EPISTEMIC PRINCIPLE:
MPU6050 tracks robot ego-motion (acceleration and angular rates).
It CANNOT determine GPS/geographic coordinates or human position.
States:
  ROBOT_STATIONARY
  ROBOT_MOVING
  ORIENTATION_CHANGED
  SUDDEN_ACCELERATION
  SUDDEN_MOTION
  TILT_HAZARD
"""

import time
import math
from enum import Enum
from typing import Dict, Any

class RobotMotionState(str, Enum):
    STATIONARY = "ROBOT_STATIONARY"
    MOVING = "ROBOT_MOVING"
    ORIENTATION_CHANGED = "ORIENTATION_CHANGED"
    SUDDEN_ACCELERATION = "SUDDEN_ACCELERATION"
    SUDDEN_MOTION = "SUDDEN_MOTION"
    TILT_HAZARD = "TILT_HAZARD"

class MPU6050Sensor:
    def __init__(self, sda_pin: int = 21, scl_pin: int = 22, i2c_addr: int = 0x68):
        self.sda_pin = sda_pin
        self.scl_pin = scl_pin
        self.i2c_addr = i2c_addr
        
        # Current kinematics
        self.ax: float = 0.0  # m/s^2 or g
        self.ay: float = 0.0
        self.az: float = 1.0  # 1g downwards default
        self.gx: float = 0.0  # deg/s
        self.gy: float = 0.0
        self.gz: float = 0.0
        
        # Computed orientation
        self.pitch_deg: float = 0.0
        self.roll_deg: float = 0.0
        self.heading_deg: float = 0.0
        self.last_update_time: float = time.time()
        
        # Dynamics classification
        self.state: RobotMotionState = RobotMotionState.STATIONARY
        self.tilt_hazard_threshold_deg: float = 35.0
        self.accel_threshold: float = 2.2  # g total magnitude
        self.motion_accel_threshold: float = 0.15 # g delta from resting 1g
        self.gyro_motion_threshold: float = 10.0 # deg/s

    def update_telemetry(
        self,
        ax: float, ay: float, az: float,
        gx: float, gy: float, gz: float
    ) -> Dict[str, Any]:
        now = time.time()
        dt = max(0.001, min(now - self.last_update_time, 0.5))
        self.last_update_time = now

        self.ax, self.ay, self.az = ax, ay, az
        self.gx, self.gy, self.gz = gx, gy, gz

        # Simple complementary angle estimation
        accel_pitch = math.atan2(ay, math.sqrt(ax**2 + az**2)) * 180.0 / math.pi
        accel_roll = math.atan2(-ax, az) * 180.0 / math.pi

        self.pitch_deg = round(0.95 * (self.pitch_deg + gx * dt) + 0.05 * accel_pitch, 2)
        self.roll_deg = round(0.95 * (self.roll_deg + gy * dt) + 0.05 * accel_roll, 2)
        self.heading_deg = round((self.heading_deg + gz * dt) % 360.0, 2)

        # Classify state
        total_accel = math.sqrt(ax**2 + ay**2 + az**2)
        accel_delta = abs(total_accel - 1.0)
        gyro_mag = math.sqrt(gx**2 + gy**2 + gz**2)

        if abs(self.pitch_deg) > self.tilt_hazard_threshold_deg or abs(self.roll_deg) > self.tilt_hazard_threshold_deg:
            self.state = RobotMotionState.TILT_HAZARD
        elif total_accel > self.accel_threshold or gyro_mag > 180.0:
            self.state = RobotMotionState.SUDDEN_MOTION
        elif gyro_mag > self.gyro_motion_threshold:
            self.state = RobotMotionState.ORIENTATION_CHANGED
        elif accel_delta > self.motion_accel_threshold:
            self.state = RobotMotionState.MOVING
        else:
            self.state = RobotMotionState.STATIONARY

        return self.get_interpretation()

    def get_interpretation(self) -> Dict[str, Any]:
        return {
            "sensor": "MPU6050_IMU",
            "state": self.state.value,
            "heading_deg": self.heading_deg,
            "pitch_deg": self.pitch_deg,
            "roll_deg": self.roll_deg,
            "tilt_hazard": self.state == RobotMotionState.TILT_HAZARD,
            "is_moving": self.state in [RobotMotionState.MOVING, RobotMotionState.ORIENTATION_CHANGED, RobotMotionState.SUDDEN_MOTION],
            "gps_coordinates": None,  # Explicit epistemic reminder
            "epistemic_note": "MPU6050 tracks robot self-motion and tilt orientation only. Does not provide GPS coordinates or human position."
        }
