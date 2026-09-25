"""
BUPI Multi-Bot Spatio-Temporal Sensor Fusion
============================================
Correlates observations from BUPI-01 (Scout) and BUPI-02 (Environmental Specialist)
across both space and time to produce unified tactical Incident Records.
Part of BUPI Spatial Intelligence Engine (SIH 2026 / SIH26218).

SCIENTIFIC CRITERIA:
- Spatial Proximity Threshold: R <= 1.5 meters
- Temporal Window Threshold: delta_t <= 60.0 seconds
- Epistemic Integrity: Synthesizes distinct sensor modalities without fabricating certainty.
"""

import time
import math
import threading
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from .event_engine import SpatialEvent

@dataclass
class FusedIncident:
    incident_id: str
    sector_name: str
    center_location: Dict[str, float]
    observations: List[str]
    participating_robots: List[str]
    severity: str
    operator_summary: str
    events_included: List[str]
    timestamp: float
    verified: bool = False
    confidence: float = 0.85

    @property
    def sector(self) -> str:
        return self.sector_name

    @property
    def summary(self) -> str:
        return self.operator_summary

    @property
    def center_x(self) -> float:
        return self.center_location.get("x_m", self.center_location.get("x", 0.0))

    @property
    def center_y(self) -> float:
        return self.center_location.get("y_m", self.center_location.get("y", 0.0))

    @property
    def contributing_events(self) -> List[str]:
        return self.events_included

    def to_dict(self) -> Dict[str, Any]:
        cx = self.center_x
        cy = self.center_y
        return {
            "incident_id": self.incident_id,
            "sector_name": self.sector_name,
            "sector": self.sector_name,
            "center_location": {
                "x_m": round(cx, 2),
                "y_m": round(cy, 2)
            },
            "center_x": round(cx, 2),
            "center_y": round(cy, 2),
            "observations": self.observations,
            "participating_robots": self.participating_robots,
            "severity": self.severity,
            "operator_summary": self.operator_summary,
            "summary": self.operator_summary,
            "confidence": self.confidence,
            "contributing_events": self.events_included,
            "events_included": self.events_included,
            "timestamp": round(self.timestamp, 2),
            "verified": self.verified
        }

