"""
Swarm Coordinator for BUPI Multi-Robot System
Coordinates collaborative interaction between Bot 1 (Scout) and Bot 2 (Environmental Specialist).
"""

import time
import json
import threading
from typing import Dict, Any, Optional, List

try:
    import paho.mqtt.publish as publish
    import paho.mqtt.client as mqtt
except ImportError:
    publish = None
    mqtt = None

class SwarmCoordinator:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(SwarmCoordinator, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, broker_host: str = "localhost"):
        if self._initialized:
            return
        self._initialized = True
        self.broker_host = broker_host
        self.state_lock = threading.Lock()

        self.swarm_state = {
            "bupi_01": {
                "name": "BUPI_01_SCOUT",
                "role": "Scout / Spatial & Motion Recon",
                "status": "ONLINE",
                "distance_cm": 200.0,
                "pir": 0,
                "heading": 0.0,
                "target_detected": False,
                "last_active": time.time(),
                "suppressed": False
            },
            "bupi_02": {
                "name": "BUPI_02_SPECIALIST",
                "role": "Environmental & Hazard Specialist",
                "status": "OFFLINE",
                "gas_ppm": 0.0,
                "temp_c": 0.0,
                "humidity_pct": 0.0,
                "distance_cm": 200.0,
                "heading": 0.0,
                "gas_alert": "UNKNOWN",
                "last_active": 0.0,
                "suppressed": False
            }
        }

        self.event_history: List[Dict[str, Any]] = []
        self._sub_client = None
        self._start_mqtt_listener()

    def _start_mqtt_listener(self):
        if not mqtt:
            return
        try:
            self._sub_client = mqtt.Client(client_id=f"bupi_swarm_coord_{int(time.time())}")
            self._sub_client.on_message = self._on_mqtt_message
            self._sub_client.connect_async(self.broker_host, 1883, 60)
            self._sub_client.subscribe("bupi/+/sensors/#")
            self._sub_client.subscribe("bupi/swarm/#")
            self._sub_client.subscribe("bupi/sensors/#")
            self._sub_client.loop_start()
        except Exception as e:
            print(f"[Swarm Coordinator Warning] MQTT subscriber startup failed: {e}", flush=True)

    def _on_mqtt_message(self, client, userdata, message):
        try:
            topic = message.topic
            payload = message.payload.decode("utf-8", errors="ignore")
            with self.state_lock:
                # Update Bot 2 Environmental Telemetry
                if "mq2" in topic or "bupi_02/sensors/mq2" in topic:
                    val = float(payload)
                    self.swarm_state["bupi_02"]["gas_ppm"] = val
                    if val > 350.0:
                        self.swarm_state["bupi_02"]["gas_alert"] = "CRITICAL"
                        self._trigger_hazard_evacuation("bupi_02", val)
                    elif val > 200.0:
                        self.swarm_state["bupi_02"]["gas_alert"] = "WARNING"
                    else:
                        self.swarm_state["bupi_02"]["gas_alert"] = "SAFE"
                    self.swarm_state["bupi_02"]["last_active"] = time.time()

                elif "temp" in topic or "temperature" in topic:
                    val = float(payload)
                    self.swarm_state["bupi_02"]["temp_c"] = val
                    self.swarm_state["bupi_02"]["last_active"] = time.time()

                elif "humidity" in topic:
                    val = float(payload)
                    self.swarm_state["bupi_02"]["humidity_pct"] = val
                    self.swarm_state["bupi_02"]["last_active"] = time.time()

                # Update Bot 1 Scout Telemetry
                elif "pir" in topic:
                    self.swarm_state["bupi_01"]["pir"] = int(float(payload))
                    self.swarm_state["bupi_01"]["last_active"] = time.time()

                elif "bupi_01" in topic and "distance" in topic:
                    self.swarm_state["bupi_01"]["distance_cm"] = float(payload)
                    self.swarm_state["bupi_01"]["last_active"] = time.time()

                elif "bupi_02" in topic and "distance" in topic:
                    self.swarm_state["bupi_02"]["distance_cm"] = float(payload)
                    self.swarm_state["bupi_02"]["last_active"] = time.time()

                elif "swarm/events" in topic:
                    data = json.loads(payload)
                    self.event_history.append(data)
                    if len(self.event_history) > 100:
                        self.event_history.pop(0)

        except Exception:
            pass

    def _trigger_hazard_evacuation(self, bot_id: str, gas_ppm: float):
        """Dispatches immediate swarm hazard alert to protect both bots and alert humans."""
        event = {
            "type": "HAZARD_ALERT",
            "source_bot": bot_id,
            "gas_ppm": gas_ppm,
            "timestamp": time.time(),
            "action": "HALT_AND_EVACUATE"
        }
        self.publish_swarm_event("bupi/swarm/events", event)
        # Immediately halt BOTH bots to prevent entering toxic gas plume
        if publish:
            try:
                publish.single("bupi/actuators/motors/cmd", "stop", hostname=self.broker_host)
                publish.single("bupi/actuators/motors/cmd/json", json.dumps({"action": "stop", "bot_id": "bupi_01", "robot_id": "bupi_01"}), hostname=self.broker_host)
                publish.single("bupi/v1/bot2/actuators/motors/cmd", "stop", hostname=self.broker_host)
                publish.single("bupi/v1/bot2/actuators/motors/cmd/json", json.dumps({"action": "stop", "bot_id": "bupi_02", "robot_id": "bupi_02"}), hostname=self.broker_host)
                # Flash relay on Bot 1 if available as warning alarm
                publish.single("bupi/hardware/relay_1/set", "ON", hostname=self.broker_host)
            except Exception:
                pass
        print(f"[Swarm Alert] Toxic gas detected ({gas_ppm:.1f} ppm) by {bot_id}! Swarm hazard halt triggered.", flush=True)

    def publish_swarm_event(self, topic: str, data: Dict[str, Any]):
        if publish:
            try:
                publish.single(topic, json.dumps(data), hostname=self.broker_host)
            except Exception as e:
                print(f"[Swarm Coordinator Error] Failed to publish event: {e}", flush=True)

    def set_bot_suppressed(self, bot_id: str, suppressed: bool):
        with self.state_lock:
            key = "bupi_02" if "2" in bot_id else "bupi_01"
            if key in self.swarm_state:
                self.swarm_state[key]["suppressed"] = suppressed
                print(f"[Swarm Coordinator] {key.upper()} suppression state set to: {suppressed}", flush=True)

    def get_swarm_state(self) -> Dict[str, Any]:
        with self.state_lock:
            return dict(self.swarm_state)

    def coordinate_tandem_reading(self) -> Dict[str, Any]:
        """
        Coordinates a joint snapshot where Bot 1 provides spatial/presence data
        and Bot 2 provides environmental data if live.
        """
        now = time.time()
        with self.state_lock:
            s1 = dict(self.swarm_state["bupi_01"])
            s2 = dict(self.swarm_state["bupi_02"])

        b2_live = (s2.get("last_active", 0.0) > 0) and ((now - s2.get("last_active", 0.0)) < 15.0)

        env_dict = None
        if b2_live:
            env_dict = {
                "bot_id": "bupi_02",
                "is_live": True,
                "gas_ppm": s2.get("gas_ppm", 0.0),
                "gas_status": s2.get("gas_alert", "SAFE"),
                "temperature_c": s2.get("temp_c", 25.0),
                "humidity_pct": s2.get("humidity_pct", 50.0),
                "air_quality": "SAFE" if s2.get("gas_ppm", 0.0) < 200.0 else "HAZARD"
            }

        return {
            "collaborative_status": "SYNCHRONIZED" if b2_live else "BOT2_OFFLINE",
            "scout": {
                "bot_id": "bupi_01",
                "obstacle_distance_cm": s1.get("distance_cm", 200.0),
                "motion_detected": bool(s1.get("pir", 0)),
                "heading_deg": s1.get("heading", 0.0)
            },
            "environmental": env_dict,
            "timestamp": now
        }

swarm_coordinator = SwarmCoordinator()
