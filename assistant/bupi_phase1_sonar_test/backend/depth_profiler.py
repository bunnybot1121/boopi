"""
Single-Sensor 2.5D/3D Depth & Elevation Profiler.
Detects horizontal depth portals (doorways) and classifies vertical multi-pass features.
"""

import math
import time
from typing import Dict, List, Optional, Tuple
from .config import CONFIG, SonarGridConfig


class DepthPortal:
    def __init__(self, angle_deg: float, d_near_cm: float, d_far_cm: float, delta_cm: float, x_cm: float, y_cm: float):
        self.angle_deg = round(angle_deg, 1)
        self.d_near_cm = round(d_near_cm, 1)
        self.d_far_cm = round(d_far_cm, 1)
        self.delta_cm = round(delta_cm, 1)
        self.x_cm = round(x_cm, 1)
        self.y_cm = round(y_cm, 1)
        self.created_at = time.time()

    def to_dict(self) -> dict:
        return {
            "angle_deg": self.angle_deg,
            "d_near_cm": self.d_near_cm,
            "d_far_cm": self.d_far_cm,
            "delta_cm": self.delta_cm,
            "x_cm": self.x_cm,
            "y_cm": self.y_cm,
            "age_s": round(time.time() - self.created_at, 1)
        }


class VerticalFeature:
    def __init__(self, angle_deg: float, feature_type: str, d_low: float, d_high: float,
                 height_pct: float, color: str, x_cm: float, y_cm: float,
                 corridor_end_x: Optional[float] = None, corridor_end_y: Optional[float] = None):
        self.angle_deg = round(angle_deg, 1)
        self.feature_type = feature_type  # 'TALL_WALL', 'LOW_OBSTACLE', 'HANGING_OVERHANG'
        self.d_low = round(d_low, 1)
        self.d_high = round(d_high, 1)
        self.height_pct = height_pct      # 1.0 for wall, 0.25 for step, 0.75 for overhang
        self.color = color
        self.x_cm = round(x_cm, 1)
        self.y_cm = round(y_cm, 1)
        self.corridor_end_x = round(corridor_end_x, 1) if corridor_end_x is not None else None
        self.corridor_end_y = round(corridor_end_y, 1) if corridor_end_y is not None else None

    def to_dict(self) -> dict:
        return {
            "angle_deg": self.angle_deg,
            "type": self.feature_type,
            "d_low": self.d_low,
            "d_high": self.d_high,
            "height_pct": self.height_pct,
            "color": self.color,
            "x_cm": self.x_cm,
            "y_cm": self.y_cm,
            "corridor_end_x": self.corridor_end_x,
            "corridor_end_y": self.corridor_end_y,
        }


