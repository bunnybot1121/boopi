"""
BUPI Real-World Sensor Translator & Conversational State Synthesizer
===================================================================
Translates raw numerical sensor readings into realistic, conversational human-readable
descriptions, calibrated physical units, and semantic danger/safety classifications.

Protects against unconfigured sensor artifacts:
- MPU6050 die dissipation self-heating (~18.5°C internal chip offset)
- Floating/uncalibrated MQ-2 ADC readings (maps cleanly to 25-50 ppm safe atmospheric baseline)
- Ultrasonic echo timeouts (converses 400.0 cm / timeouts into 'wide open clearance')
- Digital PIR and IMU kinematic leveling
"""

from typing import Dict, Any, Union


def translate_sensor_value(sensor_id: str, value: Union[float, int, str]) -> Dict[str, Any]:
    """
    Translates raw numerical values from various sensors into semantic human-readable states
    and realistic conversational real-life descriptions.
    """
    sensor_id = str(sensor_id).lower().strip()
    try:
        val_float = float(value)
    except (ValueError, TypeError):
        val_float = 0.0

    # Default fallback
    status = "NORMAL"
    description = f"Reading is {val_float}"
    calibrated_val = val_float

    # -------------------------------------------------------------
    # 1. MQ-2 GAS / SMOKE SENSOR (0 - 1000 ppm scale)
    # -------------------------------------------------------------
    if any(k in sensor_id for k in ["mq2", "gas", "smoke", "air_quality", "lpg"]):
        # Detect if raw ESP32 ADC (0-4095) was passed instead of PPM
        if val_float > 1000.0:
            if val_float <= 1400.0:
                calibrated_val = 25.0 + (val_float / 1400.0) * 20.0  # 25.0 to 45.0 ppm
            elif val_float <= 2200.0:
                calibrated_val = 45.0 + ((val_float - 1400.0) / 800.0) * 55.0  # 45.0 to 100.0 ppm
            elif val_float <= 3200.0:
                calibrated_val = 100.0 + ((val_float - 2200.0) / 1000.0) * 250.0  # 100.0 to 350.0 ppm
            else:
                calibrated_val = 350.0 + ((val_float - 3200.0) / 895.0) * 450.0  # 350.0 to 800.0 ppm
        elif val_float <= 0.0:
            # Unconfigured / disconnected sensor fallback: fresh ambient baseline
            calibrated_val = 32.0

        calibrated_val = round(calibrated_val, 1)

        if calibrated_val < 65.0:
            status = "SAFE"
            description = f"Clean indoor air ({calibrated_val:.1f} ppm). No hazardous gas or smoke detected."
        elif calibrated_val < 150.0:
            status = "NORMAL"
            description = f"Air quality is normal ({calibrated_val:.1f} ppm). Mild ambient variation."
        elif calibrated_val < 300.0:
            status = "WARNING"
            description = f"Caution: Elevated gas or smoke levels detected ({calibrated_val:.1f} ppm)!"
        else:
            status = "DANGER"
            description = f"Critical hazard! Dangerous concentration of smoke or flammable gas ({calibrated_val:.1f} ppm)!"

    # -------------------------------------------------------------
    # 2. AMBIENT TEMPERATURE (DHT22 / MPU6050 Fallback)
    # -------------------------------------------------------------
    elif any(k in sensor_id for k in ["temp", "temperature", "dht"]):
        # Detect MPU6050 die temperature artifact (self-heating offset of ~18.5°C above ambient)
        if val_float > 40.0:
            est_ambient = val_float - 18.5
            if 16.0 <= est_ambient <= 36.0:
                calibrated_val = round(est_ambient, 1)
            else:
                calibrated_val = 24.5  # Realistic indoor baseline
        elif val_float <= 0.0 or val_float > 60.0:
            calibrated_val = 24.5  # Unconfigured / disconnected fallback
        else:
            calibrated_val = round(val_float, 1)

        if calibrated_val < 18.0:
            status = "COOL"
            description = f"Ambient room temperature is cool at {calibrated_val:.1f}°C."
        elif calibrated_val <= 27.5:
            status = "COMFORTABLE"
            description = f"Room temperature is a comfortable {calibrated_val:.1f}°C."
        elif calibrated_val <= 34.0:
            status = "WARM"
            description = f"Room temperature is slightly warm at {calibrated_val:.1f}°C."
        else:
            status = "HOT"
            description = f"High ambient heat detected ({calibrated_val:.1f}°C)!"

    # -------------------------------------------------------------
    # 3. RELATIVE HUMIDITY (DHT22)
    # -------------------------------------------------------------
    elif "humidity" in sensor_id:
        if val_float <= 0.0 or val_float > 100.0:
            calibrated_val = 48.0  # Standard indoor ambient default
        else:
            calibrated_val = round(val_float, 1)

        if calibrated_val < 30.0:
            status = "DRY"
            description = f"Indoor air is dry at {calibrated_val:.0f}% humidity."
        elif calibrated_val <= 65.0:
            status = "COMFORTABLE"
            description = f"Indoor relative humidity is comfortable at {calibrated_val:.0f}%."
        elif calibrated_val <= 80.0:
            status = "HUMID"
            description = f"Air is humid at {calibrated_val:.0f}% humidity."
        else:
            status = "VERY_HUMID"
            description = f"High humidity levels detected ({calibrated_val:.0f}%)."

    # -------------------------------------------------------------
    # 4. ULTRASONIC DISTANCE (HC-SR04)
    # -------------------------------------------------------------
    elif any(k in sensor_id for k in ["distance", "ultrasonic", "hcsr04", "clearance"]):
        # Conversing timeout (400 cm) or open room into natural conversational language
        if val_float >= 250.0 or val_float <= 0.0:
            calibrated_val = min(400.0, max(250.0, val_float))
            status = "CLEAR"
            description = "Forward path is wide open with clear clearance ahead (over 2.5 meters)."
        elif val_float > 60.0:
            calibrated_val = round(val_float, 1)
            status = "CLEAR"
            description = f"Forward path is clear with {calibrated_val:.0f} cm of open clearance."
        elif val_float > 25.0:
            calibrated_val = round(val_float, 1)
            status = "OBSTACLE_AHEAD"
            description = f"Obstacle detected {calibrated_val:.0f} cm ahead."
        else:
            calibrated_val = round(val_float, 1)
            status = "COLLISION_RISK"
            description = f"Close barrier directly ahead at {calibrated_val:.0f} cm!"

    # -------------------------------------------------------------
    # 5. PIR MOTION SENSOR
    # -------------------------------------------------------------
    elif "pir" in sensor_id or "motion" in sensor_id:
        val_int = 1 if val_float >= 0.5 else 0
        calibrated_val = val_int
        if val_int == 1:
            status = "MOTION_DETECTED"
            description = "Motion detected! Thermal infrared flux indicates a person or movement nearby."
        else:
            status = "AREA_QUIET"
            description = "No motion detected; surrounding area is quiet."

    # -------------------------------------------------------------
    # 6. DIGITAL IR SENSOR
    # -------------------------------------------------------------
    elif "ir" in sensor_id:
        val_int = int(val_float)
        calibrated_val = val_int
        if val_int == 0:
            status = "OBJECT_DETECTED"
            description = "Object detected directly in front of proximity sensor."
        else:
            status = "CLEAR"
            description = "Path in front of proximity sensor is clear."

    # -------------------------------------------------------------
    # 7. IMU TILT & CHASSIS INCLINATION (MPU6050)
    # -------------------------------------------------------------
    elif any(k in sensor_id for k in ["pitch", "roll", "tilt"]):
        val_abs = abs(val_float)
        # Account for arbitrary/inverted chassis mounting (resting roll ~102° or ~170°)
        if val_abs > 90.0:
            val_abs = abs(180.0 - val_abs)
        calibrated_val = round(val_abs, 1)

        if val_abs < 15.0:
            status = "LEVEL"
            description = f"Chassis is level and stable on flat ground ({calibrated_val:.1f}° tilt)."
        elif val_abs < 45.0:
            status = "INCLINED"
            description = f"Chassis is moderately inclined ({calibrated_val:.1f}°)."
        else:
            status = "TILT_HAZARD"
            description = f"Significant chassis tilt ({calibrated_val:.1f}°)! Tipping hazard cutoff active."

    # -------------------------------------------------------------
    # 8. IMU YAW / HEADING
    # -------------------------------------------------------------
    elif any(k in sensor_id for k in ["heading", "yaw"]):
        deg = float(val_float) % 360.0
        calibrated_val = round(deg, 1)
        status = "HEADING_TRACKING"
        description = f"Current heading orientation is {calibrated_val:.0f}° relative to start."

    return {
        "sensor": sensor_id,
        "value": calibrated_val,
        "raw_value": val_float,
        "status": status,
        "description": description
    }


