"""
BUPI Intent Parser & Natural Language Understanding
===================================================
Converts single high-level user commands into autonomous robot intents.

SUPPORTED INTENTS:
- SEARCH_FOR_PRESENCE
- EXPLORE_SAFE
- PATROL
- MONITOR_MOTION
- OBSERVE_SURROUNDINGS
- APPROACH_TARGET
- STOP_AND_WAIT
"""

import re
import os
from enum import Enum
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict

class HighLevelIntent(str, Enum):
    SEARCH_FOR_PRESENCE = "SEARCH_FOR_PRESENCE"
    EXPLORE_SAFE = "EXPLORE_SAFE"
    PATROL = "PATROL"
    MONITOR_MOTION = "MONITOR_MOTION"
    OBSERVE_SURROUNDINGS = "OBSERVE_SURROUNDINGS"
    APPROACH_TARGET = "APPROACH_TARGET"
    STOP_AND_WAIT = "STOP_AND_WAIT"

@dataclass
class ParsedGoal:
    raw_command: str
    intent: HighLevelIntent
    confidence: float
    goal_description: str
    relevant_capabilities: List[str]
    stop_condition: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["intent"] = self.intent.value
        return d

# Section 15 Training / Knowledge Base Dataset
KNOWLEDGE_BASE_EXAMPLES = [
    {"input": "Find a person in the room.", "intent": HighLevelIntent.SEARCH_FOR_PRESENCE},
    {"input": "BUPI, find a person in this room.", "intent": HighLevelIntent.SEARCH_FOR_PRESENCE},
    {"input": "Search around and find someone.", "intent": HighLevelIntent.SEARCH_FOR_PRESENCE},
    {"input": "Look around this room for people.", "intent": HighLevelIntent.SEARCH_FOR_PRESENCE},
    {"input": "Locate someone in the house.", "intent": HighLevelIntent.SEARCH_FOR_PRESENCE},
    {"input": "See if anyone is inside.", "intent": HighLevelIntent.SEARCH_FOR_PRESENCE},
    {"input": "Can you check if there is a human here?", "intent": HighLevelIntent.SEARCH_FOR_PRESENCE},
    {"input": "Search for any human presence.", "intent": HighLevelIntent.SEARCH_FOR_PRESENCE},

    {"input": "Explore this area safely.", "intent": HighLevelIntent.EXPLORE_SAFE},
    {"input": "Go around the room without hitting anything.", "intent": HighLevelIntent.EXPLORE_SAFE},
    {"input": "Roam around the room safely.", "intent": HighLevelIntent.EXPLORE_SAFE},
    {"input": "Navigate and avoid obstacles.", "intent": HighLevelIntent.EXPLORE_SAFE},
    {"input": "Map the clear paths in this area.", "intent": HighLevelIntent.EXPLORE_SAFE},

    {"input": "Patrol the perimeter.", "intent": HighLevelIntent.PATROL},
    {"input": "Guard this room.", "intent": HighLevelIntent.PATROL},
    {"input": "Do a patrol sweep around the room.", "intent": HighLevelIntent.PATROL},
    {"input": "Keep patrolling back and forth.", "intent": HighLevelIntent.PATROL},

    {"input": "Tell me whenever you detect movement.", "intent": HighLevelIntent.MONITOR_MOTION},
    {"input": "Watch for motion and alert me.", "intent": HighLevelIntent.MONITOR_MOTION},
    {"input": "Stay still and detect movement.", "intent": HighLevelIntent.MONITOR_MOTION},
    {"input": "Monitor this door for any motion.", "intent": HighLevelIntent.MONITOR_MOTION},

    {"input": "Look around and report what you see.", "intent": HighLevelIntent.OBSERVE_SURROUNDINGS},
    {"input": "Scan your surroundings.", "intent": HighLevelIntent.OBSERVE_SURROUNDINGS},
    {"input": "Check the room environment.", "intent": HighLevelIntent.OBSERVE_SURROUNDINGS},

    {"input": "Move closer to the detected target.", "intent": HighLevelIntent.APPROACH_TARGET},
    {"input": "Approach the obstacle slowly.", "intent": HighLevelIntent.APPROACH_TARGET},
    {"input": "Get closer to that person.", "intent": HighLevelIntent.APPROACH_TARGET},

    {"input": "Stop.", "intent": HighLevelIntent.STOP_AND_WAIT},
    {"input": "Halt immediately.", "intent": HighLevelIntent.STOP_AND_WAIT},
    {"input": "Freeze and wait.", "intent": HighLevelIntent.STOP_AND_WAIT},
    {"input": "Stop moving.", "intent": HighLevelIntent.STOP_AND_WAIT},
    {"input": "Emergency stop.", "intent": HighLevelIntent.STOP_AND_WAIT},
]

