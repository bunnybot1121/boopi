"""
BUPI Sensor Event Engine
========================
Standardized event factory and event stream manager for physical perception events.
Enforces strict epistemic honesty:
- PIR + HC-SR04 -> POSSIBLE_HUMAN_PRESENCE (Never 'Confirmed Human')
- MQ-2 -> ELEVATED_GAS_SMOKE (Never specific gas identification)
Part of BUPI Spatial Intelligence Engine (SIH 2026 / SIH26218).
"""

import time
import uuid
import threading
from enum import Enum
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict


class EventType(str, Enum):
    POSSIBLE_HUMAN_PRESENCE = "POSSIBLE_HUMAN_PRESENCE"
    OBSTACLE_DETECTED = "OBSTACLE_DETECTED"
    ELEVATED_GAS_SMOKE = "ELEVATED_GAS_SMOKE"
    HIGH_AMBIENT_TEMPERATURE = "HIGH_AMBIENT_TEMPERATURE"
    COMMUNICATION_WARNING = "COMMUNICATION_WARNING"


@dataclass
class SpatialEvent:
    event_id: str
    robot_id: str
    timestamp: float
    event_type: Any
    location: Optional[Dict[str, float]]
    sources: List[str]
    raw_values: Dict[str, Any]
    confidence: float
    uncertainty_m: float
    status: str
    description: str

    @property
    def x(self) -> float:
        return self.location.get("x", 0.0) if self.location else 0.0

    @property
    def y(self) -> float:
        return self.location.get("y", 0.0) if self.location else 0.0

    def to_dict(self) -> Dict[str, Any]:
        ev_type = self.event_type.value if hasattr(self.event_type, "value") else str(self.event_type)
        return {
            "event_id": self.event_id,
            "robot_id": self.robot_id,
            "timestamp": round(self.timestamp, 2),
            "event_type": ev_type,
            "location": self.location,
            "x": self.x,
            "y": self.y,
            "sources": self.sources,
            "raw_values": self.raw_values,
            "confidence": round(self.confidence, 2),
            "uncertainty_m": round(self.uncertainty_m, 2),
            "status": self.status,
            "description": self.description
        }


