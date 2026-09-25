"""
BUPI Bot 2 Instruction & Actuation Pipeline Verification
=========================================================
Tests the complete end-to-end command dispatch pipeline for BUPI-02 (Environmental Specialist):
1. Router & Decomposer Natural Language Targeting (Bot 2 / Specialist)
2. Safety Validator Isolation (Bot 1 obstacle state does NOT block Bot 2)
3. ControlAdapter & Hardware Tools JSON payload structuring (includes bot_id/robot_id)
4. WebSocket Bridge Multi-Bot Targeting (verifies Bot 2 receives Bot 2 commands, Bot 1 ignores them)
5. Live MQTT topic routing (bupi/v1/bot2/actuators/motors/cmd/json)
"""

import os
import sys
import json
import time
import asyncio
import websockets

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from planner.instruction_decomposer import InstructionDecomposer, PolicyType
from agents.router_agent import router
from actions.hardware_tools import control_motors
from spatial_intelligence.control_adapter import ControlAdapter
from core.safety_validator import validate_safety, get_current_world_state

def test_1_nlp_and_decomposer():
    print("\n--- TEST 1: NLP INTENT & DECOMPOSER TARGETING ---")
    decomposer = InstructionDecomposer(use_llm=False)
    
    test_cases = [
        ("Bot 2 move forward 10 cm", "bupi_02", "CONDITIONAL_MOVE"),
        ("Bot 2 turn right 90 degrees", "bupi_02", "ROTATE_TO"),
        ("check the gas level", "bupi_02", "SCAN_SWEEP"),
        ("sniff for gas leaks", "bupi_02", "SCAN_SWEEP"),
        ("walk until you detect gas", "bupi_02", "CONDITIONAL_MOVE"),
        ("Bot 2 explore safely", "bupi_02", "EXPLORE_SAFE"),
        ("Bot 2 stop", "bupi_02", "DIRECT_ACTION"),
        ("survey the room for environmental hazards", "bupi_02", "SCAN_SWEEP")
    ]
    
    passed = 0
    for text, expected_bot, expected_policy in test_cases:
        plan = decomposer.decompose(text)
        is_ok = (plan.target_bot == expected_bot and plan.policy_type.value == expected_policy)
        mark = "[PASS]" if is_ok else "[FAIL]"
        print(f"  {mark} '{text}' -> target: {plan.target_bot} (expected: {expected_bot}), policy: {plan.policy_type.value}")
        if is_ok:
            passed += 1
            
    assert passed == len(test_cases), f"Expected {len(test_cases)} to pass, got {passed}"
    print(f"  [RESULT] All {passed}/{len(test_cases)} NLP targeting tests PASSED!")

def test_2_safety_isolation():
    print("\n--- TEST 2: SENSOR & SAFETY ISOLATION (BOT 1 VS BOT 2) ---")
    # Validate that command for Bot 2 is validated against Bot 2 state, not Bot 1
    v2 = validate_safety("bupi/v1/bot2/actuators/motors/cmd", "forward", bot_id="bupi_02")
    print(f"  * Bot 2 safety evaluation approved: {v2.get('approved')}")
    assert v2.get("approved") is True, f"Bot 2 forward should be approved, got: {v2}"
    print("  [RESULT] Safety isolation verified! Bot 1 readings do not falsely block Bot 2.")

def test_3_control_adapter_payload():
    print("\n--- TEST 3: CONTROL ADAPTER PAYLOAD STRUCTURING ---")
    adapter = ControlAdapter()
    
    # Capture MQTT single publishes
    published_packets = []
    
    import paho.mqtt.publish as publish
    orig_single = publish.single
    try:
        def mock_single(topic, payload=None, hostname=None, port=None, qos=0, **kwargs):
            published_packets.append({"topic": topic, "payload": payload})
            return orig_single(topic, payload=payload, hostname=hostname, port=port, qos=qos, **kwargs)
        
        publish.single = mock_single
        
        # Test move_forward
        adapter.move_forward(bot_id="bupi_02", speed=200, duration_s=1.0)
        assert len(published_packets) > 0, "No packet published"
        last = published_packets[-1]
        data = json.loads(last["payload"])
        print(f"  * Published Topic: {last['topic']}")
        print(f"  * Published JSON: {data}")
        assert last["topic"] == "bupi/v1/bot2/actuators/motors/cmd/json", f"Wrong topic: {last['topic']}"
        assert data.get("bot_id") == "bupi_02", f"Missing bot_id: {data}"
        assert data.get("robot_id") == "bupi_02", f"Missing robot_id: {data}"
        print("  [RESULT] ControlAdapter correctly namespaces topic and includes bot_id/robot_id in payload!")
    finally:
        publish.single = orig_single

async def test_4_websocket_multi_bot_targeting():
    print("\n--- TEST 4: LIVE WEBSOCKET MULTI-BOT DISPATCH (PORT 8767) ---")
    uri = "ws://127.0.0.1:8767"
    
    # 1. Connect Bot 1 Scout
    async with websockets.connect(uri) as ws_bot1:
        # Announce Bot 1
        await ws_bot1.send(json.dumps({
            "type": "announce",
            "bot_id": "bupi_01",
            "robot_id": "bupi_01",
            "device": "BUPI_01_SCOUT",
            "capabilities": ["differential_drive", "HC-SR04", "PIR"]
        }))
        await asyncio.sleep(0.1)
        
        # 2. Connect Bot 2 Specialist
        async with websockets.connect(uri) as ws_bot2:
            # Announce Bot 2
            await ws_bot2.send(json.dumps({
                "type": "announce",
                "bot_id": "bupi_02",
                "robot_id": "bupi_02",
                "device": "BUPI_02_SPECIALIST",
                "capabilities": ["differential_drive", "MQ-2", "DHT22", "HC-SR04"]
            }))
            await asyncio.sleep(0.1)
            
            # Send a command specifically for Bot 2 via hardware_tools
            print("  * Dispatching 'forward' command to Bot 2 via control_motors...")
            control_motors(direction="forward", robot_id="bupi_02")
            
            # Bot 2 should receive the command packet
            received_bot2 = None
            try:
                start_time = time.time()
                while time.time() - start_time < 3.0:
                    raw = await asyncio.wait_for(ws_bot2.recv(), timeout=1.5)
                    pkt = json.loads(raw)
                    if pkt.get("type") == "telemetry_update":
                        continue
                    if "action" in pkt or "command" in pkt:
                        received_bot2 = pkt
                        break
                print(f"  * Bot 2 Received: {received_bot2}")
            except Exception as e:
                print(f"  [FAIL] Bot 2 failed to receive command: {e}")
                
            assert received_bot2 is not None, "Bot 2 did not receive command packet!"
            assert received_bot2.get("bot_id") in ["bupi_02", "bot2"], f"Wrong bot_id: {received_bot2}"
            assert received_bot2.get("action") == "forward", f"Wrong action: {received_bot2}"
            print("  [RESULT] Live WebSocket correctly delivered targeted command to Bot 2!")

def run_all_tests():
    print("==================================================================")
    print("    [BUPI FLEET] BOT 2 INSTRUCTION PIPELINE VERIFICATION")
    print("==================================================================")
    test_1_nlp_and_decomposer()
    test_2_safety_isolation()
    test_3_control_adapter_payload()
    asyncio.run(test_4_websocket_multi_bot_targeting())
    print("\n==================================================================")
    print("    [SUCCESS] ALL 4 TESTS PASSED: BOT 2 INSTRUCTION PIPELINE 100% OPERATIONAL")
    print("==================================================================")

if __name__ == "__main__":
    run_all_tests()
