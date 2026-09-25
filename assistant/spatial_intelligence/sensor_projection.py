"""
BUPI Sensor Projection & Coordinate Transformation
==================================================
Transforms local robot-frame sensor readings (HC-SR04 ultrasonic echo, PIR cone,
and servo angles) into global map coordinates (X, Y).
Part of BUPI Spatial Intelligence Engine (SIH 2026 / SIH26218).

Accounts for:
- Robot global pose (X_r, Y_r, Heading_theta)
- Physical sensor mounting offsets (d_ox, d_oy) on chassis
- Mechanical sensor yaw alignment error
- Optional SG90 panning servo angle (0° to 180°, 90° = forward)
"""

import math
from typing import Dict, Any, Tuple, Optional
from dataclasses import dataclass

@dataclass
class ProjectedCoordinate:
    global_x_m: float
    global_y_m: float
    bearing_deg: float
    distance_m: float
    uncertainty_radius_m: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "x_m": round(self.global_x_m, 3),
            "y_m": round(self.global_y_m, 3),
            "bearing_deg": round(self.bearing_deg, 1),
            "distance_m": round(self.distance_m, 3),
            "uncertainty_radius_m": round(self.uncertainty_radius_m, 3)
        }

class SensorProjectionEngine:
    def __init__(
        self,
        sensor_mount_offset_x_m: float = 0.08,   # 8cm forward from robot center of rotation
        sensor_mount_offset_y_m: float = 0.0,    # Centered laterally
        mounting_yaw_bias_deg: float = 0.0,      # Calibration correction for physical bracket tilt
        sensor_offset_forward_m: Optional[float] = None
    ):
        self.offset_x = sensor_offset_forward_m if sensor_offset_forward_m is not None else sensor_mount_offset_x_m
        self.offset_y = sensor_mount_offset_y_m
        self.mounting_yaw_bias_deg = mounting_yaw_bias_deg

    def project_ultrasonic_contact(
        self,
        robot_x: float,
        robot_y: float,
        robot_theta: float,
        distance_cm: float
    ) -> Tuple[float, float]:
        """
        Convenience method returning (projected_x, projected_y) in meters.
        """
        proj = self.project_ultrasonic_target(
            robot_x_m=robot_x,
            robot_y_m=robot_y,
            robot_heading_deg=robot_theta,
            distance_cm=distance_cm
        )
        if proj is not None:
            return round(proj.global_x_m, 3), round(proj.global_y_m, 3)

        # Fallback projection if distance is out of bounds
        dist_m = distance_cm / 100.0
        rad = math.radians(robot_theta)
        return round(robot_x + math.cos(rad) * dist_m, 3), round(robot_y + math.sin(rad) * dist_m, 3)

    def project_ultrasonic_target(
        self,
        robot_x_m: float,
        robot_y_m: float,
        robot_heading_deg: float,
        distance_cm: float,
        servo_angle_deg: float = 90.0,
        robot_uncertainty_m: float = 0.05
    ) -> Optional[ProjectedCoordinate]:
        """
        Projects an acoustic reflection from the HC-SR04 into global coordinates.
        Servo angle: 90° is directly forward; 0° is full left; 180° is full right.
        """
        if distance_cm <= 2.0 or distance_cm >= 450.0:
            return None  # Out of reliable sensor bounds

        distance_m = distance_cm / 100.0

        # Relative angle of the sensor beam relative to robot chassis forward vector
        # servo 90° -> relative 0°
        relative_beam_angle = (servo_angle_deg - 90.0) + self.mounting_yaw_bias_deg

        # Total world bearing angle (CCW from +X axis)
        total_bearing_deg = (robot_heading_deg + relative_beam_angle) % 360.0
        theta_rad = math.radians(robot_heading_deg)
        bearing_rad = math.radians(total_bearing_deg)

        # 1. Transform mounting offset from robot body frame to world frame
        mount_world_x = robot_x_m + (self.offset_x * math.cos(theta_rad) - self.offset_y * math.sin(theta_rad))
        mount_world_y = robot_y_m + (self.offset_x * math.sin(theta_rad) + self.offset_y * math.cos(theta_rad))

        # 2. Project target along total bearing
        target_x = mount_world_x + (distance_m * math.cos(bearing_rad))
        target_y = mount_world_y + (distance_m * math.sin(bearing_rad))

        # Target uncertainty grows with distance due to the ~20° ultrasonic beam spread
        beam_spread_m = distance_m * math.tan(math.radians(10.0))
        total_uncertainty = robot_uncertainty_m + beam_spread_m + 0.03

        return ProjectedCoordinate(
            global_x_m=target_x,
            global_y_m=target_y,
            bearing_deg=total_bearing_deg,
            distance_m=distance_m,
            uncertainty_radius_m=total_uncertainty
        )
