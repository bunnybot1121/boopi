"""
BUPI Sensors Package
====================
Modular sensor drivers and epistemic interpretation layers for:
- PIR (Passive Infrared Motion Sensor)
- HC-SR04 (Ultrasonic Distance Ranging)
- MPU6050 (6-Axis IMU Self-Orientation / Dynamics)
- SensorFusion (Epistemic Ladder: Observation -> Measurement -> Interpretation -> Inference)
"""

from .pir_sensor import PIRSensor, PIRState
from .ultrasonic_sensor import UltrasonicSensor, DistanceClassification
from .mpu6050_sensor import MPU6050Sensor, RobotMotionState
from .sensor_fusion import SensorFusion, EpistemicLadder, TargetInference

__all__ = [
    "PIRSensor",
    "PIRState",
    "UltrasonicSensor",
    "DistanceClassification",
    "MPU6050Sensor",
    "RobotMotionState",
    "SensorFusion",
    "EpistemicLadder",
    "TargetInference"
]
