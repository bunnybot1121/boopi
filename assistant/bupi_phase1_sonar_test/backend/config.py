"""
Configuration constants for BUPI Phase 1 Ultrasonic Vision & Plotting Engine.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SonarGridConfig:
    # High-resolution grid (200x200: 2.0cm/px @ 200cm Room default, 1.0cm/px @ 100cm, 4.0cm/px @ 400cm)
    GRID_WIDTH: int = 200
    GRID_HEIGHT: int = 200
    RESOLUTION_CM: float = 2.0  # Default cm per pixel/cell at 200cm Room view

    # Origin: Center of the grid (X=100, Y=100)
    ORIGIN_X: int = 100
    ORIGIN_Y: int = 100

    # Ultrasonic Sensor physical specs
    CONE_ANGLE_DEG: float = 15.0
    CONE_HALF_ANGLE_DEG: float = 7.5
    MIN_RANGE_CM: float = 3.0
    MAX_RANGE_CM: float = 200.0        # Default 200cm Room view (100cm / 150cm / 200cm / 400cm selectable)
    MAX_HARDWARE_RANGE_CM: float = 400.0

    # Asymmetric Log-Odds Bayesian Occupancy Grid Parameters with Hit-Lock Hysteresis
    L_0: float = 0.0          # Prior log-odds (p=0.5 -> log(0.5/0.5)=0)
    L_FREE: float = -0.20     # Weak free-space update (cannot easily erase real walls)
    L_HIT: float = 1.40       # Strong obstacle hit weight
    L_LOCK_THRESH: float = 1.50  # Protected wall log-odds threshold against oblique free rays
    L_MIN: float = -4.0       # Clamp bounds for numerical stability
    L_MAX: float = 6.0

    # Probability thresholds
    PROB_FREE_THRESH: float = 0.42
    PROB_OCC_THRESH: float = 0.65

    # 2.5D / 3D Depth Discontinuity Thresholds
    HORIZ_DEPTH_JUMP_CM: float = 35.0   # Doorway / Portal edge detection
    MAX_HORIZ_ANGLE_DIFF: float = 25.0  # Max angular gap to consider consecutive

    # Two-Pass Vertical Height Thresholds
    VERT_WALL_DIFF_CM: float = 15.0     # abs(d_high - d_low) < 15 -> Tall Wall
    VERT_STEP_DIFF_CM: float = 35.0     # (d_high - d_low) > 35 -> Low Obstacle

    # OpenCV Safety Buffer Dilation
    DILATION_KERNEL_SIZE: int = 5       # 5x5 kernel ~ robot clearance buffer
    MORPH_CLOSE_SIZE: int = 3           # 3x3 morphological closing to fuse obstacle gaps


CONFIG = SonarGridConfig()

