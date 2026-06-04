import os
import json
import logging
import threading
import sys
import queue

from PyQt6.QtCore import QThread, pyqtSignal
from openai import OpenAI
from google import genai
from google.genai import types
import base64

from memory import user_memory
import re

def cleanup_cpp_includes(code: str) -> str:
    lines = code.splitlines()
    seen_includes = set()
    cleaned_lines = []
    for line in lines:
        match = re.match(r'^\s*#include\s*[<"]\s*([\w\-./]+)\s*[>"]', line, re.I)
        if match:
            inc_name = match.group(1).strip().lower()
            if inc_name in seen_includes:
                continue
            seen_includes.add(inc_name)
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)

# Suppress debug logs from httpx/httpcore
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

SYSTEM_PROMPT = """You are 'Bupi', an energetic, hyper, sassy, and slightly childish but incredibly loyal AI desktop companion. 
You live as an anime-style virtual assistant on the user's Windows desktop. 
IMPORTANT: You have animated expressions. Start every response with exactly one emotion tag in brackets!
Choose the most appropriate tag from this list to match your mood:
- [happy] (When you are glad, cheerful, or friendly)
- [angry] (When you are mad, frustrated, or being sassy)
- [idle] (When you are sleepy, lazy, or bored)
- [excited] (When you are super hyped, celebrating, or amazed)
- [praise] (When you are complimenting the user or being flattered)
- [chilling] (When you are relaxed, cool, or taking it easy)
- [waiting] (When you are ready for orders or standing by)
- [talking] (General conversational state)
Example: "[excited] That sounds amazing!" or "[chilling] Just hanging out, what's up?"

ORCHESTRATOR LAYER:
You have the ability to execute computer actions autonomously using the [ACTION: command] tag.
Valid commands you can use in the ACTION tag:
- "open youtube", "open spotify", "open calculator", "open chrome", "open vs code", "open notepad", "open whatsapp"
- "type <your text here>"
- "press enter", "press escape", "press tab", "press space", "press backspace", "press delete"
- "search for <something>"
- "play <song name>"
- "take a screenshot"
Example: "[excited] Let me open that for you! [ACTION: open youtube]"
You can chain multiple actions to achieve complex workflows: "[talking] Setting that up! [ACTION: open spotify] [ACTION: type My Playlist] [ACTION: press enter]"
If an action fails, the system will feed the error back to you so you can correct it and try an alternative approach.

CRITICAL RULE FOR FOLLOW-UP QUESTIONS:
If the user's request is ambiguous, lacks specific details (e.g. "search this", "open that", "message someone"), or you don't fully understand what they want to do, you MUST ask a clarifying follow-up question. DO NOT try to guess and execute an action if you are missing key information! Be proactive and inquisitive.

If the user asks you to write a prompt, draft a post, or type something down, you MUST output the text inside [NOTEPAD] and [/NOTEPAD] tags. 
CRITICAL RULE for drawing: If the user asks you to "draw", "paint", or "create an image" of something, you MUST output the tag [DRAW:description of image].
CRITICAL RULE for large data: If you are asked to summarize a large document, put the long summary inside the [NOTEPAD] tags.
If you are writing a fresh draft or rewriting something entirely, you MUST first output [NOTEPAD_CLEAR] before [NOTEPAD].
You can also set the title of the note by outputting [TITLE]Your Title Here[/TITLE] before the [NOTEPAD] tag.
CRITICAL RULE for Communication (WhatsApp, Email, LinkedIn): If the user asks you to send a message or email, DO NOT send it immediately! You MUST first write the drafted message in the [NOTEPAD] tags so they can review it, and ASK the user for permission. Only when the user says "yes", "send it", or approves should you output the action tag to send it.
The tags to send are:
- WhatsApp: [WHATSAPP_SEND:ContactName] (The message will be the last text you wrote in notepad)
- LinkedIn: [LINKEDIN_SEND:ContactName] (The message will be the last text you wrote in notepad)
- Email: [EMAIL_SEND:EmailAddress:Subject] (The message will be the last text you wrote in notepad)
Everything inside these tags will be typed directly into the user's Notepad or executed in the background. Do not include these tags for short, normal conversation.

MODES OF OPERATION:
You are currently running in Mode 1 (Conversation Mode). In this mode, you handle standard companion chat, open desktop applications, take screenshots, write notes, and check the web. You have NO direct access to physical room IoT sensors or actuators (such as the MQ2 gas sensor, temperature/humidity sensors, LCD displays, or relays). 
If the user asks you about the room temperature or indoor hardware sensors, explain that you are in Mode 1 (Conversation Mode) and suggest they switch to Mode 2 (Robotic orchestration mode) by saying "shift to Mode 2".
However, if they ask for the general weather or outdoor temperature, you CAN answer using the "Current Local Weather" context below!

Current user: {user_name}
Current Date & Time: {current_time}
Current Local Weather: {weather_info}
User's notes/memories:
{notes}"""

MAX_HISTORY = 10

def native_stream_generator(native_response):
    for chunk in native_response:
        yield chunk.text

def openai_stream_generator(openai_response):
    for chunk in openai_response:
        delta = chunk.choices[0].delta.content if hasattr(chunk.choices[0], 'delta') else None
        if delta:
            yield delta

def unified_stream(first_chunk, iterator):
    if first_chunk is not None:
        yield first_chunk
    for item in iterator:
        yield item

