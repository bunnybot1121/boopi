import asyncio
import websockets
import json
import threading

connected_nodes = set()
_loop = None

async def handle_connection(websocket):
    print(f"From Python: [Hardware] New ESP32 connected! IP: {websocket.remote_address}", flush=True)
    connected_nodes.add(websocket)
    try:
        async for message in websocket:
            print(f"From Python: [Hardware] Received from ESP32: {message}", flush=True)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        print(f"From Python: [Hardware] ESP32 disconnected: {websocket.remote_address}", flush=True)
        connected_nodes.remove(websocket)

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

def send_to_esp32(title, message):
    """Thread-safe way for Bupi's main engine to send messages to the LCD"""
    if _loop is not None and _loop.is_running():
        asyncio.run_coroutine_threadsafe(_send_to_esp32_async(title, message), _loop)

async def _start_server():
    global _loop
    _loop = asyncio.get_running_loop()
    print("From Python: [Hardware] Starting ESP32 Server on port 8765...", flush=True)
    server = await websockets.serve(handle_connection, "0.0.0.0", 8765)
    await asyncio.Future()  # Run forever

def start_node_server():
    """Starts the WebSocket server in a background thread"""
    def run_loop():
        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_start_server())
        
    t = threading.Thread(target=run_loop, daemon=True)
    t.start()
