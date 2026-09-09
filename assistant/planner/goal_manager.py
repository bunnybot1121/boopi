"""
BUPI Goal Manager
=================
Maintains lifecycle management of high-level missions and capability allocation.
"""

import time
from enum import Enum
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from intent.intent_parser import ParsedGoal, HighLevelIntent

class GoalStatus(str, Enum):
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    VERIFYING = "VERIFYING"
    TARGET_DETECTED = "TARGET_DETECTED"
    HOLDING = "HOLDING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"

@dataclass
class ActiveMission:
    goal: ParsedGoal
    status: GoalStatus = GoalStatus.IDLE
    start_time: float = field(default_factory=time.time)
    detections_count: int = 0
    reports_emitted: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.goal.intent.value,
            "goal_description": self.goal.goal_description,
            "raw_command": self.goal.raw_command,
            "status": self.status.value,
            "elapsed_seconds": round(time.time() - self.start_time, 1),
            "detections_count": self.detections_count,
            "reports_emitted": self.reports_emitted,
            "capabilities": self.goal.relevant_capabilities
        }

class GoalManager:
    def __init__(self):
        self.active_mission: Optional[ActiveMission] = None

    def start_mission(self, parsed_goal: ParsedGoal) -> ActiveMission:
        self.active_mission = ActiveMission(
            goal=parsed_goal,
            status=GoalStatus.ACTIVE,
            start_time=time.time()
        )
        return self.active_mission

    def record_detection(self, report_message: str):
        if self.active_mission:
            self.active_mission.detections_count += 1
            self.active_mission.reports_emitted.append(report_message)
            self.active_mission.status = GoalStatus.TARGET_DETECTED

    def set_status(self, status: GoalStatus):
        if self.active_mission:
            self.active_mission.status = status

    def get_mission_info(self) -> Dict[str, Any]:
        if self.active_mission:
            return self.active_mission.to_dict()
        return {"status": GoalStatus.IDLE.value, "goal_description": "No active mission"}
