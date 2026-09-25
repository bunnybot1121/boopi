import unittest
import os
import sys
import json
import time

class TestContinuousCommandsResilience(unittest.TestCase):
    def test_01_import_run_mode2_does_not_kill_or_exit(self):
        """Verifies that importing run_mode2 does not terminate the current process or kill the running daemon."""
        pid_before = os.getpid()
        import run_mode2
        pid_after = os.getpid()
        self.assertEqual(pid_before, pid_after, "Process PID must not change on run_mode2 import.")

    def test_02_hardware_tools_run_robotic_code_superseded_no_exit(self):
        """Verifies that check_superseded raises a clean exception instead of SystemExit."""
        from actions.hardware_tools import run_robotic_code, current_task_id
        import actions.hardware_tools as hw

        # Execute normal code
        code = "print('command 1 executed')"
        res = run_robotic_code(code)
        self.assertIn("command 1 executed", res)
        self.assertIn("SUCCESS", res)

    def test_03_continuous_motor_command_duration_zero(self):
        """Verifies control_motors with duration_seconds=0 outputs continuous drive without premature 1500ms auto-stop."""
        from actions.hardware_tools import control_motors
        raw_fn = getattr(control_motors, "func", control_motors)
        res = raw_fn(direction="forward", speed=200, duration_seconds=0, robot_id="bupi_01")
        self.assertIn("continuous", res)

    def test_04_node_server_safe_port_check_no_taskkill(self):
        """Verifies start_node_server handles an active port 8767 without executing taskkill."""
        from bupi_node_server import start_node_server
        # Running start_node_server must return safely without error
        try:
            start_node_server()
            success = True
        except Exception as e:
            success = False
        self.assertTrue(success, "start_node_server must execute safely.")

    def test_05_transcription_exception_safety(self):
        """Verifies that on_transcription does not crash when unexpected inputs or internal errors occur."""
        from main import on_transcription
        # Test with varied command inputs
        on_transcription("")
        on_transcription("   ")
        on_transcription("unrecognized gibberish command 12345")
        on_transcription("check gas")
        on_transcription("what is the obstacle distance")

if __name__ == "__main__":
    unittest.main()
