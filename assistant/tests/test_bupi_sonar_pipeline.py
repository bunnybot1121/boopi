"""
Unit tests for BUPI Phase 1 Sonar Vision & DIP Engine.
"""

import sys
import os
import unittest
import numpy as np

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bupi_phase1_sonar_test")))

from backend.config import CONFIG
from backend.log_odds_grid import LogOddsOccupancyGrid
from backend.depth_profiler import DepthProfiler
from backend.cv_pipeline import SonarCVPipeline
from backend.sonar_imaging_engine import SonarImagingEngine
from backend.serial_manager import SerialManager


class TestSonarPipeline(unittest.TestCase):
    def setUp(self):
        self.engine = SonarImagingEngine(CONFIG)

    def test_grid_coordinate_transforms(self):
        grid = LogOddsOccupancyGrid(CONFIG)
        # Origin (0, 0) cm should map to (60, 60)
        c, r = grid.world_to_grid(0.0, 0.0)
        self.assertEqual((c, r), (60, 60))

        # Forward 100cm (+Y) should decrease row index (60 - 25 = 35)
        c, r = grid.world_to_grid(0.0, 100.0)
        self.assertEqual(c, 60)
        self.assertEqual(r, 35)

        # Right 100cm (+X) should increase col index (60 + 25 = 85)
        c, r = grid.world_to_grid(100.0, 0.0)
        self.assertEqual(c, 85)
        self.assertEqual(r, 60)

    def test_bayesian_log_odds_integration(self):
        grid = LogOddsOccupancyGrid(CONFIG)
        initial_prob = grid.get_probability_grid()
        # Initial cells must be 0.5 (unknown)
        np.testing.assert_allclose(initial_prob[60, 60], 0.5, atol=1e-3)

        # Ping straight ahead (90 deg) at 120 cm
        grid.integrate_ping(angle_deg=90.0, distance_cm=120.0, is_valid=True)
        prob = grid.get_probability_grid()

        # Free space along the ray (e.g. at Y = 60 cm, row = 60 - 15 = 45) must have P < 0.5
        self.assertLess(prob[45, 60], 0.5)

        # Obstacle endpoint (at Y = 120 cm, row = 60 - 30 = 30) must have P > 0.5
        self.assertGreater(prob[30, 60], 0.5)

    def test_depth_portal_discontinuity(self):
        profiler = DepthProfiler(CONFIG)
        # Ping at 45 deg, dist 100cm
        p1, d1 = profiler.process_ping(angle_deg=45.0, distance_cm=100.0, is_valid=True)
        self.assertIsNone(p1)

        # Ping at 47 deg with depth jump to 220cm (delta = 120cm > 35cm threshold)
        p2, d2 = profiler.process_ping(angle_deg=47.0, distance_cm=220.0, is_valid=True)
        self.assertIsNotNone(p2)
        self.assertGreaterEqual(abs(d2), 35.0)
        self.assertEqual(len(profiler.detected_portals), 1)

    def test_two_pass_vertical_comparator(self):
        profiler = DepthProfiler(CONFIG)

        # Pass 1: Low ground sweep
        profiler.set_active_pass("pass1")
        profiler.process_ping(angle_deg=90.0, distance_cm=100.0, is_valid=True)   # Tall wall test
        profiler.process_ping(angle_deg=130.0, distance_cm=80.0, is_valid=True)   # Low step test

        # Pass 2: High tilted sweep
        profiler.set_active_pass("pass2")
        profiler.process_ping(angle_deg=90.0, distance_cm=102.0, is_valid=True)   # diff = 2cm < 15 -> Tall Wall
        profiler.process_ping(angle_deg=130.0, distance_cm=180.0, is_valid=True)  # diff = 100cm > 35 -> Low Step + Corridor

        features = profiler.compute_vertical_features()
        self.assertEqual(len(features), 2)

        feat_types = {f.angle_deg: f.feature_type for f in features}
        self.assertEqual(feat_types[90.0], "TALL_WALL")
        self.assertEqual(feat_types[130.0], "LOW_OBSTACLE")

    def test_cv_pipeline_dilation_and_semantic(self):
        cv_pipe = SonarCVPipeline(CONFIG)
        grid = LogOddsOccupancyGrid(CONFIG)
        # Add hit
        grid.integrate_ping(angle_deg=90.0, distance_cm=100.0, is_valid=True)
        prob = grid.get_probability_grid()

        # Generate grayscale
        gray = cv_pipe.generate_grayscale_image(prob)
        self.assertEqual(gray.shape, (120, 120))
        self.assertEqual(gray.dtype, np.uint8)

        # Generate dilation mask
        dilated = cv_pipe.generate_dilation_mask(prob)
        self.assertEqual(dilated.shape, (120, 120))
        self.assertGreater(np.sum(dilated > 0), 0)

        # Generate semantic RGB
        semantic = cv_pipe.generate_semantic_image(prob, [], [], show_dilation=True)
        self.assertEqual(semantic.shape, (120, 120, 3))
        self.assertEqual(semantic.dtype, np.uint8)

        # Check PNG encoding
        png_bytes = cv_pipe.encode_png_bytes(semantic)
        self.assertTrue(png_bytes.startswith(b'\x89PNG\r\n\x1a\n'))

    def test_ai_decision_reader_and_astar(self):
        # Ingest a set of pings
        self.engine.ingest_ping(angle_deg=90.0, distance_cm=180.0, is_valid=True)
        self.engine.ingest_ping(angle_deg=45.0, distance_cm=120.0, is_valid=True)
        self.engine.ingest_ping(angle_deg=135.0, distance_cm=90.0, is_valid=True)

        snapshot = self.engine.get_state_snapshot(include_image=False)
        self.assertIn("ai_decision", snapshot)
        ai = snapshot["ai_decision"]

        # 1. 5 Sectors
        self.assertIn("sectors", ai)
        self.assertIn("Center", ai["sectors"])
        self.assertIn("Left", ai["sectors"])
        self.assertIn("Right", ai["sectors"])

        # 2. A* Path & Steering Command
        self.assertIn("astar_path", ai)
        self.assertIn("steering_command", ai)
        self.assertTrue(len(ai["steering_command"]) > 0)

        # 3. 20x20 ASCII Matrix
        self.assertIn("ascii_matrix", ai)
        self.assertIn("+--------------------+", ai["ascii_matrix"])
        self.assertIn("B", ai["ascii_matrix"])  # Robot origin marker

        # 4. Active Voxels
        self.assertIn("active_voxels", snapshot)
        self.assertIsInstance(snapshot["active_voxels"], list)

    def test_dual_sonar_3d_engine_classification(self):
        from backend.sonar_3d_engine import Sonar3DEngine
        engine_3d = Sonar3DEngine(CONFIG)

        # 1. Tall Wall: d1 = 100cm, d2 = 104cm (abs(delta) <= 25)
        res_wall = engine_3d.integrate_dual_ping(90.0, 100.0, 104.0, True, True, 90.0, 90.0)
        self.assertEqual(res_wall["class"], "TALL_SOLID_WALL")
        self.assertEqual(res_wall["z_cm"], 25.0)

        # 2. Low Step: d1 = 80cm, d2 = 180cm (delta = 100cm > 30)
        res_step = engine_3d.integrate_dual_ping(45.0, 80.0, 180.0, True, True, 45.0, 45.0)
        self.assertEqual(res_step["class"], "LOW_STEP_RUBBLE")
        self.assertEqual(res_step["z_cm"], 6.0)

        # 3. Overhang: d1 = 200cm, d2 = 90cm (delta = -110cm < -30)
        res_over = engine_3d.integrate_dual_ping(135.0, 200.0, 90.0, True, True, 135.0, 135.0)
        self.assertEqual(res_over["class"], "OVERHANG_HAZARD")

        # 4. 3D point cloud & voxels
        self.assertGreater(len(engine_3d.points_3d), 0)
        voxels = engine_3d.extract_3d_voxels()
        self.assertIsInstance(voxels, list)

        # 5. Sector clearance
        sectors = engine_3d.analyze_5_sectors_3d()
        self.assertIn("Center", sectors)
        self.assertIn("Front-Right", sectors)

        # 6. ASCII 3D Map
        ascii_map = engine_3d.generate_ascii_20x20_3d()
        self.assertIn("B", ascii_map)

    def test_server_endpoints_and_dual_ping_api(self):
        from fastapi.testclient import TestClient
        from backend.server import app
        client = TestClient(app)

        # 1. Status
        res = client.get("/api/status")
        self.assertEqual(res.status_code, 200)
        self.assertIn("connected", res.json())

        # 2. Scan Cfg
        res_cfg = client.post("/api/scan_cfg", json={
            "mode": "STACKED_3D",
            "min_ang": 45,
            "max_ang": 135,
            "step": 3,
            "sweep_en": 1,
            "center_90": 0
        })
        self.assertEqual(res_cfg.status_code, 200)

        # 3. Dual Ping Ingest
        res_ping = client.post("/api/ping", json={
            "angle_deg": 90.0,
            "d1_cm": 120.0,
            "d2_cm": 125.0,
            "s1_ang": 90.0,
            "s2_ang": 90.0,
            "mode": "STACKED_3D",
            "valid": 1,
            "valid1": 1,
            "valid2": 1,
            "safety_stop": 0
        })
        self.assertEqual(res_ping.status_code, 200)
        tel = res_ping.json()["telemetry"]
        self.assertEqual(tel["d1_cm"], 120.0)
        self.assertEqual(tel["d2_cm"], 125.0)
        self.assertEqual(tel["class_3d"], "TALL_SOLID_WALL")


if __name__ == "__main__":
    unittest.main()
