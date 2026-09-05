import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

import os
import json
import time
import sqlite3
import asyncio
from openai import OpenAI
from core.safety_validator import get_current_world_state
import actions.hardware_tools as hw_tools

def _get_raw_tool(tool_obj):
    """Unwraps CrewAI or custom tool wrapper to get the raw callable function."""
    if hasattr(tool_obj, "func"):
        return tool_obj.func
    elif hasattr(tool_obj, "_run"):
        return tool_obj._run
    return tool_obj

# Define standard OpenAI-format tool schemas for local Ollama
LOCAL_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "control_relay",
            "description": "Turns a hardware relay ON or OFF on the ESP32.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "The relay identifier, e.g. 'relay_1'"},
                    "action": {"type": "string", "enum": ["turn_on", "turn_off"], "description": "The action to perform"}
                },
                "required": ["device_id", "action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "display_on_esp32",
            "description": "Displays a short text message on the ESP32 screen (LCD/OLED).",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The message to display"}
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_sensor_status",
            "description": "Reads the latest telemetry and semantic status for a sensor (e.g. 'mq2', 'distance', 'temp', 'humidity').",
            "parameters": {
                "type": "object",
                "properties": {
                    "sensor_id": {"type": "string", "description": "The sensor ID, e.g. 'mq2', 'temp', 'distance'"}
                },
                "required": ["sensor_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_world_state",
            "description": "Returns a full semantic snapshot of the physical environment (gas levels, tilt, distance, obstacles).",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "universal_mqtt_tool",
            "description": "Publishes an arbitrary payload to an MQTT topic to control custom actuators.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "The MQTT topic"},
                    "payload": {"type": "string", "description": "The payload string"}
                },
                "required": ["topic", "payload"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_robotic_code",
            "description": "Executes a custom Python script for complex closed-loop robotic control, sensor tracking, or background automation loops.",
            "parameters": {
                "type": "object",
                "properties": {
                    "script_code": {"type": "string", "description": "The complete Python script to execute"}
                },
                "required": ["script_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "control_motors",
            "description": "Drives the robot mobile base (forward, reverse, left, right, stop) with optional speed (0-255) and duration in seconds.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["forward", "reverse", "left", "right", "stop"], "description": "Direction to drive"},
                    "speed": {"type": "integer", "description": "Motor PWM speed 0 to 255 (default 200)"},
                    "duration_seconds": {"type": "number", "description": "Optional seconds to run before auto-stopping (0 for continuous)"}
                },
                "required": ["direction"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_hardware_knowledge",
            "description": "Retrieves exact offline specifications, pinouts, truth tables, and wiring guides for components like 'TB6612FNG', 'HC-SR04', 'MPU6050', 'MQ2', 'RELAY', 'ESP32_PINOUT'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "component_name": {"type": "string", "description": "The component name, e.g. 'TB6612FNG', 'HC-SR04', 'MPU6050', 'MQ2', 'RELAY', 'ESP32_PINOUT'"}
                },
                "required": ["component_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_connected_nodes",
            "description": "Queries all active ESP32 nodes connected to the system, their IP addresses, capabilities, and heartbeat status.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "start_autonomous_mission",
            "description": "Starts an autonomous closed-loop robotic mission (e.g. 'find the human in the room', 'patrol and inspect gas', 'explore and avoid obstacles'). Use this whenever the user asks Boopi to search, patrol, explore, or complete a multi-step objective on its own.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mission_description": {"type": "string", "description": "The high-level goal or mission description, e.g. 'find human in the room'"}
                },
                "required": ["mission_description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "stop_current_mission",
            "description": "Immediately cancels any active autonomous mission, halts motors, and sets Boopi to idle standby.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]

TOOL_DISPATCH_MAP = {
    "control_relay": _get_raw_tool(hw_tools.control_relay),
    "display_on_esp32": _get_raw_tool(hw_tools.display_on_esp32),
    "control_motors": _get_raw_tool(hw_tools.control_motors),
    "read_sensor_status": _get_raw_tool(hw_tools.read_sensor_status),
    "get_world_state": _get_raw_tool(hw_tools.get_world_state),
    "universal_mqtt_tool": _get_raw_tool(hw_tools.universal_mqtt_tool),
    "run_robotic_code": _get_raw_tool(hw_tools.run_robotic_code),
    "get_hardware_knowledge": _get_raw_tool(hw_tools.get_hardware_knowledge),
    "get_connected_nodes": _get_raw_tool(hw_tools.get_connected_nodes),
    "start_autonomous_mission": _get_raw_tool(hw_tools.start_autonomous_mission),
    "stop_current_mission": _get_raw_tool(hw_tools.stop_current_mission),
}

class LocalAgentOrchestrator:
    def __init__(self, ollama_url: str = "http://localhost:11434/v1"):
        self.ollama_url = ollama_url
        self.local_client = OpenAI(base_url=self.ollama_url, api_key="ollama")
        self.primary_model = "llama3.2:3b"
        self.fallback_model = "llama3.1:8b"
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.db_path = os.path.join(self.project_root, "bupi_telemetry.db")

    def _get_hardware_knowledge(self) -> str:
        mem_path = os.path.join(self.project_root, "hardware_memory.txt")
        if os.path.exists(mem_path):
            try:
                with open(mem_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    return content
            except Exception:
                pass
        return "Standard hardware: relay_1 on 'bupi/hardware/relay_1/set', desk_display on 'bupi/nodes/desk_display/cmd', mq2 gas sensor on 'bupi/sensors/mq2/state'."

    def run_task(self, user_request: str) -> str:
        """
        Executes a robotics task using local Ollama with native tool calling.
        Fast single-turn execution (<500ms on RTX 4050 GPU), 100% offline.
        """
        start_time = time.time()
        world_state = get_current_world_state()
        hw_knowledge = self._get_hardware_knowledge()

        system_prompt = f"""You are BUPI's Master Robotic Orchestrator. You are running 100% locally and offline.
Your goal is to fulfill the operator's hardware, navigation, and mission requests using the provided tools.

CURRENT PHYSICAL WORLD STATE:
{json.dumps(world_state, indent=2)}

REGISTERED HARDWARE KNOWLEDGE:
{hw_knowledge}

RULES:
1. For high-level autonomous tasks (e.g. 'find the human in the room', 'patrol the room', 'explore the area'), ALWAYS invoke start_autonomous_mission. Do NOT try to micromanage single wheel turns.
2. If the user asks to stop, halt, or cancel a mission, use stop_current_mission or control_motors('stop').
3. Prefer using tools directly (e.g. read_sensor_status, control_relay, display_on_esp32) instead of guessing.
4. If the user asks if the ESP32 is connected, call get_connected_nodes.
5. If the user asks about pinouts or wiring specs, call get_hardware_knowledge.
6. Keep spoken responses short, concise, and direct (under 2 sentences).
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_request}
        ]

        models_to_try = [self.primary_model, self.fallback_model]
        last_err = None

        for model_name in models_to_try:
            try:
                print(f"[Local Orchestrator] Executing with local model: {model_name}...", flush=True)
                resp = self.local_client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    tools=LOCAL_TOOLS_SCHEMA,
                    tool_choice="auto",
                    temperature=0.1
                )

                choice = resp.choices[0]
                message = choice.message
                tool_calls = getattr(message, "tool_calls", None)

                executed_results = []
                if tool_calls:
                    print(f"[Local Orchestrator] Model requested {len(tool_calls)} tool call(s).", flush=True)
                    for tc in tool_calls:
                        fn_name = tc.function.name
                        try:
                            fn_args = json.loads(tc.function.arguments)
                        except Exception:
                            fn_args = {}
                        
                        print(f"[Local Orchestrator] [TOOL] Dispatching: {fn_name}({fn_args})", flush=True)
                        tool_fn = TOOL_DISPATCH_MAP.get(fn_name)
                        if tool_fn:
                            try:
                                res = tool_fn(**fn_args)
                            except Exception as exec_err:
                                res = f"Tool execution error: {exec_err}"
                        else:
                            res = f"Error: Tool '{fn_name}' not registered."
                            
                        print(f"[Local Orchestrator] Tool result: {res}", flush=True)
                        executed_results.append(f"{fn_name}: {res}")

                    # Log decision to SQLite
                    self._log_decision(user_request, world_state, executed_results)

                    elapsed = (time.time() - start_time) * 1000
                    print(f"[Local Orchestrator] Completed in {elapsed:.1f}ms!", flush=True)

                    # Build quick spoken response
                    if message.content and message.content.strip():
                        return message.content.strip()
                    else:
                        first_result = executed_results[0]
                        if "Successfully" in first_result or "Success" in first_result:
                            return "Action executed successfully."
                        elif "read_sensor_status" in first_result or "mq2" in first_result:
                            return f"Here are the sensor readings: {first_result.split(': ', 1)[-1]}"
                        return f"Completed: {first_result}"

                else:
                    elapsed = (time.time() - start_time) * 1000
                    print(f"[Local Orchestrator] Text response in {elapsed:.1f}ms: '{message.content}'", flush=True)
                    self._log_decision(user_request, world_state, [message.content or ""])
                    return message.content or "I have processed your request."

            except Exception as e:
                print(f"[Local Orchestrator Warning] Execution with '{model_name}' failed: {e}", flush=True)
                last_err = e
                continue

        return f"Local orchestrator error: {last_err}"

    async def run_task_async(self, user_request: str) -> str:
        """Asynchronous wrapper to keep asyncio / PyQt event loops non-blocking."""
        return await asyncio.to_thread(self.run_task, user_request)

    def _log_decision(self, request: str, world_state: dict, results: list):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS decisions (
                    timestamp REAL,
                    world_state TEXT,
                    decision TEXT,
                    result TEXT
                )
            """)
            cursor.execute(
                "INSERT INTO decisions (timestamp, world_state, decision, result) VALUES (?, ?, ?, ?)",
                (time.time(), json.dumps(world_state), request, "; ".join(str(r) for r in results))
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[Local Orchestrator Error] Failed to log decision: {e}", flush=True)

# Global singleton
local_orchestrator = LocalAgentOrchestrator()
