"""
BUPI Mission State Machine (FSM)
Part of BUPI Spatial Intelligence Engine (SIH 2026 / SIH26218)

Implements a deterministic, 12-state finite state machine that governs multi-robot
disaster-response and scouting missions. Ensures AI agent directives cannot violate
deterministic safety and operational sequences.
"""

from enum import Enum
import time
import logging
from typing import Dict, Any, List, Optional, Callable

logger = logging.getLogger("BUPI_MissionFSM")


class MissionState(Enum):
    IDLE = "IDLE"                                   # Stationed at base / dock, awaiting orders
    PLANNING = "PLANNING"                           # Parsing sector boundaries & mission objectives
    DISPATCHING = "DISPATCHING"                     # Moving robots from staging to search perimeter
    SCOUTING = "SCOUTING"                           # Bot 1 actively scanning target sector
    OBSERVATION = "OBSERVATION"                     # Bot 1 halted; verifying transient sensor signals
    POSSIBLE_HUMAN = "POSSIBLE_HUMAN"               # Scout detected PIR + range; verifying presence
    ENVIRONMENTAL_HAZARD = "ENVIRONMENTAL_HAZARD"   # Bot 2 detected elevated gas/smoke or temp
    REASSESS = "REASSESS"                           # Spatio-temporal fusion correlating multi-bot events
    RETURNING = "RETURNING"                         # Robots navigating back to origin / Wi-Fi boundary
    MISSION_COMPLETE = "MISSION_COMPLETE"           # Target sectors scouted; incident report compiled
    FAULT = "FAULT"                                 # Communication loss, sensor failure, or motor stall
    EMERGENCY_STOP = "EMERGENCY_STOP"               # Immediate hard stop across all robots


# Permissible deterministic state transitions
VALID_TRANSITIONS: Dict[MissionState, List[MissionState]] = {
    MissionState.IDLE: [
        MissionState.PLANNING,
        MissionState.FAULT,
        MissionState.EMERGENCY_STOP
    ],
    MissionState.PLANNING: [
        MissionState.DISPATCHING,
        MissionState.IDLE,
        MissionState.FAULT,
        MissionState.EMERGENCY_STOP
    ],
    MissionState.DISPATCHING: [
        MissionState.SCOUTING,
        MissionState.RETURNING,
        MissionState.FAULT,
        MissionState.EMERGENCY_STOP
    ],
    MissionState.SCOUTING: [
        MissionState.OBSERVATION,
        MissionState.POSSIBLE_HUMAN,
        MissionState.ENVIRONMENTAL_HAZARD,
        MissionState.RETURNING,
        MissionState.MISSION_COMPLETE,
        MissionState.FAULT,
        MissionState.EMERGENCY_STOP
    ],
    MissionState.OBSERVATION: [
        MissionState.POSSIBLE_HUMAN,
        MissionState.SCOUTING,
        MissionState.FAULT,
        MissionState.EMERGENCY_STOP
    ],
    MissionState.POSSIBLE_HUMAN: [
        MissionState.ENVIRONMENTAL_HAZARD,
        MissionState.REASSESS,
        MissionState.SCOUTING,
        MissionState.RETURNING,
        MissionState.FAULT,
        MissionState.EMERGENCY_STOP
    ],
    MissionState.ENVIRONMENTAL_HAZARD: [
        MissionState.REASSESS,
        MissionState.RETURNING,
        MissionState.FAULT,
        MissionState.EMERGENCY_STOP
    ],
    MissionState.REASSESS: [
        MissionState.SCOUTING,
        MissionState.RETURNING,
        MissionState.MISSION_COMPLETE,
        MissionState.FAULT,
        MissionState.EMERGENCY_STOP
    ],
    MissionState.RETURNING: [
        MissionState.IDLE,
        MissionState.MISSION_COMPLETE,
        MissionState.FAULT,
        MissionState.EMERGENCY_STOP
    ],
    MissionState.MISSION_COMPLETE: [
        MissionState.IDLE,
        MissionState.PLANNING,
        MissionState.EMERGENCY_STOP
    ],
    MissionState.FAULT: [
        MissionState.IDLE,
        MissionState.EMERGENCY_STOP
    ],
    MissionState.EMERGENCY_STOP: [
        MissionState.IDLE   # Requires explicit manual reset
    ]
}


