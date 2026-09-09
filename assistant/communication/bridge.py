"""
BUPI Bridge & 2D Physics Arena Simulation (Section 12, 13)
==========================================================
Provides dual-mode interfacing:
1. Virtual 2D Room Arena Simulation:
   - High-fidelity raycasted Ultrasonic distance measurement
   - PIR 100-degree field-of-view motion detector for warm entities
   - Differential drive kinematics (position, heading, velocity)
   - Real-time drag-and-drop targets and obstacles
2. Physical ESP32 Hardware Bridge:
   - Real-time communication via WebSocket / Serial / MQTT
"""

import time
import math
import json
import asyncio
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from motion.differential_drive import MovementAction

@dataclass
class HumanEntity:
    id: str
    x: float  # cm
    y: float  # cm
    is_warm: bool = True
    is_moving: bool = True
    speed: float = 1.2
    heading: float = 0.0

@dataclass
class ObstacleEntity:
    id: str
    x: float  # cm
    y: float  # cm
    width: float = 40.0
    height: float = 40.0

class ArenaSimulation:
    def __init__(self, room_width_cm: float = 500.0, room_height_cm: float = 400.0):
        self.width = room_width_cm
        self.height = room_height_cm
        
        # Robot pose
        self.robot_x: float = 100.0
        self.robot_y: float = 200.0
        self.robot_theta_deg: float = 0.0  # 0 deg = facing East (+x)
        self.robot_radius_cm: float = 8.0
        
        # Simulated sensor parameters
        self.ultrasonic_fov_deg: float = 25.0
        self.ultrasonic_max_range_cm: float = 350.0
        self.pir_fov_deg: float = 100.0
        self.pir_max_range_cm: float = 250.0
        
        # Current simulated raw readings
        self.raw_pir: int = 0
        self.raw_distance_cm: float = 125.0
        self.ax: float = 0.0
        self.ay: float = 0.0
        self.az: float = 1.0
        self.gx: float = 0.0
        self.gy: float = 0.0
        self.gz: float = 0.0

        # Entities in arena
        self.humans: List[HumanEntity] = [
            HumanEntity(id="person_1", x=340.0, y=200.0, is_warm=True, is_moving=True)
        ]
        self.obstacles: List[ObstacleEntity] = [
            ObstacleEntity(id="box_1", x=220.0, y=80.0, width=40.0, height=40.0),
            ObstacleEntity(id="pillar_1", x=250.0, y=300.0, width=30.0, height=30.0)
        ]

        self.last_step_time = time.time()

    def update_physics(self, motor_action: str, speed_percent: int, dt: float):
        """
        Updates robot kinematics based on active motor action.
        """
        linear_vel = 0.0
        angular_vel_deg_s = 0.0

        max_speed = 22.0  # cm/s
        speed_factor = (speed_percent / 100.0) * max_speed

        if motor_action == "MOVE_FORWARD":
            linear_vel = speed_factor
            self.ax = 0.12 * (speed_percent / 100.0)
            self.gz = 0.0
        elif motor_action == "MOVE_BACKWARD":
            linear_vel = -speed_factor
            self.ax = -0.12 * (speed_percent / 100.0)
            self.gz = 0.0
        elif motor_action == "TURN_LEFT":
            angular_vel_deg_s = -65.0 * (speed_percent / 100.0)
            self.gz = angular_vel_deg_s
            self.ax = 0.0
        elif motor_action == "TURN_RIGHT":
            angular_vel_deg_s = 65.0 * (speed_percent / 100.0)
            self.gz = angular_vel_deg_s
            self.ax = 0.0
        else:  # STOP
            linear_vel = 0.0
            angular_vel_deg_s = 0.0
            self.ax = 0.0
            self.gz = 0.0

        # Update heading
        self.robot_theta_deg = (self.robot_theta_deg + angular_vel_deg_s * dt) % 360.0
        rad = math.radians(self.robot_theta_deg)

        # Update position
        new_x = self.robot_x + linear_vel * math.cos(rad) * dt
        new_y = self.robot_y + linear_vel * math.sin(rad) * dt

        # Collision clamping with room walls
        margin = self.robot_radius_cm + 5.0
        self.robot_x = max(margin, min(new_x, self.width - margin))
        self.robot_y = max(margin, min(new_y, self.height - margin))

        # Slowly oscillate humans to simulate moving bodies
        for h in self.humans:
            if h.is_moving:
                h.x += math.cos(time.time() * 0.8) * 0.4
                h.y += math.sin(time.time() * 0.8) * 0.4

        # Re-compute sensor perception
        self._compute_sensors()

    def _compute_sensors(self):
        """
        Raycasts distance along robot forward heading and checks PIR detection cone.
        """
        rad = math.radians(self.robot_theta_deg)
        cos_t = math.cos(rad)
        sin_t = math.sin(rad)

        # 1. Ultrasonic Raycasting
        min_dist = self.ultrasonic_max_range_cm

        # Check room boundary walls
        if cos_t > 0.001:
            d = (self.width - self.robot_x) / cos_t
            if d > 0: min_dist = min(min_dist, d)
        elif cos_t < -0.001:
            d = (-self.robot_x) / cos_t
            if d > 0: min_dist = min(min_dist, d)

        if sin_t > 0.001:
            d = (self.height - self.robot_y) / sin_t
            if d > 0: min_dist = min(min_dist, d)
        elif sin_t < -0.001:
            d = (-self.robot_y) / sin_t
            if d > 0: min_dist = min(min_dist, d)

        # Check obstacles
        for obs in self.obstacles:
            dist = self._ray_to_box_dist(
                self.robot_x, self.robot_y, cos_t, sin_t,
                obs.x - obs.width/2, obs.y - obs.height/2, obs.width, obs.height
            )
            if dist is not None and dist > 0:
                min_dist = min(min_dist, dist)

        # Check humans for acoustic reflection
        for h in self.humans:
            dist = self._ray_to_circle_dist(self.robot_x, self.robot_y, cos_t, sin_t, h.x, h.y, radius=18.0)
            if dist is not None and dist > 0:
                min_dist = min(min_dist, dist)

        self.raw_distance_cm = round(max(2.0, min(min_dist, self.ultrasonic_max_range_cm)), 1)

        # 2. PIR Motion FOV
        self.raw_pir = 0
        for h in self.humans:
            if h.is_warm and h.is_moving:
                # Vector to human
                dx = h.x - self.robot_x
                dy = h.y - self.robot_y
                dist_to_h = math.sqrt(dx*dx + dy*dy)

                if dist_to_h <= self.pir_max_range_cm:
                    angle_to_h = math.degrees(math.atan2(dy, dx))
                    angle_diff = (angle_to_h - self.robot_theta_deg + 180) % 360 - 180
                    if abs(angle_diff) <= (self.pir_fov_deg / 2.0):
                        self.raw_pir = 1
                        break

    def _ray_to_box_dist(self, rx, ry, dx, dy, bx, by, bw, bh) -> Optional[float]:
        # Simple AABB ray intersection
        tmin = -1e9
        tmax = 1e9

        if abs(dx) > 1e-6:
            t1 = (bx - rx) / dx
            t2 = (bx + bw - rx) / dx
            tmin = max(tmin, min(t1, t2))
            tmax = min(tmax, max(t1, t2))
        else:
            if rx < bx or rx > bx + bw:
                return None

        if abs(dy) > 1e-6:
            t1 = (by - ry) / dy
            t2 = (by + bh - ry) / dy
            tmin = max(tmin, min(t1, t2))
            tmax = min(tmax, max(t1, t2))
        else:
            if ry < by or ry > by + bh:
                return None

        if tmax >= tmin and tmax > 0:
            return tmin if tmin > 0 else tmax
        return None

    def _ray_to_circle_dist(self, rx, ry, dx, dy, cx, cy, radius) -> Optional[float]:
        # Ray-circle intersection
        ox = rx - cx
        oy = ry - cy
        b = 2.0 * (ox * dx + oy * dy)
        c = ox * ox + oy * oy - radius * radius
        disc = b * b - 4.0 * c
        if disc < 0:
            return None
        sqrt_d = math.sqrt(disc)
        t1 = (-b - sqrt_d) / 2.0
        t2 = (-b + sqrt_d) / 2.0
        if t1 > 0: return t1
        if t2 > 0: return t2
        return None

    def set_human_position(self, human_id: str, x: float, y: float):
        for h in self.humans:
            if h.id == human_id:
                h.x = max(20.0, min(x, self.width - 20.0))
                h.y = max(20.0, min(y, self.height - 20.0))
                self._compute_sensors()
                break

    def set_obstacle_position(self, obs_id: str, x: float, y: float):
        for o in self.obstacles:
            if o.id == obs_id:
                o.x = max(30.0, min(x, self.width - 30.0))
                o.y = max(30.0, min(y, self.height - 30.0))
                self._compute_sensors()
                break

    def spawn_obstacle_in_front(self, distance_cm: float = 12.0):
        rad = math.radians(self.robot_theta_deg)
        target_dist = distance_cm + self.robot_radius_cm + 15.0
        ox = self.robot_x + math.cos(rad) * target_dist
        oy = self.robot_y + math.sin(rad) * target_dist
        found = False
        for o in self.obstacles:
            if o.id == "box_1":
                o.x = max(20.0, min(ox, self.width - 20.0))
                o.y = max(20.0, min(oy, self.height - 20.0))
                found = True
                break
        if not found:
            self.obstacles.append(ObstacleEntity(id="box_1", x=ox, y=oy, width=30.0, height=30.0))
        self._compute_sensors()

    def get_arena_state(self) -> Dict[str, Any]:
        return {
            "room": {"width_cm": self.width, "height_cm": self.height},
            "robot": {
                "x": round(self.robot_x, 1),
                "y": round(self.robot_y, 1),
                "heading_deg": round(self.robot_theta_deg, 1),
                "radius_cm": self.robot_radius_cm,
                "ultrasonic_fov_deg": self.ultrasonic_fov_deg,
                "pir_fov_deg": self.pir_fov_deg
            },
            "sensors": {
                "raw_pir": self.raw_pir,
                "raw_distance_cm": self.raw_distance_cm,
                "ax": self.ax, "ay": self.ay, "az": self.az,
                "gx": self.gx, "gy": self.gy, "gz": self.gz
            },
            "humans": [asdict(h) for h in self.humans],
            "obstacles": [asdict(o) for o in self.obstacles]
        }

