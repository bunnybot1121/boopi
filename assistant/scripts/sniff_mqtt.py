import paho.mqtt.client as mqtt
import time

def on_message(client, userdata, msg):
    print(f"[{msg.topic}] {msg.payload.decode('utf-8', errors='ignore')}", flush=True)

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="Sniffer")
client.on_message = on_message
client.connect("127.0.0.1", 1883, 60)
client.subscribe("#")
client.loop_start()
print("Listening for MQTT messages for 6 seconds...", flush=True)
time.sleep(6)
client.loop_stop()
print("Done sniffing.", flush=True)
