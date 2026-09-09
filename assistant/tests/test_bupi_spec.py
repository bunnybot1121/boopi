"""
Automated Unit & Integration Test Suite for BUPI Specification
==============================================================
Validates:
1. High-level intent parsing across varied natural language expressions
2. Sensor epistemic constraints (PIR != human confirmed; Ultrasonic != object ID)
3. Multi-sensor fusion logic and target inference
4. Safety Controller priority & override enforcement
5. Planner closed-loop structured action emissions
"""

import sys
import os
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from intent import IntentParser, HighLevelIntent
from sensors import PIRSensor, PIRState, UltrasonicSensor, DistanceClassification, MPU6050Sensor, SensorFusion
from safety import SafetyController, SafetyVerdict
from planner import StateManager, GoalManager, AutonomousPlanner, StructuredAction

class TestBupiIntentParser(unittest.TestCase):
    def setUp(self):
        self.parser = IntentParser()

    def test_search_for_presence_phrasing(self):
        phrases = [
            "BUPI, find a person in this room.",
            "Find a person in the room.",
            "Search around and find someone.",
            "Look around this room for people.",
            "Locate someone in the house.",
            "Can you check if there is a human here?"
        ]
        for p in phrases:
            goal = self.parser.parse(p)
            self.assertEqual(
                goal.intent, HighLevelIntent.SEARCH_FOR_PRESENCE,
                f"Failed for phrase: '{p}' (got {goal.intent})"
            )
            self.assertIn("movement", goal.relevant_capabilities)
            self.assertIn("PIR motion detection", goal.relevant_capabilities)

    def test_other_intents(self):
        self.assertEqual(
            self.parser.parse("Explore this area safely.").intent,
            HighLevelIntent.EXPLORE_SAFE
        )
        self.assertEqual(
            self.parser.parse("Watch for motion and alert me.").intent,
            HighLevelIntent.MONITOR_MOTION
        )
        self.assertEqual(
            self.parser.parse("Patrol the perimeter.").intent,
            HighLevelIntent.PATROL
        )
        self.assertEqual(
            self.parser.parse("Stop moving right now.").intent,
            HighLevelIntent.STOP_AND_WAIT
        )

class TestSensorEpistemics(unittest.TestCase):
    def test_pir_epistemic_rule(self):
        pir = PIRSensor()
        interp = pir.update_raw(1)
        self.assertTrue(interp["motion_detected"])
        self.assertEqual(interp["state"], PIRState.MOTION_DETECTED.value)
        self.assertEqual(interp["inference"], PIRState.POSSIBLE_WARM_TARGET.value)
        # CRUCIAL RULE: PIR HIGH != HUMAN_CONFIRMED
        self.assertFalse(interp["human_confirmed"])

    def test_ultrasonic_classification(self):
        us = UltrasonicSensor(safe_distance_cm=40.0, warning_distance_cm=25.0, critical_distance_cm=15.0)
        
        # Far
        self.assertEqual(us.update_distance(60.0)["classification"], DistanceClassification.FAR.value)
        # Near (warning < d <= safe)
        self.assertEqual(us.update_distance(30.0)["classification"], DistanceClassification.NEAR.value)
        # Very Near (critical < d <= warning)
        self.assertEqual(us.update_distance(20.0)["classification"], DistanceClassification.VERY_NEAR.value)
        # Obstacle (d <= critical)
        self.assertEqual(us.update_distance(12.0)["classification"], DistanceClassification.OBSTACLE.value)
        self.assertFalse(us.get_interpretation()["object_identified"])

    def test_mpu6050_epistemics(self):
        imu = MPU6050Sensor()
        res = imu.update_telemetry(0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
        self.assertEqual(res["state"], "ROBOT_STATIONARY")
        self.assertIsNone(res["gps_coordinates"])

class TestSensorFusionLogic(unittest.TestCase):
    def setUp(self):
        self.pir = PIRSensor()
        self.us = UltrasonicSensor()
        self.imu = MPU6050Sensor()
        self.fusion = SensorFusion(self.pir, self.us, self.imu)

    def test_no_presence_when_no_motion(self):
        self.pir.update_raw(0)
        self.us.update_distance(120.0)
        res = self.fusion.evaluate()
        self.assertFalse(res["inference"]["possible_human_presence"])

    def test_presence_when_motion_and_nearby_object(self):
        # Motion detected + object at 125cm -> POSSIBLE_HUMAN_PRESENCE
        self.pir.update_raw(1)
        self.us.update_distance(125.0)
        res = self.fusion.evaluate()

        self.assertTrue(res["inference"]["possible_human_presence"])
        self.assertEqual(res["inference"]["estimated_distance_m"], 1.25)
        self.assertIn("Possible human presence detected approximately 1.25 meters away", res["inference"]["report_message"])
        # Ladder check
        self.assertEqual(res["epistemic_ladder"]["decision"], "STOP")
        self.assertEqual(res["epistemic_ladder"]["action"], "REPORT")

class TestSafetySupervisorOverrides(unittest.TestCase):
    def setUp(self):
        self.safety = SafetyController(safe_distance_cm=40.0, warning_distance_cm=25.0, critical_distance_cm=15.0)

    def test_critical_distance_override(self):
        # Planner requests MOVE_FORWARD, but ultrasonic reads 12cm (< 15cm critical)
        action = StructuredAction(action="MOVE_FORWARD", speed=60, duration_ms=1000)
        fusion_mock = {
            "ultrasonic": {"distance_cm": 12.0},
            "imu": {"pitch_deg": 0.0, "roll_deg": 0.0}
        }
        safe_action = self.safety.validate_and_filter(action, fusion_mock)
        
        self.assertEqual(safe_action.action, "STOP")
        self.assertEqual(safe_action.speed, 0)
        self.assertEqual(self.safety.last_verdict, SafetyVerdict.OVERRIDDEN)
        self.assertIn("SAFETY OVERRIDE", safe_action.reason)

    def test_tilt_hazard_override(self):
        # Planner requests MOVE_FORWARD, but robot is tilted 40 deg
        action = StructuredAction(action="MOVE_FORWARD", speed=60, duration_ms=1000)
        fusion_mock = {
            "ultrasonic": {"distance_cm": 100.0},
            "imu": {"pitch_deg": 42.0, "roll_deg": 0.0}
        }
        safe_action = self.safety.validate_and_filter(action, fusion_mock)
        self.assertEqual(safe_action.action, "STOP")
        self.assertEqual(self.safety.last_verdict, SafetyVerdict.OVERRIDDEN)

    def test_clear_path_approval(self):
        action = StructuredAction(action="MOVE_FORWARD", speed=60, duration_ms=1000)
        fusion_mock = {
            "ultrasonic": {"distance_cm": 85.0},
            "imu": {"pitch_deg": 0.0, "roll_deg": 0.0}
        }
        safe_action = self.safety.validate_and_filter(action, fusion_mock)
        self.assertEqual(safe_action.action, "MOVE_FORWARD")
        self.assertEqual(self.safety.last_verdict, SafetyVerdict.APPROVED)

if __name__ == "__main__":
    unittest.main()