class MissionFSM:
    """
    Deterministic Mission State Machine for coordinating BUPI-01 and BUPI-02.
    """

    def __init__(self, mission_id: Optional[str] = None):
        self.mission_id: str = mission_id or f"MSN_{int(time.time())}"
        self.current_state: MissionState = MissionState.IDLE
        self.previous_state: Optional[MissionState] = None
        self.state_entry_time: float = time.time()
        self.state_history: List[Dict[str, Any]] = []
        
        # Mission Context
        self.active_sector: Optional[str] = None
        self.objectives: List[str] = []
        self.fault_reason: Optional[str] = None
        self.discovered_pois: List[Dict[str, Any]] = []
        self.metadata: Dict[str, Any] = {}

        # Callbacks for state transitions: Callable[[MissionState, MissionState, Dict[str, Any]], None]
        self._transition_listeners: List[Callable[[MissionState, MissionState, Dict[str, Any]], None]] = []

        self._record_transition(None, MissionState.IDLE, "FSM Initialized")

    def register_listener(self, listener: Callable[[MissionState, MissionState, Dict[str, Any]], None]):
        """Register a callback that fires on every valid state transition."""
        if listener not in self._transition_listeners:
            self._transition_listeners.append(listener)

    def transition_to(self, new_state: MissionState, reason: str = "") -> bool:
        """
        Attempt a state transition. Returns True if valid and executed, False if rejected.
        """
        # Emergency stop is always allowed from any state
        if new_state == MissionState.EMERGENCY_STOP:
            return self._execute_transition(new_state, reason or "Emergency Stop Triggered")

        allowed_targets = VALID_TRANSITIONS.get(self.current_state, [])
        if new_state not in allowed_targets:
            logger.warning(
                f"[FSM] REJECTED transition: {self.current_state.value} -> {new_state.value}. "
                f"Allowed: {[s.value for s in allowed_targets]}. Reason: {reason}"
            )
            return False

        return self._execute_transition(new_state, reason)

    def _execute_transition(self, new_state: MissionState, reason: str) -> bool:
        old_state = self.current_state
        self.previous_state = old_state
        self.current_state = new_state
        self.state_entry_time = time.time()

        record = {
            "from": old_state.value if old_state else None,
            "to": new_state.value,
            "timestamp": self.state_entry_time,
            "reason": reason,
            "active_sector": self.active_sector
        }
        self.state_history.append(record)

        logger.info(f"[FSM] State: {old_state.value} -> {new_state.value} | Reason: {reason}")

        # Notify listeners
        for listener in self._transition_listeners:
            try:
                listener(old_state, new_state, record)
            except Exception as e:
                logger.error(f"[FSM] Listener callback error: {e}")

        return True

    def trigger_emergency_stop(self, reason: str = "Operator manual abort") -> bool:
        """Immediately transitions FSM to EMERGENCY_STOP."""
        return self.transition_to(MissionState.EMERGENCY_STOP, reason)

    def trigger_fault(self, reason: str) -> bool:
        """Transitions FSM to FAULT state with recorded diagnostics."""
        self.fault_reason = reason
        return self.transition_to(MissionState.FAULT, reason)

    def reset_to_idle(self) -> bool:
        """Resets the mission state machine back to IDLE."""
        self.fault_reason = None
        self.active_sector = None
        self.objectives.clear()
        return self.transition_to(MissionState.IDLE, "Manual reset to IDLE")

    def set_mission(self, mission_id: str, sector: str, objectives: List[str]):
        """Sets mission scope during PLANNING state."""
        self.mission_id = mission_id
        self.active_sector = sector
        self.objectives = list(objectives)

    def add_poi(self, poi: Dict[str, Any]):
        """Records a point of interest discovered during the mission."""
        self.discovered_pois.append(poi)

    def get_time_in_current_state(self) -> float:
        """Returns seconds spent in the current state."""
        return time.time() - self.state_entry_time

    def to_dict(self) -> Dict[str, Any]:
        """Serializes current FSM state for telemetry and UI synchronization."""
        return {
            "mission_id": self.mission_id,
            "current_state": self.current_state.value,
            "previous_state": self.previous_state.value if self.previous_state else None,
            "time_in_state_s": round(self.get_time_in_current_state(), 1),
            "active_sector": self.active_sector,
            "objectives": self.objectives,
            "fault_reason": self.fault_reason,
            "poi_count": len(self.discovered_pois),
            "total_transitions": len(self.state_history)
        }

    def _record_transition(self, old: Optional[MissionState], new: MissionState, reason: str):
        self.state_history.append({
            "from": old.value if old else None,
            "to": new.value,
            "timestamp": time.time(),
            "reason": reason,
            "active_sector": self.active_sector
        })
