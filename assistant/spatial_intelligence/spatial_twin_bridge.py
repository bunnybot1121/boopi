"""
BUPI Spatial Twin WebSocket & MQTT Bridge
Part of BUPI Spatial Intelligence Engine (SIH 2026 / SIH26218)

Provides a real-time bridge streaming multi-robot poses, sensor projections,
fused incidents, and mission state machine updates to the 2.5D/3D Tactical Twin
(Three.js / BWE visualizer) and desktop dashboards.
"""

import asyncio
import json
import logging
import threading
import time
from typing import Dict, Any, List, Set, Optional

logger = logging.getLogger("BUPI_SpatialTwinBridge")


class SpatialTwinBridge:
    """
    Asynchronous WebSocket and MQTT bridge for the BUPI Multi-Robot Spatial Twin.
    """

    def __init__(self, ws_host: str = "0.0.0.0", ws_port: int = 8768, mqtt_broker: str = "127.0.0.1", mqtt_port: int = 1883):
        self.ws_host = ws_host
        self.ws_port = ws_port
        self.mqtt_broker = mqtt_broker
        self.mqtt_port = mqtt_port

        self._connected_ws_clients: Set[Any] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_server = None
        self._thread: Optional[threading.Thread] = None
        self._is_running = False

        self._mqtt_client = None
        self._mqtt_connected = False

        # Cache of latest telemetry
        self.latest_poses: Dict[str, Dict[str, Any]] = {}
        self.active_entities: List[Dict[str, Any]] = []
        self.active_incidents: List[Dict[str, Any]] = []
        self.latest_mission_state: Dict[str, Any] = {}

    # -------------------------------------------------------------
    # WebSocket Server Lifecycle
    # -------------------------------------------------------------
    async def _handle_ws_client(self, websocket):
        """Handle incoming WebSocket connections from visualizer / UI."""
        self._connected_ws_clients.add(websocket)
        logger.info(f"[SpatialBridge] Visualizer connected from {getattr(websocket, 'remote_address', 'unknown')}")

        # Send initial state synchronization dump
        try:
            init_sync = {
                "type": "spatial.initial_sync",
                "timestamp": time.time(),
                "poses": self.latest_poses,
                "entities": self.active_entities,
                "incidents": self.active_incidents,
                "mission_state": self.latest_mission_state
            }
            await websocket.send(json.dumps(init_sync))

            async for message in websocket:
                try:
                    data = json.loads(message)
                    self._handle_incoming_client_message(websocket, data)
                except Exception as e:
                    logger.debug(f"[SpatialBridge] Non-JSON or malformed client message: {e}")
        except Exception:
            pass
        finally:
            self._connected_ws_clients.discard(websocket)
            logger.info(f"[SpatialBridge] Visualizer disconnected: {getattr(websocket, 'remote_address', 'unknown')}")

    def _handle_incoming_client_message(self, websocket, data: Dict[str, Any]):
        """Handles operator or visualizer commands sent via WebSocket."""
        msg_type = data.get("type", "")
        if msg_type == "ping":
            asyncio.run_coroutine_threadsafe(
                websocket.send(json.dumps({"type": "pong", "timestamp": time.time()})),
                self._loop
            )
        elif msg_type == "request_sync":
            asyncio.run_coroutine_threadsafe(
                websocket.send(json.dumps({
                    "type": "spatial.initial_sync",
                    "timestamp": time.time(),
                    "poses": self.latest_poses,
                    "entities": self.active_entities,
                    "incidents": self.active_incidents,
                    "mission_state": self.latest_mission_state
                })),
                self._loop
            )

    async def _start_ws_server(self):
        try:
            import websockets
            self._ws_server = await websockets.serve(self._handle_ws_client, self.ws_host, self.ws_port)
            logger.info(f"[SpatialBridge] WebSocket server active on ws://{self.ws_host}:{self.ws_port}")
            await asyncio.Future()  # run forever
        except Exception as e:
            logger.error(f"[SpatialBridge] WebSocket server error: {e}")

    # -------------------------------------------------------------
    # MQTT Integration
    # -------------------------------------------------------------
    def _init_mqtt(self):
        try:
            import paho.mqtt.client as mqtt
            import random
            client_id = f"BUPI_SpatialTwin_{random.randint(1000, 9999)}"
            self._mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)

            def on_connect(client, userdata, flags, reason_code, properties=None):
                logger.info(f"[SpatialBridge] Connected to MQTT broker ({self.mqtt_broker}:{self.mqtt_port})")
                self._mqtt_connected = True
                # Subscribe to relevant raw telemetry
                client.subscribe("bupi/sensors/#")
                client.subscribe("bupi/v1/#")

            def on_disconnect(client, userdata, flags, reason_code, properties=None):
                self._mqtt_connected = False
                logger.warning(f"[SpatialBridge] MQTT disconnected: {reason_code}")

            self._mqtt_client.on_connect = on_connect
            self._mqtt_client.on_disconnect = on_disconnect
            self._mqtt_client.connect(self.mqtt_broker, self.mqtt_port, 60)
            self._mqtt_client.loop_start()
        except Exception as e:
            logger.warning(f"[SpatialBridge] MQTT connection skipped/unavailable: {e}")

    # -------------------------------------------------------------
    # Public Broadcast Methods
    # -------------------------------------------------------------
    def broadcast_pose(self, bot_id: str, x: float, y: float, theta: float, uncertainty_r: float = 0.05, battery: float = 100.0, rssi: int = -50):
        """Broadcast real-time metric pose update for a robot."""
        payload = {
            "type": "spatial.bot_pose",
            "bot_id": bot_id,
            "x": round(x, 3),
            "y": round(y, 3),
            "theta": round(theta, 3),
            "uncertainty_r": round(uncertainty_r, 3),
            "battery": round(battery, 1),
            "rssi": int(rssi),
            "timestamp": time.time()
        }
        self.latest_poses[bot_id] = payload
        self._dispatch_json(payload, mqtt_topic=f"bupi/spatial/poses/{bot_id}")

    def broadcast_entity(self, entity_data: Dict[str, Any]):
        """Broadcast placed spatial entity (obstacle, heat signature, gas reading, marker)."""
        payload = {
            "type": "spatial.entity_placed",
            "entity": entity_data,
            "timestamp": time.time()
        }
        # Keep track of recent entities (limit to 100)
        self.active_entities.append(entity_data)
        if len(self.active_entities) > 100:
            self.active_entities.pop(0)

        self._dispatch_json(payload, mqtt_topic="bupi/spatial/entities")

    def broadcast_incident(self, incident_data: Dict[str, Any]):
        """Broadcast fused multi-robot incident report."""
        payload = {
            "type": "spatial.incident_fused",
            "incident": incident_data,
            "timestamp": time.time()
        }
        self.active_incidents.append(incident_data)
        if len(self.active_incidents) > 50:
            self.active_incidents.pop(0)

        self._dispatch_json(payload, mqtt_topic="bupi/spatial/incidents")

    def broadcast_mission_state(self, mission_state: Dict[str, Any]):
        """Broadcast FSM state change."""
        payload = {
            "type": "spatial.mission_state",
            "mission": mission_state,
            "timestamp": time.time()
        }
        self.latest_mission_state = mission_state
        self._dispatch_json(payload, mqtt_topic="bupi/spatial/mission")

    def _dispatch_json(self, payload: Dict[str, Any], mqtt_topic: Optional[str] = None):
        """Dispatches JSON string to all WebSocket clients and MQTT if available."""
        msg_str = json.dumps(payload)

        # 1. Send to WebSocket clients
        if self._loop and self._loop.is_running() and self._connected_ws_clients:
            for client in list(self._connected_ws_clients):
                try:
                    asyncio.run_coroutine_threadsafe(client.send(msg_str), self._loop)
                except Exception:
                    pass

        # 2. Publish to MQTT
        if self._mqtt_client and self._mqtt_connected and mqtt_topic:
            try:
                self._mqtt_client.publish(mqtt_topic, msg_str)
            except Exception:
                pass

    # -------------------------------------------------------------
    # Lifecycle Controls
    # -------------------------------------------------------------
    def start(self):
        """Starts the bridge in a background daemon thread."""
        if self._is_running:
            return

        self._is_running = True
        self._init_mqtt()

        def run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._start_ws_server())

        self._thread = threading.Thread(target=run_loop, daemon=True, name="BUPI_SpatialTwinBridge")
        self._thread.start()
        logger.info("[SpatialBridge] Bridge thread started.")

    def stop(self):
        """Stops bridge and disconnects clients."""
        self._is_running = False
        if self._mqtt_client:
            try:
                self._mqtt_client.loop_stop()
                self._mqtt_client.disconnect()
            except Exception:
                pass
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        logger.info("[SpatialBridge] Bridge stopped.")
