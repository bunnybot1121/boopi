import sys
import os
import asyncio

# Ensure Python can find the 'core' module from the parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event_bus_async import bus
from core.mqtt_bridge import MQTTBridge
from agents.router_agent import router

def on_tts_intent(payload):
    print(f"\n🗣️ [BUPI SPEAKS]: {payload.get('text', '')}")

async def cli_loop():
    print("\n--- BUPI AI Interface ---")
    print("Type anything! E.g. 'turn on the lights' or 'how are you?'")
    print("Type 'exit' to quit.")
    
    while True:
        # We use asyncio.to_thread to not block the event loop while waiting for input
        cmd = await asyncio.to_thread(input, "\n[YOU] > ")
        cmd = cmd.strip()
        
        if cmd.lower() in ["exit", "quit"]:
            break
            
        if cmd:
            await bus.publish("user_utterance", {"text": cmd})
            
        # Give a small delay to let async callbacks fire and LLM to respond
        await asyncio.sleep(0.5)

async def main():
    # Start the bridge to listen for hardware events
    bridge = MQTTBridge()
    bridge.connect()
    
    # Start the Router Agent
    router.start()
    
    # Listen for BUPI talking back
    bus.subscribe("tts_intent", on_tts_intent)
    
    # Run the CLI loop
    await cli_loop()
    
    # Cleanup
    bridge.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting CLI...")
