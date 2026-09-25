"""
BUPI Kinematics, Inertial Odometry & RF Distance Engine
======================================================
Fuses:
1. MPU6050 6-Axis IMU peak acceleration gait / step detection
2. Gyroscope-integrated yaw dead-reckoning (Cartesian X, Y coordinates in meters)
3. Wi-Fi RSSI indoor log-distance path loss modeling (distance in meters from host laptop/hotspot)
4. RF proximity trend analysis ("APPROACHING", "RECEDING", "STATIONARY")
"""

import math
import time
import threading
from typing import Dict, Any, Optional, List

# Indoor Wi-Fi Log-Distance Path Loss Parameters
# Standard calibrated values for typical residential/lab room environments:
# RSSI_REF_1M: Expected signal strength at 1.0 meter (calibrated for ESP32 PCB antenna)
# PATH_LOSS_EXPONENT (n): 2.4 - 2.8 for indoor unobstructed-to-light-clutter environments
RSSI_REF_1M = -42.0
PATH_LOSS_EXPONENT = 2.5

# Gait / Step Parameters for N20 Mobile Base
CALIBRATED_STRIDE_M = 0.075  # ~7.5 cm per step / vibration cycle
STEP_ACCEL_THRESHOLD_G = 1.20 # Peak dynamic acceleration threshold
STEP_DEBOUNCE_SEC = 0.18      # 180ms refractory period between steps (max ~5.5 steps/sec)


def estimate_wifi_distance(rssi: float) -> Dict[str, Any]:
    """
    Estimates distance in meters from the host laptop / access point using
    the Log-Distance Path Loss Model:
        d = 10 ^ ((RSSI_0 - RSSI) / (10 * n))
    """
    if rssi == 0 or rssi is None or rssi < -100.0 or rssi > 0:
        return {
            "distance_m": None,
            "rssi_dbm": 0,
            "signal_quality_pct": 0,
            "proximity_zone": "UNKNOWN",
            "description": "Wi-Fi disconnected or operating in USB standalone mode"
        }

    # Constrain RSSI to realistic physical bounds
    clamped_rssi = max(-95.0, min(-25.0, float(rssi)))

    # Calculate distance via log-distance formula
    ratio = (RSSI_REF_1M - clamped_rssi) / (10.0 * PATH_LOSS_EXPONENT)
    distance_m = round(math.pow(10.0, ratio), 2)
    distance_m = max(0.2, min(35.0, distance_m))

    # Signal quality (linear percent from -95 dBm [0%] to -30 dBm [100%])
    quality_pct = int(max(0, min(100, (clamped_rssi + 95.0) / 65.0 * 100.0)))

    # Proximity classification
    if distance_m <= 1.2:
        zone = "IMMEDIATE_PROXIMITY"
    elif distance_m <= 3.0:
        zone = "NEAR_DESK"
    elif distance_m <= 6.0:
        zone = "MID_ROOM"
    else:
        zone = "PERIMETER_FAR"

    return {
        "distance_m": distance_m,
        "rssi_dbm": round(clamped_rssi, 1),
        "signal_quality_pct": quality_pct,
        "proximity_zone": zone,
        "description": f"Approx. {distance_m:.1f} meters from laptop/hotspot ({quality_pct}% signal, {clamped_rssi:.0f} dBm)"
    }


class RobotOdometryState:
    def __init__(self, bot_id: str):
        self.bot_id = bot_id
        self.x_m: float = 0.0
        self.y_m: float = 0.0
        self.heading_deg: float = 0.0
        self.total_distance_m: float = 0.0
        self.step_count: int = 0
        self.last_step_time: float = 0.0
        
        # Wi-Fi RSSI Tracking
        self.smoothed_rssi: Optional[float] = None
        self.rssi_samples: List[float] = []
        self.proximity_trend: str = "STATIONARY"  # "APPROACHING", "RECEDING", "STATIONARY"
        self.last_wifi_update: float = 0.0

    def reset_pose(self):
        """Resets the Cartesian origin to (0.0, 0.0) for a new mission."""
        self.x_m = 0.0
        self.y_m = 0.0
        self.total_distance_m = 0.0
        self.step_count = 0
        self.last_step_time = 0.0
        self.smoothed_rssi = None
        self.rssi_samples = []
        self.proximity_trend = "STATIONARY"


