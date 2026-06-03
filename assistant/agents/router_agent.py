import asyncio
from core.event_bus_async import bus
from services.llm_gateway import LLMGateway

class RouterAgent:
    def __init__(self):
        self.llm = LLMGateway()

    def start(self):
        print("[Router Agent] Started. Listening for user utterances...")
        bus.subscribe("user_utterance", self.on_user_utterance)

    async def on_user_utterance(self, payload: dict):
        text = payload.get("text", "")
        if not text:
            return
            
        print(f"\n[Router Agent] Received utterance: '{text}'")
        print("[Router Agent] Consulting LLM Gateway...")
        
        # Call LLM to classify intent
        intent_json = await self.llm.classify_intent(text)
        intent_type = intent_json.get("type")
        intent_payload = intent_json.get("payload", {})
        
        if intent_type == "hardware_intent":
            print(f"[Router Agent] ➡️ Classified as HARDWARE -> {intent_payload}")
            await bus.publish("hardware_intent", intent_payload)
            
        elif intent_type == "chat_response":
            print(f"[Router Agent] ➡️ Classified as CHAT")
            await bus.publish("tts_intent", {"text": intent_payload.get('text', '')})
            
        else:
            print(f"[Router Agent] Unknown intent type: {intent_type}")

# Global instance
router = RouterAgent()
