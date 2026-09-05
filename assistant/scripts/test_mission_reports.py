"""
scripts/test_mission_reports.py
Automated test suite to verify:
1. Project-Agnostic classification for diverse missions
2. Telemetry and event recording in SQLite
3. Dynamic sensor discovery and report compilation (Markdown & JSON)
4. get_mission_history and get_status APIs
"""

import os
import sys
import time
import json
import sqlite3

# Ensure assistant root is on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from agents.autonomous_goal_agent import AutonomousGoalAgent

def test_mission_system():
    print("==========================================================")
    print("🚀 BUPI MISSION DEBRIEF & REPORTS AUTOMATED TEST SUITE")
    print("==========================================================")

    agent = AutonomousGoalAgent()

    # ---------------------------------------------------------
    # 1. Test Project Classification
    # ---------------------------------------------------------
    test_cases = [
        ("Find the human in the room and confirm presence", "Search & Rescue"),
        ("Inspect room for gas leaks and air hazards", "Hazard & Gas Inspection"),
        ("Patrol room perimeter and map obstacle locations", "Perimeter Security Patrol"),
        ("Survey environmental conditions and temperature", "Environmental Climate Survey"),
        ("Map out unknown room layout and navigate", "Autonomous Room Exploration")
    ]

    print("\n[1] Testing Project-Agnostic Classification:")
    for goal, expected_type in test_cases:
        actual_type = agent._classify_project_type(goal)
        assert actual_type == expected_type, f"Mismatch for '{goal}': expected {expected_type}, got {actual_type}"
        print(f"  ✅ '{goal[:35]}...' -> {actual_type}")

    # ---------------------------------------------------------
    # 2. Test Dynamic Multi-Sensor Ingestion into SQLite
    # ---------------------------------------------------------
    print("\n[2] Ingesting Dynamic Sensor Data into bupi_telemetry.db:")
    db_path = os.path.join(PROJECT_ROOT, "bupi_telemetry.db")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Insert simulated readings for different sensors
    now = time.time()
    sample_sensors = [
        ("ultrasonic_distance", 18.5, now),
        ("mq2_gas", 285.0, now),
        ("dht_temp", 24.2, now),
        ("dht_humidity", 58.0, now),
        ("imu_pitch", -1.2, now)
    ]
    for sid, val, ts in sample_sensors:
        c.execute("INSERT INTO telemetry (sensor_id, value, timestamp) VALUES (?, ?, ?)", (sid, val, ts))
    conn.commit()
    conn.close()
    print(f"  ✅ Ingested {len(sample_sensors)} diverse sensors (ultrasonic, mq2, dht_temp, dht_humidity, imu_pitch)")

    # ---------------------------------------------------------
    # 3. Simulate Mission Execution & Event Logging
    # ---------------------------------------------------------
    print("\n[3] Simulating Autonomous Mission Execution & Telemetry Snapshots:")
    goal = "Find the human in the room and confirm presence"
    agent.current_mission_name = "FIND_HUMAN"
    agent.active_mission_data = {
        "goal": goal,
        "project_type": "Search & Rescue",
        "started_at": time.time() - 14.5,
        "events": [],
        "step_count": 5,
        "obstacles_avoided": 2,
        "target_found": True,
        "sensor_snapshots": []
    }

    agent.record_event("MISSION_STARTED", f"Goal initialized: {goal}")
    agent.record_event("OBSTACLE_AVOID", "Proximity obstacle at 18.5cm; steered +45° right")
    agent.record_event("TARGET_DETECTED", "Human presence verified via ultrasonic & sector sweep")
    agent.record_sensor_snapshot()
    print(f"  ✅ Recorded {len(agent.active_mission_data['events'])} events in timeline")

    # ---------------------------------------------------------
    # 4. Compile and Save Structured Debrief Card
    # ---------------------------------------------------------
    print("\n[4] Compiling and Persisting Mission Debrief Card:")
    report = agent._compile_and_save_report(
        final_status="COMPLETED: Target verified",
        summary_notes="Successfully navigated sector A, avoided 2 obstacles, verified human presence, and sounded confirmation chime."
    )

    assert report is not None
    assert report["project_type"] == "Search & Rescue"
    assert report["target_found"] is True
    assert "ultrasonic_distance" in report["active_sensors"]
    assert "mq2_gas" in report["active_sensors"]
    assert "dht_temp" in report["active_sensors"]
    print("  ✅ Report Data compiled with dynamic sensors:")
    for s_name, s_data in report["active_sensors"].items():
        print(f"     - Sensor: {s_name} = {s_data['value']}")

    print("\n  📄 Generated Markdown Debrief Card Preview:")
    for line in report["report_markdown"].split("\n")[:12]:
        print(f"     {line}")

    # ---------------------------------------------------------
    # 5. Verify SQLite Persistence & Query APIs
    # ---------------------------------------------------------
    print("\n[5] Verifying SQLite Retrieval (get_latest_mission_report & get_mission_history):")
    latest = agent.get_latest_mission_report()
    assert latest is not None
    assert latest["mission_name"] == "FIND_HUMAN"
    print(f"  ✅ get_latest_mission_report() returned mission: '{latest['mission_name']}'")

    history = agent.get_mission_history(limit=5)
    assert len(history) > 0
    print(f"  ✅ get_mission_history() returned {len(history)} missions:")
    for h in history:
        print(f"     • [{h['id']}] {h['project_type']}: {h['goal'][:30]}... ({h['duration_seconds']}s, status: {h['status']})")

    # ---------------------------------------------------------
    # 6. Verify Live Status API
    # ---------------------------------------------------------
    print("\n[6] Verifying get_status() API:")
    status = agent.get_status()
    assert "state" in status
    assert "sensors" in status
    assert "obstacles_avoided" in status
    print(f"  ✅ get_status() returned state: '{status['state']}', sensors: {list(status['sensors'].keys())}")

    print("\n==========================================================")
    print("🎉 ALL TESTS PASSED! UNIVERSAL MISSION ENGINE IS 100% OPERATIONAL")
    print("==========================================================")

if __name__ == "__main__":
    test_mission_system()