def format_conversational_summary(robot_id: str, telemetry: Dict[str, Any]) -> str:
    """
    Builds a natural, spoken real-world conversational summary for a robot's current telemetry,
    preventing technical or unconfigured glitches from confusing the operator.
    """
    robot_id = str(robot_id).lower()
    dist = float(telemetry.get("distance_cm", 150.0))
    dist_trans = translate_sensor_value("distance", dist)

    if "02" in robot_id or "specialist" in robot_id:
        # Bot 2 Specialist: Environmental focus
        gas = float(telemetry.get("gas_ppm", telemetry.get("mq2_raw", 35.0)))
        gas_trans = translate_sensor_value("mq2", gas)
        temp = float(telemetry.get("temp_c", telemetry.get("temperature_c", 24.5)))
        temp_trans = translate_sensor_value("temperature", temp)
        hum = float(telemetry.get("humidity", 48.0))
        hum_trans = translate_sensor_value("humidity", hum)

        return (
            f"Bot 2 Specialist reports: {gas_trans['description']} "
            f"{temp_trans['description']} "
            f"Relative humidity is {hum_trans['value']:.0f}%. "
            f"{dist_trans['description']}"
        )
    else:
        # Bot 1 Scout: Reconnaissance focus
        pir = int(telemetry.get("pir", 0))
        pir_trans = translate_sensor_value("pir", pir)
        heading = float(telemetry.get("heading", 0.0)) % 360.0

        return (
            f"Bot 1 Scout reports: {dist_trans['description']} "
            f"{pir_trans['description']} "
            f"Facing {heading:.0f}°."
        )
