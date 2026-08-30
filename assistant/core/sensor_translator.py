def translate_sensor_value(sensor_id: str, value: float) -> dict:
    """
    Translates raw numerical values from various sensors into semantic human-readable states.
    Supports MQ2, IR, DHT (Temperature & Humidity), and Ultrasonic Distance sensors.
    """
    sensor_id = sensor_id.lower()
    
    # Default fallback
    status = "Normal"
    description = f"Reading is {value}"
    
    if "mq2" in sensor_id:
        # Analog MQ2 ranges from 0 to 4095 on ESP32
        if value < 600:
            status = "SAFE"
            description = "Gas levels are safe."
        elif value < 1500:
            status = "WARNING"
            description = "Elevated gas or smoke concentration detected."
        elif value < 2500:
            status = "DANGER"
            description = "Dangerous concentration of smoke or flammable gas!"
        else:
            status = "CRITICAL"
            description = "Immediate hazard! Extreme gas or smoke levels!"
            
    elif "ir" in sensor_id:
        # Digital IR sensor: 0 means object detected, 1 means clear
        try:
            val_int = int(value)
        except Exception:
            val_int = 1
            
        if val_int == 0:
            status = "OBJECT_DETECTED"
            description = "Object detected in front of sensor."
        else:
            status = "CLEAR"
            description = "No object detected."
            
    elif "temp" in sensor_id or "dht" in sensor_id:
        if value < 18.0:
            status = "COLD"
            description = "Temperature is cold."
        elif value <= 28.0:
            status = "COMFORTABLE"
            description = "Temperature is comfortable."
        elif value <= 35.0:
            status = "WARM"
            description = "Temperature is warm."
        else:
            status = "HOT"
            description = "Temperature is hot."
            
    elif "humidity" in sensor_id:
        if value < 30.0:
            status = "DRY"
            description = "Air is dry."
        elif value <= 60.0:
            status = "NORMAL"
            description = "Humidity is normal and comfortable."
        elif value <= 80.0:
            status = "HUMID"
            description = "Air is humid."
        else:
            status = "VERY_HUMID"
            description = "Air is extremely humid."
            
    elif "distance" in sensor_id or "ultrasonic" in sensor_id or "hcsr04" in sensor_id:
        if value < 10.0:
            status = "COLLISION_RISK"
            description = "Immediate collision risk!"
        elif value < 30.0:
            status = "VERY_CLOSE"
            description = "Obstacle detected very close."
        elif value < 80.0:
            status = "NEAR"
            description = "Obstacle detected nearby."
        else:
            status = "CLEAR"
            description = "Path is clear."
            
    return {
        "sensor": sensor_id,
        "value": value,
        "status": status,
        "description": description
    }
