"""
Unified Sonar Imaging Engine coordinating Bayesian grid, depth profiler, CV pipeline,
AI Map Decision Reader, and 2.5D/3D Volumetric Mapping Engine.
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
from .sonar_3d_engine import Sonar3DEngine


class SonarImagingEngine:
    def __init__(self, cfg: SonarGridConfig = CONFIG):
        self.cfg = cfg
        self.grid = LogOddsOccupancyGrid(cfg)
        self.profiler = DepthProfiler(cfg)
        self.cv_pipe = SonarCVPipeline(cfg)
        self.ai_reader = AIMapDecisionReader(cfg)
        self.engine_3d = Sonar3DEngine(cfg)

        self.total_pings: int = 0
        self.hit_count: int = 0
        self.latest_telemetry: Dict[str, Any] = {
            "bot_id": "BUPI-01",
            "ts": 0,
            "mode": "STACKED_3D",
            "d1_cm": 0.0,
            "d2_cm": 0.0,
            "d_cm": 0.0,
            "s1_ang": 90.0,
            "s2_ang": 90.0,
            "s_ang": 90.0,
            "angle_deg": 90.0,
            "delta_d": 0.0,
            "valid1": 0,
            "valid2": 0,
            "valid": 0,
            "safety_stop": 0,
            "imu": False,
            "yaw": None,
            "pitch": None,
            "class_3d": "OPEN_CORRIDOR",
            "sweep_dir": "STEADY",
            "min_ang": 45.0,
            "max_ang": 135.0,
            "active_pass": "pass1"
        }

        self.polar_history: List[Dict[str, Any]] = []

    def set_active_pass(self, pass_name: str):
        self.profiler.set_active_pass(pass_name)
        self.latest_telemetry["active_pass"] = pass_name

    def ingest_dual_ping(
        self,
        theta_deg: float,
        d1_cm: float,
        d2_cm: float,
        valid1: bool = True,
        valid2: bool = True,
        s1_ang: Optional[float] = None,
        s2_ang: Optional[float] = None,
        mode: str = "STACKED_3D",
        timestamp_ms: Optional[int] = None,
        safety_stop: int = 0,
        imu_detected: bool = False,
        yaw: Optional[float] = None,
        pitch: Optional[float] = None,
        min_ang: float = 45.0,
        max_ang: float = 135.0,
        sweep_dir: str = "STEADY",
        bot_id: str = "BUPI-01"
    ) -> Dict[str, Any]:
        """
        Ingests synchronized Dual-Ultrasonic + Dual-Servo reading.
        Updates 2.5D/3D volumetric tensor, differential depth features, and safety status.
        """
        self.total_pings += 1
        ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
        s1 = s1_ang if s1_ang is not None else theta_deg
        s2 = s2_ang if s2_ang is not None else s1

        # Integrate with 3D engine
        res_3d = self.engine_3d.integrate_dual_ping(
            theta_deg=theta_deg,
            d1_cm=d1_cm,
            d2_cm=d2_cm,
            valid1=valid1,
            valid2=valid2,
            s1_ang=s1,
            s2_ang=s2,
            pitch_deg=pitch if pitch is not None else 12.0
        )

        # Update legacy 2D grid
        self.grid.integrate_ping(theta_deg, d1_cm, valid1)
        if valid1 and d1_cm < (self.cfg.MAX_RANGE_CM - 5.0):
            self.hit_count += 1

        portal, _ = self.profiler.process_ping(theta_deg, d1_cm, valid1)

        delta_d = round(d2_cm - d1_cm, 1)
        self.latest_telemetry = {
            "bot_id": bot_id,
            "ts": ts,
            "mode": mode,
            "d1_cm": round(d1_cm, 1),
            "d2_cm": round(d2_cm, 1),
            "d_cm": round(d1_cm, 1),
            "s1_ang": round(s1, 1),
            "s2_ang": round(s2, 1),
            "s_ang": round(s1, 1),
            "angle_deg": round(theta_deg, 1),
            "delta_d": delta_d,
            "valid1": 1 if valid1 else 0,
            "valid2": 1 if valid2 else 0,
            "valid": 1 if valid1 else 0,
            "safety_stop": safety_stop or (1 if ((valid1 and d1_cm < 18.0) or (valid2 and d2_cm < 18.0)) else 0),
            "imu": imu_detected,
            "yaw": round(yaw, 1) if yaw is not None else None,
            "pitch": round(pitch, 1) if pitch is not None else None,
            "class_3d": res_3d["class"],
            "color_3d": res_3d["color"],
            "sweep_dir": sweep_dir,
            "min_ang": round(min_ang, 1),
            "max_ang": round(max_ang, 1),
            "portal_detected": res_3d["is_portal"],
            "total_pings": self.total_pings,
            "hit_count": self.hit_count
        }

        # Rolling history supporting dual beams (Beam 1 Low + Beam 2 High)
        history_item = {
            "angle_deg": round(theta_deg, 1),
            "s1_ang": round(s1, 1),
            "s2_ang": round(s2, 1),
            "d1_cm": round(d1_cm, 1),
            "d2_cm": round(d2_cm, 1),
            "d_cm": round(d1_cm, 1),
            "delta_d": delta_d,
            "valid1": 1 if valid1 else 0,
            "valid2": 1 if valid2 else 0,
            "class_3d": res_3d["class"],
            "is_portal": res_3d["is_portal"],
            "ts": ts
        }
        self.polar_history.append(history_item)
        if len(self.polar_history) > 120:
            self.polar_history.pop(0)

        return self.latest_telemetry

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
        """Backward-compatible single-beam ingestion routing to dual-ping handler."""
        return self.ingest_dual_ping(
            theta_deg=angle_deg,
            d1_cm=distance_cm,
            d2_cm=distance_cm,
            valid1=is_valid,
            valid2=is_valid,
            s1_ang=s_ang,
            s2_ang=s_ang,
            mode="STACKED_3D",
            timestamp_ms=timestamp_ms,
            safety_stop=safety_stop,
            imu_detected=imu_detected,
            yaw=yaw,
            pitch=pitch,
            min_ang=min_ang or 45.0,
            max_ang=max_ang or 135.0,
            sweep_dir=sweep_dir or "STEADY",
            bot_id=bot_id
        )

    def get_state_snapshot(self, include_image: bool = True, show_dilation: bool = True) -> Dict[str, Any]:
        """Generates comprehensive real-time state payload for WebSocket clients."""
        prob_grid = self.engine_3d.get_probability_grid()
        portals = self.engine_3d.portals
        vertical_features = self.profiler.compute_vertical_features()

        image_b64 = None
        if include_image:
            semantic_img = self.cv_pipe.generate_semantic_image(
                prob_grid, portals, vertical_features, show_dilation=show_dilation
            )
            image_b64 = self.cv_pipe.encode_base64_data_url(semantic_img)

        # AI Map Reader & Decisions from 3D Engine
        sectors_3d = self.engine_3d.analyze_5_sectors_3d()
        astar_waypoints, command, target_heading = self.engine_3d.compute_astar_2_5d()
        ascii_matrix = self.engine_3d.generate_ascii_20x20_3d()

        # True 3D Voxels with height extrusions
        active_voxels = self.engine_3d.extract_3d_voxels()

        free_cells = int(np.sum(prob_grid < self.cfg.PROB_FREE_THRESH))
        occ_cells = int(np.sum(prob_grid >= self.cfg.PROB_OCC_THRESH))
        unknown_cells = int((self.cfg.GRID_WIDTH * self.cfg.GRID_HEIGHT) - (free_cells + occ_cells))

        return {
            "telemetry": self.latest_telemetry,
            "portals": portals,
            "vertical_features": [vf.to_dict() for vf in vertical_features],
            "points_3d": self.engine_3d.points_3d[-150:],
            "polar_history": self.polar_history[-60:],
            "semantic_image_b64": image_b64,
            "active_voxels": active_voxels,
            "ai_decision": {
                "sectors": sectors_3d,
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
                "hit_count": self.hit_count,
                "points_3d_count": len(self.engine_3d.points_3d)
            }
        }

    def reset(self):
        self.grid.reset()
        self.profiler.reset()
        self.engine_3d.reset()
        self.total_pings = 0
        self.hit_count = 0
        self.polar_history.clear()
        self.latest_telemetry["valid"] = 0
        self.latest_telemetry["valid1"] = 0
        self.latest_telemetry["valid2"] = 0
        self.latest_telemetry["safety_stop"] = 0
        self.latest_telemetry["delta_d"] = 0.0
        self.latest_telemetry["portal_detected"] = False
