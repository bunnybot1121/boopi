"""
Test prompts, TTS strings, and intent routing datasets for BUPI voice stack benchmark.
"""

# 3 TTS Evaluation Strings
TTS_PROMPTS = {
    "short": "Hey Boopi, what's up?",
    "medium": "I am scanning the room with ultrasonic sensors, and all readings indicate that the path ahead is completely clear.",
    "long": "Autonomous mode is currently engaged. I have checked the ambient temperature, gas sensors, and battery voltage levels. Everything is operating within normal parameters. The Wi-Fi hotspot connection to the ESP32 robot node is stable, and I am ready to begin the next scheduled room inspection routine whenever you give the command."
}

# 10 Intent Routing Prompts with Ground Truth Labels
# Categories: hardware_intent | chat_response | rag_search
INTENT_PROMPTS = [
    {
        "id": "intent_01",
        "prompt": "Move forward at speed seventy for three seconds.",
        "expected": "hardware_intent"
    },
    {
        "id": "intent_02",
        "prompt": "Hey Boopi, how was your day today?",
        "expected": "chat_response"
    },
    {
        "id": "intent_03",
        "prompt": "Search my notes for the Wi-Fi router password.",
        "expected": "rag_search"
    },
    {
        "id": "intent_04",
        "prompt": "Emergency stop all motors right now!",
        "expected": "hardware_intent"
    },
    {
        "id": "intent_05",
        "prompt": "Tell me a fun and quick joke about robots.",
        "expected": "chat_response"
    },
    {
        "id": "intent_06",
        "prompt": "Look up the project architecture documentation for the ESP32 pinout.",
        "expected": "rag_search"
    },
    {
        "id": "intent_07",
        "prompt": "Turn on relay one and scan the obstacle distance.",
        "expected": "hardware_intent"
    },
    {
        "id": "intent_08",
        "prompt": "What do you think is the best way to learn robotics?",
        "expected": "chat_response"
    },
    {
        "id": "intent_09",
        "prompt": "Find the meeting notes from yesterday regarding the robot budget.",
        "expected": "rag_search"
    },
    {
        "id": "intent_10",
        "prompt": "Spin 180 degrees and check if human presence is detected.",
        "expected": "hardware_intent"
    }
]

# 3 Tool-Call / JSON-Format Tests
JSON_TEST_PROMPTS = [
    {
        "id": "json_01",
        "prompt": "Move forward 2 seconds with speed 80 and turn on headlights. Output ONLY valid JSON matching this schema: {\"command\": \"move_forward\", \"speed\": 80, \"duration\": 2, \"headlights\": true}.",
        "required_keys": ["command", "speed", "duration", "headlights"]
    },
    {
        "id": "json_02",
        "prompt": "Create a note titled 'Shopping List' with content 'Milk, Eggs, Bread'. Output ONLY valid JSON matching this schema: {\"action\": \"create_note\", \"title\": \"Shopping List\", \"items\": [\"Milk\", \"Eggs\", \"Bread\"]}.",
        "required_keys": ["action", "title", "items"]
    },
    {
        "id": "json_03",
        "prompt": "Remind me to drink water in 30 minutes with high priority. Output ONLY valid JSON matching this schema: {\"type\": \"reminder\", \"event\": \"drink water\", \"delay_minutes\": 30, \"priority\": \"high\"}.",
        "required_keys": ["type", "event", "delay_minutes", "priority"]
    }
]
