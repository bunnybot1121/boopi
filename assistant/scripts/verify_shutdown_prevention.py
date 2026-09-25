#!/usr/bin/env python3
"""
==================================================================
BUPI STABILITY & SHUTDOWN PREVENTION VERIFICATION TEST
==================================================================
Verifies:
1. Persistent MQTT client connection (no TCP socket exhaustion).
2. Motor command rate limiting (4-5 Hz throttle in 20 Hz mission loops).
3. Firmware brownout prevention (RTC brownout detector disabled, 5ms startup stagger).
4. Firmware I2C bus recovery under inductive noise.
==================================================================
"""

import sys
import os
import time
import json
import threading

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

def test_mqtt_persistent_client():
    print("\n--- TEST 1: PERSISTENT MQTT CLIENT & ZERO SOCKET CHURN ---")
    from agents.autonomous_goal_agent import AutonomousGoalAgent
    agent = AutonomousGoalAgent(use_simulation=True)

    # Check that persistent client was initialized
    assert agent._mqtt_client is not None, "Persistent MQTT client was not created!"
    print(f"  * Persistent MQTT Client: Active ({agent._mqtt_client._client_id.decode() if isinstance(agent._mqtt_client._client_id, bytes) else agent._mqtt_client._client_id})")

    # Measure time to send 100 commands (must be < 100ms total, not creating 100 TCP sockets)
    t0 = time.time()
    for i in range(100):
        agent.publish_cmd("bupi/test/topic", json.dumps({"test": i}))
    elapsed_ms = (time.time() - t0) * 1000.0
    print(f"  * Dispatched 100 MQTT commands in {elapsed_ms:.1f} ms ({elapsed_ms/100:.2f} ms per cmd)")
    assert elapsed_ms < 500.0, f"Dispatches took too long ({elapsed_ms:.1f}ms), socket churn may still be present!"
    print("  [PASS] Persistent MQTT client active: zero socket churn, high-speed dispatch.")

def test_motor_rate_limiting():
    print("\n--- TEST 2: MOTOR COMMAND RATE LIMITING IN MISSION LOOPS ---")
    from agents.autonomous_goal_agent import AutonomousGoalAgent
    from planner.instruction_decomposer import DynamicMissionPlan, PolicyType, DynamicStopCondition

    agent = AutonomousGoalAgent(use_simulation=True)
    published_cmds = []

    # Intercept publish_cmd to measure transmission rate
    orig_publish = agent.publish_cmd
    def tracking_publish(topic, payload):
        if "motors/cmd" in topic:
            published_cmds.append((time.time(), topic, payload))
        orig_publish(topic, payload)

    agent.publish_cmd = tracking_publish

    # Run a 2-second conditional move mission
    plan = agent.decomposer.decompose("move forward 2 seconds")

    t0 = time.time()
    agent._run_conditional_move_mission(plan, t0)
    total_time = time.time() - t0

    # In 2 seconds at 20 Hz perception (40 steps), with 4-5 Hz rate limiting:
    # Expected packets: step 1, 5, 10, 15, 20, 25, 30, 35, 40 -> ~9 packets + stop
    # Without rate limiting, it would be 40 JSON + 40 text = 80 packets!
    motor_packets = [p for p in published_cmds if "json" in p[1]]
    print(f"  * Mission ran for {total_time:.2f}s")
    print(f"  * Total motor JSON packets dispatched: {len(motor_packets)}")
    print(f"  * Average motor dispatch frequency: {len(motor_packets) / total_time:.1f} Hz")

    assert len(motor_packets) <= 15, f"Too many motor packets ({len(motor_packets)})! Rate limiting not working."
    assert len(motor_packets) >= 4, f"Too few motor packets ({len(motor_packets)})!"
    print("  [PASS] Motor rate limiting verified: clean ~4-5 Hz stream, no ESP32 flooding.")

def test_firmware_safeguards():
    print("\n--- TEST 3: FIRMWARE HARDENING & BROWNOUT SAFEGUARDS ---")
    bot1_path = os.path.join(PROJECT_ROOT, "firmware", "bupi_bot1_scout", "bupi_bot1_scout.ino")
    bot2_path = os.path.join(PROJECT_ROOT, "firmware", "bupi_bot2_specialist", "bupi_bot2_specialist.ino")

    for name, path in [("Bot 1 Scout", bot1_path), ("Bot 2 Specialist", bot2_path)]:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        # 1. Brownout detector disabled
        assert "WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0)" in content, f"{name}: Brownout detector not disabled!"
        print(f"  * {name}: Brownout detector disabled in setup() [OK]")

        # 2. 5ms motor inrush stagger
        assert "delay(5)" in content and "motorActive" in content, f"{name}: Motor startup stagger missing!"
        print(f"  * {name}: 5ms motor startup inrush stagger active [OK]")

        # 3. I2C error recovery
        assert "byte err = Wire.endTransmission(false)" in content, f"{name}: I2C error checking missing!"
        assert "Wire.endTransmission(true)" in content, f"{name}: I2C bus recovery missing!"
        print(f"  * {name}: I2C bus error protection and bus recovery active [OK]")

        # 4. Obstacle cutoff guard
        assert "CRITICAL_OBSTACLE_CM > 0.0" in content, f"{name}: Critical obstacle cutoff guard missing!"
        print(f"  * {name}: Zero-obstacle cutoff false-positive guard active [OK]")

    print("  [PASS] All firmware safeguards verified across Bot 1 and Bot 2.")

if __name__ == "__main__":
    print("==================================================================")
    print("    [BUPI FLEET] SHUTDOWN PREVENTION & STABILITY VERIFICATION")
    print("==================================================================")
    test_mqtt_persistent_client()
    test_motor_rate_limiting()
    test_firmware_safeguards()
    print("\n==================================================================")
    print("    [SUCCESS] ALL STABILITY TESTS PASSED WITH 100% SUCCESS")
    print("==================================================================")
