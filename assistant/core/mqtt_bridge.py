import json
import asyncio
import paho.mqtt.client as mqtt
from core.event_bus_async import bus

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
COMMAND_TOPIC = "bupi/cmd"

class MQTTBridge:
    def __init__(self):
        # API v2 is required for newer paho-mqtt
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="BUPI_Orchestrator")
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self._last_bridged = {}
        
        # Multi-sensor telemetry states
        self.telemetry_modes = {"mq2": "continuous"}  # maps sensor_id -> mode (continuous, highest, lowest, average)
        self.highest_vals = {}     # maps sensor_id -> float
        self.lowest_vals = {}      # maps sensor_id -> float
        self.values_histories = {} # maps sensor_id -> list of float
        self.latest_formatted_lines = {} # maps sensor_id -> formatted display string
        self._init_db()

    # 100% Backward compatibility getters/setters for single sensor mq2
    @property
    def telemetry_mode(self):
        return self.telemetry_modes.get("mq2")

    @telemetry_mode.setter
    def telemetry_mode(self, value):
        self.set_sensor_mode("mq2", value)

    @property
    def highest_val(self):
        return self.highest_vals.get("mq2", -1.0)

    @highest_val.setter
    def highest_val(self, value):
        self.highest_vals["mq2"] = value

    @property
    def lowest_val(self):
        return self.lowest_vals.get("mq2", 999999.0)

    @lowest_val.setter
    def lowest_val(self, value):
        self.lowest_vals["mq2"] = value

    @property
    def values_list(self):
        if "mq2" not in self.values_histories:
            self.values_histories["mq2"] = []
        return self.values_histories["mq2"]

    @values_list.setter
    def values_list(self, value):
        self.values_histories["mq2"] = value

    @property
    def mq2_to_lcd_active(self):
        return self.telemetry_mode == "continuous"

    @mq2_to_lcd_active.setter
    def mq2_to_lcd_active(self, value):
        if value:
            self.telemetry_mode = "continuous"
        elif self.telemetry_mode == "continuous":
            self.telemetry_mode = None

    def set_sensor_mode(self, sensor_id, mode):
        """Sets or resets the telemetry mode for a specific sensor."""
        if mode is None:
            if sensor_id in self.telemetry_modes:
                del self.telemetry_modes[sensor_id]
            if sensor_id in self.latest_formatted_lines:
                del self.latest_formatted_lines[sensor_id]
        else:
            self.telemetry_modes[sensor_id] = mode
            self.highest_vals[sensor_id] = -1.0
            self.lowest_vals[sensor_id] = 999999.0
            self.values_histories[sensor_id] = []
            if sensor_id in self.latest_formatted_lines:
                del self.latest_formatted_lines[sensor_id]
        
    def _init_db(self):
        import sqlite3
        import os
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.db_path = os.path.join(base_dir, "bupi_telemetry.db")
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS telemetry (
                    timestamp REAL,
                    sensor_id TEXT,
                    value REAL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS nodes (
                    client_id TEXT PRIMARY KEY,
                    device_name TEXT,
                    ip_address TEXT,
                    capabilities TEXT,
                    last_heartbeat REAL,
                    status TEXT
                )
            """)
            conn.commit()
            conn.close()
            print(f"[MQTT Bridge] SQLite database initialized at {self.db_path}", flush=True)
        except Exception as e:
            print(f"[MQTT Bridge Error] Failed to initialize SQLite: {e}", flush=True)

    def log_node_heartbeat(self, client_id, device_name, ip_address, capabilities, status="online"):
        """Records node heartbeat, IP, and online state into persistent SQLite database."""
        import sqlite3
        import time
        import threading
        import json
        
        def worker():
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                caps_str = json.dumps(capabilities) if not isinstance(capabilities, str) else capabilities
                cursor.execute("""
                    INSERT INTO nodes (client_id, device_name, ip_address, capabilities, last_heartbeat, status)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(client_id) DO UPDATE SET
                        device_name=excluded.device_name,
                        ip_address=excluded.ip_address,
                        capabilities=excluded.capabilities,
                        last_heartbeat=excluded.last_heartbeat,
                        status=excluded.status
                """, (client_id, device_name, ip_address, caps_str, time.time(), status))
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"[MQTT Bridge Error] Failed to log node heartbeat: {e}", flush=True)
                
        threading.Thread(target=worker, daemon=True).start()

    def log_to_db(self, sensor_id, value):
        import sqlite3
        import time
        import threading
        
        def worker():
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO telemetry (timestamp, sensor_id, value) VALUES (?, ?, ?)",
                    (time.time(), sensor_id, value)
                )
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"[MQTT Bridge Error] Failed to log to SQLite: {e}", flush=True)
                
        # Run in a background thread to prevent blocking
        threading.Thread(target=worker, daemon=True).start()

    def get_historical_readings(self, sensor_id, limit=100):
        """Returns the latest historical readings for a sensor from the persistent database."""
        import sqlite3
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT timestamp, value FROM telemetry WHERE sensor_id = ? ORDER BY rowid DESC LIMIT ?",
                (sensor_id, limit)
            )
            rows = cursor.fetchall()
            conn.close()
            # Convert to list of dicts, sorted chronologically (ascending timestamp)
            return [{"timestamp": r[0], "value": r[1]} for r in reversed(rows)]
        except Exception as e:
            print(f"[MQTT Bridge Error] Failed to query SQLite: {e}", flush=True)
            return []

    def get_average_reading(self, sensor_id, since_seconds=None):
        """Calculates the average reading of a sensor since a relative duration in seconds."""
        import sqlite3
        import time
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            if since_seconds:
                t_threshold = time.time() - since_seconds
                cursor.execute(
                    "SELECT AVG(value) FROM telemetry WHERE sensor_id = ? AND timestamp >= ?",
                    (sensor_id, t_threshold)
                )
            else:
                cursor.execute("SELECT AVG(value) FROM telemetry WHERE sensor_id = ?", (sensor_id,))
            val = cursor.fetchone()[0]
            conn.close()
            return val if val is not None else 0.0
        except Exception as e:
            print(f"[MQTT Bridge Error] Failed to query average: {e}", flush=True)
            return 0.0

    def get_max_reading(self, sensor_id, since_seconds=None):
        """Gets the maximum reading of a sensor since a relative duration in seconds."""
        import sqlite3
        import time
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            if since_seconds:
                t_threshold = time.time() - since_seconds
                cursor.execute(
                    "SELECT MAX(value) FROM telemetry WHERE sensor_id = ? AND timestamp >= ?",
                    (sensor_id, t_threshold)
                )
            else:
                cursor.execute("SELECT MAX(value) FROM telemetry WHERE sensor_id = ?", (sensor_id,))
            val = cursor.fetchone()[0]
            conn.close()
            return val if val is not None else 0.0
        except Exception as e:
            print(f"[MQTT Bridge Error] Failed to query max: {e}", flush=True)
            return 0.0

    def get_min_reading(self, sensor_id, since_seconds=None):
        """Gets the minimum reading of a sensor since a relative duration in seconds."""
        import sqlite3
        import time
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            if since_seconds:
                t_threshold = time.time() - since_seconds
                cursor.execute(
                    "SELECT MIN(value) FROM telemetry WHERE sensor_id = ? AND timestamp >= ?",
                    (sensor_id, t_threshold)
                )
            else:
                cursor.execute("SELECT MIN(value) FROM telemetry WHERE sensor_id = ?", (sensor_id,))
            val = cursor.fetchone()[0]
            conn.close()
            return val if val is not None else 0.0
        except Exception as e:
            print(f"[MQTT Bridge Error] Failed to query min: {e}", flush=True)
            return 0.0

    def get_sensor_status(self, sensor_id):
        """Fetches the latest reading for a sensor and returns its semantic translation."""
        import sqlite3
        from core.sensor_translator import translate_sensor_value
        try:
            # Query the latest reading from SQLite
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM telemetry WHERE sensor_id = ? ORDER BY rowid DESC LIMIT 1",
                (sensor_id,)
            )
            row = cursor.fetchone()
            conn.close()
            
            if row is not None:
                raw_val = row[0]
                return translate_sensor_value(sensor_id, raw_val)
        except Exception as e:
            print(f"[MQTT Bridge Error] Failed to get translated status: {e}", flush=True)
            
        # Fallback to RAM history if DB fails or is empty
        if sensor_id in self.values_histories and self.values_histories[sensor_id]:
            raw_val = self.values_histories[sensor_id][-1]
            return translate_sensor_value(sensor_id, raw_val)
            
        return {
            "sensor": sensor_id,
            "value": 0.0,
            "status": "Unknown",
            "description": "No readings received yet."
        }
        
    def connect(self):
        print(f"[MQTT Bridge] Connecting to {MQTT_BROKER}:{MQTT_PORT}...")
        try:
            self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.client.loop_start()
            
            # Subscribe to the internal event bus for hardware intents
            bus.subscribe("hardware_intent", self.on_hardware_intent)
            print("[MQTT Bridge] Subscribed to 'hardware_intent' on Event Bus.")
            
            # Start the dynamic display cycler thread
            import threading
            threading.Thread(target=self._display_cycler, daemon=True).start()
        except Exception as e:
            print(f"[MQTT Bridge] Failed to connect: {e}")

    def _display_cycler(self):
        """Background thread cycling active telemetry displays every 3 seconds if multiple are active."""
        import time
        current_index = 0
        while True:
            try:
                # Gather active sensor lines
                active_sensors = [
                    s for s, mode in self.telemetry_modes.items()
                    if mode is not None and s in self.latest_formatted_lines
                ]
                
                # Cycle display only if multiple sensors are active
                if len(active_sensors) > 1:
                    current_index = current_index % len(active_sensors)
                    sensor_id = active_sensors[current_index]
                    msg = self.latest_formatted_lines[sensor_id]
                    
                    if self._last_bridged.get("bupi/actuators/lcd/cmd") != msg:
                        self._last_bridged["bupi/actuators/lcd/cmd"] = msg
                        print(f"[MQTT Bridge] [Cycler] Displaying {sensor_id}: {msg}", flush=True)
                        self.client.publish("bupi/actuators/lcd/cmd", msg)
                    
                    current_index += 1
                time.sleep(3.0)
            except Exception as e:
                print(f"[MQTT Bridge Error] Cycler error: {e}", flush=True)
                time.sleep(3.0)

    def on_connect(self, client, userdata, flags, reason_code, properties):
        print(f"[MQTT Bridge] Connected to Mosquitto with result code {reason_code}")
        # Subscribe to all sensor and command topics to perform automatic bridging/translation
        client.subscribe("footmo2/+/sensor/#")
        client.subscribe("bupi/sensors/+/state")
        client.subscribe("bupi/sensors/+/lpg")
        client.subscribe("bupi/actuators/lcd/cmd")
        client.subscribe("bupi/nodes/desk_display/cmd")
        client.subscribe("bupi/nodes/announce")
        client.subscribe("bupi/nodes/heartbeat")
        client.subscribe("bupi/nodes/#")
        print("[MQTT Bridge] Subscribed to all bridging and node topics.")
        
    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        print("[MQTT Bridge] Disconnected from Mosquitto.")

    def on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8', errors='ignore')
            if not payload:
                return
                
            # 0. Node announcement and heartbeat tracking
            if topic in ["bupi/nodes/announce", "bupi/nodes/heartbeat"] or (topic.startswith("bupi/nodes/") and not topic.endswith("/cmd")):
                try:
                    data = json.loads(payload)
                    if isinstance(data, dict):
                        client_id = data.get("client_id") or data.get("device_id") or "ESP32_Node"
                        device_name = data.get("device") or data.get("name") or "ESP32 Device"
                        ip_addr = data.get("ip") or data.get("ip_address") or "unknown"
                        caps = data.get("capabilities", [])
                        status = data.get("status", "online")
                        self.log_node_heartbeat(client_id, device_name, ip_addr, caps, status)
                except Exception:
                    pass

            # Dynamic Sensor to LCD telemetry bridging & persistent DB logging
            sensor_id = None
            if topic.startswith("bupi/sensors/") and topic.endswith("/state"):
                sensor_id = topic.split("/")[2]
            elif topic.startswith("footmo2/") and "/sensor/" in topic:
                parts = topic.split("/")
                if len(parts) >= 4:
                    sensor_id = parts[3]
            elif topic.startswith("bupi/sensors/") and topic.endswith("/lpg"):
                sensor_id = "mq2"
                
            if sensor_id:
                raw_val = None
                try:
                    data = json.loads(payload)
                    if isinstance(data, dict):
                        for key in ["value", "lpg", "reading", "val", "lpg_ppm", "temp", "temperature", "humidity", "distance"]:
                            if key in data:
                                raw_val = float(data[key])
                                break
                    else:
                        raw_val = float(data)
                except Exception:
                    try:
                        raw_val = float(payload)
                    except Exception:
                        pass
                        
                if raw_val is not None:
                    # Always log incoming telemetry to persistent DB and update RAM history
                    self.log_to_db(sensor_id, raw_val)
                    if sensor_id not in self.highest_vals or self.highest_vals[sensor_id] == -1.0 or raw_val > self.highest_vals[sensor_id]:
                        self.highest_vals[sensor_id] = raw_val
                        
                    if sensor_id not in self.lowest_vals or self.lowest_vals[sensor_id] == 999999.0 or raw_val < self.lowest_vals[sensor_id]:
                        self.lowest_vals[sensor_id] = raw_val
                        
                    if sensor_id not in self.values_histories:
                        self.values_histories[sensor_id] = []
                    self.values_histories[sensor_id].append(raw_val)
                    if len(self.values_histories[sensor_id]) > 100:
                        self.values_histories[sensor_id].pop(0)
                        
                    # If telemetry display mode is active for this sensor, format and display on LCD
                    if self.telemetry_modes.get(sensor_id):
                        mode = self.telemetry_modes[sensor_id]
                        sensor_label = sensor_id.upper()
                        
                        def format_val(v):
                            try:
                                if v == int(v):
                                    return str(int(v))
                                return f"{v:.1f}"
                            except Exception:
                                return str(v)
                                
                        lcd_msg = None
                        if sensor_id == "mq2":
                            if mode == "continuous":
                                lcd_msg = f"MQ2: {int(raw_val)} ppm"
                            elif mode == "highest":
                                lcd_msg = f"MQ2 Max: {int(self.highest_vals[sensor_id])} ppm"
                            elif mode == "lowest":
                                lcd_msg = f"MQ2 Min: {int(self.lowest_vals[sensor_id])} ppm"
                            elif mode == "average":
                                avg_val = sum(self.values_histories[sensor_id]) / len(self.values_histories[sensor_id])
                                lcd_msg = f"MQ2 Avg: {int(avg_val)} ppm"
                        else:
                            if mode == "continuous":
                                lcd_msg = f"{sensor_label}: {format_val(raw_val)}"
                            elif mode == "highest":
                                lcd_msg = f"{sensor_label} Max: {format_val(self.highest_vals[sensor_id])}"
                            elif mode == "lowest":
                                lcd_msg = f"{sensor_label} Min: {format_val(self.lowest_vals[sensor_id])}"
                            elif mode == "average":
                                avg_val = sum(self.values_histories[sensor_id]) / len(self.values_histories[sensor_id])
                                lcd_msg = f"{sensor_label} Avg: {format_val(avg_val)}"
                                
                        if lcd_msg:
                            self.latest_formatted_lines[sensor_id] = lcd_msg
                            
                            active_sensors = [
                                s for s, m in self.telemetry_modes.items()
                                if m is not None and s in self.latest_formatted_lines
                            ]
                            
                            # Direct display updates if only one sensor is active (zero latency)
                            if len(active_sensors) <= 1:
                                if self._last_bridged.get("bupi/actuators/lcd/cmd") != lcd_msg:
                                    self._last_bridged["bupi/actuators/lcd/cmd"] = lcd_msg
                                    print(f"[MQTT Bridge] Auto-forwarding {sensor_id} -> LCD ({mode}): {lcd_msg}", flush=True)
                                    self.client.publish("bupi/actuators/lcd/cmd", lcd_msg)
                                    self.client.publish("bupi/nodes/desk_display/cmd", lcd_msg)
                        
                        # Direct display updates if only one sensor is active (zero latency)
                        # Direct display updates if only one sensor is active (zero latency)
                        if len(active_sensors) <= 1:
                            if self._last_bridged.get("bupi/actuators/lcd/cmd") != lcd_msg:
                                self._last_bridged["bupi/actuators/lcd/cmd"] = lcd_msg
                                print(f"[MQTT Bridge] Auto-forwarding {sensor_id} -> LCD ({mode}): {lcd_msg}", flush=True)
                                self.client.publish("bupi/actuators/lcd/cmd", lcd_msg)
                    
            # 1. Bridge from FootMo2 ESP32 topic to Bupi state topic
            # Topic format: footmo2/<device_id>/sensor/<sensor_name> -> bupi/sensors/<sensor_name>/state
            if topic.startswith("footmo2/") and "/sensor/" in topic:
                parts = topic.split("/")
                if len(parts) >= 4:
                    sensor_name = parts[3]
                    target_topic = f"bupi/sensors/{sensor_name}/state"
                    
                    try:
                        # Test if payload is already JSON (must be structured dict or list)
                        parsed = json.loads(payload)
                        if not isinstance(parsed, (dict, list)):
                            raise ValueError()
                        
                        # Recursively convert string numbers to float/int to be robust
                        def convert_numeric_strings(data):
                            if isinstance(data, dict):
                                return {k: convert_numeric_strings(v) for k, v in data.items()}
                            elif isinstance(data, list):
                                return [convert_numeric_strings(v) for v in data]
                            elif isinstance(data, str):
                                try:
                                    if "." in data:
                                        return float(data)
                                    else:
                                        return int(data)
                                except ValueError:
                                    return data
                            return data
                        
                        parsed = convert_numeric_strings(parsed)
                        target_payload = json.dumps(parsed)
                    except Exception:
                        # Try to cast payload to float or int first so JSON values are numerical
                        val = payload
                        try:
                            if "." in payload:
                                val = float(payload)
                            else:
                                val = int(payload)
                        except ValueError:
                            pass
                        # Otherwise wrap it in a clean JSON object
                        target_payload = json.dumps({"value": val, "lpg": val, "reading": val})
                        
                    # Prevent duplicate loopback
                    if self._last_bridged.get(target_topic) != target_payload:
                        self._last_bridged[target_topic] = target_payload
                        print(f"[MQTT Bridge] Bridging FootMo2 -> Bupi: {topic} -> {target_topic} | {target_payload}", flush=True)
                        self.client.publish(target_topic, target_payload, retain=True)
                    
            # 2. Bridge from Bupi state topic to FootMo2 sensor topic (for display / frontend visualization)
            # Topic format: bupi/sensors/<sensor_name>/state -> footmo2/esp32-001/sensor/<sensor_name>
            elif topic.startswith("bupi/sensors/") and topic.endswith("/state"):
                parts = topic.split("/")
                if len(parts) >= 3:
                    sensor_name = parts[2]
                    target_topic = f"footmo2/esp32-001/sensor/{sensor_name}"
                    
                    # Extract raw numerical reading from Bupi's JSON payload if present
                    raw_val = payload
                    try:
                        data = json.loads(payload)
                        if isinstance(data, dict):
                            for key in ["value", "lpg", "reading", "val", "lpg_ppm"]:
                                if key in data:
                                    raw_val = str(data[key])
                                    break
                    except Exception:
                        pass
                        
                    # Prevent duplicate loopback
                    if self._last_bridged.get(target_topic) != raw_val:
                        self._last_bridged[target_topic] = raw_val
                        print(f"[MQTT Bridge] Bridging Bupi -> FootMo2: {topic} -> {target_topic} | {raw_val}", flush=True)
                        self.client.publish(target_topic, raw_val, retain=True)
                    
            # 3. Bridge LCD commands from Bupi to FootMo2 ESP32 command topic
            elif topic == "bupi/actuators/lcd/cmd" or topic == "bupi/nodes/desk_display/cmd":
                target_topic = "footmo2/esp32-001/cmd"
                if self._last_bridged.get(target_topic) != payload:
                    self._last_bridged[target_topic] = payload
                    print(f"[MQTT Bridge] Bridging command: {topic} -> {target_topic} | {payload}", flush=True)
                    self.client.publish(target_topic, payload)
                
        except Exception as e:
            print(f"[MQTT Bridge] Error in bridging message: {e}", flush=True)

    async def on_hardware_intent(self, payload):
        """
        Triggered when an internal agent emits a hardware command.
        Validates and forwards it to the MQTT broker.
        """
        # Validate payload structure
        if "device" not in payload or "action" not in payload:
            print(f"[MQTT Bridge] Error: Invalid payload {payload}", flush=True)
            return
            
        topic = f"{COMMAND_TOPIC}/{payload['device']}"
        message = json.dumps({"action": payload["action"]})
        
        print(f"[MQTT Bridge] Publishing -> Topic: {topic} | Msg: {message}", flush=True)
        self.client.publish(topic, message)

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()
