import sys
import json
import os
import random
import threading
from dotenv import load_dotenv

# Reconfigure stdout/stderr to UTF-8 to prevent cp1252 charmap encoding errors on Windows console
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from crewai import Agent, Task, Crew, Process, LLM
from actions.hardware_tools import control_relay, display_on_esp32, universal_mqtt_tool, read_mqtt_sensor, run_robotic_code

load_dotenv()

# litellm Key Rotation Patch (BUPI Rule 2: Non-blocking / Resilient API Calls)
import litellm
_original_completion = litellm.completion

def custom_completion(*args, **kwargs):
    model = kwargs.get("model", "")
    if "groq/" in model or model.startswith("groq"):
        import os, random
        groq_keys = [v.strip() for k, v in os.environ.items() if k.startswith("GROQ_API_KEY") and v.strip()]
        if groq_keys:
            kwargs["api_key"] = random.choice(groq_keys)
    elif "gemini/" in model or model.startswith("gemini"):
        import os, random
        google_keys = [v.strip() for k, v in os.environ.items() if k.startswith("GOOGLE_AI_STUDIO_KEY") and v.strip()]
        if google_keys:
            kwargs["api_key"] = random.choice(google_keys)
    elif "openrouter/" in model or model.startswith("openrouter"):
        import os, random
        openrouter_keys = [v.strip() for k, v in os.environ.items() if k.startswith("OPENROUTER_API_KEY") and v.strip()]
        if openrouter_keys:
            kwargs["api_key"] = random.choice(openrouter_keys)
    elif "deepseek-ai/" in model or "nvidia" in model:
        import os
        nvidia_key = os.environ.get("NVIDIA_API_KEY", "").strip()
        if nvidia_key:
            kwargs["api_key"] = nvidia_key
    return _original_completion(*args, **kwargs)

litellm.completion = custom_completion

try:
    from google import genai
    _original_genai_init = genai.Client.__init__
    def custom_genai_init(self, *args, **kwargs):
        import os, random
        google_keys = [v.strip() for k, v in os.environ.items() if k.startswith("GOOGLE_AI_STUDIO_KEY") and v.strip()]
        if google_keys:
            selected_key = random.choice(google_keys)
            if "api_key" in kwargs:
                kwargs["api_key"] = selected_key
            elif len(args) > 0:
                args_list = list(args)
                args_list[0] = selected_key
                args = tuple(args_list)
            else:
                kwargs["api_key"] = selected_key
        _original_genai_init(self, *args, **kwargs)
    genai.Client.__init__ = custom_genai_init
except Exception as e:
    print(f"[Robotic Crew Patch Warning] Failed to patch google-genai Client: {e}")

