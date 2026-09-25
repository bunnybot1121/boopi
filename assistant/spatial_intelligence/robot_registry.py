"""
BUPI Robot Registry & Multi-Robot Identity Manager
==================================================
Manages identity, operational roles, starting offsets, communication status,
and sensor capabilities for BUPI-01 (Scout) and BUPI-02 (Environmental).
Part of BUPI Spatial Intelligence Engine (SIH 2026 / SIH26218).
"""

import time
import threading
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field
from enum import Enum


class RobotRole(str, Enum):
    SCOUT = "scout"
    ENVIRONMENTAL = "environmental"
    SPECIALIST = "specialist"


@dataclass
class Pose:
    x_m: float = 0.0
    y_m: float = 0.0
    heading_deg: float = 0.0
    uncertainty_radius_m: float = 0.05

    def to_dict(self) -> Dict[str, float]:
        return {
            "x_m": round(self.x_m, 3),
            "y_m": round(self.y_m, 3),
            "heading_deg": round(self.heading_deg, 1),
            "uncertainty_radius_m": round(self.uncertainty_radius_m, 3)
        }


@dataclass
class RobotNode:
    bot_id: str
    name: str
    role: Union[RobotRole, str]
    sensor_suite: List[str] = field(default_factory=list)
    x: float = 0.0
    y: float = 0.0
    theta: float = 0.0
    uncertainty_radius: float = 0.05
    status: str = "OFFLINE"
    last_heartbeat: float = 0.0
    wifi_rssi: int = -60
    battery_v: float = 4.2
    battery_percent: float = 100.0
    active_mission_id: Optional[str] = None
    latest_sensors: Dict[str, Any] = field(default_factory=dict)
    initial_pose: Optional[Pose] = None
    current_pose: Optional[Pose] = None

    def __post_init__(self):
        if self.initial_pose is None:
            self.initial_pose = Pose(x_m=self.x, y_m=self.y, heading_deg=self.theta, uncertainty_radius_m=self.uncertainty_radius)
        if self.current_pose is None:
            self.current_pose = Pose(x_m=self.x, y_m=self.y, heading_deg=self.theta, uncertainty_radius_m=self.uncertainty_radius)

    @property
    def robot_id(self) -> str:
        return self.bot_id

    @property
    def capabilities(self) -> List[str]:
        return self.sensor_suite

    def __getitem__(self, item):
        d = self.to_dict()
        return d[item]

    def get(self, key, default=None):
        return self.to_dict().get(key, default)

    def to_dict(self) -> Dict[str, Any]:
        role_str = self.role.value if hasattr(self.role, "value") else str(self.role)
        return {
            "robot_id": self.bot_id,
            "bot_id": self.bot_id,
            "name": self.name,
            "role": role_str,
            "sensor_suite": self.sensor_suite,
            "sensors": self.sensor_suite,
            "capabilities": self.sensor_suite,
            "x": round(self.x, 3),
            "y": round(self.y, 3),
            "theta": round(self.theta, 1),
            "uncertainty_radius": round(self.uncertainty_radius, 3),
            "pose": {
                "x": round(self.x, 3),
                "y": round(self.y, 3),
                "theta": round(self.theta, 1)
            },
            "initial_pose": self.initial_pose.to_dict() if self.initial_pose else None,
            "current_pose": {
                "x_m": round(self.x, 3),
                "y_m": round(self.y, 3),
                "heading_deg": round(self.theta, 1),
                "uncertainty_radius_m": round(self.uncertainty_radius, 3)
            },
            "status": self.status,
            "last_heartbeat": round(self.last_heartbeat, 2),
            "wifi_rssi": self.wifi_rssi,
            "battery_v": round(self.battery_v, 2),
            "battery_percent": round(self.battery_percent, 1),
            "active_mission_id": self.active_mission_id,
            "latest_sensors": self.latest_sensors
        }


# Backward compatibility alias
RobotIdentity = RobotNode


