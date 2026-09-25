"""
BUPI Fleet Multi-Robot Coordination Verification Test
=====================================================
Validates end-to-end multi-robot telemetry isolation, dynamic routing,
hazard shutdown, and independent dual-bot actuation for Bot 1 & Bot 2.
"""

import sys
import os
import time
import json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from bupi_node_server import get_latest_telemetry, _normalize_bot_id
from communication.bridge import BupiBridge
from agents.router_agent import router
from core.swarm_coordinator import swarm_coordinator

def test_telemetry_isolation():
    print("\n--- TEST 1: TELEMETRY ISOLATION & SENSOR PROFILES ---")
    t1 = get_latest_telemetry("bupi_01")
    t2 = get_latest_telemetry("bupi_02")
    t2_alias = get_latest_telemetry("specialist")

    print(f"  * Bot 1 Telemetry Bot ID: {t1.get('bot_id')}")
    print(f"  * Bot 2 Telemetry Bot ID: {t2.get('bot_id')}")
    print(f"  * Specialist Alias Bot ID: {t2_alias.get('bot_id')}")

    assert t1.get("bot_id") == "bupi_01", f"Expected bupi_01, got {t1.get('bot_id')}"
    assert t2.get("bot_id") == "bupi_02", f"Expected bupi_02, got {t2.get('bot_id')}"
    assert t2_alias.get("bot_id") == "bupi_02", f"Expected bupi_02, got {t2_alias.get('bot_id')}"
    print("  [PASS] Telemetry isolation verified! Aliases resolve to distinct robot profiles.")

def test_bridge_sensor_data():
    print("\n--- TEST 2: BRIDGE DATA INGESTION PER BOT ---")
    bridge = BupiBridge(use_simulation=False)
    b1_data = bridge.get_latest_sensor_data("bupi_01")
    b2_data = bridge.get_latest_sensor_data("bupi_02")

    print(f"  * Bridge Bot 1 Data: {b1_data.get('bot_id')}, dist={b1_data.get('distance_cm')}")
    print(f"  * Bridge Bot 2 Data: {b2_data.get('bot_id')}, gas={b2_data.get('gas_ppm')}")

    assert b1_data.get("bot_id") == "bupi_01"
    assert b2_data.get("bot_id") == "bupi_02"
    print("  [PASS] Bridge correctly partitions sensory feeds for Bot 1 and Bot 2.")

def test_router_intent_targeting():
    print("\n--- TEST 3: ROUTER CLASSIFICATION TARGETING ---")
    test_cases = [
        ("Bot 1 stop", "hardware_intent", "bupi_01"),
        ("Bot 2 stop", "hardware_intent", "bupi_02"),
        ("emergency stop", "hardware_intent", "all"),
        ("Bot 1 move forward", "hardware_intent", "bupi_01"),
        ("Bot 2 move forward", "hardware_intent", "bupi_02"),
        ("check the gas level", "sensor_query", "bupi_02"),
        ("check motion sensor", "sensor_query", "bupi_01"),
    ]

    for utterance, expected_type, expected_bot in test_cases:
        res = router.quick_regex_classify(utterance)
        actual_type = res.get("type")
        actual_bot = res.get("payload", {}).get("robot_id")
        assert actual_type == expected_type, f"'{utterance}' type expected {expected_type}, got {actual_type}"
        assert actual_bot == expected_bot, f"'{utterance}' robot_id expected {expected_bot}, got {actual_bot}"
        print(f"  [PASS] '{utterance}' -> type: {actual_type}, robot_id: {actual_bot}")

def test_swarm_hazard_evacuation():
    print("\n--- TEST 4: SWARM HAZARD SHUTDOWN DISPATCH ---")
    published = []
    import paho.mqtt.publish as publish
    orig_single = publish.single
    try:
        def mock_publish(topic, payload=None, hostname=None, **kwargs):
            published.append({"topic": topic, "payload": payload})
            return orig_single(topic, payload=payload, hostname=hostname, **kwargs)
        publish.single = mock_publish

        swarm_coordinator._trigger_hazard_evacuation("bupi_02", 450.0)

        topics_hit = [p["topic"] for p in published]
        print(f"  * Swarm Alert Topics Dispatched: {topics_hit}")

        assert "bupi/actuators/motors/cmd" in topics_hit, "Bot 1 text stop topic missing"
        assert "bupi/actuators/motors/cmd/json" in topics_hit, "Bot 1 JSON stop topic missing"
        assert "bupi/v1/bot2/actuators/motors/cmd" in topics_hit, "Bot 2 text stop topic missing"
        assert "bupi/v1/bot2/actuators/motors/cmd/json" in topics_hit, "Bot 2 JSON stop topic missing"
        print("  [PASS] Swarm hazard evacuation halts BOTH Bot 1 and Bot 2 simultaneously!")
    finally:
        publish.single = orig_single

if __name__ == "__main__":
    print("==================================================================")
    print("    [BUPI FLEET] BOT 1 & BOT 2 COORDINATION VERIFICATION")
    print("==================================================================")
    test_telemetry_isolation()
    test_bridge_sensor_data()
    test_router_intent_targeting()
    test_swarm_hazard_evacuation()
    print("\n==================================================================")
    print("    [SUCCESS] ALL FLEET TESTS PASSED WITH 100% SUCCESS")
    print("==================================================================")
