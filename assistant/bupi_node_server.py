import asyncio
import websockets
import json
import threading
import time

connected_nodes = set()
_loop = None

# Live nodes presence tracking
live_nodes = {}
live_nodes_lock = threading.Lock()

def register_node(node_id, ip, conn_type, device="Unknown Device", capabilities=None, tasks=None):
    if capabilities is None:
        capabilities = []
    if tasks is None:
        tasks = []
    
    with live_nodes_lock:
        live_nodes[node_id] = {
            "id": node_id,
            "ip": ip,
            "type": conn_type,
            "device": device,
            "capabilities": capabilities,
            "tasks": tasks,
            "last_seen": time.time(),
            "status": "online"
        }
    broadcast_nodes()

def update_node_heartbeat(node_id):
    with live_nodes_lock:
        if node_id in live_nodes:
            live_nodes[node_id]["last_seen"] = time.time()
            if live_nodes[node_id]["status"] != "online":
                live_nodes[node_id]["status"] = "online"
                broadcast_nodes()

def mark_node_offline(node_id):
    with live_nodes_lock:
        if node_id in live_nodes and live_nodes[node_id]["status"] != "offline":
            live_nodes[node_id]["status"] = "offline"
            broadcast_nodes()

def check_node_timeouts():
    now = time.time()
    changed = False
    with live_nodes_lock:
        for node_id, node in live_nodes.items():
            if node["status"] == "online" and now - node["last_seen"] > 15:
                node["status"] = "offline"
                changed = True
    if changed:
        broadcast_nodes()

def broadcast_nodes():
    with live_nodes_lock:
        nodes_list = list(live_nodes.values())
    print(json.dumps({"type": "connected_nodes", "value": nodes_list}), flush=True)


async def handle_connection(websocket):
    ip = websocket.remote_address[0]
    print(f"From Python: [Hardware] New ESP32 connected! IP: {ip}", flush=True)
    connected_nodes.add(websocket)
    
    node_id = f"WS_{ip.replace('.', '_')}"
    # Register initially with basic info
    register_node(node_id, ip, "WebSocket", "ESP32 LCD Client", ["Display"], ["Displaying Bupi Status/Reminders"])
    
    try:
        async for message in websocket:
            print(f"From Python: [Hardware] Received from ESP32: {message}", flush=True)
            try:
                data = json.loads(message)
                if data.get("type") == "announce":
                    register_node(
                        node_id,
                        ip,
                        "WebSocket",
                        data.get("device", "ESP32 LCD Client"),
                        data.get("capabilities", ["Display"]),
                        data.get("tasks", ["Displaying Bupi Status/Reminders"])
                    )
                elif data.get("type") == "heartbeat":
                    update_node_heartbeat(node_id)
            except Exception:
                # Fallback to general heartbeat on raw messages
                update_node_heartbeat(node_id)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        print(f"From Python: [Hardware] ESP32 disconnected: {websocket.remote_address}", flush=True)
        connected_nodes.remove(websocket)
        mark_node_offline(node_id)


async def _send_to_esp32_async(title, message):
    if not connected_nodes:
        return

    payload = json.dumps({
        "title": title[:16],      # Keep under 16 chars for LCD
        "message": message[:16]   # Keep under 16 chars for LCD
    })

    print(f"From Python: [Hardware] Broadcasting: {payload}", flush=True)
    
    for node in connected_nodes:
        try:
            await node.send(payload)
        except Exception as e:
            print(f"From Python: [Hardware Error] Could not send: {e}", flush=True)


_message_override_until = 0

def send_to_esp32(title, message, duration=0):
    global _message_override_until
    
    # If this is an automated status update, check if we are locked by a custom message
    if title == "Bupi Status:" and time.time() < _message_override_until:
        return
        
    if duration > 0:
        _message_override_until = time.time() + duration

    """Thread-safe way for Bupi's main engine to send messages to the LCD"""
    
    # 1. Send via MQTT to the new Hive Display
    try:
        from actions.iot_agent import handle_iot_command
        # If there's a specific title, we can send it, otherwise just the message
        payload = f"{title} {message}".strip()
        if title == "Bupi Status:":
            payload = message # Keep it short for the LCD
        handle_iot_command("bupi/nodes/desk_display/cmd", payload)
    except Exception as e:
        print(f"From Python: [MQTT Error] Could not send to display: {e}", flush=True)
        
    # 2. Send via WebSockets to legacy displays
    if _loop is not None and _loop.is_running():
        asyncio.run_coroutine_threadsafe(_send_to_esp32_async(title, message), _loop)

async def _start_server():
    global _loop
    _loop = asyncio.get_running_loop()
    print("From Python: [Hardware] Starting ESP32 Server on port 8767...", flush=True)
    server = await websockets.serve(handle_connection, "0.0.0.0", 8767)
    await asyncio.Future()  # Run forever

def start_node_server():
    """Starts the WebSocket server in a background thread"""
    def run_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_start_server())
        
    t = threading.Thread(target=run_loop, daemon=True)
    t.start()
