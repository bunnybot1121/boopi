import paho.mqtt.client as mqtt
import json
import time

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
LISTEN_TOPIC = "bupi/cmd/#"

def on_connect(client, userdata, flags, reason_code, properties):
    print(f"[ESP32 Mock] Connected to broker. Listening on {LISTEN_TOPIC}")
    client.subscribe(LISTEN_TOPIC)

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        device = msg.topic.split("/")[-1]
        action = payload.get("action", "UNKNOWN")
        print(f"\n[ESP32 Mock] 🚨 HARDWARE TRIGGERED: Device '{device}' -> Action '{action}' 🚨\n")
    except json.JSONDecodeError:
        print(f"[ESP32 Mock] Received malformed JSON on {msg.topic}: {msg.payload.decode()}")

if __name__ == "__main__":
    print("Starting ESP32 Hardware Mock...")
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ESP32_Mock_Node_1")
    client.on_connect = on_connect
    client.on_message = on_message
    
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except KeyboardInterrupt:
        print("Stopping ESP32 Mock.")
        client.disconnect()
    except Exception as e:
        print(f"Failed to connect: {e}")