class KinematicsOdometryEngine:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(KinematicsOdometryEngine, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.state_lock = threading.Lock()
        self.robots: Dict[str, RobotOdometryState] = {
            "bupi_01": RobotOdometryState("bupi_01"),
            "bupi_02": RobotOdometryState("bupi_02")
        }

    def _get_robot(self, bot_id: str) -> RobotOdometryState:
        key = "bupi_02" if "2" in bot_id else "bupi_01"
        if key not in self.robots:
            self.robots[key] = RobotOdometryState(key)
        return self.robots[key]

    def reset(self, bot_id: str = "bupi_01"):
        with self.state_lock:
            bot = self._get_robot(bot_id)
            bot.reset_pose()

    def reset_all(self):
        with self.state_lock:
            for bot in self.robots.values():
                bot.reset_pose()

    def update_imu(self, bot_id: str, ax: float, ay: float, az: float, heading: float, dt: float = 0.05, is_moving: bool = False, firmware_steps: Optional[int] = None):
        """
        Updates inertial kinematics, peak-detection step counting, and dead-reckoning position.
        """
        with self.state_lock:
            bot = self._get_robot(bot_id)
            now = time.time()
            bot.heading_deg = heading

            # If firmware provides authoritative onboard step count, sync with it
            if firmware_steps is not None and firmware_steps > bot.step_count:
                delta_steps = firmware_steps - bot.step_count
                bot.step_count = firmware_steps
                delta_dist = delta_steps * CALIBRATED_STRIDE_M
                bot.total_distance_m += delta_dist

                rad = math.radians(heading)
                bot.x_m += delta_dist * math.cos(rad)
                bot.y_m += delta_dist * math.sin(rad)
                return

            # Software peak-acceleration detector (runs if firmware step counter is idle or simulated)
            if is_moving:
                total_accel = math.sqrt(ax * ax + ay * ay + az * az)
                # Dynamic peak: check if total g exceeds threshold and debounce window has elapsed
                if total_accel >= STEP_ACCEL_THRESHOLD_G and (now - bot.last_step_time) >= STEP_DEBOUNCE_SEC:
                    bot.step_count += 1
                    bot.last_step_time = now
                    delta_dist = CALIBRATED_STRIDE_M
                    bot.total_distance_m += delta_dist

                    rad = math.radians(heading)
                    bot.x_m += delta_dist * math.cos(rad)
                    bot.y_m += delta_dist * math.sin(rad)

    def record_step(self, bot_id: str, count: int = 1):
        """Directly registers dynamic steps."""
        with self.state_lock:
            bot = self._get_robot(bot_id)
            bot.step_count += count
            delta_dist = count * CALIBRATED_STRIDE_M
            bot.total_distance_m += delta_dist
            rad = math.radians(bot.heading_deg)
            bot.x_m += delta_dist * math.cos(rad)
            bot.y_m += delta_dist * math.sin(rad)

    def update_wifi(self, bot_id: str, rssi: float):
        """
        Updates Wi-Fi RSSI, applies EWMA smoothing, and evaluates proximity trend.
        """
        if rssi == 0 or rssi is None or rssi < -100.0 or rssi > 0:
            return

        with self.state_lock:
            bot = self._get_robot(bot_id)
            now = time.time()
            bot.last_wifi_update = now

            # Exponential Weighted Moving Average (EWMA: alpha = 0.25)
            if bot.smoothed_rssi is None:
                bot.smoothed_rssi = float(rssi)
            else:
                bot.smoothed_rssi = 0.25 * float(rssi) + 0.75 * bot.smoothed_rssi

            bot.rssi_samples.append(bot.smoothed_rssi)
            if len(bot.rssi_samples) > 12:
                bot.rssi_samples.pop(0)

            # Evaluate trend if we have at least 5 samples
            if len(bot.rssi_samples) >= 5:
                delta = bot.rssi_samples[-1] - bot.rssi_samples[0]
                if delta >= 2.5:
                    bot.proximity_trend = "APPROACHING"  # Signal getting significantly stronger
                elif delta <= -2.5:
                    bot.proximity_trend = "RECEDING"    # Signal getting significantly weaker
                else:
                    bot.proximity_trend = "STATIONARY"

    def get_state(self, bot_id: str = "bupi_01") -> Dict[str, Any]:
        """
        Returns the unified kinematics, odometry, and RF proximity state for the specified robot.
        """
        with self.state_lock:
            bot = self._get_robot(bot_id)
            displacement = math.sqrt(bot.x_m * bot.x_m + bot.y_m * bot.y_m)
            
            # Wi-Fi distance
            wifi_info = estimate_wifi_distance(bot.smoothed_rssi if bot.smoothed_rssi is not None else 0)

            return {
                "bot_id": bot.bot_id,
                "step_count": bot.step_count,
                "total_distance_m": round(bot.total_distance_m, 2),
                "total_distance_cm": round(bot.total_distance_m * 100.0, 1),
                "x_m": round(bot.x_m, 2),
                "y_m": round(bot.y_m, 2),
                "displacement_m": round(displacement, 2),
                "heading_deg": round(bot.heading_deg, 1),
                "wifi_rssi": round(bot.smoothed_rssi, 1) if bot.smoothed_rssi is not None else None,
                "distance_from_laptop_m": wifi_info["distance_m"],
                "proximity_trend": bot.proximity_trend,
                "signal_quality_pct": wifi_info["signal_quality_pct"],
                "proximity_zone": wifi_info["proximity_zone"],
                "summary": (
                    f"Steps: {bot.step_count} | Dist: {bot.total_distance_m:.2f}m | "
                    f"Pose: ({bot.x_m:+.2f}m, {bot.y_m:+.2f}m) | "
                    f"Laptop Dist: {wifi_info['distance_m']}m ({bot.proximity_trend})"
                    if wifi_info["distance_m"] is not None else
                    f"Steps: {bot.step_count} | Dist: {bot.total_distance_m:.2f}m | Pose: ({bot.x_m:+.2f}m, {bot.y_m:+.2f}m)"
                )
            }


odometry_engine = KinematicsOdometryEngine()