class RobotRegistry:
    def __init__(self, heartbeat_timeout_s: float = 5.0):
        self._lock = threading.Lock()
        self.heartbeat_timeout_s = heartbeat_timeout_s
        self.robots: Dict[str, RobotNode] = {}
        self._init_default_fleet()

    def _init_default_fleet(self):
        """Initializes the standard SIH 2-robot disaster scouting fleet."""
        # BUPI-01: Scout (PIR, Ultrasonic, MPU6050)
        self.register_robot(
            bot_id="bupi_01",
            name="BUPI-01 Alpha (Scout)",
            role=RobotRole.SCOUT,
            sensor_suite=["HC-SR04", "HC-SR501_PIR", "MPU6050", "DIFFERENTIAL_DRIVE"],
            initial_x=0.0,
            initial_y=0.0,
            initial_theta=0.0
        )

        # BUPI-02: Environmental Specialist (MQ-2, DHT22, Ultrasonic, MPU6050)
        # Starting offset 0.6m along Y axis from Origin
        self.register_robot(
            bot_id="bupi_02",
            name="BUPI-02 Beta (Environmental)",
            role=RobotRole.ENVIRONMENTAL,
            sensor_suite=["MQ-2_GAS", "DHT22_CLIMATE", "HC-SR04", "MPU6050", "DIFFERENTIAL_DRIVE"],
            initial_x=0.0,
            initial_y=0.6,
            initial_theta=0.0
        )

    def register_robot(
        self,
        bot_id: str,
        name_or_role: Union[RobotRole, str] = RobotRole.SCOUT,
        role_or_pose: Optional[Union[RobotRole, str, tuple, list]] = None,
        sensor_suite: Optional[List[str]] = None,
        initial_x: float = 0.0,
        initial_y: float = 0.0,
        initial_theta: float = 0.0,
        role: Optional[Union[RobotRole, str]] = None,
        name: Optional[str] = None
    ) -> RobotNode:
        with self._lock:
            # Detect whether 2nd arg was role or name
            if isinstance(name_or_role, RobotRole) or str(name_or_role).lower() in ["scout", "environmental", "specialist"]:
                actual_role = name_or_role
                actual_name = name or f"BUPI-{bot_id}"
                if isinstance(role_or_pose, (tuple, list)) and len(role_or_pose) >= 2:
                    initial_x = float(role_or_pose[0])
                    initial_y = float(role_or_pose[1])
                    initial_theta = float(role_or_pose[2]) if len(role_or_pose) > 2 else 0.0
            else:
                actual_name = str(name_or_role)
                actual_role = role or role_or_pose or RobotRole.SCOUT

            bot = RobotNode(
                bot_id=bot_id,
                name=actual_name,
                role=actual_role,
                sensor_suite=sensor_suite or [],
                x=initial_x,
                y=initial_y,
                theta=initial_theta,
                uncertainty_radius=0.05,
                status="OFFLINE"
            )
            self.robots[bot_id] = bot
            return bot

    def update_telemetry(self, robot_id: str, telemetry: Dict[str, Any]):
        with self._lock:
            if robot_id in self.robots:
                bot = self.robots[robot_id]
                bot.last_heartbeat = time.time()
                bot.status = "ONLINE"
                if "wifi_rssi" in telemetry:
                    bot.wifi_rssi = int(telemetry["wifi_rssi"])
                if "battery_percent" in telemetry:
                    bot.battery_percent = float(telemetry["battery_percent"])
                if "battery_v" in telemetry:
                    bot.battery_v = float(telemetry["battery_v"])
                bot.latest_sensors.update(telemetry)

    def set_initial_pose(self, robot_id: str, x_m: float, y_m: float, heading_deg: float):
        with self._lock:
            if robot_id in self.robots:
                bot = self.robots[robot_id]
                bot.x = x_m
                bot.y = y_m
                bot.theta = heading_deg % 360.0
                bot.initial_pose = Pose(x_m=x_m, y_m=y_m, heading_deg=heading_deg, uncertainty_radius_m=0.05)
                bot.current_pose = Pose(x_m=x_m, y_m=y_m, heading_deg=heading_deg, uncertainty_radius_m=0.05)

    def update_heartbeat(self, robot_id: str, wifi_rssi: Optional[int] = None, battery_v: Optional[float] = None):
        with self._lock:
            if robot_id in self.robots:
                bot = self.robots[robot_id]
                bot.last_heartbeat = time.time()
                bot.status = "ONLINE"
                if wifi_rssi is not None:
                    bot.wifi_rssi = wifi_rssi
                if battery_v is not None:
                    bot.battery_v = battery_v

    def update_pose(self, robot_id: str, x_m: float, y_m: float, heading_deg: float, uncertainty_m: float = 0.05):
        with self._lock:
            if robot_id in self.robots:
                bot = self.robots[robot_id]
                bot.x = x_m
                bot.y = y_m
                bot.theta = heading_deg % 360.0
                bot.uncertainty_radius = uncertainty_m
                if bot.current_pose:
                    bot.current_pose.x_m = x_m
                    bot.current_pose.y_m = y_m
                    bot.current_pose.heading_deg = heading_deg % 360.0
                    bot.current_pose.uncertainty_radius_m = uncertainty_m
                bot.last_heartbeat = time.time()
                bot.status = "ONLINE"

    def update_sensors(self, robot_id: str, sensor_dict: Dict[str, Any]):
        with self._lock:
            if robot_id in self.robots:
                self.robots[robot_id].latest_sensors.update(sensor_dict)
                self.robots[robot_id].last_heartbeat = time.time()
                self.robots[robot_id].status = "ONLINE"

    def check_timeouts(self) -> List[str]:
        """Checks for missed heartbeats and marks robots as OFFLINE."""
        now = time.time()
        offline_bots = []
        with self._lock:
            for bot_id, bot in self.robots.items():
                if bot.status == "ONLINE" and (now - bot.last_heartbeat) > self.heartbeat_timeout_s:
                    bot.status = "OFFLINE"
                    offline_bots.append(bot_id)
        return offline_bots

    def get_robot(self, robot_id: str) -> Optional[RobotNode]:
        with self._lock:
            return self.robots.get(robot_id)

    def get_all_robots(self) -> List[Dict[str, Any]]:
        self.check_timeouts()
        with self._lock:
            return [b.to_dict() for b in self.robots.values()]

    def get_fleet_summary(self) -> Dict[str, Any]:
        with self._lock:
            total = len(self.robots)
            online = sum(1 for b in self.robots.values() if b.status == "ONLINE")
            return {
                "total_registered": total,
                "online_count": online,
                "robots": [b.to_dict() for b in self.robots.values()]
            }


_global_robot_registry: Optional[RobotRegistry] = None

def get_robot_registry() -> RobotRegistry:
    """Returns the singleton RobotRegistry instance."""
    global _global_robot_registry
    if _global_robot_registry is None:
        _global_robot_registry = RobotRegistry()
    return _global_robot_registry

# Module-level singleton instance for convenient direct import
robot_registry = get_robot_registry()
