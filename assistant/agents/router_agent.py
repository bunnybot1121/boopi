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

        else:
            print(f"[Router Agent Warning] Unknown intent type: {intent_type}. Defaulting to TTS.")
            await bus.publish("tts_intent", {"text": "I received your request."})

# Global instance
router = RouterAgent()
