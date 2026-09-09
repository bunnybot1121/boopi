import asyncio
import re
import time
from core.event_bus_async import bus
from services.llm_gateway import LLMGateway

NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20", "twenty-five": "25",
    "twenty five": "25", "thirty": "30", "forty": "40", "forty-five": "45",
    "forty five": "45", "fifty": "50", "sixty": "60", "seventy": "70",
    "eighty": "80", "ninety": "90", "one hundred": "100", "one-eighty": "180",
    "one eighty": "180", "one hundred eighty": "180", "three sixty": "360",
    "three-sixty": "360", "three hundred sixty": "360"
}

def normalize_stt_command(text: str) -> str:
    """
    Normalizes speech-to-text transcriptions for robust command routing:
    - Strips punctuation (commas, quotes, question marks, exclamations, standalone dots).
    - Converts spoken number-words preceding units into digits ('twenty cm' -> '20 cm').
    - Strips conversational wake words and politeness prefixes ('hey boopi', 'can you please').
    """
    if not text:
        return ""
    
    # 1. Lowercase and strip quotes/commas/question marks/exclamations/dots (preserving decimals)
    cleaned = text.lower().strip()
    cleaned = re.sub(r"[,?!;:\"']", " ", cleaned)
    cleaned = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # 2. Convert spoken number words preceding units
    for word, digit in sorted(NUMBER_WORDS.items(), key=lambda x: -len(x[0])):
        pattern = r"\b" + re.escape(word) + r"\b(?=\s*(?:cm|centimeter|centimeters|cms|m|meter|meters|inch|inches|mm|millimeters|deg|degree|degrees)\b)"
        cleaned = re.sub(pattern, digit, cleaned)

    # 3. Strip leading conversational wake words and vocative addressing
    wake_prefix_pattern = (
        r"^(?:(?:hey|hi|hello|ok|okay)\s+)?"
        r"(?:boopi|bupi|boopy|boopie|bupie|prag|pragg|prak|prog|puppy|robot|the\s+robot|bot|the\s+bot)\b[:,]?\s*"
    )
    cleaned = re.sub(wake_prefix_pattern, "", cleaned).strip()

    # 4. Strip polite prefixes
    polite_prefix_pattern = (
        r"^(?:can\s+you\s+(?:please\s+)?|could\s+you\s+(?:please\s+)?|would\s+you\s+(?:please\s+)?|"
        r"please\s+|just\s+|go\s+ahead\s+and\s+|now\s+)"
    )
    cleaned = re.sub(polite_prefix_pattern, "", cleaned).strip()

    return cleaned

