"""
BUPI Sensor Fusion Engine & Epistemic Ladder
============================================
Fuses observations and measurements from PIR, Ultrasonic, and MPU6050 sensors
into disciplined epistemic conclusions:

1. OBSERVATION: Raw pin or bus state (e.g. PIR = HIGH, Echo pulse = 7350us)
2. MEASUREMENT: Calibrated physical quantity (e.g. Distance = 125 cm, Gyro = 0 deg/s)
3. INTERPRETATION: Single-sensor domain meaning (e.g. Warm movement detected, Nearby surface present)
4. INFERENCE: Multi-sensor synthesized hypothesis (e.g. Possible moving warm target ~1.25m away)
5. DECISION: High-level intention selection (e.g. STOP, REPORT)
6. ACTION: Concrete structured action (e.g. STOP_MOTORS, EMIT_REPORT)
7. REPORT: Clear human communication without overclaiming certainty.
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from .pir_sensor import PIRSensor, PIRState
from .ultrasonic_sensor import UltrasonicSensor, DistanceClassification
from .mpu6050_sensor import MPU6050Sensor, RobotMotionState

@dataclass
class EpistemicLadder:
    observation: str
    measurement: str
    interpretation: str
    inference: str
    decision: str
    action: str
    report: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)

@dataclass
class TargetInference:
    possible_human_presence: bool
    estimated_distance_m: Optional[float]
    confidence_score: float  # 0.0 to 1.0
    summary: str
    report_message: str

class SensorFusion:
    def __init__(
        self,
        pir: Optional[PIRSensor] = None,
        ultrasonic: Optional[UltrasonicSensor] = None,
        imu: Optional[MPU6050Sensor] = None,
        human_detection_min_dist_cm: float = 20.0,
        human_detection_max_dist_cm: float = 250.0
    ):
        self.pir = pir or PIRSensor()
        self.ultrasonic = ultrasonic or UltrasonicSensor()
        self.imu = imu or MPU6050Sensor()
        
        self.human_detection_min_dist_cm = human_detection_min_dist_cm
        self.human_detection_max_dist_cm = human_detection_max_dist_cm
        
        # Future vision integration hook
        self.camera_available: bool = False
        self.camera_human_confidence: float = 0.0

    def evaluate(self) -> Dict[str, Any]:
        """
        Runs the full sensor fusion cycle across current sensor states
        and returns the complete epistemic synthesis.
        """
        pir_info = self.pir.get_interpretation()
        dist_info = self.ultrasonic.get_interpretation()
        imu_info = self.imu.get_interpretation()

        motion_detected = pir_info["motion_detected"]
        distance_cm = dist_info["distance_cm"]
        dist_class = dist_info["classification"]

        # Epistemic Rule from Spec:
        # Motion detected (PIR) + Nearby object within detection corridor (Ultrasonic)
        # = POSSIBLE_HUMAN_PRESENCE (NOT human confirmed)
        has_nearby_object = (
            self.human_detection_min_dist_cm <= distance_cm <= self.human_detection_max_dist_cm
        )

        possible_human = False
        confidence = 0.0
        distance_m = round(distance_cm / 100.0, 2)

        if motion_detected and has_nearby_object:
            possible_human = True
            # Synthetic confidence score reflecting probability of warm moving presence
            confidence = 0.85 if distance_cm <= 150 else 0.70
            report_msg = f"Possible human presence detected approximately {distance_m} meters away."
            inference_summary = f"Possible warm moving target at approximately {distance_cm} cm."
        elif motion_detected and not has_nearby_object:
            report_msg = "Warm motion detected, but no obstacle found in direct forward line-of-sight."
            inference_summary = "PIR trigger without direct acoustic reflection (target may be off-axis)."
            confidence = 0.35
        elif not motion_detected and dist_class == DistanceClassification.OBSTACLE.value:
            report_msg = f"Inanimate obstacle detected at close range ({distance_cm} cm). No warm motion."
            inference_summary = "Static obstacle in proximity corridor."
            confidence = 0.1
        else:
            report_msg = "Area clear. No human presence or critical obstacles observed."
            inference_summary = "Quiescent environment."
            confidence = 0.0

        # Build Epistemic Ladder Stage representation
        ladder = EpistemicLadder(
            observation=f"PIR={'HIGH' if pir_info['raw_value'] else 'LOW'}; Ping Echo={distance_cm}cm; IMU={imu_info['state']}",
            measurement=f"Distance={distance_cm} cm; Heading={imu_info['heading_deg']}°; Tilt={imu_info['pitch_deg']}°",
            interpretation=(
                f"{'Motion detected' if motion_detected else 'No motion'}; "
                f"Proximity classification: '{dist_class}'"
            ),
            inference=inference_summary,
            decision="STOP" if (possible_human or dist_class == "obstacle") else "CONTINUE_SEARCH",
            action="REPORT" if possible_human else ("EMERGENCY_STOP" if dist_class == "obstacle" else "MOVE_FORWARD"),
            report=report_msg
        )

        target_inference = TargetInference(
            possible_human_presence=possible_human,
            estimated_distance_m=distance_m if possible_human else None,
            confidence_score=confidence,
            summary=inference_summary,
            report_message=report_msg
        )

        return {
            "pir": pir_info,
            "ultrasonic": dist_info,
            "imu": imu_info,
            "inference": asdict(target_inference),
            "epistemic_ladder": ladder.to_dict(),
            "future_vision_ready": True
        }
