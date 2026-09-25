"""
BUPI Control Adapter Layer
==========================
Translates high-level mission directives into commands consumed by the existing,
frozen BUPI motor control and firmware interface.

ABSOLUTE INTEGRITY GUARANTEE:
- Does NOT touch TB6612 motor driver logic.
- Does NOT touch ESP32 C++ firmware.
- Uses existing MQTT topics: 'bupi/actuators/motors/cmd/json' (Bot 1)
  and 'bupi/v1/bot2/actuators/motors/cmd/json' (Bot 2).
"""

import time
import json
import logging
from typing import Dict, Any, Optional

try:
    import paho.mqtt.publish as publish
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

logger = logging.getLogger("BUPI_ControlAdapter")

class BupiControlAdapter:
    def __init__(self, broker_host: str = "localhost", broker_port: int = 1883, mqtt_client: Any = None):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.mqtt_client = mqtt_client
        self.last_command_time: Dict[str, float] = {}
        self.min_command_interval_s = 0.20  # Prevent command flooding (>5Hz safe limit)

        # Standard topics
        self.topics = {
            "bupi_01": "bupi/actuators/motors/cmd/json",  # Existing frozen topic
            "bupi_02": "bupi/v1/bot2/actuators/motors/cmd/json"  # Namespaced for Bot 2
        }

    def _publish_mqtt(self, topic: str, payload_dict: Dict[str, Any]) -> bool:
        payload_str = json.dumps(payload_dict)
        if self.mqtt_client:
            try:
                self.mqtt_client.publish(topic, payload_str)
                logger.info(f"[ControlAdapter -> MQTT Client] {topic} <= {payload_str}")
                return True
            except Exception as e:
                logger.warning(f"[ControlAdapter] mqtt_client publish error: {e}, falling back to publish.single")

        if not MQTT_AVAILABLE:
            logger.warning(f"[ControlAdapter MOCK] MQTT not available. Would publish to '{topic}': {payload_str}")
            return True

        try:
            publish.single(
                topic,
                payload=payload_str,
                hostname=self.broker_host,
                port=self.broker_port,
                qos=1
            )
            logger.info(f"[ControlAdapter -> MQTT] {topic} <= {payload_str}")
            return True
        except Exception as e:
            logger.error(f"[ControlAdapter ERROR] Failed to publish to {topic}: {e}")
            return False

    def _rate_limit(self, robot_id: str) -> bool:
        now = time.time()
        last_t = self.last_command_time.get(robot_id, 0.0)
        if (now - last_t) < self.min_command_interval_s:
            return False
        self.last_command_time[robot_id] = now
        return True

    def move_forward(self, robot_id: Optional[str] = None, speed: int = 255, duration_s: float = 1.5, bot_id: Optional[str] = None) -> bool:
        """Commands robot forward using existing supported action."""
        target_id = bot_id or robot_id or "bupi_01"
        if not self._rate_limit(target_id):
            return False
        topic = self.topics.get(target_id, self.topics["bupi_01"])
        payload = {
            "action": "forward",
            "speed": max(50, min(255, speed)),
            "duration_ms": int(duration_s * 1000),
            "bot_id": target_id,
            "robot_id": target_id
        }
        return self._publish_mqtt(topic, payload)

    def move_backward(self, robot_id: Optional[str] = None, speed: int = 255, duration_s: float = 1.5, bot_id: Optional[str] = None) -> bool:
        """Commands robot backward using existing supported action."""
        target_id = bot_id or robot_id or "bupi_01"
        if not self._rate_limit(target_id):
            return False
        topic = self.topics.get(target_id, self.topics["bupi_01"])
        payload = {
            "action": "reverse",
            "speed": max(50, min(255, speed)),
            "duration_ms": int(duration_s * 1000),
            "bot_id": target_id,
            "robot_id": target_id
        }
        return self._publish_mqtt(topic, payload)

    def rotate_degrees(self, robot_id: Optional[str] = None, degrees: float = 90.0, speed: int = 255, bot_id: Optional[str] = None) -> bool:
        """Rotates using closed-loop MPU6050 gyro feedback supported by firmware."""
        target_id = bot_id or robot_id or "bupi_01"
        if not self._rate_limit(target_id):
            return False
        topic = self.topics.get(target_id, self.topics["bupi_01"])
        payload = {
            "action": "turn_by",
            "degrees": float(degrees),
            "speed": max(100, min(255, speed)),
            "bot_id": target_id,
            "robot_id": target_id
        }
        return self._publish_mqtt(topic, payload)

    def turn_left(self, robot_id: Optional[str] = None, speed: int = 255, duration_s: float = 0.6, bot_id: Optional[str] = None) -> bool:
        target_id = bot_id or robot_id or "bupi_01"
        if not self._rate_limit(target_id):
            return False
        topic = self.topics.get(target_id, self.topics["bupi_01"])
        payload = {
            "action": "left",
            "speed": max(50, min(255, speed)),
            "duration_ms": int(duration_s * 1000),
            "bot_id": target_id,
            "robot_id": target_id
        }
        return self._publish_mqtt(topic, payload)

    def turn_right(self, robot_id: Optional[str] = None, speed: int = 255, duration_s: float = 0.6, bot_id: Optional[str] = None) -> bool:
        target_id = bot_id or robot_id or "bupi_01"
        if not self._rate_limit(target_id):
            return False
        topic = self.topics.get(target_id, self.topics["bupi_01"])
        payload = {
            "action": "right",
            "speed": max(50, min(255, speed)),
            "duration_ms": int(duration_s * 1000),
            "bot_id": target_id,
            "robot_id": target_id
        }
        return self._publish_mqtt(topic, payload)

    def stop(self, robot_id: Optional[str] = None, bot_id: Optional[str] = None) -> bool:
        """Unconditional stop for specified robot."""
        target_id = bot_id or robot_id or "bupi_01"
        topic = self.topics.get(target_id, self.topics["bupi_01"])
        payload = {"action": "stop", "speed": 0, "bot_id": target_id, "robot_id": target_id}
        return self._publish_mqtt(topic, payload)

    def emergency_stop_all(self) -> bool:
        """Broadcasts immediate emergency stop to all robot nodes."""
        success = True
        for b_id in self.topics:
            if not self.stop(robot_id=b_id):
                success = False
        return success


# Backward and cross-module compatibility alias
ControlAdapter = BupiControlAdapter

