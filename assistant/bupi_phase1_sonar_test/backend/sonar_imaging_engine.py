"""
Unified Sonar Imaging Engine coordinating Bayesian grid, depth profiler, CV pipeline,
and AI Map Decision Reader.
"""

import time
import math
from typing import Any, Dict, List, Optional
import numpy as np

from .config import CONFIG, SonarGridConfig
from .log_odds_grid import LogOddsOccupancyGrid
from .depth_profiler import DepthProfiler, DepthPortal, VerticalFeature
from .cv_pipeline import SonarCVPipeline
from .ai_map_decision_reader import AIMapDecisionReader


class SonarImagingEngine:
    def __init__(self, cfg: SonarGridConfig = CONFIG):
        self.cfg = cfg
        self.grid = LogOddsOccupancyGrid(cfg)
        self.profiler = DepthProfiler(cfg)
        self.cv_pipe = SonarCVPipeline(cfg)
        self.ai_reader = AIMapDecisionReader(cfg)

        # Statistics & telemetry state
        self.total_pings: int = 0
        self.hit_count: int = 0
        self.latest_telemetry: Dict[str, Any] = {
            "ts": 0,
            "d_cm": 0.0,
            "angle_deg": 90.0,
            "valid": 0,
            "safety_stop": 0,
            "imu": False,
            "yaw": None,
            "pitch": None,
            "delta_d": None,
            "active_pass": "pass1"
        }

        # Rolling history of recent polar pings for the radar scope
        self.polar_history: List[Dict[str, Any]] = []

    def set_active_pass(self, pass_name: str):
        self.profiler.set_active_pass(pass_name)
        self.latest_telemetry["active_pass"] = pass_name

    def ingest_ping(
        self,
        angle_deg: float,
        distance_cm: float,
        is_valid: bool = True,
        timestamp_ms: Optional[int] = None,
        safety_stop: int = 0,
        imu_detected: bool = False,
        yaw: Optional[float] = None,
        pitch: Optional[float] = None,
        weight_scale: float = 1.0,
        s_ang: Optional[float] = None,
        min_ang: Optional[float] = 45.0,
        max_ang: Optional[float] = 135.0,
        sweep_dir: Optional[str] = "STEADY",
        bot_id: str = "BUPI-01"
    ) -> Dict[str, Any]:
        """
        Ingest a single ultrasonic reading:
        1. Updates Bayesian Log-Odds grid.
        2. Detects horizontal depth portals & stores vertical pass buffer.
        3. Records telemetry and updates rolling history.
        """
        self.total_pings += 1
        ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)

        # 1. Update Bayesian Occupancy Grid
        self.grid.integrate_ping(angle_deg, distance_cm, is_valid, weight_scale)
        if is_valid and distance_cm < (self.cfg.MAX_RANGE_CM - 5.0):
            self.hit_count += 1

        # 2. Process Depth Profiler (Horizontal Portals & Pass Buffers)
        portal, delta_d = self.profiler.process_ping(angle_deg, distance_cm, is_valid)

        # 3. Update telemetry state with Hardware Servo Turret details
        cur_s_ang = round(s_ang, 1) if s_ang is not None else round(angle_deg, 1)
        self.latest_telemetry = {
            "bot_id": bot_id,
            "ts": ts,
            "d_cm": round(distance_cm, 1),
            "angle_deg": round(angle_deg, 1),
            "s_ang": cur_s_ang,
            "min_ang": round(min_ang, 1) if min_ang is not None else 45.0,
            "max_ang": round(max_ang, 1) if max_ang is not None else 135.0,
            "sweep_dir": sweep_dir or "STEADY",
            "valid": 1 if is_valid else 0,
            "safety_stop": safety_stop or (1 if is_valid and distance_cm <= 15.0 else 0),
            "imu": imu_detected,
            "yaw": round(yaw, 1) if yaw is not None else None,
            "pitch": round(pitch, 1) if pitch is not None else None,
            "delta_d": round(delta_d, 1) if delta_d is not None else None,
            "portal_detected": portal is not None,
            "active_pass": self.profiler.active_pass,
            "total_pings": self.total_pings,
            "hit_count": self.hit_count
        }

        # 4. Add to rolling polar history
        history_item = {
            "angle_deg": round(angle_deg, 1),
            "s_ang": cur_s_ang,
            "d_cm": round(distance_cm, 1),
            "valid": 1 if is_valid else 0,
            "delta_d": round(delta_d, 1) if delta_d is not None else None,
            "is_portal": portal is not None,
            "pass": self.profiler.active_pass,
            "ts": ts
        }
        self.polar_history.append(history_item)
        if len(self.polar_history) > 120:
            self.polar_history.pop(0)

        return self.latest_telemetry

    def get_state_snapshot(self, include_image: bool = True, show_dilation: bool = True) -> Dict[str, Any]:
        """
        Generate full real-time state payload for WebSocket clients.
        """
        prob_grid = self.grid.get_probability_grid()
        portals = self.profiler.detected_portals
        vertical_features = self.profiler.compute_vertical_features()

        image_b64 = None
        if include_image:
            semantic_img = self.cv_pipe.generate_semantic_image(
                prob_grid, portals, vertical_features, show_dilation=show_dilation
            )
            image_b64 = self.cv_pipe.encode_base64_data_url(semantic_img)

        # Quantized stats for UI badge
        free_cells = int(np.sum(prob_grid < self.cfg.PROB_FREE_THRESH))
        occ_cells = int(np.sum(prob_grid >= self.cfg.PROB_OCC_THRESH))
        unknown_cells = int((self.cfg.GRID_WIDTH * self.cfg.GRID_HEIGHT) - (free_cells + occ_cells))

        # AI Map Reader & Decisions
        sectors = self.ai_reader.analyze_5_sectors(self.profiler.pass1_buffer, portals, vertical_features)
        astar_waypoints, command, target_heading = self.ai_reader.compute_astar_path(prob_grid, portals, sectors)
        ascii_matrix = self.ai_reader.generate_ascii_20x20(prob_grid, portals, vertical_features)

        # Extract active non-empty cells for Viewport 3 Voxel rendering
        active_voxels = self._extract_active_voxels(prob_grid, vertical_features)

        return {
            "telemetry": self.latest_telemetry,
            "portals": [p.to_dict() for p in portals],
            "vertical_features": [vf.to_dict() for vf in vertical_features],
            "polar_history": self.polar_history[-40:],
            "semantic_image_b64": image_b64,
            "active_voxels": active_voxels,
            "ai_decision": {
                "sectors": sectors,
                "astar_path": astar_waypoints,
                "steering_command": command,
                "target_heading_deg": target_heading,
                "ascii_matrix": ascii_matrix
            },
            "stats": {
                "free_cells": free_cells,
                "occ_cells": occ_cells,
                "unknown_cells": unknown_cells,
                "total_pings": self.total_pings,
                "pass1_points": len(self.profiler.pass1_buffer),
                "pass2_points": len(self.profiler.pass2_buffer)
            }
        }

    def _extract_active_voxels(self, prob_grid: np.ndarray, vertical_features: List[VerticalFeature]) -> List[Dict[str, Any]]:
        """
        Extract active 3D cells for full voxel mesh generation:
        - Walls (P >= 0.65)
        - Free floor (P <= 0.35)
        Downsamples slightly if many cells to maintain 60 FPS in 3D.
        """
        voxels = []
        h, w = prob_grid.shape

        # Identify low step angles
        low_step_angles = set()
        for vf in vertical_features:
            if vf.feature_type == "LOW_OBSTACLE":
                low_step_angles.add(round(vf.angle_deg))

        # Scan cells with step 1 or 2
        step = 1 if (np.sum(prob_grid >= self.cfg.PROB_OCC_THRESH) < 400) else 2
        for r in range(0, h, step):
            for c in range(0, w, step):
                p = prob_grid[r, c]
                if p >= self.cfg.PROB_OCC_THRESH:
                    wx = (c - self.cfg.ORIGIN_X) * self.cfg.RESOLUTION_CM
                    wy = (self.cfg.ORIGIN_Y - r) * self.cfg.RESOLUTION_CM
                    ang = int(round((math.degrees(math.atan2(wy, wx)) + 360) % 360))

                    is_low_step = ang in low_step_angles
                    voxels.append({
                        "x": round(wx, 1),
                        "y": round(wy, 1),
                        "type": "LOW_STEP" if is_low_step else "TALL_WALL",
                        "p": round(float(p), 2)
                    })
                elif p <= self.cfg.PROB_FREE_THRESH and (r % 3 == 0 and c % 3 == 0):
                    # Sampled free floor tiles
                    wx = (c - self.cfg.ORIGIN_X) * self.cfg.RESOLUTION_CM
                    wy = (self.cfg.ORIGIN_Y - r) * self.cfg.RESOLUTION_CM
                    voxels.append({
                        "x": round(wx, 1),
                        "y": round(wy, 1),
                        "type": "FREE_FLOOR",
                        "p": round(float(p), 2)
                    })

        return voxels

    def get_map_png(self, show_dilation: bool = True) -> bytes:
        prob_grid = self.grid.get_probability_grid()
        portals = self.profiler.detected_portals
        vertical_features = self.profiler.compute_vertical_features()
        semantic_img = self.cv_pipe.generate_semantic_image(
            prob_grid, portals, vertical_features, show_dilation=show_dilation
        )
        return self.cv_pipe.encode_png_bytes(semantic_img)

    def export_full_matrix_json(self) -> Dict[str, Any]:
        """Export raw log-odds matrix, config, and 3D features as JSON."""
        return {
            "config": {
                "width": self.cfg.GRID_WIDTH,
                "height": self.cfg.GRID_HEIGHT,
                "resolution_cm": self.cfg.RESOLUTION_CM,
                "origin": [self.cfg.ORIGIN_X, self.cfg.ORIGIN_Y]
            },
            "log_odds_matrix": self.grid.grid.tolist(),
            "portals": [p.to_dict() for p in self.profiler.detected_portals],
            "vertical_features": [vf.to_dict() for vf in self.profiler.compute_vertical_features()],
            "pass1_buffer": self.profiler.pass1_buffer,
            "pass2_buffer": self.profiler.pass2_buffer,
            "telemetry": self.latest_telemetry
        }

    def reset(self):
        self.grid.reset()
        self.profiler.reset()
        self.total_pings = 0
        self.hit_count = 0
        self.polar_history.clear()
        self.latest_telemetry["valid"] = 0
        self.latest_telemetry["safety_stop"] = 0
        self.latest_telemetry["delta_d"] = None
        self.latest_telemetry["portal_detected"] = False
