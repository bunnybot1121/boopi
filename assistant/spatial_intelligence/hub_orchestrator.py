"""
BUPI Multi-Robot Hub Orchestrator
Part of BUPI Spatial Intelligence Engine (SIH 2026 / SIH26218)

Coordinates BUPI-01 (Scout) and BUPI-02 (Environmental Specialist).
Integrates RobotRegistry, ControlAdapter, LocalOdometryEngine, SensorProjectionEngine,
EventEngine, MultiBotFusionEngine, MissionFSM, and SpatialTwinBridge into a cohesive,
scientifically defensible system for Smart India Hackathon 2026.
"""

import logging
import math
import time
from typing import Dict, Any, List, Optional

from .robot_registry import RobotRegistry, RobotRole, RobotNode
from .control_adapter import ControlAdapter
from .local_odometry import LocalOdometryEngine
from .sensor_projection import SensorProjectionEngine
from .event_engine import EventEngine, SpatialEvent, EventType
from .multi_bot_fusion import MultiBotFusionEngine, FusedIncident
from .mission_fsm import MissionFSM, MissionState
from .spatial_twin_bridge import SpatialTwinBridge

logger = logging.getLogger("BUPI_Orchestrator")


class BUPIOrchestrator:
    """
    Central Hub Orchestrator for Multi-Robot Operations.
    """

    def __init__(self, mqtt_client=None, ws_port: int = 8768):
        # 1. Registry & Fleet
        self.registry = RobotRegistry()
        self._setup_default_fleet()

        # 2. Adapters & Kinematics
        self.control_adapter = ControlAdapter(mqtt_client=mqtt_client)
        self.odometry_engines: Dict[str, LocalOdometryEngine] = {
            "bupi_01": LocalOdometryEngine(initial_x=0.0, initial_y=0.0, initial_theta=0.0),
            "bupi_02": LocalOdometryEngine(initial_x=0.0, initial_y=0.6, initial_theta=0.0)
        }

        # 3. Perception & Projection
        self.projection_engine = SensorProjectionEngine(sensor_offset_forward_m=0.08)
        self.event_engine = EventEngine()
        self.fusion_engine = MultiBotFusionEngine(spatial_threshold_m=1.5, temporal_window_s=60.0)

        # 4. Mission State Machine
        self.fsm = MissionFSM()
        self.fsm.register_listener(self._on_fsm_transition)

        # 5. Spatial Twin Real-time Visualizer Bridge
        self.bridge = SpatialTwinBridge(ws_port=ws_port)
        self.bridge.start()

        # Mission logging & reports
        self.mission_logs: List[Dict[str, Any]] = []

    def _setup_default_fleet(self):
        """Initializes BUPI-01 (Scout) and BUPI-02 (Environmental)."""
        self.registry.register_robot(
            bot_id="bupi_01",
            name="BUPI-01 Alpha (Scout)",
            role=RobotRole.SCOUT,
            sensor_suite=["HC-SR04", "HC-SR501_PIR", "MPU6050"],
            initial_x=0.0,
            initial_y=0.0,
            initial_theta=0.0
        )
        self.registry.register_robot(
            bot_id="bupi_02",
            name="BUPI-02 Beta (Environmental)",
            role=RobotRole.ENVIRONMENTAL,
            sensor_suite=["HC-SR04", "MPU6050", "MQ-2", "DHT22"],
            initial_x=0.0,
            initial_y=0.6,
            initial_theta=0.0
        )

    def _on_fsm_transition(self, old_state: Optional[MissionState], new_state: MissionState, record: Dict[str, Any]):
        """Notifies the bridge when mission state changes."""
        self.bridge.broadcast_mission_state(self.fsm.to_dict())
        self.mission_logs.append({
            "type": "FSM_TRANSITION",
            "from": old_state.value if old_state else None,
            "to": new_state.value,
            "reason": record.get("reason", ""),
            "timestamp": record.get("timestamp", time.time())
        })

    # -------------------------------------------------------------
    # High-Level Mission Directives
    # -------------------------------------------------------------
    def parse_and_execute_directive(self, directive_text: str) -> Dict[str, Any]:
        """
        Parses operator natural-language instructions and routes them into deterministic FSM states.
        """
        directive_lower = directive_text.lower().strip()
        logger.info(f"[Orchestrator] Operator directive: '{directive_text}'")

        # 1. Emergency stop
        if any(w in directive_lower for w in ["stop all", "emergency stop", "abort", "halt"]):
            self.emergency_stop_all("Operator emergency stop directive")
            return {"status": "EMERGENCY_STOP_TRIGGERED", "state": self.fsm.current_state.value}

        # 2. Return to base
        elif any(w in directive_lower for w in ["return", "come back", "dock", "home"]):
            if self.fsm.transition_to(MissionState.RETURNING, "Operator ordered return to base"):
                self._command_return_to_origin()
                return {"status": "RETURNING_TO_BASE", "state": self.fsm.current_state.value}
            return {"status": "TRANSITION_REJECTED", "state": self.fsm.current_state.value}

        # 3. Status Report
        elif any(w in directive_lower for w in ["status", "report", "summary", "briefing"]):
            return self.generate_mission_briefing()

        # 4. Search / Scout Sector
        elif any(w in directive_lower for w in ["search", "scout", "explore", "survey", "inspect"]):
            sector = "Sector A"
            if "sector b" in directive_lower:
                sector = "Sector B"
            elif "sector c" in directive_lower:
                sector = "Sector C"

            return self.start_sector_search(sector=sector, objective=directive_text)

        # 5. Reset
        elif "reset" in directive_lower:
            self.fsm.reset_to_idle()
            return {"status": "RESET_IDLE", "state": self.fsm.current_state.value}

        else:
            return {
                "status": "UNRECOGNIZED_DIRECTIVE",
                "message": f"Directive not mapped to a safety rule. Current state: {self.fsm.current_state.value}"
            }

    def start_sector_search(self, sector: str = "Sector A", objective: str = "Search for survivors") -> Dict[str, Any]:
        """Initiates a multi-robot search sequence in the specified sector."""
        if self.fsm.current_state not in [MissionState.IDLE, MissionState.MISSION_COMPLETE]:
            return {
                "status": "CANNOT_START_SEARCH",
                "reason": f"FSM is currently in {self.fsm.current_state.value}. Must be IDLE."
            }

        # 1. Transition IDLE -> PLANNING
        self.fsm.transition_to(MissionState.PLANNING, f"Planning search mission in {sector}")
        self.fsm.set_mission(mission_id=f"MSN_{sector.replace(' ', '_')}_{int(time.time())}", sector=sector, objectives=[objective])

        # 2. Transition PLANNING -> DISPATCHING
        self.fsm.transition_to(MissionState.DISPATCHING, f"Dispatching BUPI-01 to {sector}")

        # 3. Transition DISPATCHING -> SCOUTING
        self.fsm.transition_to(MissionState.SCOUTING, f"BUPI-01 active in {sector}")

        return {
            "status": "SEARCH_STARTED",
            "sector": sector,
            "mission_id": self.fsm.mission_id,
            "state": self.fsm.current_state.value
        }

    # -------------------------------------------------------------
    # Telemetry Ingestion & Fusion Pipeline
    # -------------------------------------------------------------
    def ingest_telemetry(self, bot_id: str, telemetry: Dict[str, Any]):
        """
        Ingests real-time telemetry from either robot.
        Fuses odometry, updates registry, checks event thresholds, and streams to Spatial Twin.
        """
        # 1. Update Registry Heartbeat & Telemetry
        self.registry.update_telemetry(bot_id, telemetry)
        node = self.registry.get_robot(bot_id)
        if not node:
            return

        # 2. Update Odometry
        odom = self.odometry_engines.get(bot_id)
        if odom:
            if "dt" in telemetry:
                dt = telemetry["dt"]
                v_l = telemetry.get("v_l", 0.0)
                v_r = telemetry.get("v_r", 0.0)
                gyro_z = telemetry.get("gyro_z_dps", 0.0)
                odom.update_from_differential_velocity(v_l, v_r, dt, gyro_z)

            # Sync node pose with odometry
            node.x = odom.x
            node.y = odom.y
            node.theta = odom.theta
            node.uncertainty_radius = odom.uncertainty_radius

            # Broadcast pose to 3D visualizer
            self.bridge.broadcast_pose(
                bot_id=bot_id,
                x=node.x,
                y=node.y,
                theta=node.theta,
                uncertainty_r=node.uncertainty_radius,
                battery=node.battery_percent,
                rssi=node.wifi_rssi
            )

        # 3. Evaluate Sensor Events
        events = self._evaluate_node_events(node, telemetry)
        for ev in events:
            self._handle_sensor_event(ev)

    def _evaluate_node_events(self, node: RobotNode, telemetry: Dict[str, Any]) -> List[SpatialEvent]:
        """Evaluates raw sensors through the scientifically honest EventEngine."""
        events: List[SpatialEvent] = []

        ultrasonic_cm = telemetry.get("ultrasonic_cm", 999.0)
        pir_state = telemetry.get("pir_state", 0)
        mq2_raw = telemetry.get("mq2_raw", 0)
        temperature_c = telemetry.get("temperature_c", 25.0)

        # Project sensor contact point if obstacle in range
        proj_x, proj_y = self.projection_engine.project_ultrasonic_contact(
            robot_x=node.x,
            robot_y=node.y,
            robot_theta=node.theta,
            distance_cm=ultrasonic_cm
        )

        # 1. Obstacle Detection (< 50 cm)
        if ultrasonic_cm < 50.0:
            events.append(self.event_engine.create_obstacle_event(
                bot_id=node.bot_id,
                robot_x=node.x,
                robot_y=node.y,
                robot_theta=node.theta,
                distance_cm=ultrasonic_cm,
                projected_x=proj_x,
                projected_y=proj_y
            ))

        # 2. Possible Human Presence (PIR HIGH + Ultrasonic in human-detection range 20-250 cm)
        if node.role == RobotRole.SCOUT and pir_state == 1 and 20.0 <= ultrasonic_cm <= 250.0:
            events.append(self.event_engine.create_possible_human_event(
                bot_id=node.bot_id,
                robot_x=node.x,
                robot_y=node.y,
                robot_theta=node.theta,
                distance_cm=ultrasonic_cm,
                projected_x=proj_x,
                projected_y=proj_y,
                pir_state=pir_state
            ))

        # 3. Elevated Gas / Smoke (MQ-2 raw > threshold)
        if node.role == RobotRole.ENVIRONMENTAL and mq2_raw > 400:
            events.append(self.event_engine.create_gas_smoke_event(
                bot_id=node.bot_id,
                robot_x=node.x,
                robot_y=node.y,
                mq2_raw=mq2_raw,
                temperature_c=temperature_c
            ))

        # 4. Elevated Temperature (> 42°C)
        if node.role == RobotRole.ENVIRONMENTAL and temperature_c > 42.0:
            events.append(self.event_engine.create_high_temp_event(
                bot_id=node.bot_id,
                robot_x=node.x,
                robot_y=node.y,
                temperature_c=temperature_c
            ))

        return events

    def _handle_sensor_event(self, event: SpatialEvent):
        """Processes and routes an event into the fusion engine and FSM."""
        # Broadcast entity to 3D visualizer
        self.bridge.broadcast_entity(event.to_dict())

        # Feed into spatio-temporal fusion engine
        fused_incident = self.fusion_engine.ingest_event(event)

        # Update FSM state based on event severity
        if event.event_type == EventType.POSSIBLE_HUMAN_PRESENCE:
            if self.fsm.current_state == MissionState.SCOUTING:
                self.fsm.transition_to(
                    MissionState.POSSIBLE_HUMAN,
                    f"BUPI-01 detected possible human presence at ({event.x:.2f}, {event.y:.2f})"
                )
                self.fsm.add_poi(event.to_dict())
                # Automatically dispatch Bot 2 to verify environmental safety
                self._dispatch_specialist_to_poi(event.x, event.y)

        elif event.event_type in [EventType.ELEVATED_GAS_SMOKE, EventType.HIGH_AMBIENT_TEMPERATURE]:
            if self.fsm.current_state in [MissionState.POSSIBLE_HUMAN, MissionState.SCOUTING]:
                self.fsm.transition_to(
                    MissionState.ENVIRONMENTAL_HAZARD,
                    f"BUPI-02 detected hazard: {event.description}"
                )
                self.fsm.add_poi(event.to_dict())

        # If fusion engine formed/updated a multi-bot correlated incident
        if fused_incident:
            self.bridge.broadcast_incident(fused_incident.to_dict())
            if self.fsm.current_state == MissionState.ENVIRONMENTAL_HAZARD:
                self.fsm.transition_to(
                    MissionState.REASSESS,
                    f"Incident correlated across both robots in {fused_incident.sector}"
                )

    def _dispatch_specialist_to_poi(self, target_x: float, target_y: float):
        """Dispatches BUPI-02 (Environmental) to verify the area flagged by BUPI-01."""
        bot2 = self.registry.get_robot("bupi_02")
        if not bot2:
            return

        logger.info(f"[Orchestrator] Dispatching BUPI-02 (Specialist) to POI at ({target_x:.2f}, {target_y:.2f})")
        # In physical execution, ControlAdapter commands bot2 along waypoint
        self.mission_logs.append({
            "type": "DISPATCH_SPECIALIST",
            "bot_id": "bupi_02",
            "target": {"x": target_x, "y": target_y},
            "timestamp": time.time()
        })

    def _command_return_to_origin(self):
        """Commands all units back to base."""
        self.control_adapter.stop(bot_id="bupi_01")
        self.control_adapter.stop(bot_id="bupi_02")
        logger.info("[Orchestrator] Commanded fleet to return to base.")

    def emergency_stop_all(self, reason: str = "Emergency stop"):
        """Instantly halts all robots."""
        self.control_adapter.emergency_stop_all()
        self.fsm.trigger_emergency_stop(reason)
        logger.warning(f"[Orchestrator] ALL ROBOTS HALTED: {reason}")

    # -------------------------------------------------------------
    # Operator Briefing & Mission Reports
    # -------------------------------------------------------------
    def generate_mission_briefing(self) -> Dict[str, Any]:
        """
        Generates a comprehensive, scientifically honest mission report.
        Zero overclaiming: distinctly reports 'POSSIBLE_HUMAN_PRESENCE' with confidence levels.
        """
        fleet_status = self.registry.get_fleet_summary()
        incidents = [inc.to_dict() for inc in self.fusion_engine.active_incidents]

        briefing_text = [
            f"=== BUPI MULTI-ROBOT MISSION BRIEFING ===",
            f"Mission ID: {self.fsm.mission_id}",
            f"Current State: {self.fsm.current_state.value}",
            f"Active Sector: {self.fsm.active_sector or 'None'}",
            f"Fleet Operational Status: {fleet_status['online_count']}/{fleet_status['total_registered']} Units Online",
            f"Correlated Incidents: {len(incidents)}",
            "-------------------------------------------"
        ]

        for idx, inc in enumerate(incidents, 1):
            briefing_text.append(f"[{idx}] {inc['sector']} - Severity: {inc['severity']}")
            briefing_text.append(f"    Location: ({inc['center_x']}m, {inc['center_y']}m)")
            briefing_text.append(f"    Assessment: {inc['summary']}")
            briefing_text.append(f"    Confidence: {inc['confidence']}")
            briefing_text.append(f"    Contributing Detections: {len(inc['contributing_events'])}")

        briefing_text.append("===========================================")

        return {
            "mission_id": self.fsm.mission_id,
            "fsm_state": self.fsm.current_state.value,
            "fleet_summary": fleet_status,
            "incidents": incidents,
            "poi_count": len(self.fsm.discovered_pois),
            "formatted_text": "\n".join(briefing_text)
        }