def run_robotic_task(user_request: str) -> str:
    """
    Executes the hierarchical multi-agent Crew.
    Dynamically loads the persistent agent registry, queries active online ESP32 capabilities,
    spawns persistent specialized sub-agents for any connected hardware, and kicks off the tasks.
    """
    # Gather OpenRouter keys
    openrouter_keys = []
    if os.environ.get("OPENROUTER_API_KEY") and os.environ.get("OPENROUTER_API_KEY").strip():
        openrouter_keys.append(os.environ.get("OPENROUTER_API_KEY").strip())
    for i in range(2, 11):
        key = os.environ.get(f"OPENROUTER_API_KEY_{i}")
        if key and key.strip():
            openrouter_keys.append(key.strip())

    # Gather Groq keys
    groq_keys = []
    if os.environ.get("GROQ_API_KEY") and os.environ.get("GROQ_API_KEY").strip():
        groq_keys.append(os.environ.get("GROQ_API_KEY").strip())
    for i in range(2, 11):
        key = os.environ.get(f"GROQ_API_KEY_{i}")
        if key and key.strip():
            groq_keys.append(key.strip())

    # Gather Google AI Studio keys
    google_keys = []
    if os.environ.get("GOOGLE_AI_STUDIO_KEY") and os.environ.get("GOOGLE_AI_STUDIO_KEY").strip():
        google_keys.append(os.environ.get("GOOGLE_AI_STUDIO_KEY").strip())
    for i in range(2, 11):
        key = os.environ.get(f"GOOGLE_AI_STUDIO_KEY_{i}")
        if key and key.strip():
            google_keys.append(key.strip())

    # Gather NVIDIA keys
    nvidia_keys = []
    if os.environ.get("NVIDIA_API_KEY") and os.environ.get("NVIDIA_API_KEY").strip():
        nvidia_keys.append(os.environ.get("NVIDIA_API_KEY").strip())

    # Try Gemini first, then fall back to Groq, then NVIDIA, then OpenRouter (prevents 429/402 quota exhaustion crashes)
    models_to_try = []
    if google_keys:
        models_to_try.append(("gemini/gemini-2.5-flash", google_keys, None))
    if groq_keys:
        models_to_try.append(("groq/llama-3.3-70b-versatile", groq_keys, None))
    if nvidia_keys:
        models_to_try.append(("openai/deepseek-ai/deepseek-v4-pro", nvidia_keys, "https://integrate.api.nvidia.com/v1"))
    if openrouter_keys:
        models_to_try.append(("openrouter/meta-llama/llama-3.3-70b-instruct:free", openrouter_keys, None))
    
    # Always append local Ollama fallback as the final option
    models_to_try.append(("ollama/llama3.2", ["ollama"], "http://localhost:11434/v1"))
        
    if not models_to_try:
        models_to_try.append(("gemini/gemini-2.5-flash", [""], None))

    last_error = None
    for model_name, keys_list, base_url in models_to_try:
        try:
            print(f"[Robotic Crew] Attempting execution with model: {model_name}...", flush=True)
            api_key = random.choice(keys_list)
            
            orchestrator_llm = LLM(
                model=model_name,
                api_key=api_key,
                base_url=base_url
            )

            # 2. Load Persistent Agent Registry from trained_agents.json
            agents_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "brain", "trained_agents.json")
            trained_agents = {}
            if os.path.exists(agents_file):
                try:
                    with open(agents_file, "r", encoding="utf-8") as f:
                        trained_agents = json.load(f)
                except Exception as e:
                    print(f"[Robotic Crew Error] Could not load trained_agents.json: {e}")

            # Ensure base templates exist in the registry
            if "robotic_orchestrator" not in trained_agents:
                trained_agents["robotic_orchestrator"] = {
                    "role": "Robotic Orchestrator",
                    "goal": "Fulfill the user request by planning and executing the required hardware actions using the available tools.",
                    "backstory": "You are the master robotic and IoT orchestrator of Bupi. You analyze user intents and coordinate specialized sensor and actuator sub-agents to achieve seamless hardware actions."
                }

            # 3. Query dynamic plug-and-play active online nodes
            from bupi_node_server import live_nodes, live_nodes_lock
            active_devices = []
            with live_nodes_lock:
                for node in live_nodes.values():
                    if node.get("status") == "online":
                        active_devices.append(node)

            print(f"[Robotic Crew] Discovered {len(active_devices)} online ESP32 hardware devices.", flush=True)

            # 4. Dynamically spawn specialized sub-agents based on online capabilities and persist them
            crew_agents = []
            crew_tasks = []
            registry_updated = False

            # Instantiate the master Robotic Orchestrator Agent
            orchestrator_config = trained_agents["robotic_orchestrator"]
            orchestrator_agent = Agent(
                role=orchestrator_config["role"],
                goal=orchestrator_config["goal"],
                backstory=orchestrator_config["backstory"],
                verbose=True,
                allow_delegation=True,
                tools=[control_relay, display_on_esp32, universal_mqtt_tool, read_mqtt_sensor, run_robotic_code],
                llm=orchestrator_llm
            )
            crew_agents.append(orchestrator_agent)

            # For each online device capability, retrieve from registry or dynamically spawn a persistent sub-agent
            for dev in active_devices:
                dev_name = dev.get("device", "ESP32 Device")
                dev_id_safe = dev.get("id", "esp32_device").lower().replace(" ", "_").replace("-", "_")
                capabilities = dev.get("capabilities", [])

                # Spawn Sensor Listener Sub-Agent if the device has a Sensor capability
                if "Sensor" in capabilities:
                    agent_id = f"sensor_listener_{dev_id_safe}"
                    if agent_id not in trained_agents:
                        trained_agents[agent_id] = {
                            "role": f"Sensor Listener for {dev_name}",
                            "goal": f"Monitor telemetry, track values, and check thresholds for the {dev_name} sensor connected to the ESP32.",
                            "backstory": f"You are a persistent, specialized sensor listener sub-agent trained specifically to read, monitor, and process data from the {dev_name}."
                        }
                        registry_updated = True
                    
                    sub_config = trained_agents[agent_id]
                    sensor_agent = Agent(
                        role=sub_config["role"],
                        goal=sub_config["goal"],
                        backstory=sub_config["backstory"],
                        verbose=True,
                        allow_delegation=False,
                        tools=[],
                        llm=orchestrator_llm
                    )
                    crew_agents.append(sensor_agent)

                    # Create specific task for this sensor sub-agent
                    sensor_task = Task(
                        description=f"Monitor the telemetry and readings generated by the '{dev_name}' sensor. Detect any data changes or threshold shifts.",
                        expected_output=f"A structured log or reading report from the '{dev_name}' sensor.",
                        agent=sensor_agent
                    )
                    crew_tasks.append(sensor_task)

                # Spawn Actuator/Display Controller Sub-Agent if the device has a Display/Actuator capability
                if "Display" in capabilities or "Actuator" in capabilities:
                    agent_id = f"actuator_controller_{dev_id_safe}"
                    if agent_id not in trained_agents:
                        trained_agents[agent_id] = {
                            "role": f"Actuator Controller for {dev_name}",
                            "goal": f"Directly format display strings, control signals, and write outputs to the {dev_name} screen/actuator.",
                            "backstory": f"You are a persistent, specialized actuator dispatcher sub-agent trained specifically to send formatted screen displays and trigger control signals for the {dev_name}."
                        }
                        registry_updated = True
                    
                    sub_config = trained_agents[agent_id]
                    actuator_agent = Agent(
                        role=sub_config["role"],
                        goal=sub_config["goal"],
                        backstory=sub_config["backstory"],
                        verbose=True,
                        allow_delegation=False,
                        tools=[],
                        llm=orchestrator_llm
                    )
                    crew_agents.append(actuator_agent)

                    # Create specific task for this actuator sub-agent
                    actuator_task = Task(
                        description=f"Format and execute the display text or physical control commands for the '{dev_name}' actuator/screen.",
                        expected_output=f"A confirmation that the command was successfully dispatched to the '{dev_name}'.",
                        agent=actuator_agent
                    )
                    crew_tasks.append(actuator_task)

            # 5. Save updated registry to disk persistently
            if registry_updated:
                try:
                    with open(agents_file, "w", encoding="utf-8") as f:
                        json.dump(trained_agents, f, indent=2)
                    print(f"[Robotic Crew] Persistent agent registry updated in '{agents_file}'.", flush=True)
                except Exception as e:
                    print(f"[Robotic Crew Error] Could not save trained_agents.json: {e}")

            # 6. Load dynamic hardware knowledge
            mem_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "hardware_memory.txt")
            hardware_knowledge = ""
            if os.path.exists(mem_path):
                with open(mem_path, "r", encoding="utf-8") as f:
                    hardware_knowledge = f.read().strip()
                    
            if not hardware_knowledge:
                hardware_knowledge = "No dynamic hardware learned yet. You can only use 'relay_1' (tool: control_relay) and the default display (tool: display_on_esp32)."

            # 7. Create the master Orchestration Task
            orchestrator_task = Task(
                description=f"User Request: '{user_request}'.\n\nHere is the complete hardware knowledge:\n{hardware_knowledge}\n\nCo-ordinate the dynamically spawned sensor listener and actuator controller sub-agents to achieve the goal. Plan the overall telemetry processing loop.\n\nCRITICAL FOR CONTINUOUS AUTOMATIONS/TRIGGERS:\nIf the request requires continuous automation or value tracking, you MUST use the `run_robotic_code` tool to execute a Python script. The script should run a non-blocking loop (by starting a `threading.Thread` loop) to subscribe to sensor topics (e.g. `bupi/sensors/+/state` or `footmo2/esp32-001/sensor/+`), read values, perform checks/math, and publish the output to the command/display topics.",
                expected_output="A very short, highly concise, and conversational companion notification (under 2 sentences) indicating that the loop/action has been successfully established and is active. Keep it simple and direct.",
                agent=orchestrator_agent
            )
            crew_tasks.append(orchestrator_task)

            # 8. Kick off hierarchical crew execution
            crew = Crew(
                agents=crew_agents,
                tasks=crew_tasks,
                process=Process.sequential,
                verbose=True
            )

            result = crew.kickoff()
            return str(result)
            
        except Exception as e:
            print(f"[Robotic Crew Warning] Crew execution failed with {model_name} due to: {e}", flush=True)
            last_error = e
            
    # If all models failed, raise the last encountered error
    raise last_error