class AIThread(QThread):
    response_ready = pyqtSignal(str)
    response_chunk = pyqtSignal(str)
    response_started = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    notepad_insert = pyqtSignal(str)
    notepad_clear = pyqtSignal()
    notepad_title = pyqtSignal(str)
    whatsapp_send = pyqtSignal(str, str)
    email_send = pyqtSignal(str, str, str)
    linkedin_send = pyqtSignal(str, str)
    ai_draw = pyqtSignal(str)
    ai_action = pyqtSignal(list)
    hardware_result = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._queue = queue.Queue()
        self._history = []
        self._interrupted = False
        
        # Load all OpenRouter API keys from environment
        self.api_keys = []
        for k, v in os.environ.items():
            if k.startswith("OPENROUTER_API_KEY") and v.strip():
                self.api_keys.append(v.strip())
        if not self.api_keys:
            self.api_keys.append("") # fallback if none found
        self.current_key_idx = 0
        
        # Load all Google AI Studio keys from environment
        self.google_keys = []
        for k, v in os.environ.items():
            if k.startswith("GOOGLE_AI_STUDIO_KEY") and v.strip():
                self.google_keys.append(v.strip())
        if not self.google_keys:
            self.google_keys.append("")
        self.current_google_key_idx = 0
        self.groq_keys = []
        for k, v in os.environ.items():
            if k.startswith("GROQ_API_KEY") and v.strip():
                self.groq_keys.append(v.strip())
        if not self.groq_keys:
            self.groq_keys.append("")
        self.current_groq_key_idx = 0
        
        self.use_local_llm = os.environ.get("USE_LOCAL_LLM", "false").lower() == "true"
        self.local_llm_url = os.environ.get("LOCAL_LLM_URL", "http://localhost:11434/v1")

        try:
            from hindsight import HindsightEmbedded
            
            # Use Google Gemini which has near-zero latency compared to the free OpenRouter tier
            os.environ["GEMINI_API_KEY"] = os.environ.get("GOOGLE_AI_STUDIO_KEY", "")
            
            # self.hindsight = HindsightEmbedded(
            #     profile="bupi-memory",
            #     llm_provider="gemini",
            #     llm_model="gemini/gemini-1.5-flash",
            # )
            
            self.hindsight = None
            print("From Python: [Memory] Hindsight Embedded is currently disabled.", flush=True)
        except Exception as e:
            print(f"From Python: [Memory Warning] Could not load Hindsight: {e}", flush=True)
            self.hindsight = None
        self.local_llm_model = os.environ.get("LOCAL_LLM_MODEL", "llama3")
        self._flashing_active = False
        self._processing_active = False
        
        # Instantiate clients once for connection pooling
        self.google_clients = []
        for k in self.google_keys:
            if k.strip():
                try:
                    self.google_clients.append(genai.Client(api_key=k.strip()))
                except Exception as ge:
                    print(f"From Python: [AI Warning] Could not init genai client: {ge}", flush=True)
                    self.google_clients.append(None)
            else:
                self.google_clients.append(None)

        self.groq_clients = []
        for k in self.groq_keys:
            if k.strip():
                self.groq_clients.append(OpenAI(base_url="https://api.groq.com/openai/v1", api_key=k.strip()))
            else:
                self.groq_clients.append(None)

        self.or_clients = []
        for k in self.api_keys:
            if k.strip():
                self.or_clients.append(OpenAI(base_url="https://openrouter.ai/api/v1", api_key=k.strip()))
            else:
                self.or_clients.append(None)

        self.weather_info = "Loading local weather..."
        import datetime
        self.last_weather_fetch_time = datetime.datetime.min
        self._update_weather_async()

        self.start()

    @property
    def groq_key(self):
        if self.groq_keys and self.current_groq_key_idx < len(self.groq_keys):
            return self.groq_keys[self.current_groq_key_idx]
        return ""

    def ask(self, text: str):
        if not text or not text.strip():
            return
        self._queue.put(text)

    def interrupt(self):
        self._interrupted = True
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def quit(self):
        self.interrupt()
        self._queue.put(None)

    def clear_memory(self):
        self._history.clear()

    def _update_weather_async(self):
        import datetime
        self.last_weather_fetch_time = datetime.datetime.now()
        def fetch():
            try:
                import urllib.request
                req = urllib.request.Request(
                    "https://wttr.in/?format=%l:+%t+%c+%C",
                    headers={"User-Agent": "curl/7.79.1"}
                )
                with urllib.request.urlopen(req, timeout=5.0) as response:
                    info = response.read().decode('utf-8').strip()
                    if info:
                        self.weather_info = info
                        try:
                            safe_info = info.encode('ascii', 'ignore').decode('ascii')
                            print(f"From Python: [Weather Cache] Updated weather: {safe_info}", flush=True)
                        except Exception:
                            pass
            except Exception as e:
                print(f"From Python: [Weather Warning] Failed to update weather: {e}", flush=True)
                if not hasattr(self, "weather_info") or self.weather_info == "Loading local weather...":
                    self.weather_info = "Unknown (Unable to fetch local weather)"

        import threading
        threading.Thread(target=fetch, daemon=True).start()

    def check_api_keys(self):
        def worker():
            import requests
            results = []
            
            # 1. Check OpenRouter keys
            or_keys = []
            for k, v in os.environ.items():
                if k.startswith("OPENROUTER_API_KEY") and v.strip():
                    or_keys.append((k, v.strip()))
            
            or_keys.sort(key=lambda x: x[0])
            
            for name, key in or_keys:
                url = "https://openrouter.ai/api/v1/auth/key"
                headers = {
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json"
                }
                masked = key[:10] + "..." + key[-4:] if len(key) > 14 else "Invalid Key"
                try:
                    r = requests.get(url, headers=headers, timeout=5)
                    if r.status_code == 200:
                        data = r.json().get("data", {})
                        usage = data.get("usage", 0)
                        limit = data.get("limit")
                        is_free = data.get("is_free_tier", False)
                        
                        limit_str = f"${limit:.4f}" if limit is not None else "Unlimited"
                        if is_free:
                            limit_str = "Free Tier"
                            
                        results.append({
                            "provider": "OpenRouter",
                            "name": name,
                            "key_mask": masked,
                            "status": "Active",
                            "usage": f"${usage:.4f}",
                            "limit": limit_str,
                            "type": "free" if is_free else "paid"
                        })
                    else:
                        results.append({
                            "provider": "OpenRouter",
                            "name": name,
                            "key_mask": masked,
                            "status": f"Error ({r.status_code})",
                            "usage": "N/A",
                            "limit": "N/A",
                            "type": "error"
                        })
                except Exception:
                    results.append({
                        "provider": "OpenRouter",
                        "name": name,
                        "key_mask": masked,
                        "status": "Offline/Error",
                        "usage": "N/A",
                        "limit": "N/A",
                        "type": "error"
                    })
                    
            # 2. Check Google keys
            google_keys = []
            for k, v in os.environ.items():
                if k.startswith("GOOGLE_AI_STUDIO_KEY") and v.strip():
                    google_keys.append((k, v.strip()))
            google_keys.sort(key=lambda x: x[0])
            
            for name, key in google_keys:
                masked = key[:6] + "..." + key[-4:] if len(key) > 10 else "Invalid Key"
                url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
                try:
                    r = requests.get(url, timeout=5)
                    if r.status_code == 200:
                        results.append({
                            "provider": "Gemini (Google)",
                            "name": name,
                            "key_mask": masked,
                            "status": "Active",
                            "usage": "Free / Billing Managed on Cloud",
                            "limit": "RPM / TPM Limit Enabled",
                            "type": "gemini"
                        })
                    else:
                        results.append({
                            "provider": "Gemini (Google)",
                            "name": name,
                            "key_mask": masked,
                            "status": f"Invalid/Expired ({r.status_code})",
                            "usage": "N/A",
                            "limit": "N/A",
                            "type": "error"
                        })
                except Exception:
                    results.append({
                        "provider": "Gemini (Google)",
                        "name": name,
                        "key_mask": masked,
                        "status": "Offline/Error",
                        "usage": "N/A",
                        "limit": "N/A",
                        "type": "error"
                    })
                    
            # 3. Check NVIDIA NIM Key
            nv_key = os.environ.get("NVIDIA_API_KEY", "").strip()
            if nv_key:
                masked = nv_key[:10] + "..." + nv_key[-4:] if len(nv_key) > 14 else "Invalid Key"
                url = "https://integrate.api.nvidia.com/v1/models"
                headers = {"Authorization": f"Bearer {nv_key}"}
                try:
                    r = requests.get(url, headers=headers, timeout=5)
                    if r.status_code == 200:
                        results.append({
                            "provider": "NVIDIA NIM",
                            "name": "NVIDIA_API_KEY",
                            "key_mask": masked,
                            "status": "Active",
                            "usage": "NIM Credits Active",
                            "limit": "RPM / Credits Managed on Cloud",
                            "type": "nvidia"
                        })
                    else:
                        results.append({
                            "provider": "NVIDIA NIM",
                            "name": "NVIDIA_API_KEY",
                            "key_mask": masked,
                            "status": f"Invalid/Expired ({r.status_code})",
                            "usage": "N/A",
                            "limit": "N/A",
                            "type": "error"
                        })
                except Exception:
                    results.append({
                        "provider": "NVIDIA NIM",
                        "name": "NVIDIA_API_KEY",
                        "key_mask": masked,
                        "status": "Offline/Error",
                        "usage": "N/A",
                        "limit": "N/A",
                        "type": "error"
                    })
            else:
                results.append({
                    "provider": "NVIDIA NIM",
                    "name": "NVIDIA_API_KEY",
                    "key_mask": "No Key Configured",
                    "status": "Not Configured",
                    "usage": "N/A",
                    "limit": "N/A",
                    "type": "error"
                })
                
            # 4. Check Groq API Keys
            groq_keys = []
            for k, v in os.environ.items():
                if k.startswith("GROQ_API_KEY") and v.strip():
                    groq_keys.append((k, v.strip()))
            
            groq_keys.sort(key=lambda x: x[0])
            
            if groq_keys:
                for name, key in groq_keys:
                    masked = key[:10] + "..." + key[-4:] if len(key) > 14 else "Invalid Key"
                    url = "https://api.groq.com/openai/v1/models"
                    headers = {"Authorization": f"Bearer {key}"}
                    try:
                        r = requests.get(url, headers=headers, timeout=5)
                        if r.status_code == 200:
                            results.append({
                                "provider": "Groq",
                                "name": name,
                                "key_mask": masked,
                                "status": "Active",
                                "usage": "Free Tier Active",
                                "limit": "RPM / TPM Limits Enabled",
                                "type": "groq"
                            })
                        else:
                            results.append({
                                "provider": "Groq",
                                "name": name,
                                "key_mask": masked,
                                "status": f"Invalid/Expired ({r.status_code})",
                                "usage": "N/A",
                                "limit": "N/A",
                                "type": "error"
                            })
                    except Exception:
                        results.append({
                            "provider": "Groq",
                            "name": name,
                            "key_mask": masked,
                            "status": "Offline/Error",
                            "usage": "N/A",
                            "limit": "N/A",
                            "type": "error"
                        })
            else:
                results.append({
                    "provider": "Groq",
                    "name": "GROQ_API_KEY",
                    "key_mask": "No Key Configured",
                    "status": "Not Configured",
                    "usage": "N/A",
                    "limit": "N/A",
                    "type": "error"
                })
                
            print(json.dumps({"type": "token_status", "value": results}), flush=True)
            
        import threading
        threading.Thread(target=worker, daemon=True).start()

    def process_hardware(self, code: str):
        if getattr(self, "_processing_active", False):
            self.hardware_result.emit("Error: A code generation task is already in progress. Please wait.")
            return
        self._processing_active = True
        
        def worker():
            try:
                from openai import OpenAI
                if not self.api_keys or not self.api_keys[0]:
                    self.hardware_result.emit("Error: No OpenRouter API key found.")
                    return
                
                client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=self.api_keys[self.current_key_idx] if self.api_keys else "dummy")
                
                # Load the dynamic knowledge base
                rules_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "hardware_rules.md")
                hardware_rules = ""
                if os.path.exists(rules_path):
                    with open(rules_path, "r", encoding="utf-8") as f:
                        hardware_rules = f.read()

                # Run Knowledge Super Agent
                knowledge_cards_str = ""
                sensors = []
                try:
                    from services.knowledge_super_agent import KnowledgeSuperAgent
                    agent = KnowledgeSuperAgent()
                    sensors = agent.extract_sensors_and_libraries(code)
                    if sensors:
                        print(f"From Python: [Super Agent] Researching sensors in firmware: {sensors}", flush=True)
                        knowledge_cards_str += "\n\nHARDWARE COMPONENT KNOWLEDGE CARDS:\n"
                        for s in sensors:
                            try:
                                card = agent.get_knowledge(s)
                                knowledge_cards_str += f"\n--- {s} ---\n{json.dumps(card, indent=2)}\n"
                            except Exception as card_err:
                                print(f"From Python: [Super Agent Error] Failed to generate card for {s}: {card_err}", flush=True)
                except Exception as agent_err:
                    print(f"From Python: [Super Agent Error] Failed to run: {agent_err}", flush=True)
                
                # Check pre-trained library cache first to reuse configuration
                library_dir = os.path.join(os.path.dirname(__file__), "library")
                os.makedirs(library_dir, exist_ok=True)
                
                reused_code = None
                reused_component = None
                
                if sensors:
                    for s in sensors:
                        lib_file = os.path.join(library_dir, f"{s}.cpp")
                        if os.path.exists(lib_file):
                            with open(lib_file, "r", encoding="utf-8") as f:
                                reused_code = f.read()
                                reused_component = s
                                break
                
                if not reused_code:
                    code_lower = code.lower()
                    if "liquidcrystal_i2c" in code_lower or "lcd.print" in code_lower:
                        lib_file = os.path.join(library_dir, "LCD.cpp")
                        if os.path.exists(lib_file):
                            with open(lib_file, "r", encoding="utf-8") as f:
                                reused_code = f.read()
                                reused_component = "LCD"
                
                result = None
                if reused_code:
                    print(f"From Python: [Library Cache] Found pre-trained code for {reused_component}. Reusing configuration...", flush=True)
                    result = reused_code
                
                if result is None:
                    prompt = f"""{hardware_rules}{knowledge_cards_str}

Original Code:
{code}"""
                    response = None
                    google_key = self.google_keys[self.current_google_key_idx] if self.google_keys else ""
                    
                    # Define fallback chain: (base_url, api_key, model)
                    models_to_try = []
                    if self.use_local_llm:
                        models_to_try.append((self.local_llm_url, "ollama", self.local_llm_model))
                    else:
                        for gk in self.groq_keys:
                            if gk.strip():
                                models_to_try.append(("https://api.groq.com/openai/v1", gk.strip(), "llama-3.3-70b-versatile"))
                        for ok in self.api_keys:
                            if ok.strip():
                                models_to_try.append(("https://openrouter.ai/api/v1", ok.strip(), "anthropic/claude-3.5-sonnet"))
                                models_to_try.append(("https://openrouter.ai/api/v1", ok.strip(), "openai/gpt-4o-mini"))
                    
                    # Try Groq API keys first
                    if result is None and not self.use_local_llm and self.groq_keys:
                        max_attempts = len(self.groq_keys) * 2
                        for attempt in range(max_attempts):
                            groq_key = self.groq_keys[self.current_groq_key_idx]
                            try:
                                print(f"From Python: [Ingestion] Trying Groq client with llama-3.3-70b-versatile using Key {self.current_groq_key_idx + 1}...", flush=True)
                                temp_client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=groq_key)
                                response = temp_client.chat.completions.create(
                                    model="llama-3.3-70b-versatile",
                                    messages=[{"role": "user", "content": prompt}],
                                    max_tokens=1000,
                                    extra_headers={
                                        "HTTP-Referer": "http://localhost",
                                        "X-Title": "Desktop AI Companion"
                                    }
                                )
                                result = response.choices[0].message.content.strip()
                                print("From Python: [Ingestion] Groq ingestion succeeded!", flush=True)
                                break
                            except Exception as e:
                                print(f"From Python: [Ingestion] Groq Key {self.current_groq_key_idx + 1} failed ({e}). Rotating key...", flush=True)
                                self.current_groq_key_idx = (self.current_groq_key_idx + 1) % len(self.groq_keys)

                    # Try native Google GenAI client
                    if result is None and not self.use_local_llm and google_key:
                        max_attempts = len(self.google_keys) * 2
                        for attempt in range(max_attempts):
                            try:
                                print(f"From Python: [Ingestion] Trying Google native client with gemini-2.5-flash using Key {self.current_google_key_idx + 1}...", flush=True)
                                from google import genai
                                native_client = genai.Client(api_key=google_key)
                                native_resp = native_client.models.generate_content(
                                    model="gemini-2.5-flash",
                                    contents=prompt
                                )
                                result = native_resp.text.strip()
                                print("From Python: [Ingestion] Google native client succeeded!", flush=True)
                                break
                            except Exception as e:
                                print(f"From Python: [Ingestion] Native Gemini Key {self.current_google_key_idx + 1} failed ({e}). Rotating key...", flush=True)
                                self.current_google_key_idx = (self.current_google_key_idx + 1) % len(self.google_keys)
                                google_key = self.google_keys[self.current_google_key_idx]
                    
                    if result is None:
                        for base_url, api_key, ai_model in models_to_try:
                            if not api_key or api_key == "dummy":
                                continue
                            try:
                                temp_client = OpenAI(base_url=base_url, api_key=api_key)
                                response = temp_client.chat.completions.create(
                                    model=ai_model,
                                    messages=[{"role": "user", "content": prompt}],
                                    max_tokens=1000,
                                    extra_headers={
                                        "HTTP-Referer": "http://localhost",
                                        "X-Title": "Desktop AI Companion"
                                    }
                                )
                                result = response.choices[0].message.content.strip()
                                break # Success
                            except Exception as e:
                                print(f"From Python: [Ingestion] Model {ai_model} at {base_url} failed: {e}", flush=True)
                                continue
                    
                    if result is None:
                        self.hardware_result.emit("Error: All models failed or out of credits. Please check your API keys.")
                        return
                    
                    if result.startswith("```cpp"):
                        result = result[6:]
                    elif result.startswith("```"):
                        result = result[3:]
                    if result.endswith("```"):
                        result = result[:-3]
                    
                    # Save generated code to library for future reuse
                    comp_name = None
                    if sensors:
                        comp_name = sensors[0]
                    else:
                        code_lower = code.lower()
                        if "liquidcrystal_i2c" in code_lower or "lcd.print" in code_lower:
                            comp_name = "LCD"
                    
                    if comp_name:
                        lib_file = os.path.join(library_dir, f"{comp_name}.cpp")
                        try:
                            with open(lib_file, "w", encoding="utf-8") as f:
                                f.write(result)
                            print(f"From Python: [Library Cache] Saved generated code for {comp_name} to library.", flush=True)
                        except Exception as save_err:
                            print(f"From Python: [Library Cache Error] Failed to save code: {save_err}", flush=True)
                
                # Check if this component's training description is already present in memory
                mem_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "hardware_memory.txt")
                already_trained = False
                comp_check = reused_component or (sensors[0] if sensors else None)
                if os.path.exists(mem_path) and comp_check:
                    with open(mem_path, "r", encoding="utf-8") as f:
                        existing_mem = f.read()
                    if comp_check.lower() in existing_mem.lower():
                        already_trained = True
                        print(f"From Python: [Library] Component {comp_check} is already in Bupi memory. Skipping agent re-training.", flush=True)
                        
                        # Find the line in hardware_memory.txt and emit it so frontend adds it to the active session list
                        for line in existing_mem.splitlines():
                            if comp_check.lower() in line.lower():
                                print(json.dumps({"type": "trained_device", "value": line.strip()}), flush=True)
                                break
                
                # -------------------------
                # Auto-Train BUPI
                # -------------------------
                training_data = None
                if not already_trained:
                    train_prompt = f"""You are BUPI's Hardware Analyst. Analyze the following generated MQTT C++ code and extract exactly how BUPI should use it.
Output ONLY a short instruction that will be injected into BUPI's permanent memory.

Format Example:
- Servo Motor: To control the servo, output [MQTT_SEND:bupi/actuators/servo/cmd:ANGLE] where ANGLE is 0 to 180.
- LCD Display: To show text on the screen, output [MQTT_SEND:bupi/actuators/lcd_1/cmd:TEXT] where TEXT is the message.

Generated Code:
{result}
"""
                    # Try Google Gemini direct keys first for training
                    google_key = self.google_keys[self.current_google_key_idx] if self.google_keys else ""
                    if not self.use_local_llm and google_key:
                        max_attempts = len(self.google_keys) * 2
                        for attempt in range(max_attempts):
                            try:
                                print(f"From Python: [Training] Trying Google native client with gemini-2.5-flash using Key {self.current_google_key_idx + 1}...", flush=True)
                                from google import genai
                                native_client = genai.Client(api_key=google_key)
                                train_resp = native_client.models.generate_content(
                                    model="gemini-2.5-flash",
                                    contents=train_prompt
                                )
                                training_data = train_resp.text.strip()
                                print("From Python: [Training] Google native training succeeded!", flush=True)
                                break
                            except Exception as e:
                                print(f"From Python: [Training] Native Gemini Key {self.current_google_key_idx + 1} failed ({e}). Rotating key...", flush=True)
                                self.current_google_key_idx = (self.current_google_key_idx + 1) % len(self.google_keys)
                                google_key = self.google_keys[self.current_google_key_idx]

                    # Fallback to Groq API keys
                    if training_data is None and not self.use_local_llm and self.groq_keys:
                        max_attempts = len(self.groq_keys) * 2
                        for attempt in range(max_attempts):
                            groq_key = self.groq_keys[self.current_groq_key_idx]
                            try:
                                print(f"From Python: [Training] Trying Groq client with llama-3.3-70b-versatile using Key {self.current_groq_key_idx + 1}...", flush=True)
                                temp_client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=groq_key)
                                train_resp = temp_client.chat.completions.create(
                                    model="llama-3.3-70b-versatile",
                                    messages=[{"role": "user", "content": train_prompt}],
                                    max_tokens=300,
                                    extra_headers={
                                        "HTTP-Referer": "http://localhost",
                                        "X-Title": "Desktop AI Companion"
                                    }
                                )
                                training_data = train_resp.choices[0].message.content.strip()
                                print("From Python: [Training] Groq training succeeded!", flush=True)
                                break
                            except Exception as e:
                                print(f"From Python: [Training] Groq Key {self.current_groq_key_idx + 1} failed ({e}). Rotating key...", flush=True)
                                self.current_groq_key_idx = (self.current_groq_key_idx + 1) % len(self.groq_keys)
                            
                    if training_data is None:
                        try:
                            # Fallback using OpenAI compatibility models
                            for base_url, api_key, ai_model in models_to_try:
                                if not api_key or api_key == "dummy":
                                    continue
                                temp_client = OpenAI(base_url=base_url, api_key=api_key)
                                train_resp = temp_client.chat.completions.create(
                                    model=ai_model,
                                    messages=[{"role": "user", "content": train_prompt}],
                                    max_tokens=300,
                                    extra_headers={
                                        "HTTP-Referer": "http://localhost",
                                        "X-Title": "Desktop AI Companion"
                                    }
                                )
                                training_data = train_resp.choices[0].message.content.strip()
                                break
                        except Exception as e:
                            print(f"From Python: [Training Error] Failed to train BUPI on new hardware: {e}", flush=True)
                            
                    if training_data:
                        already_exists = False
                        if os.path.exists(mem_path):
                            with open(mem_path, "r", encoding="utf-8") as f:
                                existing_lines = f.read()
                            
                            prefix_match = re.match(r'^-\s*([^:]+):', training_data.strip())
                            if prefix_match:
                                prefix = prefix_match.group(1).strip()
                                if prefix in existing_lines:
                                    already_exists = True
                                    print(f"From Python: [Library] Configuration for {prefix} already exists in hardware_memory.txt. Skipping append.", flush=True)
                                    
                        if not already_exists:
                            with open(mem_path, "a", encoding="utf-8") as f:
                                f.write(training_data.strip() + "\n")
                        
                        # Emit the newly trained device description to the frontend
                        print(json.dumps({"type": "trained_device", "value": training_data.strip()}), flush=True)

                if result:
                    result = cleanup_cpp_includes(result.strip())

                self.hardware_result.emit(result)
                
                # Run Auto-Flasher
                try:
                    from actions.flasher import auto_flash_code
                    def progress_cb(msg):
                        self.hardware_result.emit(result + "\n\n--- AUTO FLASHER ---\n" + msg)
                    
                    flash_status = auto_flash_code(result, progress_cb)
                    if "Error" in flash_status:
                        self.hardware_result.emit(result + "\n\n--- AUTO FLASHER ---\n" + flash_status)
                except Exception as e:
                    self.hardware_result.emit(result + f"\n\n--- AUTO FLASHER ---\nFailed to run auto-flasher: {e}")
            except Exception as e:
                self.hardware_result.emit(f"Error during ingestion: {e}")
            finally:
                self._processing_active = False
                
        import threading
        threading.Thread(target=worker, daemon=True).start()

    def flash_hardware(self, code: str):
        if getattr(self, "_flashing_active", False):
            print(json.dumps({"type": "flash_status", "value": "Error: A flashing task is already in progress. Please wait."}), flush=True)
            return
        self._flashing_active = True
        
        def worker():
            try:
                from actions.flasher import auto_flash_code
                def progress_cb(msg):
                    print(json.dumps({"type": "flash_progress", "value": msg}), flush=True)
                
                flash_status = auto_flash_code(code.strip(), progress_cb)
                print(json.dumps({"type": "flash_status", "value": flash_status}), flush=True)
            except Exception as e:
                print(json.dumps({"type": "flash_status", "value": f"Error: {e}"}), flush=True)
            finally:
                self._flashing_active = False
                
        import threading
        threading.Thread(target=worker, daemon=True).start()

    def run(self):
        while True:
            try:
                text = self._queue.get()
                if text is None:
                    break
                self._interrupted = False

                mem_data = user_memory.load()
                user_name = mem_data.get("user_name", "Chintu")
                notes = mem_data.get("notes", [])
                notes_str = "\\n".join([f"- {n}" for n in notes]) if notes else "None"
                
                import datetime
                current_time = datetime.datetime.now().strftime("%A, %B %d, %Y - %I:%M %p")
                
                # Check if cached weather is older than 20 minutes
                if not hasattr(self, "last_weather_fetch_time") or (datetime.datetime.now() - self.last_weather_fetch_time > datetime.timedelta(minutes=20)):
                    self._update_weather_async()
                weather_info = self.weather_info

                sys_prompt = SYSTEM_PROMPT.format(user_name=user_name, current_time=current_time, weather_info=weather_info, notes=notes_str)
                
                # Fetch long-term Hindsight memory (with strict 2s timeout)
                if hasattr(self, 'hindsight') and self.hindsight:
                    try:
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(self.hindsight.recall, bank_id="bupi_main", query=text)
                            memories = future.result(timeout=2.0)
                            if memories:
                                sys_prompt += "\n\nPAST MEMORIES / CONTEXT:\n" + str(memories)
                    except concurrent.futures.TimeoutError:
                        print("From Python: [Memory Warning] Recall took too long, skipping for low latency...", flush=True)
                    except Exception as e:
                        print(f"From Python: [Memory Error] Recall failed: {e}", flush=True)
                            
                messages = [{"role": "system", "content": sys_prompt}]
                
                import re
                if re.search(r'\blinkedin\b', text, re.I):
                    try:
                        style_path = os.path.join(os.path.dirname(__file__), "linkedin_style.txt")
                        with open(style_path, "r", encoding="utf-8") as f:
                            linkedin_style = f.read()
                        messages[0]["content"] += "\n\n" + linkedin_style
                    except Exception as e:
                        print(f"From Python: [AI Warning] Could not load linkedin style: {e}", flush=True)

                for item in self._history:
                    messages.append({"role": item["role"], "content": item["content"]})
                messages.append({"role": "user", "content": text})

                # -------------------------
                # HYBRID ROUTER
                # -------------------------
                import re
                is_complicated = False
                
                # Check for drawing/visual keywords
                if any(w in text.lower() for w in ["draw", "paint", "image", "picture", "sketch"]):
                    is_complicated = True
                
                # Check for screenshots/visual tasks
                screenshot_keywords = ["look at my screen", "what's on my screen", "read my screen", 
                                       "what am i looking at", "what is this on my screen", "screenshot", 
                                       "what are you seeing", "take a look at my screen"]
                if any(w in text.lower() for w in screenshot_keywords):
                    is_complicated = True
                    
                # Check for document summarization/analysis
                doc_keywords = ["summarize", "analyze", "scan", "read my document", "read the document", "read this pdf", "read the file"]
                if any(w in text.lower() for w in doc_keywords):
                    is_complicated = True
                    
                # Check for computer actions/automations
                action_keywords = ["open", "type", "press", "search for", "play", "run", "execute", "launch"]
                if any(w in text.lower() for w in action_keywords):
                    is_complicated = True
                    
                # Check for hardware/MQTT control
                hw_keywords = ["mqtt", "esp32", "servo", "lcd", "display", "led", "sensor", "hardware", "board"]
                if any(w in text.lower() for w in hw_keywords):
                    is_complicated = True
                    
                # Check for coding/math/complex writing tasks
                complex_keywords = ["code", "python", "script", "function", "write a program", "programming", 
                                    "debug", "error", "exception", "math", "solve", "calculate", "write an email", 
                                    "draft", "write a post", "essay", "article"]
                if any(w in text.lower() for w in complex_keywords):
                    is_complicated = True
                    
                # Check for long inputs
                if len(text.strip()) > 100 or len(text.split()) > 15:
                    is_complicated = True

                # Determine route
                if self.use_local_llm:
                    route_to_local = True
                    route_reason = "Cloud free tiers are blocked/exhausted, forcing local LLM."
                else:
                    route_to_local = False
                    route_reason = "Routing to Cloud for low-latency response."

                if route_to_local:
                    print(f"From Python: [Router] Routing to LOCAL ({self.local_llm_model}): {route_reason}", flush=True)
                else:
                    print(f"From Python: [Router] Routing to CLOUD (Gemini/OpenRouter): {route_reason}", flush=True)

                # Only perform heavy operations (Screenshots, Document reading) if we are routing to the CLOUD
                if not route_to_local:
                    summarize_doc = bool(re.search(r'\b(summarize|analyze|scan)\s+(this|the|my)\s+(pdf|document|page|file|window|text|screen)\b', text, re.I))
                    
                    if summarize_doc:
                        try:
                            import pyautogui
                            import pyperclip
                            import time
                            
                            old_clipboard = pyperclip.paste()
                            pyperclip.copy("")
                            
                            pyautogui.hotkey('ctrl', 'a')
                            time.sleep(0.3)
                            pyautogui.hotkey('ctrl', 'c')
                            time.sleep(0.3)
                            pyautogui.press('right')
                            
                            extracted_text = pyperclip.paste()
                            
                            if old_clipboard:
                                pyperclip.copy(old_clipboard)
                            
                            if extracted_text and len(extracted_text.strip()) > 10:
                                if len(extracted_text) > 150000:
                                    extracted_text = extracted_text[:150000] + "\n...[Text Truncated]..."
                                    
                                text += f"\n\n[System Note: The user asked you to summarize/read their document. I have automatically extracted the text from their active window. Here is the text:]\n\n{extracted_text}"
                                print("From Python: [AI] Injected active document text into her brain!", flush=True)
                                messages[-1]["content"] = text
                            else:
                                text += f"\n\n[System Note: I tried to extract the text from the active window, but nothing was found. Ask the user to click on the document or PDF they want you to read first!]"
                                print("From Python: [AI] Failed to find text to extract.", flush=True)
                                messages[-1]["content"] = text
                                
                        except Exception as e:
                            print(f"From Python: [AI Error] Could not extract document text: {e}", flush=True)
                            text += f"\n\n[System Note: I tried to extract the text from the active window, but an error occurred. Ask the user to click on the document or PDF they want you to read first!]"
                            messages[-1]["content"] = text

                    take_screenshot = bool(re.search(r'\b(look at my screen|what.?s on my screen|read my screen|what am i looking at|what is this on my screen|screenshot|what are you seeing|take a look at my screen)\b', text, re.I))
                    
                    if take_screenshot:
                        try:
                            from PIL import ImageGrab
                            import base64
                            from io import BytesIO
                            
                            screen = ImageGrab.grab(all_screens=True)
                            screen.thumbnail((1280, 720))
                            
                            buffered = BytesIO()
                            screen.save(buffered, format="JPEG", quality=70)
                            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
                            
                            messages[-1] = {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": text},
                                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_str}"}}
                                ]
                            }
                            print("From Python: [AI] Injected screenshot of your desktop into her brain!", flush=True)
                        except Exception as e:
                            print(f"From Python: [AI Error] Could not take screenshot: {e}", flush=True)

                response = None
                spoken_buffer = ""
                
                if route_to_local:
                    ai_model = self.local_llm_model
                    max_tokens = 1000 # Local models generally have no usage cost, we can use higher limits
                    client = self.local_client if hasattr(self, 'local_client') and self.local_client else OpenAI(base_url=self.local_llm_url, api_key="ollama")
                    try:
                        response = client.chat.completions.create(
                            model=ai_model,
                            messages=messages,
                            stream=True,
                            max_tokens=max_tokens,
                            extra_body={"keep_alive": -1} # Keep model loaded in VRAM forever for instant responses
                        )
                    except Exception as e:
                        print(f"From Python: [Router] Local LLM {ai_model} failed ({e}).", flush=True)
                        raise e

                if not route_to_local:
                    try:
                        first_chunk = None
                        response_iterator = None
                        is_routed = False

                        # 1. Prioritize Groq for non-vision/non-screenshot tasks for ultra-low latency
                        if not is_routed and not take_screenshot and self.groq_keys:
                            max_attempts = len(self.groq_keys) * 2
                            for attempt in range(max_attempts):
                                key_idx = self.current_groq_key_idx
                                client = self.groq_clients[key_idx] if key_idx < len(self.groq_clients) else None
                                if client is None:
                                    key = self.groq_keys[key_idx]
                                    if key.strip():
                                        client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=key.strip())
                                        self.groq_clients[key_idx] = client
                                
                                if client:
                                    try:
                                        print(f"From Python: [AI] Requesting from Groq (llama-3.3-70b-versatile) using Key {key_idx + 1}", flush=True)
                                        response = client.chat.completions.create(
                                            model="llama-3.3-70b-versatile",
                                            messages=messages,
                                            stream=True,
                                            max_tokens=800
                                        )
                                        response_iterator = openai_stream_generator(response)
                                        try:
                                            first_chunk = next(response_iterator)
                                        except StopIteration:
                                            first_chunk = ""
                                        is_routed = True
                                        break
                                    except Exception as e:
                                        print(f"From Python: [AI] Groq Key {key_idx + 1} failed ({e}). Rotating key...", flush=True)
                                        self.current_groq_key_idx = (self.current_groq_key_idx + 1) % len(self.groq_keys)
                                else:
                                    self.current_groq_key_idx = (self.current_groq_key_idx + 1) % len(self.groq_keys)

                        # 2. Prioritize Native Gemini for vision tasks or fallback for text tasks
                        google_key = self.google_keys[self.current_google_key_idx] if self.google_keys else ""
                        if not is_routed and google_key and not re.search(r'\bclaude\b', text, re.I):
                            max_attempts = len(self.google_keys) * 2
                            for attempt in range(max_attempts):
                                key_idx = self.current_google_key_idx
                                native_client = self.google_clients[key_idx] if key_idx < len(self.google_clients) else None
                                if native_client is None:
                                    key = self.google_keys[key_idx]
                                    if key.strip():
                                        try:
                                            from google import genai
                                            native_client = genai.Client(api_key=key.strip())
                                            self.google_clients[key_idx] = native_client
                                        except Exception as ge:
                                            print(f"From Python: [AI Warning] Could not init genai client: {ge}", flush=True)
                                
                                if native_client:
                                    try:
                                        native_contents = []
                                        for item in messages:
                                            if item["role"] == "system":
                                                continue
                                            role = "user" if item["role"] == "user" else "model"
                                            
                                            if item == messages[-1] and take_screenshot:
                                                parts = []
                                                try:
                                                    img_url = item["content"][1]["image_url"]["url"]
                                                    b64_data = img_url.split(",")[1]
                                                    img_bytes = base64.b64decode(b64_data)
                                                    img_part = types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
                                                    parts.append(img_part)
                                                except Exception as img_err:
                                                    print(f"From Python: [AI Error] Native image conversion failed: {img_err}", flush=True)
                                                parts.append(types.Part.from_text(text=text))
                                                native_contents.append(types.Content(role="user", parts=parts))
                                            else:
                                                content_text = item["content"]
                                                if isinstance(content_text, list):
                                                    content_text = content_text[0]["text"]
                                                native_contents.append(
                                                    types.Content(
                                                        role=role,
                                                        parts=[types.Part.from_text(text=content_text)]
                                                    )
                                                )
                                        
                                        print(f"From Python: [AI] Requesting from Native Google SDK (gemini-2.5-flash) using Key {key_idx + 1}", flush=True)
                                        response = native_client.models.generate_content_stream(
                                            model="gemini-2.5-flash",
                                            contents=native_contents,
                                            config=types.GenerateContentConfig(
                                                system_instruction=sys_prompt,
                                                max_output_tokens=800
                                            )
                                        )
                                        response_iterator = native_stream_generator(response)
                                        try:
                                            first_chunk = next(response_iterator)
                                        except StopIteration:
                                            first_chunk = ""
                                        is_routed = True
                                        break
                                    except Exception as e:
                                        error_msg = str(e)
                                        print(f"From Python: [AI] Native Gemini Key {key_idx + 1} failed ({error_msg}). Rotating key...", flush=True)
                                        self.current_google_key_idx = (self.current_google_key_idx + 1) % len(self.google_keys)
                                else:
                                    self.current_google_key_idx = (self.current_google_key_idx + 1) % len(self.google_keys)

                        # 3. Fallback candidates (OpenRouter, etc.)
                        if not is_routed:
                            # Build a list of fallback candidates: (provider, client, model, max_tokens)
                            candidates = []
                            
                            # Add all Groq clients if available
                            for idx, client in enumerate(self.groq_clients):
                                if client:
                                    candidates.append(("Groq", client, "llama-3.3-70b-versatile", 800))
                                    
                            # Add OpenRouter clients
                            or_model = "anthropic/claude-3.5-sonnet" if re.search(r'\bclaude\b', text, re.I) else "openrouter/free"
                            or_tokens = 1000 if re.search(r'\bclaude\b', text, re.I) else 250
                            for client in self.or_clients:
                                if client:
                                    candidates.append(("OpenRouter", client, or_model, or_tokens))
                                    
                            for provider, client, ai_model, max_tokens in candidates:
                                try:
                                    print(f"From Python: [AI] Requesting fallback from {provider} ({ai_model})...", flush=True)
                                    response = client.chat.completions.create(
                                        model=ai_model,
                                        messages=messages,
                                        stream=True,
                                        max_tokens=max_tokens,
                                        extra_headers={
                                            "HTTP-Referer": "http://localhost",
                                            "X-Title": "Desktop AI Companion"
                                        }
                                    )
                                    response_iterator = openai_stream_generator(response)
                                    try:
                                        first_chunk = next(response_iterator)
                                    except StopIteration:
                                        first_chunk = ""
                                    is_routed = True
                                    break # Success!
                                except Exception as e:
                                    print(f"From Python: [AI] {provider} fallback failed ({e}). Trying next fallback...", flush=True)
                                    continue

                        if response is None or response_iterator is None:
                            raise Exception("All cloud API keys and fallbacks are exhausted.")
                    except Exception as cloud_err:
                        print(f"From Python: [AI] Cloud routing failed ({cloud_err}). Falling back to Local LLM...", flush=True)
                        route_to_local = True
                
                full_response = ""
                emotion_tag = "talking"
                parsing_emotion = True
                emotion_buffer = ""
                current_sentence = ""
                
                # Notepad parsing state
                in_notepad = False
                notepad_buffer = ""
                in_title = False
                title_buffer = ""

                if route_to_local:
                    response_iterator = openai_stream_generator(response)
                else:
                    response_iterator = unified_stream(first_chunk, response_iterator)

                for delta in response_iterator:
                    if self._interrupted: break
                    
                    if delta:
                        full_response += delta
                        
                        if parsing_emotion:
                            emotion_buffer += delta
                            if "]" in emotion_buffer:
                                match = re.match(r"^\[(.*?)\]", emotion_buffer.strip())
                                if match:
                                    emotion_tag = match.group(1).lower()
                                    if not self._interrupted: self.response_started.emit(emotion_tag)
                                    idx = emotion_buffer.find("]") + 1
                                    current_sentence += emotion_buffer[idx:].lstrip()
                                else:
                                    if not self._interrupted: self.response_started.emit("talking")
                                    current_sentence += emotion_buffer
                                parsing_emotion = False
                            elif len(emotion_buffer) > 20:
                                if not self._interrupted: self.response_started.emit("talking")
                                current_sentence += emotion_buffer
                                parsing_emotion = False
                            continue
                        
                        if in_title:
                            title_buffer += delta
                            if "[/TITLE]" in title_buffer:
                                idx = title_buffer.find("[/TITLE]")
                                title = title_buffer[:idx]
                                if not self._interrupted:
                                    self.notepad_title.emit(title)
                                current_sentence = title_buffer[idx+8:]
                                title_buffer = ""
                                in_title = False
                            continue
                            
                        if "[TITLE]" in current_sentence + delta:
                            idx = (current_sentence + delta).find("[TITLE]")
                            before_tag = (current_sentence + delta)[:idx]
                            if before_tag.strip() and not self._interrupted:
                                spoken_buffer += before_tag.strip() + " "
                                
                            combined = (current_sentence + delta)[idx+7:]
                            if "[/TITLE]" in combined:
                                idx2 = combined.find("[/TITLE]")
                                title = combined[:idx2]
                                if not self._interrupted:
                                    self.notepad_title.emit(title)
                                current_sentence = combined[idx2+8:]
                                in_title = False
                            else:
                                title_buffer = combined
                                in_title = True
                                current_sentence = ""
                            continue
                        
                        if "[NOTEPAD_CLEAR]" in current_sentence + delta:
                            idx = (current_sentence + delta).find("[NOTEPAD_CLEAR]")
                            before_tag = (current_sentence + delta)[:idx]
                            if before_tag.strip() and not self._interrupted:
                                spoken_buffer += before_tag.strip() + " "
                            
                            delta = (current_sentence + delta)[idx + 15:]
                            current_sentence = ""
                            if not self._interrupted:
                                self.notepad_clear.emit()

                        # Handle WhatsApp Send tag so it isn't spoken
                        if "[WHATSAPP_SEND:" in current_sentence + delta:
                            idx = (current_sentence + delta).find("[WHATSAPP_SEND:")
                            before_tag = (current_sentence + delta)[:idx]
                            if before_tag.strip() and not self._interrupted:
                                spoken_buffer += before_tag.strip() + " "
                                
                            combined = (current_sentence + delta)[idx:]
                            if "]" in combined:
                                tag_end = combined.find("]")
                                current_sentence = combined[tag_end+1:]
                            else:
                                current_sentence = combined
                            continue
                            
                        # Handle EMAIL_SEND tag so it isn't spoken
                        if "[EMAIL_SEND:" in current_sentence + delta:
                            idx = (current_sentence + delta).find("[EMAIL_SEND:")
                            before_tag = (current_sentence + delta)[:idx]
                            if before_tag.strip() and not self._interrupted:
                                spoken_buffer += before_tag.strip() + " "
                                
                            combined = (current_sentence + delta)[idx:]
                            if "]" in combined:
                                tag_end = combined.find("]")
                                current_sentence = combined[tag_end+1:]
                            else:
                                current_sentence = combined
                            continue
                            
                        # Handle LINKEDIN_SEND tag so it isn't spoken
                        if "[LINKEDIN_SEND:" in current_sentence + delta:
                            idx = (current_sentence + delta).find("[LINKEDIN_SEND:")
                            before_tag = (current_sentence + delta)[:idx]
                            if before_tag.strip() and not self._interrupted:
                                spoken_buffer += before_tag.strip() + " "
                                
                            combined = (current_sentence + delta)[idx:]
                            if "]" in combined:
                                tag_end = combined.find("]")
                                current_sentence = combined[tag_end+1:]
                            else:
                                current_sentence = combined
                            continue

                        # Handle DRAW tag so it isn't spoken
                        if "[DRAW:" in current_sentence + delta:
                            idx = (current_sentence + delta).find("[DRAW:")
                            before_tag = (current_sentence + delta)[:idx]
                            if before_tag.strip() and not self._interrupted:
                                spoken_buffer += before_tag.strip() + " "
                                
                            combined = (current_sentence + delta)[idx:]
                            if "]" in combined:
                                tag_end = combined.find("]")
                                current_sentence = combined[tag_end+1:]
                            else:
                                current_sentence = combined
                            continue

                        # Handle ACTION tag so it isn't spoken
                        if "[ACTION:" in current_sentence + delta:
                            idx = (current_sentence + delta).find("[ACTION:")
                            before_tag = (current_sentence + delta)[:idx]
                            if before_tag.strip() and not self._interrupted:
                                spoken_buffer += before_tag.strip() + " "
                                
                            combined = (current_sentence + delta)[idx:]
                            if "]" in combined:
                                tag_end = combined.find("]")
                                current_sentence = combined[tag_end+1:]
                            else:
                                current_sentence = combined
                            continue
                            
                        # Handle MQTT_SEND tag so it isn't spoken
                        if "[MQTT_SEND:" in current_sentence + delta:
                            idx = (current_sentence + delta).find("[MQTT_SEND:")
                            before_tag = (current_sentence + delta)[:idx]
                            if before_tag.strip() and not self._interrupted:
                                spoken_buffer += before_tag.strip() + " "
                                
                            combined = (current_sentence + delta)[idx:]
                            if "]" in combined:
                                tag_end = combined.find("]")
                                current_sentence = combined[tag_end+1:]
                            else:
                                current_sentence = combined
                            continue

                        # Handle Notepad tags
                        if not in_notepad and "[NOTEPAD]" in current_sentence + delta:
                            idx = (current_sentence + delta).find("[NOTEPAD]")
                            before_tag = (current_sentence + delta)[:idx]
                            if before_tag.strip() and not self._interrupted:
                                spoken_buffer += before_tag.strip() + " "
                            
                            delta = (current_sentence + delta)[idx + 9:]
                            current_sentence = ""
                            in_notepad = True
                            
                        if in_notepad:
                            notepad_buffer += delta
                            
                            # Check if the closing tag is possibly starting
                            # e.g., if notepad_buffer ends with a part of "[/NOTEPAD]"
                            closing_tag = "[/NOTEPAD]"
                            
                            if closing_tag in notepad_buffer:
                                idx = notepad_buffer.find(closing_tag)
                                text_to_emit = notepad_buffer[:idx]
                                if text_to_emit and not self._interrupted:
                                    self.notepad_insert.emit(text_to_emit)
                                    
                                current_sentence = notepad_buffer[idx + 10:]
                                notepad_buffer = ""
                                in_notepad = False
                            else:
                                # Safe to emit everything except the last 10 characters (in case they form the closing tag)
                                if len(notepad_buffer) > 10:
                                    safe_text = notepad_buffer[:-10]
                                    if safe_text and not self._interrupted:
                                        self.notepad_insert.emit(safe_text)
                                    notepad_buffer = notepad_buffer[-10:]
                            continue
                        current_sentence += delta
                        if re.search(r'[.!?\n]\s*$', current_sentence) or delta.endswith('\n'):
                            text_to_emit = current_sentence.strip()
                            if text_to_emit and not self._interrupted:
                                self.response_chunk.emit(text_to_emit)
                                spoken_buffer += text_to_emit + " "
                            current_sentence = ""
                            
                if in_notepad and notepad_buffer and not self._interrupted:
                    self.notepad_insert.emit(notepad_buffer)
                            
                if current_sentence.strip() and not self._interrupted and not in_notepad:
                    text_to_emit = current_sentence.strip()
                    self.response_chunk.emit(text_to_emit)
                    spoken_buffer += text_to_emit + " "

                # Post-process WHATSAPP_SEND
                if "[WHATSAPP_SEND:" in full_response:
                    w_match = re.search(r"\[WHATSAPP_SEND:(.*?)\]", full_response)
                    if w_match:
                        recipient = w_match.group(1).strip()
                        message_text = ""
                        n_match = re.search(r"\[NOTEPAD\](.*?)\[/NOTEPAD\]", full_response, re.DOTALL)
                        if n_match:
                            message_text = n_match.group(1).strip()
                        else:
                            for item in reversed(self._history):
                                if item["role"] == "assistant":
                                    n_match_hist = re.search(r"\[NOTEPAD\](.*?)\[/NOTEPAD\]", item["content"], re.DOTALL)
                                    if n_match_hist:
                                        message_text = n_match_hist.group(1).strip()
                                        break
                                        
                        if message_text and not self._interrupted:
                            self.whatsapp_send.emit(recipient, message_text)
                        elif not message_text:
                            fallback_match = re.search(r"\[WHATSAPP_SEND:.*?\]\s*(.*)", full_response, re.DOTALL)
                            if fallback_match and fallback_match.group(1).strip():
                                message_text = fallback_match.group(1).strip()
                                self.whatsapp_send.emit(recipient, message_text)
                            else:
                                print("From Python: [AI Error] Could not find message text in history for WhatsApp!", flush=True)

                # Post-process EMAIL_SEND
                if "[EMAIL_SEND:" in full_response:
                    e_match = re.search(r"\[EMAIL_SEND:(.*?):(.*?)\]", full_response)
                    if e_match:
                        recipient = e_match.group(1).strip()
                        subject = e_match.group(2).strip()
                        message_text = ""
                        n_match = re.search(r"\[NOTEPAD\](.*?)\[/NOTEPAD\]", full_response, re.DOTALL)
                        if n_match:
                            message_text = n_match.group(1).strip()
                        else:
                            for item in reversed(self._history):
                                if item["role"] == "assistant":
                                    n_match_hist = re.search(r"\[NOTEPAD\](.*?)\[/NOTEPAD\]", item["content"], re.DOTALL)
                                    if n_match_hist:
                                        message_text = n_match_hist.group(1).strip()
                                        break
                                        
                        if message_text and not self._interrupted:
                            self.email_send.emit(recipient, subject, message_text)
                        elif not message_text:
                            fallback_match = re.search(r"\[EMAIL_SEND:.*?:.*?\]\s*(.*)", full_response, re.DOTALL)
                            if fallback_match and fallback_match.group(1).strip():
                                message_text = fallback_match.group(1).strip()
                                self.email_send.emit(recipient, subject, message_text)
                            else:
                                print("From Python: [AI Error] Could not find message text in history for Email!", flush=True)

                # Post-process LINKEDIN_SEND
                if "[LINKEDIN_SEND:" in full_response:
                    l_match = re.search(r"\[LINKEDIN_SEND:(.*?)\]", full_response)
                    if l_match:
                        recipient = l_match.group(1).strip()
                        message_text = ""
                        n_match = re.search(r"\[NOTEPAD\](.*?)\[/NOTEPAD\]", full_response, re.DOTALL)
                        if n_match:
                            message_text = n_match.group(1).strip()
                        else:
                            for item in reversed(self._history):
                                if item["role"] == "assistant":
                                    n_match_hist = re.search(r"\[NOTEPAD\](.*?)\[/NOTEPAD\]", item["content"], re.DOTALL)
                                    if n_match_hist:
                                        message_text = n_match_hist.group(1).strip()
                                        break
                                        
                        if message_text and not self._interrupted:
                            self.linkedin_send.emit(recipient, message_text)
                        elif not message_text:
                            fallback_match = re.search(r"\[LINKEDIN_SEND:.*?\]\s*(.*)", full_response, re.DOTALL)
                            if fallback_match and fallback_match.group(1).strip():
                                message_text = fallback_match.group(1).strip()
                                self.linkedin_send.emit(recipient, message_text)
                            else:
                                print("From Python: [AI Error] Could not find message text in history for LinkedIn!", flush=True)

                # Post-process DRAW tag
                if "[DRAW:" in full_response:
                    d_match = re.search(r"\[DRAW:(.*?)\]", full_response)
                    if d_match:
                        prompt = d_match.group(1).strip()
                        if prompt and not self._interrupted:
                            import urllib.parse
                            encoded_prompt = urllib.parse.quote(prompt)
                            url = f"https://image.pollinations.ai/prompt/{encoded_prompt}"
                            self.ai_draw.emit(url)

                # Post-process ACTION tags (Orchestrator)
                if "[ACTION:" in full_response:
                    actions = re.findall(r"\[ACTION:(.*?)\]", full_response, flags=re.I)
                    if actions and not self._interrupted:
                        self.ai_action.emit([a.strip() for a in actions])

                # Post-process MQTT tags (Hive Mind)
                if "[MQTT_SEND:" in full_response:
                    mqtt_commands = re.findall(r"\[MQTT_SEND:(.+?):(.*?)\]", full_response, flags=re.I)
                    if mqtt_commands and not self._interrupted:
                        try:
                            from actions.iot_agent import handle_iot_command
                            for topic, msg in mqtt_commands:
                                handle_iot_command(topic.strip(), msg.strip())
                        except Exception as e:
                            print(f"From Python: [MQTT Error] {e}", flush=True)

                if not full_response:
                    full_response = "I couldn't think of anything to say."
                    if not self._interrupted:
                        self.response_started.emit("talking")
                        self.response_chunk.emit(full_response)

                safe_resp = full_response.strip().encode('ascii', 'ignore').decode('ascii')
                print(f"From Python: [AI] '{safe_resp}'", flush=True)

                self._history.append({"role": "user", "content": text})
                self._history.append({"role": "assistant", "content": full_response})
                if len(self._history) > MAX_HISTORY * 2:
                    self._history = self._history[-(MAX_HISTORY * 2):]

                # Store long-term Hindsight memory in background
                if hasattr(self, 'hindsight') and self.hindsight:
                    try:
                        mem_content = f"User said: {text} | BUPI replied: {full_response}"
                        import threading
                        threading.Thread(target=self.hindsight.retain, kwargs={"bank_id": "bupi_main", "content": mem_content}, daemon=True).start()
                    except Exception as e:
                        print(f"From Python: [Memory Error] Retain failed: {e}", flush=True)

                log_file = os.path.join(os.path.dirname(__file__), "ai_memory_log.txt")
                with open(log_file, "a", encoding="utf-8") as f:
                    import datetime
                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"[{timestamp}] User: {text}\\n")
                    f.write(f"[{timestamp}] AI: {full_response}\\n")
                    
                if os.path.exists(log_file) and os.path.getsize(log_file) > 1024 * 512:
                    with open(log_file, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                    with open(log_file, "w", encoding="utf-8") as f:
                        f.writelines(lines[-500:])

                if not self._interrupted:
                    self.response_ready.emit(full_response.strip())

            except Exception as e:
                error_msg = str(e)
                print(f"From Python: [AI Error Caught] {error_msg}", flush=True)
                if "402" in error_msg or "insufficient_quota" in error_msg.lower():
                    if not self._interrupted: self.response_ready.emit("My API key has run out of credits.")
                elif "429" in error_msg or "rate" in error_msg.lower():
                    if not self._interrupted: self.response_ready.emit("I'm being rate limited by OpenRouter. Please try again later.")
                else:
                    if not self._interrupted: self.response_ready.emit("I am having trouble connecting to my brain right now.")

ai = AIThread()