class EventEngine:
    def __init__(self, max_history: int = 500):
        self._lock = threading.Lock()
        self.events: List[SpatialEvent] = []
        self.max_history = max_history

    def _add_event(self, event: SpatialEvent) -> SpatialEvent:
        with self._lock:
            self.events.append(event)
            if len(self.events) > self.max_history:
                self.events.pop(0)
        return event

    def create_obstacle_event(
        self,
        bot_id: str,
        robot_x: float,
        robot_y: float,
        robot_theta: float,
        distance_cm: float,
        projected_x: float,
        projected_y: float
    ) -> SpatialEvent:
        loc = {"x": projected_x, "y": projected_y}
        evt = self.emit_obstacle_detected(robot_id=bot_id, distance_cm=distance_cm, location=loc)
        if evt is None:
            evt = SpatialEvent(
                event_id=f"evt_obs_{int(time.time()*1000)%1000000}",
                robot_id=bot_id,
                timestamp=time.time(),
                event_type=EventType.OBSTACLE_DETECTED,
                location=loc,
                sources=["HC-SR04"],
                raw_values={"distance_cm": round(distance_cm, 1)},
                confidence=0.95,
                uncertainty_m=0.20,
                status="ACTIVE",
                description=f"Acoustic obstacle detected at ({round(projected_x, 2)}, {round(projected_y, 2)})"
            )
            self._add_event(evt)
        return evt

    def clear_all(self):
        """Clears all historical and active events."""
        with self._lock:
            self.events.clear()

    def get_active_events(self) -> List[SpatialEvent]:
        """Returns all currently active spatial events."""
        with self._lock:
            return list(self.events)

    def create_possible_human_event(
        self,
        bot_id: str,
        robot_x: Any = 0.0,
        robot_y: float = 0.0,
        robot_theta: float = 0.0,
        distance_cm: float = 100.0,
        projected_x: Optional[float] = None,
        projected_y: Optional[float] = None,
        pir_state: int = 1,
        confidence: float = 0.85,
        location: Optional[Dict[str, float]] = None
    ) -> SpatialEvent:
        if isinstance(robot_x, (tuple, list)) and len(robot_x) >= 2:
            px, py = float(robot_x[0]), float(robot_x[1])
            loc = {"x": px, "y": py}
        elif location is not None:
            loc = location
        elif projected_x is not None and projected_y is not None:
            loc = {"x": projected_x, "y": projected_y}
        else:
            loc = {"x": float(robot_x), "y": float(robot_y)}

        evt = SpatialEvent(
            event_id=f"evt_human_{int(time.time()*1000)%1000000}",
            robot_id=bot_id,
            timestamp=time.time(),
            event_type=EventType.POSSIBLE_HUMAN_PRESENCE,
            location=loc,
            sources=["PIR", "HC-SR04"],
            raw_values={"distance_cm": round(distance_cm, 1), "pir_pin": pir_state},
            confidence=confidence,
            uncertainty_m=0.35,
            status="NEEDS_VERIFICATION",
            description=f"Possible warm moving presence localized at ({round(loc['x'], 2)}, {round(loc['y'], 2)})."
        )
        return self._add_event(evt)

    def create_gas_smoke_event(
        self,
        bot_id: str,
        robot_x: Any = 0.0,
        robot_y: float = 0.0,
        mq2_raw: float = 350.0,
        temperature_c: float = 25.0,
        gas_level: Optional[float] = None,
        confidence: float = 0.85,
        location: Optional[Dict[str, float]] = None
    ) -> SpatialEvent:
        if isinstance(robot_x, (tuple, list)) and len(robot_x) >= 2:
            px, py = float(robot_x[0]), float(robot_x[1])
            loc = {"x": px, "y": py}
        elif location is not None:
            loc = location
        else:
            loc = {"x": float(robot_x), "y": float(robot_y)}

        actual_gas = gas_level if gas_level is not None else mq2_raw
        evt = SpatialEvent(
            event_id=f"evt_gas_{int(time.time()*1000)%1000000}",
            robot_id=bot_id,
            timestamp=time.time(),
            event_type=EventType.ELEVATED_GAS_SMOKE,
            location=loc,
            sources=["MQ-2"],
            raw_values={"mq2_raw": round(actual_gas, 1), "temperature_c": round(temperature_c, 1)},
            confidence=confidence,
            uncertainty_m=0.5,
            status="WARNING",
            description=f"Elevated gas/smoke index {round(actual_gas, 1)} at ({round(loc['x'], 2)}, {round(loc['y'], 2)})."
        )
        return self._add_event(evt)

    def create_high_temp_event(
        self,
        bot_id: str,
        robot_x: float,
        robot_y: float,
        temperature_c: float
    ) -> SpatialEvent:
        loc = {"x": robot_x, "y": robot_y}
        evt = self.emit_high_temperature(
            robot_id=bot_id,
            temp_c=temperature_c,
            threshold_c=38.0,
            location=loc
        )
        if evt is None:
            evt = SpatialEvent(
                event_id=f"evt_temp_{int(time.time()*1000)%1000000}",
                robot_id=bot_id,
                timestamp=time.time(),
                event_type=EventType.HIGH_AMBIENT_TEMPERATURE,
                location=loc,
                sources=["DHT22"],
                raw_values={"temp_c": round(temperature_c, 1)},
                confidence=0.90,
                uncertainty_m=0.5,
                status="WARNING",
                description=f"Elevated ambient temperature ({round(temperature_c, 1)}°C) at ({round(robot_x, 2)}, {round(robot_y, 2)})."
            )
            self._add_event(evt)
        return evt

    def emit_possible_human_presence(
        self,
        robot_id: str,
        distance_cm: float,
        pir_active: bool,
        location: Optional[Dict[str, float]] = None,
        uncertainty_m: float = 0.35
    ) -> Optional[SpatialEvent]:
        if not (pir_active and 20.0 <= distance_cm <= 250.0):
            return None

        confidence = 0.85 if distance_cm <= 120.0 else 0.70
        evt = SpatialEvent(
            event_id=f"evt_human_{int(time.time()*1000)%1000000}",
            robot_id=robot_id,
            timestamp=time.time(),
            event_type=EventType.POSSIBLE_HUMAN_PRESENCE,
            location=location,
            sources=["PIR", "HC-SR04"],
            raw_values={"distance_cm": round(distance_cm, 1), "pir_pin": 1 if pir_active else 0},
            confidence=confidence,
            uncertainty_m=uncertainty_m,
            status="NEEDS_VERIFICATION",
            description=f"Possible warm moving presence localized ~{round(distance_cm/100.0, 2)}m away. Operator verification required."
        )
        return self._add_event(evt)

    def emit_obstacle_detected(
        self,
        robot_id: str,
        distance_cm: float,
        location: Optional[Dict[str, float]] = None,
        uncertainty_m: float = 0.20
    ) -> Optional[SpatialEvent]:
        if distance_cm > 50.0 or distance_cm < 2.0:
            return None

        evt = SpatialEvent(
            event_id=f"evt_obs_{int(time.time()*1000)%1000000}",
            robot_id=robot_id,
            timestamp=time.time(),
            event_type=EventType.OBSTACLE_DETECTED,
            location=location,
            sources=["HC-SR04"],
            raw_values={"distance_cm": round(distance_cm, 1)},
            confidence=0.95,
            uncertainty_m=uncertainty_m,
            status="ACTIVE",
            description=f"Acoustic obstacle detected in forward corridor ({round(distance_cm, 1)} cm)."
        )
        return self._add_event(evt)

    def emit_elevated_gas_smoke(
        self,
        robot_id: str,
        mq2_reading: float,
        threshold: float = 300.0,
        location: Optional[Dict[str, float]] = None
    ) -> Optional[SpatialEvent]:
        if mq2_reading < threshold:
            return None

        evt = SpatialEvent(
            event_id=f"evt_gas_{int(time.time()*1000)%1000000}",
            robot_id=robot_id,
            timestamp=time.time(),
            event_type=EventType.ELEVATED_GAS_SMOKE,
            location=location,
            sources=["MQ-2"],
            raw_values={"mq2_raw": round(mq2_reading, 1), "threshold": threshold},
            confidence=0.80,
            uncertainty_m=0.5,
            status="WARNING",
            description=f"Elevated combustible gas or smoke detected (qualitative index: {round(mq2_reading, 1)})."
        )
        return self._add_event(evt)

    def emit_high_temperature(
        self,
        robot_id: str,
        temp_c: float,
        threshold_c: float = 38.0,
        location: Optional[Dict[str, float]] = None
    ) -> Optional[SpatialEvent]:
        if temp_c < threshold_c:
            return None

        evt = SpatialEvent(
            event_id=f"evt_temp_{int(time.time()*1000)%1000000}",
            robot_id=robot_id,
            timestamp=time.time(),
            event_type=EventType.HIGH_AMBIENT_TEMPERATURE,
            location=location,
            sources=["DHT22"],
            raw_values={"temp_c": round(temp_c, 1), "threshold_c": threshold_c},
            confidence=0.90,
            uncertainty_m=0.5,
            status="WARNING",
            description=f"Elevated ambient temperature ({round(temp_c, 1)}°C) exceeds safety threshold ({threshold_c}°C)."
        )
        return self._add_event(evt)

    def emit_communication_warning(self, robot_id: str, rssi_dbm: int) -> SpatialEvent:
        evt = SpatialEvent(
            event_id=f"evt_comms_{int(time.time()*1000)%1000000}",
            robot_id=robot_id,
            timestamp=time.time(),
            event_type=EventType.COMMUNICATION_WARNING,
            location=None,
            sources=["WiFi_RSSI"],
            raw_values={"rssi_dbm": rssi_dbm},
            confidence=0.99,
            uncertainty_m=0.0,
            status="WARNING",
            description=f"Weak Wi-Fi link ({rssi_dbm} dBm). Near operational boundary envelope."
        )
        return self._add_event(evt)

    def get_recent_events(self, count: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            return [e.to_dict() for e in self.events[-count:]]


_global_event_engine: Optional[EventEngine] = None

def get_event_engine() -> EventEngine:
    """Returns the singleton EventEngine instance."""
    global _global_event_engine
    if _global_event_engine is None:
        _global_event_engine = EventEngine()
    return _global_event_engine

# Module-level singleton instance for convenient direct import
event_engine = get_event_engine()
