"""
Verification script for Bot 1 (Scout) Person Detection and Room Scanner
Validates dual-sensor fusion (PIR thermal flux + HC-SR04 acoustic triangulation)
across multiple scenarios including ultrasonic absorption / open room timeouts.
"""

import sys
import os
import time

# Add assistant root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from planner.room_scanner import RoomScanner
from actions.hardware_tools import read_sensor_status


def test_person_detection_scenarios():
    print("=================================================================")
    print("RUNNING BUPI BOT 1 PERSON DETECTION VERIFICATION SUITE")
    print("=================================================================\n")

    scanner = RoomScanner()

    # -------------------------------------------------------------
    # Scenario 1: Person in room, clothes absorb ultrasound (HC-SR04 reads 400.0 cm)
    # -------------------------------------------------------------
    print("[TEST 1] Scenario: Person at 45° bearing, ultrasound echo times out (400.0 cm)")
    scanner.reset(initial_heading_deg=0.0)

    # Simulate 360-degree sweep (samples every 10 degrees)
    for h in range(0, 360, 10):
        # Person standing around heading 40° to 60°
        if 40 <= h <= 60:
            pir = 1
            dist = 400.0  # Ultrasonic timeout / clothes absorption
        else:
            pir = 0
            dist = 400.0
        scanner.record_sample(float(h), dist, pir)

    report1 = scanner.analyze_scan(duration_seconds=5.0, is_count_query=False)
    print(f"  Target Detected  : {report1.target_detected}")
    print(f"  People Count     : {report1.people_count}")
    print(f"  Target Bearing   : {report1.relative_bearing_deg}°")
    print(f"  Target Heading   : {report1.absolute_heading_deg}°")
    print(f"  Target Distance  : {report1.distance_m} m")
    print(f"  Confidence       : {report1.confidence}")
    print(f"  Verbal Report    : \"{report1.verbal_report}\"")

    assert report1.target_detected is True, "FAIL: Expected target_detected == True"
    assert report1.people_count == 1, f"FAIL: Expected people_count == 1, got {report1.people_count}"
    assert report1.targets and len(report1.targets) == 1, "FAIL: Expected 1 target in targets list"
    assert 40 <= report1.absolute_heading_deg <= 60, "FAIL: Heading mismatch"
    print("  >>> PASS: Test 1 Passed! Person detected and localized successfully despite acoustic timeout!\n")

    # -------------------------------------------------------------
    # Scenario 2: Person detected with sharp acoustic reflection at 150 cm
    # -------------------------------------------------------------
    print("[TEST 2] Scenario: Person at 120° bearing with crisp acoustic reflection (150 cm)")
    scanner.reset(initial_heading_deg=0.0)

    for h in range(0, 360, 10):
        if 110 <= h <= 130:
            pir = 1
            dist = 150.0
        else:
            pir = 0
            dist = 300.0
        scanner.record_sample(float(h), dist, pir)

    report2 = scanner.analyze_scan(duration_seconds=5.0, is_count_query=True)
    print(f"  Target Detected  : {report2.target_detected}")
    print(f"  People Count     : {report2.people_count}")
    print(f"  Target Bearing   : {report2.relative_bearing_deg}°")
    print(f"  Target Distance  : {report2.distance_m} m")
    print(f"  Confidence       : {report2.confidence}")
    print(f"  Verbal Report    : \"{report2.verbal_report}\"")

    assert report2.target_detected is True, "FAIL: Expected target_detected == True"
    assert report2.people_count == 1, "FAIL: Expected people_count == 1"
    assert report2.distance_m == 1.5, f"FAIL: Expected distance 1.5m, got {report2.distance_m}"
    assert report2.confidence == "HIGH", "FAIL: Expected HIGH confidence"
    print("  >>> PASS: Test 2 Passed! Dual acoustic + IR triangulation confirmed!\n")

    # -------------------------------------------------------------
    # Scenario 3: Empty room (no movement, clear walls)
    # -------------------------------------------------------------
    print("[TEST 3] Scenario: Empty room across 360 degrees (PIR=0 everywhere)")
    scanner.reset(initial_heading_deg=0.0)

    for h in range(0, 360, 10):
        scanner.record_sample(float(h), 250.0, 0)

    report3 = scanner.analyze_scan(duration_seconds=5.0, is_count_query=True)
    print(f"  Target Detected  : {report3.target_detected}")
    print(f"  People Count     : {report3.people_count}")
    print(f"  Verbal Report    : \"{report3.verbal_report}\"")

    assert report3.target_detected is False, "FAIL: Expected target_detected == False"
    assert report3.people_count == 0, "FAIL: Expected people_count == 0"
    print("  >>> PASS: Test 3 Passed! Area correctly identified as clear!\n")

    # -------------------------------------------------------------
    # Scenario 4: Hardware Tools read_sensor_status for PIR with recent latching
    # -------------------------------------------------------------
    print("[TEST 4] Hardware Tools read_sensor_status('pir')")
    pir_status_json = read_sensor_status(sensor_id="pir", robot_id="bupi_01")
    print(f"  PIR Sensor Query Result: {pir_status_json}")
    import json
    parsed = json.loads(pir_status_json)
    assert parsed.get("sensor") == "pir", "FAIL: Sensor name must be pir"
    assert "status" in parsed, "FAIL: Missing status field"
    print("  >>> PASS: Test 4 Passed! read_sensor_status executes cleanly!\n")

    print("=================================================================")
    print("ALL 4 PERSON DETECTION VERIFICATION TESTS PASSED SUCCESSFULLY!")
    print("=================================================================")


if __name__ == "__main__":
    test_person_detection_scenarios()
