"""
Automated Tests for BUPI Dynamic Instruction Engine & Data Pipeline
===================================================================
Verifies:
1. Dynamic Instruction Decomposition across diverse natural language inputs
2. Conditional Movement ("walk until an obstacle comes in front of you")
3. Spatial Presence Room Scanning ("are there any humans in the room?")
4. Empty room negative test (no false detections)
5. Sentry Motion Detection ("stay still and alert if anything moves")
6. Hardware Safety Supervisor critical cutoff (< 15cm)
"""

import os
import sys
import unittest
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from planner.instruction_decomposer import InstructionDecomposer, PolicyType, DynamicMissionPlan
from planner.room_scanner import RoomScanner
from agents.autonomous_goal_agent import AutonomousGoalAgent
from communication.bridge import BupiBridge, HumanEntity, ObstacleEntity

class TestDynamicInstructions(unittest.TestCase):
    def setUp(self):
        self.decomposer = InstructionDecomposer(use_llm=False)
        self.agent = AutonomousGoalAgent(use_simulation=True)

    def test_01_decomposition_walk_until_obstacle(self):
        cmd = "walk until an obstacle comes in front of you"
        plan = self.decomposer.decompose(cmd)

        self.assertEqual(plan.policy_type, PolicyType.CONDITIONAL_MOVE)
        self.assertEqual(plan.primary_action, "MOVE_FORWARD")
        self.assertEqual(plan.stop_condition.sensor, "ultrasonic")
        self.assertEqual(plan.stop_condition.operator, "<=")
        self.assertEqual(plan.stop_condition.threshold, 25.0)

    def test_02_decomposition_custom_distance_threshold(self):
        cmd = "drive forward until an obstacle is 45cm away"
        plan = self.decomposer.decompose(cmd)

        self.assertEqual(plan.policy_type, PolicyType.CONDITIONAL_MOVE)
        self.assertEqual(plan.stop_condition.threshold, 45.0)

    def test_03_decomposition_presence_search(self):
        cmd = "BUPI, are there any humans in the room?"
        plan = self.decomposer.decompose(cmd)

        self.assertEqual(plan.policy_type, PolicyType.SCAN_SWEEP)
        self.assertIn("ultrasonic", plan.sample_sensors)
        self.assertIn("pir", plan.sample_sensors)

    def test_04_decomposition_sentry_motion(self):
        cmd = "stay still and alert me if anything moves"
        plan = self.decomposer.decompose(cmd)

        self.assertEqual(plan.policy_type, PolicyType.MONITOR_HOLD)
        self.assertEqual(plan.stop_condition.sensor, "pir")
        self.assertEqual(plan.primary_action, "STOP")

    def test_05_decomposition_turn_to_angle(self):
        cmd = "turn 90 degrees to the right"
        plan = self.decomposer.decompose(cmd)

        self.assertEqual(plan.policy_type, PolicyType.ROTATE_TO)
        self.assertEqual(plan.primary_action, "TURN_RIGHT")
        self.assertEqual(plan.stop_condition.threshold, 90.0)

    def test_06_execution_walk_until_obstacle(self):
        """
        Spawns an obstacle 100cm ahead and commands BUPI to walk forward
        until an obstacle is reached. Verifies BUPI moves forward, stops at
        the obstacle threshold, and returns exact distance data.
        """
        # Place robot at (100, 200) facing East (0 deg)
        self.agent.bridge.arena.robot_x = 100.0
        self.agent.bridge.arena.robot_y = 200.0
        self.agent.bridge.arena.robot_theta_deg = 0.0

        # Place box obstacle at (200, 200) -> 100cm in front
        self.agent.bridge.arena.obstacles = [
            ObstacleEntity(id="test_wall", x=200.0, y=200.0, width=30.0, height=80.0)
        ]
        self.agent.bridge.arena._compute_sensors()

        # Initial distance should be ~85-100cm
        init_dist = self.agent.bridge.arena.raw_distance_cm
        self.assertGreater(init_dist, 50.0)

        # Run conditional walk mission
        res = self.agent.run_mission_sync("walk until an obstacle comes in front of you")

        self.assertTrue(res["obstacle_reached"])
        self.assertLessEqual(res["final_distance_cm"], 30.0)
        self.assertIn("Obstacle detected", res["summary"])
        self.assertIn("final_distance_m", res)

    def test_07_execution_scan_for_presence(self):
        """
        Places a warm human entity at (250, 200) in the arena.
        Commands BUPI to scan the room. Verifies BUPI localizes the human,
        reports distance and bearing, with HIGH or MEDIUM confidence.
        """
        self.agent.bridge.arena.robot_x = 100.0
        self.agent.bridge.arena.robot_y = 200.0
        self.agent.bridge.arena.robot_theta_deg = 0.0

        # Human placed 150cm to the East
        self.agent.bridge.arena.humans = [
            HumanEntity(id="person_alice", x=250.0, y=200.0, is_warm=True, is_moving=True)
        ]
        self.agent.bridge.arena.obstacles = []
        self.agent.bridge.arena._compute_sensors()

        res = self.agent.run_mission_sync("BUPI, are there any humans in the room?")

        self.assertTrue(res["target_detected"])
        self.assertIsNotNone(res["distance_m"])
        self.assertGreater(res["distance_m"], 0.5)
        self.assertLess(res["distance_m"], 2.5)
        self.assertIn("direction_description", res)
        self.assertIn("Possible human presence detected", res["verbal_report"])

    def test_08_empty_room_no_false_positives(self):
        """
        Removes all humans from the arena. Commands room scan.
        Verifies BUPI completes the 360 sweep and reports area clear without false positive.
        """
        self.agent.bridge.arena.humans = []
        self.agent.bridge.arena.obstacles = [
            ObstacleEntity(id="cold_box", x=250.0, y=200.0, width=40.0, height=40.0)
        ]
        self.agent.bridge.arena._compute_sensors()

        res = self.agent.run_mission_sync("is anyone in this room?")

        self.assertFalse(res["target_detected"])
        self.assertIn("No human presence", res["verbal_report"])

    def test_09_safety_critical_override(self):
        """
        Verifies that if an obstacle suddenly appears within critical distance (<15cm),
        the safety supervisor immediately brakes motors regardless of goal.
        """
        self.agent.bridge.arena.raw_distance_cm = 12.0
        res = self.agent.run_mission_sync("walk until an obstacle comes in front of you")

        self.assertTrue(res["obstacle_reached"])
        self.assertLessEqual(res["final_distance_cm"], 15.0)

if __name__ == "__main__":
    unittest.main()
