"""
BUPI Internal State Object Manager (Section 11)
==============================================
Maintains the centralized situational state of BUPI:
- Goal & Mode
- Robot Kinematics & Orientation
- Environment Perception (Distance, PIR Motion, Possible Human Presence)
- Epistemic Progression & Event History
"""

import time
from typing import Dict, Any, Optional
from dataclasses import dataclass, field, asdict

@dataclass
class RobotState:
    movement: str = "STATIONARY"  # STATIONARY, MOVING, TURNING
    orientation: str = "NORMAL"   # NORMAL, TILTED, ORIENTATION_CHANGED
    heading_deg: float = 0.0
    pitch_deg: float = 0.0
    roll_deg: float = 0.0
    speed_percent: int = 0

@dataclass
class EnvironmentState:
    distance_cm: float = 125.0
    motion_detected: bool = False
    possible_human_presence: bool = False
    proximity_class: str = "far"
    confidence: float = 0.0

@dataclass
class BupiState:
    goal: str = "IDLE"
    mode: str = "IDLE"  # IDLE, SEARCHING, VERIFYING, OBSTACLE_AVOIDING, REPORTING, EMERGENCY_STOP
    robot: RobotState = field(default_factory=RobotState)
    environment: EnvironmentState = field(default_factory=EnvironmentState)
    last_event: str = "NONE"
    last_decision: str = "NONE"
    last_action: str = "STOP"
    last_report: str = "System ready."
    timestamp: float = field(default_factory=time.time)
    epistemic_ladder: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

class StateManager:
    def __init__(self):
        self.state = BupiState()
        self.history = []

    def get_state(self) -> BupiState:
        return self.state

    def update_from_fusion(self, fusion_result: Dict[str, Any]):
        """
        Ingests the latest sensor fusion output and updates situational state.
        """
        self.state.timestamp = time.time()
        
        # Ultrasonic & PIR
        dist_info = fusion_result.get("ultrasonic", {})
        pir_info = fusion_result.get("pir", {})
        imu_info = fusion_result.get("imu", {})
        inference = fusion_result.get("inference", {})

        self.state.environment.distance_cm = dist_info.get("distance_cm", 125.0)
        self.state.environment.proximity_class = dist_info.get("classification", "far")
        self.state.environment.motion_detected = pir_info.get("motion_detected", False)
        self.state.environment.possible_human_presence = inference.get("possible_human_presence", False)
        self.state.environment.confidence = inference.get("confidence_score", 0.0)

        # IMU
        self.state.robot.heading_deg = imu_info.get("heading_deg", 0.0)
        self.state.robot.pitch_deg = imu_info.get("pitch_deg", 0.0)
        self.state.robot.roll_deg = imu_info.get("roll_deg", 0.0)
        self.state.robot.orientation = "TILT_HAZARD" if imu_info.get("tilt_hazard") else "NORMAL"

        if self.state.environment.possible_human_presence:
            self.state.last_event = "POSSIBLE_HUMAN_PRESENCE"
            self.state.last_report = inference.get("report_message", "")

        self.state.epistemic_ladder = fusion_result.get("epistemic_ladder", {})

    def set_goal(self, goal_name: str, mode: str = "SEARCHING"):
        self.state.goal = goal_name
        self.state.mode = mode
        self.state.timestamp = time.time()

    def set_decision_and_action(self, decision: str, action: str, reason: str = ""):
        self.state.last_decision = decision
        self.state.last_action = action
        if action in ["MOVE_FORWARD", "MOVE_BACKWARD"]:
            self.state.robot.movement = "MOVING"
        elif action in ["TURN_LEFT", "TURN_RIGHT"]:
            self.state.robot.movement = "TURNING"
        else:
            self.state.robot.movement = "STATIONARY"
