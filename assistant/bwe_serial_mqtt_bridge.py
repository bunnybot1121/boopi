import sys
import json
import time
import threading

# Reconfigure console streams
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("[Bridge Error] 'pyserial' package is not installed. Please run: pip install pyserial", flush=True)
    sys.exit(1)

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[Bridge Error] 'paho-mqtt' package is not installed. Please run: pip install paho-mqtt", flush=True)
    sys.exit(1)

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
ser = None
mqtt_client = None
running = True

# HIL Metrics & Diagnostics
packets_tx = 0
packets_rx = 0
error_count = 0
latency_ms = 0.0
last_send_time = 0.0
active_port = "None"

def find_esp32_port():
    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        desc = p.description.lower()
        if "silicon labs" in desc or "cp210x" in desc or "ch340" in desc or "usb-to-uart" in desc:
            print(f"[Bridge] Auto-detected ESP32 on port: {p.device} ({p.description})", flush=True)
            return p.device
    if ports:
        print(f"[Bridge] No explicit ESP32 board match. Using first available port: {ports[0].device}", flush=True)
        return ports[0].device
    return None

def publish_diagnostics():
    global mqtt_client, packets_tx, packets_rx, error_count, latency_ms, active_port
    try:
        stats = {
            "port": active_port,
            "latency": round(latency_ms, 1),
            "tx": packets_tx,
            "rx": packets_rx,
            "errors": error_count,
            "status": "online" if ser and ser.is_open else "offline"
        }
        mqtt_client.publish("bwe/esp32/stats", json.dumps(stats))
    except Exception:
        pass

def on_connect(client, userdata, flags, reason_code, properties):
    print(f"[Bridge] Connected to MQTT Broker at {MQTT_BROKER}:{MQTT_PORT}", flush=True)
    client.subscribe("bwe/simulator/write/#")
    publish_diagnostics()

def on_message(client, userdata, msg):
    global ser, packets_tx, last_send_time
    if not ser or not ser.is_open:
        return
        
    try:
        topic = msg.topic
        payload = json.loads(msg.payload.decode('utf-8'))
        
        if topic.startswith("bwe/simulator/write/"):
            pin = int(topic.split("/")[-1])
            val = float(payload.get("value", 0.0))
            
            packet = json.dumps({"type": "pin_value", "pin": pin, "val": val}) + "\n"
            
            # Start latency stopwatch
            last_send_time = time.time()
            ser.write(packet.encode('utf-8'))
            ser.flush()
            packets_tx += 1
            
            if packets_tx % 10 == 0:
                publish_diagnostics()
    except Exception as e:
        print(f"[Bridge Error] Failed to route MQTT -> Serial: {e}", flush=True)

def serial_reader_thread():
    global ser, mqtt_client, running, packets_rx, latency_ms, last_send_time, error_count
    print("[Bridge] Serial Reader Thread active.", flush=True)
    
    buffer = ""
    while running:
        if not ser or not ser.is_open:
            time.sleep(0.5)
            continue
            
        try:
            if ser.in_waiting > 0:
                char = ser.read().decode('utf-8', errors='ignore')
                if char == '\n':
                    if buffer.strip():
                        packets_rx += 1
                        # Calculate latency based on feedback confirmation
                        if last_send_time > 0.0 and ("SUCCESS" in buffer or "SUCCESS" in buffer.upper()):
                            latency_ms = (time.time() - last_send_time) * 1000.0
                            last_send_time = 0.0 # reset
                        process_serial_line(buffer.strip())
                    buffer = ""
                else:
                    buffer += char
            else:
                time.sleep(0.01)
        except Exception as e:
            print(f"[Bridge Error] Serial read error: {e}", flush=True)
            error_count += 1
            publish_diagnostics()
            time.sleep(1.0)

def process_serial_line(line):
    global mqtt_client, error_count
    try:
        data = json.loads(line)
        msg_type = data.get("type")
        pin = data.get("pin")
        val = data.get("val")
        
        if msg_type == "pin_write" and pin is not None and val is not None:
            topic = f"bwe/esp32/write/{pin}"
            payload = json.dumps({"value": val})
            mqtt_client.publish(topic, payload)
            
            # Periodically push diagnostics on incoming data
            if packets_rx % 5 == 0:
                publish_diagnostics()
    except Exception:
        # Check if it was an error or just a debug line
        if line.startswith("{"):
            error_count += 1
            publish_diagnostics()
        print(f"[ESP32 Debug] {line}", flush=True)

def main():
    global ser, mqtt_client, running, active_port
    print("\n==================================================")
    print("      BWE HIL Device-in-the-Loop Bridge")
    print("==================================================\n", flush=True)

    port = find_esp32_port()
    if not port:
        print("[Bridge Error] No USB Serial devices detected. Connect your ESP32 and try again.", flush=True)
        sys.exit(1)

    active_port = port

    try:
        ser = serial.Serial(port, 115200, timeout=1.0)
        print(f"[Bridge] Successfully opened Serial port {port} at 115200 baud.", flush=True)
    except Exception as e:
        print(f"[Bridge Error] Could not open Serial port {port}: {e}", flush=True)
        sys.exit(1)

    # Initialize MQTT
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="BWE_HIL_Bridge")
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
    except Exception as e:
        print(f"[Bridge Error] Failed to connect to Mosquitto broker: {e}", flush=True)
        sys.exit(1)

    # Start reader thread
    reader = threading.Thread(target=serial_reader_thread, daemon=True)
    reader.start()

    print("\n>>> HIL BRIDGE RUNNING <<<")
    print("Press Ctrl+C to terminate.\n", flush=True)

    # Push initial stats
    time.sleep(1)
    publish_diagnostics()

    try:
        while True:
            time.sleep(1)
            # Push periodic diagnostics pulse
            publish_diagnostics()
    except KeyboardInterrupt:
        print("\nShutting down HIL Bridge...", flush=True)
        running = False
        if ser:
            ser.close()
        mqtt_client.loop_stop()
        mqtt_client.disconnect()

if __name__ == "__main__":
    main()
