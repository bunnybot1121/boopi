"""
Configuration constants for BUPI Phase 1 Ultrasonic Vision & Plotting Engine.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SonarGridConfig:
    # Grid dimensions (120x120 @ 4.0cm = 480cm x 480cm / 4.8m x 4.8m room)
    GRID_WIDTH: int = 120
    GRID_HEIGHT: int = 120
    RESOLUTION_CM: float = 4.0  # cm per pixel/cell

    # Origin: Center of the grid (X=60, Y=60)
    ORIGIN_X: int = 60
    ORIGIN_Y: int = 60

    # Ultrasonic Sensor physical specs
    CONE_ANGLE_DEG: float = 15.0
    CONE_HALF_ANGLE_DEG: float = 7.5
    MIN_RANGE_CM: float = 3.0
    MAX_RANGE_CM: float = 400.0

    # Log-Odds Bayesian Occupancy Grid Parameters
    # L(m|z) = L(m|z_prev) + l_meas - l_0
    L_0: float = 0.0          # Prior log-odds (p=0.5 -> log(0.5/0.5)=0)
    L_FREE: float = -0.35     # Measurement update for free space cells
    L_HIT: float = 0.85       # Measurement update for obstacle hit arc
    L_MIN: float = -5.0       # Clamp bounds for numerical stability
    L_MAX: float = 5.0

    # Probability thresholds
    PROB_FREE_THRESH: float = 0.35
    PROB_OCC_THRESH: float = 0.65

    # 2.5D / 3D Depth Discontinuity Thresholds
    HORIZ_DEPTH_JUMP_CM: float = 35.0   # Doorway / Portal edge detection
    MAX_HORIZ_ANGLE_DIFF: float = 25.0  # Max angular gap to consider consecutive

    # Two-Pass Vertical Height Thresholds
    VERT_WALL_DIFF_CM: float = 15.0     # abs(d_high - d_low) < 15 -> Tall Wall
    VERT_STEP_DIFF_CM: float = 35.0     # (d_high - d_low) > 35 -> Low Obstacle

    # OpenCV Safety Buffer Dilation
    DILATION_KERNEL_SIZE: int = 5       # 5x5 kernel ~ 20cm robot clearance buffer


CONFIG = SonarGridConfig()

