"""
BUPI Local Odometry & Dead-Reckoning Kinematics
==============================================
Calculates 2D planar robot position (X, Y, Heading) using differential-drive
odometry fused with MPU6050 gyroscope heading rate.
Part of BUPI Spatial Intelligence Engine (SIH 2026 / SIH26218).

SCIENTIFIC PRINCIPLES:
- MPU6050 accelerometer alone is NEVER double-integrated (prevents exponential drift).
- Linear displacement is derived from wheel encoders (or calibrated motor timing fallback).
- Orientation is derived from MPU6050 Z-gyro integration.
- Exposes realistic, mathematically derived uncertainty radii.
"""

import math
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class OdometryPose:
    x_m: float
    y_m: float
    heading_deg: float
    uncertainty_radius_m: float
    total_distance_m: float
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "x_m": round(self.x_m, 3),
            "y_m": round(self.y_m, 3),
            "heading_deg": round(self.heading_deg, 1),
            "uncertainty_radius_m": round(self.uncertainty_radius_m, 3),
            "total_distance_m": round(self.total_distance_m, 3),
            "timestamp": round(self.timestamp, 2)
        }

class LocalOdometryEngine:
    def __init__(
        self,
        initial_x: float = 0.0,
        initial_y: float = 0.0,
        initial_heading_deg: float = 0.0,
        initial_theta: Optional[float] = None,
        wheel_radius_m: float = 0.0215,       # 43mm standard N20 rubber wheel
        wheel_track_m: float = 0.105,         # 10.5cm distance between left/right wheel centers
        encoder_ticks_per_rev: int = 1400,    # 7 PPR * 4 quad * 50:1 gear
        nominal_speed_m_s: float = 0.20       # ~20 cm/s at 100% PWM
    ):
        self.x = initial_x
        self.y = initial_y
        h = initial_theta if initial_theta is not None else initial_heading_deg
        self.heading_deg = float(h) % 360.0
        self.wheel_radius_m = wheel_radius_m
        self.wheel_track_m = wheel_track_m
        self.encoder_ticks_per_rev = encoder_ticks_per_rev
        self.nominal_speed_m_s = nominal_speed_m_s

        self.last_left_ticks = 0
        self.last_right_ticks = 0
        self.has_encoder_hardware = False

        self.total_distance_traveled_m = 0.0
        self.start_time = time.time()
        self.last_update_time = time.time()

        # Cumulative uncertainty model: initial baseline 5cm + 5% of distance + gyro drift over time
        self.base_uncertainty_m = 0.05
        self.distance_error_rate = 0.05  # 5% distance slip error on flat floors
        self.gyro_drift_rate_deg_per_s = 0.03  # ~1.8 deg per minute

    @property
    def theta(self) -> float:
        return self.heading_deg

    @theta.setter
    def theta(self, val: float):
        self.heading_deg = val % 360.0

    @property
    def uncertainty_radius(self) -> float:
        return self.get_current_pose().uncertainty_radius_m

    def reset_pose(self, x: float, y: float, heading_deg: float):
        self.x = x
        self.y = y
        self.heading_deg = heading_deg % 360.0
        self.total_distance_traveled_m = 0.0
        self.start_time = time.time()
        self.last_update_time = time.time()

    def update_from_differential_velocity(self, v_l: float, v_r: float, dt: float, gyro_z_dps: float = 0.0) -> OdometryPose:
        """
        Updates pose from commanded or observed wheel velocities (v_l, v_r in m/s) and time delta dt.
        Integrates MPU6050 gyro Z angular rate if provided.
        """
        now = time.time()
        self.last_update_time = now

        v_linear = (v_r + v_l) / 2.0
        delta_s = v_linear * dt
        self.total_distance_traveled_m += abs(delta_s)

        if abs(gyro_z_dps) > 0.001:
            self.heading_deg = (self.heading_deg + gyro_z_dps * dt) % 360.0
        else:
            omega = (v_r - v_l) / self.wheel_track_m
            self.heading_deg = (self.heading_deg + math.degrees(omega * dt)) % 360.0

        rad = math.radians(self.heading_deg)
        self.x += delta_s * math.cos(rad)
        self.y += delta_s * math.sin(rad)

        return self.get_current_pose()

    def update_from_encoders(self, left_ticks: int, right_ticks: int, gyro_heading_deg: Optional[float] = None) -> OdometryPose:
        now = time.time()
        dt = max(0.001, now - self.last_update_time)
        self.last_update_time = now
        self.has_encoder_hardware = True

        delta_l = left_ticks - self.last_left_ticks
        delta_r = right_ticks - self.last_right_ticks
        self.last_left_ticks = left_ticks
        self.last_right_ticks = right_ticks

        dist_l = (2.0 * math.pi * self.wheel_radius_m * delta_l) / self.encoder_ticks_per_rev
        dist_r = (2.0 * math.pi * self.wheel_radius_m * delta_r) / self.encoder_ticks_per_rev
        delta_s = (dist_r + dist_l) / 2.0
        self.total_distance_traveled_m += abs(delta_s)

        if gyro_heading_deg is not None:
            self.heading_deg = gyro_heading_deg % 360.0
        else:
            delta_theta_rad = (dist_r - dist_l) / self.wheel_track_m
            self.heading_deg = (self.heading_deg + math.degrees(delta_theta_rad)) % 360.0

        rad = math.radians(self.heading_deg)
        self.x += delta_s * math.cos(rad)
        self.y += delta_s * math.sin(rad)

        return self.get_current_pose()

    def update_from_action_timing(self, action: str, speed_percent: int, duration_s: float, gyro_heading_deg: Optional[float] = None) -> OdometryPose:
        now = time.time()
        self.last_update_time = now

        speed_factor = max(0.0, min(1.0, speed_percent / 100.0))
        effective_speed = self.nominal_speed_m_s * speed_factor

        act = action.lower().strip()
        delta_s = 0.0

        if act in ["forward", "move_forward"]:
            delta_s = effective_speed * duration_s
        elif act in ["reverse", "backward", "move_backward"]:
            delta_s = -effective_speed * duration_s

        self.total_distance_traveled_m += abs(delta_s)

        if gyro_heading_deg is not None:
            self.heading_deg = gyro_heading_deg % 360.0
        elif act in ["left", "turn_left"]:
            self.heading_deg = (self.heading_deg - 65.0 * speed_factor * duration_s) % 360.0
        elif act in ["right", "turn_right"]:
            self.heading_deg = (self.heading_deg + 65.0 * speed_factor * duration_s) % 360.0

        rad = math.radians(self.heading_deg)
        self.x += delta_s * math.cos(rad)
        self.y += delta_s * math.sin(rad)

        return self.get_current_pose()

    def get_current_pose(self) -> OdometryPose:
        elapsed_s = max(0.0, time.time() - self.start_time)
        time_drift_factor = (elapsed_s * (self.gyro_drift_rate_deg_per_s / 57.3)) * 0.5
        uncertainty = self.base_uncertainty_m + (self.distance_error_rate * self.total_distance_traveled_m) + time_drift_factor
        uncertainty = min(2.5, round(uncertainty, 3))

        return OdometryPose(
            x_m=round(self.x, 3),
            y_m=round(self.y, 3),
            heading_deg=round(self.heading_deg, 1),
            uncertainty_radius_m=uncertainty,
            total_distance_m=round(self.total_distance_traveled_m, 3),
            timestamp=time.time()
        )
