import paho.mqtt.client as mqtt
import json
import time

BROKER_ADDRESS = "127.0.0.1"  # Local Mosquitto broker
BROKER_PORT = 1883

class IOTAgent:
    def __init__(self):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "Bupi_Hive_Mind")
        self.connected = False
        
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        
        # Connect non-blocking
        try:
            self.client.connect_async(BROKER_ADDRESS, BROKER_PORT, 60)
            self.client.loop_start()
        except Exception as e:
            print(f"[IOT Agent] Failed to start MQTT client: {e}", flush=True)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            self.connected = True
            print(f"[IOT Agent] Connected to Hive Mind Broker at {BROKER_ADDRESS}:{BROKER_PORT}", flush=True)
        else:
            print(f"[IOT Agent] Failed to connect: {reason_code}", flush=True)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        self.connected = False
        print("[IOT Agent] Disconnected from Hive Mind Broker.", flush=True)

    def send_command(self, node_topic: str, message: str) -> str:
        """
        Publishes a command to the specified MQTT topic.
        """
        if not self.connected:
            # Try to force a reconnect or just return error
            print("[IOT Agent] Warning: Not connected to MQTT Broker. Payload might be queued.", flush=True)

        try:
            # We publish as a simple string or JSON depending on the device needs
            # For the basic display, simple string is easiest.
            info = self.client.publish(node_topic, message, qos=1)
            info.wait_for_publish(timeout=2.0)
            
            if info.is_published():
                print(f"[IOT Agent] Successfully sent '{message}' to '{node_topic}'", flush=True)
                return f"Sent command '{message}' to IoT node {node_topic}."
            else:
                return f"Failed to confirm delivery to {node_topic}."
                
        except Exception as e:
            print(f"[IOT Agent] Publish error: {e}", flush=True)
            return f"Error sending MQTT command: {e}"

# Singleton instance
iot_agent = IOTAgent()

def handle_iot_command(topic: str, message: str) -> str:
    """Entry point for the Action Engine"""
    return iot_agent.send_command(topic, message)
