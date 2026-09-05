import asyncio
import re
import time
from core.event_bus_async import bus
from services.llm_gateway import LLMGateway

class RouterAgent:
    def __init__(self):
        self.llm = LLMGateway()

    def start(self):
        print("[Router Agent] Started. Listening for user utterances...")
        bus.subscribe("user_utterance", self.on_user_utterance)

    def quick_regex_classify(self, text: str) -> dict:
        """
        Microsecond (<5ms) deterministic regex classifier for instant direct commands.
        Bypasses LLM latency when the user intent is unambiguous.
        """
        clean = text.lower().strip()

        # Autonomous High-Level Robotic Missions (<1ms fast-pass)
        if re.search(r"\b(find the human|find human|find person|locate human|locate person|search for human|search the room|search room|patrol|patrol the room|patrol and inspect|patrol area|explore|explore the room|explore room|autonomous mission)\b", clean):
            return {
                "type": "autonomous_mission",
                "payload": {"mission": text}
            }
        if re.search(r"\b(abort mission|cancel mission|stop mission)\b", clean):
            return {
                "type": "abort_mission",
                "payload": {}
            }
        if re.search(r"\b(what did you find|show mission report|mission report|mission findings|last mission|what happened in last mission|tell me what you found|show debrief|mission debrief)\b", clean):
            return {
                "type": "mission_report_query",
                "payload": {}
            }

        # Hardware E-Stop & Direct Motor Commands
        if re.search(r"\b(stop|halt|freeze|emergency stop|e-stop|stop motors|brake)\b", clean):
            return {
                "type": "hardware_intent",
                "payload": {"device": "motors", "action": "MOVE", "direction": "stop"}
            }
        if re.search(r"\b(move forward|drive forward|go forward|forward)\b", clean):
            return {
                "type": "hardware_intent",
                "payload": {"device": "motors", "action": "MOVE", "direction": "forward"}
            }
        if re.search(r"\b(move back|drive reverse|reverse|go backward)\b", clean):
            return {
                "type": "hardware_intent",
                "payload": {"device": "motors", "action": "MOVE", "direction": "reverse"}
            }
        if re.search(r"\b(turn left|spin left)\b", clean):
            return {
                "type": "hardware_intent",
                "payload": {"device": "motors", "action": "MOVE", "direction": "left"}
            }
        if re.search(r"\b(turn right|spin right)\b", clean):
            return {
                "type": "hardware_intent",
                "payload": {"device": "motors", "action": "MOVE", "direction": "right"}
            }

        # Hardware Relays & LCD
        if re.search(r"\b(turn on relay|relay on|activate relay)\b", clean):
            return {
                "type": "hardware_intent",
                "payload": {"device": "relay", "action": "ON"}
            }
        if re.search(r"\b(turn off relay|relay off|deactivate relay)\b", clean):
            return {
                "type": "hardware_intent",
                "payload": {"device": "relay", "action": "OFF"}
            }

        # Quick Sensor Telemetry Queries (<1ms bypass)
        if re.search(r"\b(gas level|gas reading|smoke level|lpg reading|check gas|gas status)\b", clean):
            return {
                "type": "sensor_query",
                "payload": {"sensor_id": "mq2"}
            }
        if re.search(r"\b(room temperature|indoor temp|current temperature|temperature reading)\b", clean):
            return {
                "type": "sensor_query",
                "payload": {"sensor_id": "temp"}
            }
        if re.search(r"\b(front distance|obstacle distance|ultrasonic reading)\b", clean):
            return {
                "type": "sensor_query",
                "payload": {"sensor_id": "distance"}
            }
        if re.search(r"\b(world state|environment state|robot status|telemetry status)\b", clean):
            return {
                "type": "world_state_query",
                "payload": {}
            }

        # ESP32 Connection & Node Presence (<1ms bypass)
        if re.search(r"\b(esp32 connected|esp connected|node connected|nodes connected|active nodes|check esp32|check esp|is esp32 online|is esp online|node status)\b", clean):
            return {
                "type": "nodes_query",
                "payload": {}
            }

        # Mission Debrief & Reports Query (<1ms bypass)
        if re.search(r"\b(what did you find|mission report|mission debrief|last mission|mission findings|debrief report|show report|show findings)\b", clean):
            return {
                "type": "mission_report_query",
                "payload": {}
            }

        # RAG / Technical Datasheet Search Keywords
        if re.search(r"\b(pinout|datasheet|schematic|wiring|specifications|spec|library index|platformio|arduino library)\b", clean):
            return {
                "type": "rag_search",
                "payload": {"query": text}
            }

        # Desktop Automation Fast Pass
        if re.search(r"\b(send whatsapp|whatsapp message|open notepad|open gmail|linkedin notification|take screenshot)\b", clean):
            return {
                "type": "desktop_automation",
                "payload": {"target": "automation", "text": text}
            }

        return None

    async def on_user_utterance(self, payload: dict):
        text = payload.get("text", "")
        if not text:
            return

        start_time = time.time()
        print(f"\n[Router Agent] Received utterance: '{text}'")

        # 1. Try Fast Pass Regex Pre-Classifier (<5ms)
        fast_intent = self.quick_regex_classify(text)
        if fast_intent:
            elapsed_ms = (time.time() - start_time) * 1000
            print(f"[Router Agent Fast-Pass] ⚡ Classified in {elapsed_ms:.1f}ms -> {fast_intent['type']} Payload: {fast_intent['payload']}")
            await self._dispatch_intent(fast_intent)
            return

        # 2. Fall back to LLM Gateway Classification
        print("[Router Agent] Fast-pass bypass missed. Consulting LLM Gateway...")
        intent_json = await self.llm.classify_intent(text)
        elapsed_ms = (time.time() - start_time) * 1000
        print(f"[Router Agent LLM] Classified in {elapsed_ms:.1f}ms -> {intent_json.get('type')}")
        await self._dispatch_intent(intent_json)

    async def _dispatch_intent(self, intent_json: dict):
        intent_type = intent_json.get("type")
        intent_payload = intent_json.get("payload", {})

        if intent_type == "hardware_intent":
            print(f"[Router Agent] ➡️ Dispatched to HARDWARE BUS -> {intent_payload}")
            await bus.publish("hardware_intent", intent_payload)

        elif intent_type == "desktop_automation":
            print(f"[Router Agent] ➡️ Dispatched to DESKTOP AUTOMATION -> {intent_payload}")
            await bus.publish("desktop_automation_intent", intent_payload)

        elif intent_type == "rag_search":
            print(f"[Router Agent] ➡️ Dispatched to RAG SEARCH -> {intent_payload}")
            await bus.publish("rag_search_intent", intent_payload)

        elif intent_type == "chat_response":
            print(f"[Router Agent] ➡️ Dispatched to CHAT TTS -> {intent_payload.get('text', '')}")
            await bus.publish("tts_intent", {"text": intent_payload.get("text", "")})

        elif intent_type == "mission_report_query":
            print(f"[Router Agent] ➡️ Dispatched to MISSION REPORT DEBRIEF")
            await bus.publish("mission_report_query", intent_payload)

        else:
            print(f"[Router Agent Warning] Unknown intent type: {intent_type}. Defaulting to TTS.")
            await bus.publish("tts_intent", {"text": "I received your request."})

# Global instance
router = RouterAgent()