class MultiBotFusionEngine:
    def __init__(
        self,
        spatial_radius_threshold_m: float = 1.5,
        temporal_window_s: float = 60.0,
        spatial_threshold_m: Optional[float] = None
    ):
        self._lock = threading.Lock()
        self.spatial_radius_m = spatial_threshold_m if spatial_threshold_m is not None else spatial_radius_threshold_m
        self.temporal_window_s = temporal_window_s
        self._incidents_dict: Dict[str, FusedIncident] = {}
        self.unfused_events: List[SpatialEvent] = []

    @property
    def active_incidents(self) -> List[FusedIncident]:
        with self._lock:
            return list(self._incidents_dict.values())

    def _get_sector_name(self, x: float, y: float) -> str:
        """Determines sector grid quadrant for operator clarity."""
        if x >= 0 and y >= 0:
            return "Sector A (North-East)"
        elif x < 0 and y >= 0:
            return "Sector B (North-West)"
        elif x < 0 and y < 0:
            return "Sector C (South-West)"
        else:
            return "Sector D (South-East)"

    def ingest_event(self, event: SpatialEvent) -> Optional[FusedIncident]:
        """
        Ingests a new perception event from either robot and checks for spatio-temporal
        correlation with observations from the other robot.
        """
        if not event.location:
            return None

        with self._lock:
            now = event.timestamp
            ex = event.location.get("x_m", event.location.get("x", 0.0))
            ey = event.location.get("y_m", event.location.get("y", 0.0))

            # 1. Check existing active incidents for spatial proximity
            matched_incident = None
            for inc in self._incidents_dict.values():
                dx = ex - inc.center_x
                dy = ey - inc.center_y
                dist = math.sqrt(dx*dx + dy*dy)
                if dist <= self.spatial_radius_m and (now - inc.timestamp) <= self.temporal_window_s:
                    matched_incident = inc
                    break

            if matched_incident:
                # Merge into existing incident
                r_id = getattr(event, "bot_id", getattr(event, "robot_id", "robot"))
                if r_id not in matched_incident.participating_robots:
                    matched_incident.participating_robots.append(r_id)
                matched_incident.observations.append(f"[{r_id}] {event.description}")
                matched_incident.events_included.append(event.event_id)
                matched_incident.timestamp = now

                # Upgrade severity if human presence correlates with environmental hazard
                has_human = any("HUMAN" in obs for obs in matched_incident.observations)
                has_gas = any("gas" in obs.lower() or "smoke" in obs.lower() for obs in matched_incident.observations)
                has_temp = any("temperature" in obs.lower() for obs in matched_incident.observations)

                if has_human and (has_gas or has_temp):
                    matched_incident.severity = "CRITICAL"
                    matched_incident.operator_summary = (
                        f"CRITICAL HAZARD: Possible human presence in {matched_incident.sector_name} "
                        f"coincides with elevated environmental hazards ({'gas/smoke, ' if has_gas else ''}"
                        f"{'elevated thermal flux' if has_temp else ''}). Immediate operator verification recommended."
                    )
                return matched_incident

            # 2. Check unfused event buffer for correlation with a complementary robot
            r_id = getattr(event, "bot_id", getattr(event, "robot_id", "robot"))
            for past_evt in list(self.unfused_events):
                past_r_id = getattr(past_evt, "bot_id", getattr(past_evt, "robot_id", "past_robot"))
                if past_r_id != r_id and past_evt.location:
                    px = past_evt.location.get("x_m", past_evt.location.get("x", 0.0))
                    py = past_evt.location.get("y_m", past_evt.location.get("y", 0.0))
                    dx = ex - px
                    dy = ey - py
                    dist = math.sqrt(dx*dx + dy*dy)
                    time_diff = abs(now - past_evt.timestamp)

                    if dist <= self.spatial_radius_m and time_diff <= self.temporal_window_s:
                        # Correlation detected: Create new Fused Incident
                        sector = self._get_sector_name(ex, ey)
                        inc_id = f"inc_{int(now*1000)%1000000}"
                        center = {"x_m": (ex + px) / 2.0, "y_m": (ey + py) / 2.0}

                        obs = [
                            f"[{past_r_id}] {past_evt.description}",
                            f"[{r_id}] {event.description}"
                        ]
                        bots = [past_r_id, r_id]

                        p_type = past_evt.event_type.value if hasattr(past_evt.event_type, "value") else str(past_evt.event_type)
                        e_type = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
                        has_human = "HUMAN" in p_type or "HUMAN" in e_type
                        has_gas = "GAS" in p_type or "GAS" in e_type
                        has_temp = "TEMP" in p_type or "TEMP" in e_type

                        severity = "WARNING"
                        if has_human and (has_gas or has_temp):
                            severity = "CRITICAL"
                            summary = (
                                f"Possible human presence detected in {sector}. "
                                f"Environmental readings indicate hazardous conditions. Operator verification recommended."
                            )
                        elif has_human:
                            summary = f"Possible human presence localized in {sector}. Corroborated by scouting fleet."
                        else:
                            summary = f"Environmental anomaly detected in {sector} by multiple sensors."

                        fused = FusedIncident(
                            incident_id=inc_id,
                            sector_name=sector,
                            center_location=center,
                            observations=obs,
                            participating_robots=bots,
                            severity=severity,
                            operator_summary=summary,
                            events_included=[past_evt.event_id, event.event_id],
                            timestamp=now
                        )
                        self._incidents_dict[inc_id] = fused
                        self.unfused_events.remove(past_evt)
                        return fused

            # No match found yet: retain in recent unfused buffer
            self.unfused_events.append(event)
            # Prune stale events older than temporal window
            self.unfused_events = [e for e in self.unfused_events if (now - e.timestamp) <= self.temporal_window_s]
            return None

    def fuse_events(self, events: List[SpatialEvent]) -> List[FusedIncident]:
        """Ingests a collection of spatial events and returns the active fused incidents."""
        for evt in events:
            self.ingest_event(evt)
        return self.active_incidents

    def get_all_incidents(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [inc.to_dict() for inc in self._incidents_dict.values()]