class DepthProfiler:
    def __init__(self, cfg: SonarGridConfig = CONFIG):
        self.cfg = cfg

        # Horizontal discontinuity tracking
        self.last_angle: Optional[float] = None
        self.last_dist: Optional[float] = None
        self.detected_portals: List[DepthPortal] = []

        # Two-pass angular buffers: bin index 0..180 (1-degree bins)
        self.num_bins = 181
        self.pass1_buffer: Dict[int, float] = {}  # Low/Flat pass: bin -> d_cm
        self.pass2_buffer: Dict[int, float] = {}  # High/Tilted pass: bin -> d_cm

        # Active recording pass ('pass1' or 'pass2')
        self.active_pass: str = "pass1"

    def set_active_pass(self, pass_name: str):
        if pass_name in ("pass1", "pass2"):
            self.active_pass = pass_name

    def process_ping(self, angle_deg: float, distance_cm: float, is_valid: bool) -> Tuple[Optional[DepthPortal], Optional[float]]:
        """
        Process incoming ping for horizontal discontinuity and record into active pass buffer.
        Returns (new_portal_or_none, delta_d_horiz).
        """
        delta_d: Optional[float] = None
        new_portal: Optional[DepthPortal] = None

        max_hw_range = getattr(self.cfg, "MAX_HARDWARE_RANGE_CM", self.cfg.MAX_RANGE_CM)
        if not is_valid or distance_cm >= max_hw_range:
            self.last_angle = None
            self.last_dist = None
            return None, None

        # 1. Horizontal Depth Discontinuity Detector (Delta d_horiz)
        if self.last_angle is not None and self.last_dist is not None:
            angle_diff = abs(angle_deg - self.last_angle)
            if angle_diff <= self.cfg.MAX_HORIZ_ANGLE_DIFF:
                delta_d = distance_cm - self.last_dist
                if abs(delta_d) >= self.cfg.HORIZ_DEPTH_JUMP_CM:
                    d_near = min(distance_cm, self.last_dist)
                    d_far = max(distance_cm, self.last_dist)
                    rad = math.radians(angle_deg)
                    px = d_near * math.cos(rad)
                    py = d_near * math.sin(rad)
                    new_portal = DepthPortal(angle_deg, d_near, d_far, delta_d, px, py)
                    self.detected_portals.append(new_portal)
                    # Keep latest 40 portals
                    if len(self.detected_portals) > 40:
                        self.detected_portals.pop(0)

        self.last_angle = angle_deg
        self.last_dist = distance_cm

        # 2. Record into active vertical scan buffer
        bin_idx = int(round(angle_deg))
        if 0 <= bin_idx < self.num_bins:
            if self.active_pass == "pass1":
                self.pass1_buffer[bin_idx] = distance_cm
            else:
                self.pass2_buffer[bin_idx] = distance_cm

        return new_portal, delta_d

    def compute_vertical_features(self) -> List[VerticalFeature]:
        """
        Compare Pass 1 (low) and Pass 2 (high) layers across overlapping angular bins.
        Classifies Tall Walls, Low Rubble / Step Obstacles with Open Corridors, and Hanging Overhangs.
        """
        features: List[VerticalFeature] = []

        # Find all bins where both passes have recorded data
        common_bins = set(self.pass1_buffer.keys()).intersection(set(self.pass2_buffer.keys()))

        for bin_idx in sorted(common_bins):
            d_low = self.pass1_buffer[bin_idx]
            d_high = self.pass2_buffer[bin_idx]
            delta_v = d_high - d_low
            rad = math.radians(float(bin_idx))

            if abs(delta_v) < self.cfg.VERT_WALL_DIFF_CM:
                # Both passes hit at the same distance -> Tall Solid Wall
                x = d_low * math.cos(rad)
                y = d_low * math.sin(rad)
                features.append(VerticalFeature(
                    angle_deg=float(bin_idx),
                    feature_type="TALL_WALL",
                    d_low=d_low,
                    d_high=d_high,
                    height_pct=1.0,
                    color="#ff3344",  # Red
                    x_cm=x,
                    y_cm=y
                ))
            elif delta_v >= self.cfg.VERT_STEP_DIFF_CM:
                # Upper beam traveled far behind lower obstacle -> Low Step/Rubble
                # Low obstacle is at d_low, and open corridor extends up to d_high
                x_near = d_low * math.cos(rad)
                y_near = d_low * math.sin(rad)
                x_far = d_high * math.cos(rad)
                y_far = d_high * math.sin(rad)
                features.append(VerticalFeature(
                    angle_deg=float(bin_idx),
                    feature_type="LOW_OBSTACLE",
                    d_low=d_low,
                    d_high=d_high,
                    height_pct=0.25,
                    color="#ffb300",  # Amber/Yellow
                    x_cm=x_near,
                    y_cm=y_near,
                    corridor_end_x=x_far,
                    corridor_end_y=y_far
                ))
            elif delta_v <= -self.cfg.VERT_STEP_DIFF_CM:
                # Lower beam penetrated under -> Hanging Overhang
                x = d_high * math.cos(rad)
                y = d_high * math.sin(rad)
                features.append(VerticalFeature(
                    angle_deg=float(bin_idx),
                    feature_type="HANGING_OVERHANG",
                    d_low=d_low,
                    d_high=d_high,
                    height_pct=0.75,
                    color="#ff6d00",  # Orange
                    x_cm=x,
                    y_cm=y
                ))

        return features

    def reset(self):
        self.last_angle = None
        self.last_dist = None
        self.detected_portals.clear()
        self.pass1_buffer.clear()
        self.pass2_buffer.clear()