class PhysicalESP32Connection:
    def __init__(self):
        self.connected: bool = False
        self.client_id: str = "ESP32_BUPI_NODE"
        self.ip: str = "192.168.0.106"
        self.last_packet_time: float = 0.0

    def parse_telemetry(self, packet_str: str) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(packet_str)
            self.last_packet_time = time.time()
            self.connected = True
            return data
        except Exception:
            return None

class BupiBridge:
    def __init__(self, use_simulation: bool = True):
        self.use_simulation = use_simulation
        self.arena = ArenaSimulation()
        self.physical = PhysicalESP32Connection()

    def get_latest_sensor_data(self) -> Dict[str, Any]:
        if self.use_simulation:
            st = self.arena.get_arena_state()["sensors"]
            return {
                "pir_pin": st["raw_pir"],
                "distance_cm": st["raw_distance_cm"],
                "imu": {
                    "ax": st["ax"], "ay": st["ay"], "az": st["az"],
                    "gx": st["gx"], "gy": st["gy"], "gz": st["gz"]
                }
            }
        else:
            try:
                from bupi_node_server import get_latest_telemetry
                telem = get_latest_telemetry()
                return {
                    "pir_pin": telem.get("pir", 0),
                    "distance_cm": telem.get("distance_cm", 150.0),
                    "heading_deg": telem.get("heading", 0.0),
                    "tilt_deg": telem.get("effective_tilt", 0.0),
                    "imu": {
                        "ax": telem.get("ax", 0.0),
                        "ay": telem.get("ay", 0.0),
                        "az": telem.get("az", 1.0),
                        "gx": telem.get("gx", 0.0),
                        "gy": telem.get("gy", 0.0),
                        "gz": telem.get("gz", 0.0)
                    }
                }
            except Exception:
                return {
                    "pir_pin": 0,
                    "distance_cm": 150.0,
                    "heading_deg": 0.0,
                    "tilt_deg": 0.0,
                    "imu": {"ax": 0.0, "ay": 0.0, "az": 1.0, "gx": 0.0, "gy": 0.0, "gz": 0.0}
                }