class IntentParser:
    def __init__(self, use_llm_fallback: bool = True):
        self.use_llm_fallback = use_llm_fallback
        self.rules = self._compile_rules()

    def _compile_rules(self) -> List[Dict[str, Any]]:
        return [
            {
                "intent": HighLevelIntent.STOP_AND_WAIT,
                "patterns": [
                    r"\b(stop|halt|freeze|pause|stay still|wait|cancel|emergency stop)\b"
                ],
                "weight": 1.0
            },
            {
                "intent": HighLevelIntent.SEARCH_FOR_PRESENCE,
                "patterns": [
                    r"\b(find|search|look for|locate|seek|detect)\b.*\b(person|someone|human|people|anybody|anyone|presence)\b",
                    r"\b(anyone|anybody)\b.*\b(here|room|inside)\b",
                    r"\bfind a person\b"
                ],
                "weight": 0.95
            },
            {
                "intent": HighLevelIntent.MONITOR_MOTION,
                "patterns": [
                    r"\b(monitor|watch|alert|tell me)\b.*\b(motion|movement|moving)\b",
                    r"\bdetect\s+motion\b"
                ],
                "weight": 0.9
            },
            {
                "intent": HighLevelIntent.APPROACH_TARGET,
                "patterns": [
                    r"\b(approach|move closer|get closer|come closer|advance to)\b"
                ],
                "weight": 0.88
            },
            {
                "intent": HighLevelIntent.PATROL,
                "patterns": [
                    r"\b(patrol|guard|sentry|sweep perimeter|perimeter)\b"
                ],
                "weight": 0.85
            },
            {
                "intent": HighLevelIntent.EXPLORE_SAFE,
                "patterns": [
                    r"\b(explore|roam|wander|walk around|go around)\b.*\b(safely|safe|without hitting|avoiding obstacles)?\b",
                    r"\bexplore\s+this\s+area\b"
                ],
                "weight": 0.8
            },
            {
                "intent": HighLevelIntent.OBSERVE_SURROUNDINGS,
                "patterns": [
                    r"\b(look around|observe|scan|inspect surroundings|report status)\b"
                ],
                "weight": 0.75
            },
        ]

    def parse(self, text: str) -> ParsedGoal:
        cleaned = text.strip().lower()

        # 1. Exact match against Knowledge Base
        for ex in KNOWLEDGE_BASE_EXAMPLES:
            if cleaned == ex["input"].strip().lower():
                return self._build_goal(text, ex["intent"], confidence=1.0)

        # 2. Rule-based Pattern Matching with semantic keyword scores
        best_intent = None
        highest_score = 0.0

        for rule in self.rules:
            for pat in rule["patterns"]:
                if re.search(pat, cleaned, re.IGNORECASE):
                    score = rule["weight"]
                    if score > highest_score:
                        highest_score = score
                        best_intent = rule["intent"]

        if best_intent and highest_score >= 0.75:
            return self._build_goal(text, best_intent, confidence=highest_score)

        # 3. Keyword semantic fallback
        if any(w in cleaned for w in ["person", "human", "someone", "people"]):
            return self._build_goal(text, HighLevelIntent.SEARCH_FOR_PRESENCE, confidence=0.8)
        if any(w in cleaned for w in ["explore", "room", "roam", "walk"]):
            return self._build_goal(text, HighLevelIntent.EXPLORE_SAFE, confidence=0.75)
        if any(w in cleaned for w in ["motion", "movement"]):
            return self._build_goal(text, HighLevelIntent.MONITOR_MOTION, confidence=0.8)
        if any(w in cleaned for w in ["stop", "halt", "wait"]):
            return self._build_goal(text, HighLevelIntent.STOP_AND_WAIT, confidence=0.9)

        # Default fallback
        return self._build_goal(text, HighLevelIntent.SEARCH_FOR_PRESENCE, confidence=0.6)

    def _build_goal(self, command: str, intent: HighLevelIntent, confidence: float) -> ParsedGoal:
        capabilities_map = {
            HighLevelIntent.SEARCH_FOR_PRESENCE: [
                "movement",
                "PIR motion detection",
                "ultrasonic distance measurement",
                "MPU6050 orientation/movement tracking",
                "obstacle avoidance",
                "event reporting"
            ],
            HighLevelIntent.EXPLORE_SAFE: [
                "movement",
                "ultrasonic distance measurement",
                "obstacle avoidance",
                "MPU6050 orientation/movement tracking"
            ],
            HighLevelIntent.PATROL: [
                "movement",
                "ultrasonic distance measurement",
                "MPU6050 orientation/movement tracking",
                "PIR motion detection",
                "periodic reporting"
            ],
            HighLevelIntent.MONITOR_MOTION: [
                "PIR motion detection",
                "ultrasonic distance measurement",
                "event reporting"
            ],
            HighLevelIntent.OBSERVE_SURROUNDINGS: [
                "MPU6050 orientation/movement tracking",
                "ultrasonic distance measurement",
                "event reporting"
            ],
            HighLevelIntent.APPROACH_TARGET: [
                "movement",
                "ultrasonic distance measurement",
                "obstacle avoidance",
                "MPU6050 tracking"
            ],
            HighLevelIntent.STOP_AND_WAIT: [
                "motor cutoff",
                "safety hold"
            ]
        }

        goal_desc_map = {
            HighLevelIntent.SEARCH_FOR_PRESENCE: "Find a location containing possible human presence.",
            HighLevelIntent.EXPLORE_SAFE: "Navigate through the room while continuously avoiding all obstacles.",
            HighLevelIntent.PATROL: "Patrol the designated perimeter and alert on state deviations.",
            HighLevelIntent.MONITOR_MOTION: "Remain in position and trigger alert upon detecting infrared motion.",
            HighLevelIntent.OBSERVE_SURROUNDINGS: "Perform an in-place rotational scan and summarize sensor surroundings.",
            HighLevelIntent.APPROACH_TARGET: "Safely reduce distance to the detected target up to warning threshold.",
            HighLevelIntent.STOP_AND_WAIT: "Immediately halt all motor activity and hold position."
        }

        stop_condition_map = {
            HighLevelIntent.SEARCH_FOR_PRESENCE: "Possible human presence detected and reported, or operator cancel.",
            HighLevelIntent.EXPLORE_SAFE: "Timeout reached or operator stop command.",
            HighLevelIntent.PATROL: "Continuous until operator cancel.",
            HighLevelIntent.MONITOR_MOTION: "Motion trigger detected or operator cancel.",
            HighLevelIntent.OBSERVE_SURROUNDINGS: "360-degree sweep complete.",
            HighLevelIntent.APPROACH_TARGET: "Safe approach threshold reached.",
            HighLevelIntent.STOP_AND_WAIT: "Immediate."
        }

        return ParsedGoal(
            raw_command=command,
            intent=intent,
            confidence=confidence,
            goal_description=goal_desc_map.get(intent, "Autonomous execution"),
            relevant_capabilities=capabilities_map.get(intent, ["movement", "obstacle avoidance"]),
            stop_condition=stop_condition_map.get(intent, "Operator command")
        )