class RouterAgent:
    def __init__(self):
        self.llm = LLMGateway()

    def start(self):
        print("[Router Agent] Started. Listening for user utterances...")
        bus.subscribe("user_utterance", self.on_user_utterance)

    def normalize_stt_command(self, text: str) -> str:
        return normalize_stt_command(text)

    def quick_regex_classify(self, text: str) -> dict:
        """
        Microsecond (<5ms) deterministic regex classifier for instant direct commands.
        Bypasses LLM latency when the user intent is unambiguous.
        """
        clean = self.normalize_stt_command(text)

        # Edge Computing Obstacle Avoidance & Autonomous Roam (<1ms fast-pass)
        if re.search(r"\b(stop obstacle avoidance|disable obstacle avoidance|turn off obstacle avoidance|stop roaming|stop wandering|cancel obstacle avoidance|stop avoiding obstacles|turn off auto avoid|disable auto avoid|stop auto avoid)\b", clean):
            return {
                "type": "edge_avoid_mode",
                "payload": {"enabled": False}
            }
        if re.search(r"\b(start obstacle avoidance|enable obstacle avoidance|turn on obstacle avoidance|avoid obstacles on your own|avoid obstacles|start avoiding obstacles|autonomous roam|roam around|wander around|roam|wander|auto avoid|auto-avoid|start roaming|start wandering)\b", clean):
            return {
                "type": "edge_avoid_mode",
                "payload": {"enabled": True}
            }

        # Hardware E-Stop & Direct Motor Commands (<1ms fast-pass)
        if re.search(r"\b(stop|halt|freeze|emergency stop|e-stop|stop motors|brake|stop moving|stop driving|stop the robot|stop the bot|stop robot)\b", clean):
            return {
                "type": "hardware_intent",
                "payload": {"device": "motors", "action": "MOVE", "direction": "stop"}
            }
        if re.search(r"\b(abort mission|cancel mission|stop mission)\b", clean):
            return {
                "type": "abort_mission",
                "payload": {}
            }
        if re.search(r"\b(what did you find|show mission report|mission report|mission findings|last mission|what happened in last mission|tell me what you found|show debrief|mission debrief|what did you see|what were the findings|debrief report|show report|show findings)\b", clean):
            return {
                "type": "mission_report_query",
                "payload": {}
            }

        # Check for distance or degree moves first
        has_distance = bool(re.search(r"(\d+(?:\.\d+)?)\s*(?:cm|centimeter|centimeters|cms|m|meter|meters|inch|inches|mm|millimeters)\b", clean))
        has_degrees = bool(re.search(r"(\d+(?:\.\d+)?)\s*(?:deg|degree|degrees)\b", clean)) or bool(re.search(r"\bturn around\b", clean))

        if not has_distance and re.search(r"\b(move forward|drive forward|go forward|forward|ahead|move ahead|drive ahead|go ahead|advance|step forward|move the bot forward|move bot forward|drive the bot forward)\b", clean):
            return {
                "type": "hardware_intent",
                "payload": {"device": "motors", "action": "MOVE", "direction": "forward"}
            }
        if not has_distance and re.search(r"\b(move backward|move backwards|move back|drive backward|drive backwards|drive back|drive reverse|go backward|go backwards|go back|backward|backwards|reverse|back up|backup|back|go in reverse|step back|move the bot backward|move bot backward)\b", clean):
            return {
                "type": "hardware_intent",
                "payload": {"device": "motors", "action": "MOVE", "direction": "reverse"}
            }
        if not has_degrees and re.search(r"\b(turn left|spin left|rotate left|go left|take a left|turn to the left|turn towards left|drive left)\b", clean):
            return {
                "type": "hardware_intent",
                "payload": {"device": "motors", "action": "MOVE", "direction": "left"}
            }
        if not has_degrees and re.search(r"\b(turn right|spin right|rotate right|go right|take a right|turn to the right|turn towards right|drive right)\b", clean):
            return {
                "type": "hardware_intent",
                "payload": {"device": "motors", "action": "MOVE", "direction": "right"}
            }

        # Quick Sensor Telemetry Queries (<1ms bypass)
        # Gas / Smoke (MQ2)
        if re.search(r"\b(?:gas|smoke|lpg|mq2)\b.*?\b(?:level|reading|sensor|status|value|read|check)\b|\b(?:check|read|what is|whats|show)\b.*?\b(?:gas|smoke|lpg|mq2)\b", clean):
            return {
                "type": "sensor_query",
                "payload": {"sensor_id": "mq2"}
            }
        # Temperature
        if re.search(r"\b(?:room\s+|indoor\s+|current\s+)?(?:temperature|temp)\b.*?\b(?:reading|sensor|status|value|read|check)\b|\b(?:check|read|what is|whats|show)\b.*?\b(?:temperature|temp)\b", clean):
            return {
                "type": "sensor_query",
                "payload": {"sensor_id": "temp"}
            }
        # Ultrasonic Distance
        if re.search(r"\b(?:front\s+)?(?:distance|ultrasonic|clearance|obstacle\s+distance)\b.*?\b(?:reading|sensor|status|value|read|check)\b|\b(?:check|read|what is|whats|how far|show)\b.*?\b(?:distance|ultrasonic|clearance|obstacle)\b", clean):
            return {
                "type": "sensor_query",
                "payload": {"sensor_id": "distance"}
            }
        # World State & System Status
        if re.search(r"\b(?:world state|environment state|robot status|telemetry status|sensor status|system status)\b|\b(?:check|what is|whats|show)\b.*?\b(?:world state|robot status|system status)\b", clean):
            return {
                "type": "world_state_query",
                "payload": {}
            }

        # ESP32 Connection & Node Presence (<1ms bypass)
        if re.search(r"\b(?:any\s+)?(?:esp32|esp|node|nodes)\b.*?\b(?:connected|online|active|status|reach|found|working|there|available)\b|\b(?:check|is|are|any)\b.*?\b(?:esp32|esp|node|nodes)\b", clean):
            return {
                "type": "nodes_query",
                "payload": {}
            }

        # Instant Semantic Plan Fast-Pass (<1ms execution)
        try:
            from planner.instruction_decomposer import InstructionDecomposer, PolicyType
            quick_decomp = InstructionDecomposer(use_llm=False)
            plan = quick_decomp._semantic_decompose(clean)
            if plan is not None:
                if plan.policy_type == PolicyType.DIRECT_ACTION and plan.primary_action == "STOP":
                    return {
                        "type": "hardware_intent",
                        "payload": {"device": "motors", "action": "MOVE", "direction": "stop"}
                    }
                return {
                    "type": "autonomous_mission",
                    "payload": {"mission": clean}
                }
        except Exception:
            pass

        # Autonomous High-Level Robotic Missions (<1ms fast-pass)
        # Dynamic regex captures: any distance move ("move 10 cm", "move the bot 12 cm", "drive 0.5 meters"),
        # rotation to angle ("turn 90 degrees", "rotate 180 degrees", "turn around"),
        # scanning ("scan the room", "scan around", "scan", "sweep"), patrol, explore, human search, etc.
        if re.search(r"\b(move towards|go towards|drive towards|walk towards|approach|head towards|get closer to)\b.*?\b(him|her|them|it|the person|a person|person|human|someone|target)\b", clean) or \
           re.search(r"\b(whenever|if|when)\b.*?\b(find|detect|see|locate)\b.*?\b(person|human|someone|target)\b.*?\b(move|go|drive|walk|approach)\b", clean) or \
           re.search(r"\b(how many|number of|count|count the|total number of)\b.*?\b(people|persons|humans|someone|occupants)\b", clean) or \
           re.search(r"\b(move towards him|move towards her|move towards them|move towards person|move towards human|move towards target|move towards it|approach person|approach human|approach the person|go towards him|go towards person|how many people|how many humans|number of people|count people|count the people|people count|find the human|find human|find person|locate human|locate person|search for human|search the room|search room|patrol|patrol the room|patrol and inspect|patrol area|explore|explore the room|explore room|autonomous mission|walk until|drive until|move until|go until|run until|are there any humans|is anyone in the room|is there anyone|anyone in the room|humans in the room|scan the room|scan room|scan around|scan area|scan surrounding|scan surroundings|scan|sweep|360 scan)\b", clean) or \
           has_distance or has_degrees:
            return {
                "type": "autonomous_mission",
                "payload": {"mission": clean}
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

        elif intent_type == "mission_report_query":
            print(f"[Router Agent] ➡️ Dispatched to MISSION REPORT DEBRIEF")
            await bus.publish("mission_report_query", intent_payload)

        elif intent_type == "autonomous_mission":
            print(f"[Router Agent] ➡️ Dispatched to AUTONOMOUS GOAL AGENT -> {intent_payload}")
            from agents.autonomous_goal_agent import goal_agent
            mission_text = intent_payload.get("mission", "")
            if mission_text:
                res = goal_agent.start_mission(mission_text)
                await bus.publish("tts_intent", {"text": res})

        elif intent_type == "abort_mission":
            print(f"[Router Agent] ➡️ Dispatched to ABORT MISSION")
            from agents.autonomous_goal_agent import goal_agent
            res = goal_agent.stop_mission(reason="User commanded abort")
            await bus.publish("tts_intent", {"text": res})

        elif intent_type == "edge_avoid_mode":
            enabled = intent_payload.get("enabled", True)
            print(f"[Router Agent] ➡️ Dispatched to EDGE AVOID MODE -> enabled={enabled}")
            try:
                import paho.mqtt.client as mqtt
                mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="router_edge_avoid")
                mqtt_client.connect("localhost", 1883, 5)
                payload_json = json.dumps({"action": "auto_avoid", "enabled": enabled})
                mqtt_client.publish("bupi/actuators/motors/cmd/json", payload_json)
                mqtt_client.disconnect()
            except Exception as me:
                print(f"[Router Agent] MQTT publish error: {me}")
            spoken = "Edge obstacle avoidance enabled. Navigating on ESP32." if enabled else "Obstacle avoidance disabled. Standby."
            await bus.publish("tts_intent", {"text": spoken})

        else:
            print(f"[Router Agent Warning] Unknown intent type: {intent_type}. Defaulting to TTS.")
            await bus.publish("tts_intent", {"text": "I received your request."})

# Global instance
router = RouterAgent()
