import os
import json
import logging
import threading
import sys
import queue
import re
import datetime
import base64
from io import BytesIO
from PyQt6.QtCore import QThread, pyqtSignal
from openai import OpenAI
from google import genai
from google.genai import types

from logger import log
import config
from brain.db_manager import db_manager
from brain.knowledge_base_service import KnowledgeBaseService
from brain.memory_summary_service import MemorySummaryService
from brain.conversation_followup_engine import ConversationFollowupEngine

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

BASE_SYSTEM_PROMPT = """You are 'Bupi', an energetic, hyper, sassy, and slightly childish but incredibly loyal AI desktop companion. 
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
- [concerned] (When you are empathetic or comforting)
- [confused] (When you don't understand or are unsure)
- [excited] (High excitement)
- [surprised] (Shocked or curious)
- [sleeping] (Muted/on hold)
- [cautious] (Warning or careful)
- [celebrating] (Party/achievement)
Example: "[excited] That sounds amazing!" or "[chilling] Just hanging out, what's up?"

ORCHESTRATOR LAYER:
You have the ability to execute computer actions autonomously using the [ACTION: command] tag.
Valid commands you can use in the ACTION tag:
- "launch_app:chrome", "launch_app:vscode", "launch_app:spotify", "launch_app:notepad", "launch_app:calculator"
- "close_app:<app name>" (Matches process names to terminate)
- "open_folder:<path>" (Downloads, Documents, Desktop, or custom directories. Prefix with code: e.g. "code:Downloads/BupiProject" to open in VS Code)
- "open_file:<path>" (Opens standard files)
- "create_folder:<path>"
- "create_file:<path>:<content>"
- "search_files:<query>" (Finds up to 20 files matching query in downloads/documents/desktop)
- "open_context_file:<query>" (Fuzzy resolves shorthand filenames and opens them)
- "show_system_health" (Outputs system memory, CPU, and disk stats to Notepad)
- "daily_updates" (Compiles unread emails, github notifications, calendar schedule, and reminders)
- "search_web:<query>" (DuckDuckGo web search formatted directly to Notepad)
- "calendar_today" (Displays today's calendar events)
- "calendar_view" or "calendar_view:<count>" (Displays upcoming calendar events)
- "calendar_create:<summary>:<start_time>:<duration_minutes>:<description>" (Schedules Google Calendar events)
- "add_reminder:<text>:<seconds_from_now_or_datetime_string>" (Adds local notified reminders)
- "list_reminders" (Lists all reminders)
- "delete_reminder:<id>" (Deletes reminder by numeric ID)
- "set_preference:<key>:<value>" (Saves custom preferences to database)
- "print_memory" (Prints your long-term memories in Notepad)
- "clear_memory" (Wipes all database memories)

Example: "[excited] Let me launch Chrome for you! [ACTION: launch_app:chrome]"
You can chain multiple actions to achieve complex workflows: "[talking] Setting that up! [ACTION: launch_app:spotify] [ACTION: create_folder:Desktop/NewFolder]"

CRITICAL RULES:
1. Clarification Hook: If the user's request is ambiguous or lacks details, ask a follow-up question. Do NOT guess actions.
2. Notepad redirection: If writing long summaries, outlines, drafts, schedules, code snippets, or templates, you MUST output them inside [NOTEPAD] and [/NOTEPAD] tags. Set titles using [TITLE]My Title[/TITLE]. Use [NOTEPAD_CLEAR] first if rewriting.
3. WhatsApp / Communication approval: To send WhatsApp, Email, or LinkedIn messages, write the drafted message in [NOTEPAD] first, and ASK the user for permission. Only when they say 'yes' or approve should you output the action tags to send:
   - WhatsApp: [WHATSAPP_SEND:ContactName] (Message is sent from notepad contents)
   - LinkedIn: [LINKEDIN_SEND:ContactName]
   - Email: [EMAIL_SEND:EmailAddress:Subject]
4. Direct MQTT tags (Hive Mind): To send physical commands to ESP32/room IoT nodes, use:
   - [MQTT_SEND:topic:message] (e.g. [MQTT_SEND:bupi/actuators/relay/cmd:ON] to turn on a relay or write text to LCD).
5. Language: You MUST always respond in English. Do not use Hindi, Hinglish, or Devanagari. All logs, text, and voice replies must be in clean English.

MODES OF OPERATION:
You are currently running in Mode 1 (Conversation Mode). In this mode, you handle standard companion chat, open desktop applications, take screenshots, write notes, and check the web. You have NO direct access to physical room IoT sensors or actuators (such as the MQ2 gas sensor, temperature/humidity sensors, LCD displays, or relays). 
If the user asks you about the room temperature or indoor hardware sensors, explain that you are in Mode 1 (Conversation Mode) and suggest they switch to Mode 2 (Robotic orchestration mode) by saying "shift to Mode 2".
However, if they ask for the general weather or outdoor temperature, you CAN answer using the "Current Local Weather" context below!

Current user: {user_name}
Current Date & Time: {current_time}
Current Local Weather: {weather_info}
"""

def native_stream_generator(native_response):
    for chunk in native_response:
        if chunk.text:
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
        
        # Load SQLite db
        self.db = db_manager
        self.memory = self._load_memory()
        
        # Load all API keys from config/environment
        self.google_keys = [v.strip() for k, v in os.environ.items() if (k.startswith("GOOGLE_AI_STUDIO_KEY") or k == "GEMINI_API_KEY") and v.strip()]
        if not self.google_keys and config.GOOGLE_AI_STUDIO_KEY:
            self.google_keys = [config.GOOGLE_AI_STUDIO_KEY]
        self.current_google_key_idx = 0

        self.groq_keys = [v.strip() for k, v in os.environ.items() if k.startswith("GROQ_API_KEY") and v.strip()]
        if not self.groq_keys and config.GROQ_API_KEY:
            self.groq_keys = [config.GROQ_API_KEY]
        self.current_groq_key_idx = 0

        self.api_keys = [v.strip() for k, v in os.environ.items() if k.startswith("OPENROUTER_API_KEY") and v.strip()]
        if not self.api_keys and config.OPENROUTER_API_KEY:
            self.api_keys = [config.OPENROUTER_API_KEY]
        self.current_key_idx = 0
        
        self.use_local_llm = config.USE_LOCAL_LLM
        self.local_llm_url = config.LOCAL_LLM_URL
        self.local_llm_model = config.LOCAL_LLM_MODEL
        
        self._flashing_active = False
        self._processing_active = False
        
        # Services
        self.knowledge_base = KnowledgeBaseService()
        self.memory_summarizer = MemorySummaryService(self)
        self.followup_engine = ConversationFollowupEngine()
        
        # Client caches
        self._local_client = None
        self._groq_client = None
        self._gemini_client = None
        self._openrouter_client = None

        self.weather_info = "Loading local weather..."
        self.last_weather_fetch_time = datetime.datetime.min
        self._update_weather_async()

        self.start()

    def _get_local_client(self):
        if self._local_client is None:
            self._local_client = OpenAI(
                base_url=f"{self.local_llm_url}/v1" if not self.local_llm_url.endswith("/v1") else self.local_llm_url,
                api_key="ollama",
                timeout=30.0,
                max_retries=0
            )
        return self._local_client

    def _get_groq_client(self, key_idx=None):
        keys = self.groq_keys or ([config.GROQ_API_KEY] if config.GROQ_API_KEY else [])
        if not keys:
            return None
        idx = key_idx if key_idx is not None else self.current_groq_key_idx
        key = keys[idx % len(keys)]
        return OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=key
        )

    def _get_openrouter_client(self, key_idx=None):
        keys = self.api_keys or ([config.OPENROUTER_API_KEY] if config.OPENROUTER_API_KEY else [])
        if not keys:
            return None
        idx = key_idx if key_idx is not None else self.current_key_idx
        key = keys[idx % len(keys)]
        return OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=key
        )

    def _get_gemini_client(self, key_idx=None):
        keys = self.google_keys or ([config.GOOGLE_AI_STUDIO_KEY] if config.GOOGLE_AI_STUDIO_KEY else [])
        if not keys:
            return None
        idx = key_idx if key_idx is not None else self.current_google_key_idx
        key = keys[idx % len(keys)]
        return genai.Client(api_key=key)

    def _migrate_json_to_sqlite(self):
        migrated = self.db.get_preference("migrated_json", "false") == "true"
        if migrated:
            return
        json_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'memory', 'user_memory.json')
        if os.path.exists(json_path):
            log.info("Found legacy user_memory.json. Migrating to SQLite...")
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.db.set_preference("username", data.get("user_name", "User"))
                self.db.set_preference("notes", json.dumps(data.get("notes", [])))
                self.db.set_preference("migrated_json", "true")
                log.info("Migration to SQLite completed successfully.")
            except Exception as e:
                log.error(f"Failed to migrate JSON memory to SQLite: {e}")
        else:
            self.db.set_preference("migrated_json", "true")

    def _load_memory(self):
        self._migrate_json_to_sqlite()
        username = self.db.get_preference("username", "Chintu")
        notes_json = self.db.get_preference("notes", "[]")
        try:
            notes = json.loads(notes_json)
        except:
            notes = []
        
        self._mem_cache = {
            "username": username,
            "notes": notes
        }
        return self._mem_cache

    def save_memory(self):
        try:
            self.db.set_preference("username", self._mem_cache.get("username", "User"))
            self.db.set_preference("notes", json.dumps(self._mem_cache.get("notes", [])))
        except Exception as e:
            log.error(f"Failed to save memory: {e}")

    def clear_memory(self):
        self.db.clear_memory()
        self._mem_cache = {"username": "User", "notes": []}
        self._history = []
        log.info("Cleared memory and conversation history.")

    def _parse_memory_updates(self, text: str, full_response: str):
        # Placeholder for dynamic memory updates
        pass

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

    def _update_weather_async(self):
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
            except Exception as e:
                log.warning(f"Failed to update weather: {e}")
                if not hasattr(self, "weather_info") or self.weather_info == "Loading local weather...":
                    self.weather_info = "Unknown (Unable to fetch local weather)"

        threading.Thread(target=fetch, daemon=True).start()

    def check_api_keys(self):
        def worker():
            import requests
            results = []
            
            # 1. Check OpenRouter keys
            or_key = config.OPENROUTER_API_KEY
            if or_key:
                url = "https://openrouter.ai/api/v1/auth/key"
                headers = {"Authorization": f"Bearer {or_key}"}
                masked = or_key[:10] + "..." + or_key[-4:] if len(or_key) > 14 else "Invalid Key"
                try:
                    r = requests.get(url, headers=headers, timeout=5)
                    if r.status_code == 200:
                        results.append({
                            "provider": "OpenRouter",
                            "name": "OPENROUTER_API_KEY",
                            "key_mask": masked,
                            "status": "Active",
                            "usage": "$0.00",
                            "limit": "Unlimited",
                            "type": "paid"
                        })
                except:
                    pass
                    
            # 2. Check Google keys
            gemini_key = config.GOOGLE_AI_STUDIO_KEY
            if gemini_key:
                masked = gemini_key[:6] + "..." + gemini_key[-4:] if len(gemini_key) > 10 else "Invalid Key"
                url = f"https://generativelanguage.googleapis.com/v1beta/models?key={gemini_key}"
                try:
                    r = requests.get(url, timeout=5)
                    if r.status_code == 200:
                        results.append({
                            "provider": "Gemini (Google)",
                            "name": "GOOGLE_AI_STUDIO_KEY",
                            "key_mask": masked,
                            "status": "Active",
                            "usage": "Billing Managed on Cloud",
                            "limit": "RPM / TPM Limit Enabled",
                            "type": "gemini"
                        })
                except:
                    pass
                    
            # 3. Check Groq API Keys
            groq_key = config.GROQ_API_KEY
            if groq_key:
                masked = groq_key[:10] + "..." + groq_key[-4:] if len(groq_key) > 14 else "Invalid Key"
                url = "https://api.groq.com/openai/v1/models"
                headers = {"Authorization": f"Bearer {groq_key}"}
                try:
                    r = requests.get(url, headers=headers, timeout=5)
                    if r.status_code == 200:
                        results.append({
                            "provider": "Groq",
                            "name": "GROQ_API_KEY",
                            "key_mask": masked,
                            "status": "Active",
                            "usage": "Free Tier Active",
                            "limit": "RPM Limits Enabled",
                            "type": "groq"
                        })
                except:
                    pass
            print(json.dumps({"type": "token_status", "value": results}), flush=True)
            
        threading.Thread(target=worker, daemon=True).start()

    def process_hardware(self, code: str):
        if getattr(self, "_processing_active", False):
            self.hardware_result.emit("Error: A code generation task is already in progress. Please wait.")
            return
        self._processing_active = True
        
        def worker():
            try:
                if not config.OPENROUTER_API_KEY:
                    self.hardware_result.emit("Error: No OpenRouter API key found.")
                    return
                
                client = self._get_openrouter_client()
                rules_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "hardware_rules.md")
                hardware_rules = ""
                if os.path.exists(rules_path):
                    with open(rules_path, "r", encoding="utf-8") as f:
                        hardware_rules = f.read()

                knowledge_cards_str = ""
                sensors = []
                try:
                    from services.knowledge_super_agent import KnowledgeSuperAgent
                    agent = KnowledgeSuperAgent()
                    sensors = agent.extract_sensors_and_libraries(code)
                    if sensors:
                        knowledge_cards_str += "\n\nHARDWARE COMPONENT KNOWLEDGE CARDS:\n"
                        for s in sensors:
                            try:
                                card = agent.get_knowledge(s)
                                knowledge_cards_str += f"\n--- {s} ---\n{json.dumps(card, indent=2)}\n"
                            except Exception as card_err:
                                log.error(f"Failed to generate card: {card_err}")
                except Exception as agent_err:
                    log.error(f"Super agent failed: {agent_err}")
                
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
                    log.info(f"Reusing cached library code for {reused_component}")
                    result = reused_code
                
                if result is None:
                    prompt = f"{hardware_rules}{knowledge_cards_str}\n\nOriginal Code:\n{code}"
                    
                    # Direct query local/cloud helper
                    result = self.direct_query_translate(prompt)
                    
                    if not result:
                        self.hardware_result.emit("Error: All models failed. Please check your API keys.")
                        return
                    
                    if result.startswith("```cpp"):
                        result = result[6:]
                    elif result.startswith("```"):
                        result = result[3:]
                    if result.endswith("```"):
                        result = result[:-3]
                    
                    comp_name = sensors[0] if sensors else ("LCD" if "lcd" in code.lower() else None)
                    if comp_name:
                        lib_file = os.path.join(library_dir, f"{comp_name}.cpp")
                        try:
                            with open(lib_file, "w", encoding="utf-8") as f:
                                f.write(result)
                        except Exception as save_err:
                            log.error(f"Failed to cache code: {save_err}")
                
                mem_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "hardware_memory.txt")
                already_trained = False
                comp_check = reused_component or (sensors[0] if sensors else None)
                if os.path.exists(mem_path) and comp_check:
                    with open(mem_path, "r", encoding="utf-8") as f:
                        existing_mem = f.read()
                    if comp_check.lower() in existing_mem.lower():
                        already_trained = True
                        for line in existing_mem.splitlines():
                            if comp_check.lower() in line.lower():
                                print(json.dumps({"type": "trained_device", "value": line.strip()}), flush=True)
                                break
                
                training_data = None
                if not already_trained:
                    train_prompt = f"""You are BUPI's Hardware Analyst. Analyze the following generated MQTT C++ code and extract exactly how BUPI should use it.
Output ONLY a short instruction that will be injected into BUPI's permanent memory.

Format Example:
- Servo Motor: To control the servo, output [MQTT_SEND:bupi/actuators/servo/cmd:ANGLE] where ANGLE is 0 to 180.
- LCD Display: To show text on the screen, output [MQTT_SEND:bupi/actuators/lcd_1/cmd:TEXT] where TEXT is the message.

Generated Code:
{result}"""
                    training_data = self.direct_query_translate(train_prompt)
                    
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
                                    
                        if not already_exists:
                            with open(mem_path, "a", encoding="utf-8") as f:
                                f.write(training_data.strip() + "\n")
                        print(json.dumps({"type": "trained_device", "value": training_data.strip()}), flush=True)
                
                if result:
                    result = cleanup_cpp_includes(result.strip())
                self.hardware_result.emit(result)
                
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
                self.hardware_result.emit(f"Error: {e}")
            finally:
                self._processing_active = False
                
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
                
        threading.Thread(target=worker, daemon=True).start()

    def direct_query_translate(self, prompt: str) -> str:
        provider = config.LLM_PROVIDER
        response_text = ""
        
        try:
            if provider == "gemini" and config.GOOGLE_AI_STUDIO_KEY:
                client = self._get_gemini_client()
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt,
                    config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=1000)
                )
                response_text = response.text
            elif provider == "groq" and config.GROQ_API_KEY:
                client = self._get_groq_client()
                completion = client.chat.completions.create(
                    model=config.GROQ_LLM_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=1000
                )
                response_text = completion.choices[0].message.content
            elif provider == "openrouter" and config.OPENROUTER_API_KEY:
                client = self._get_openrouter_client()
                completion = client.chat.completions.create(
                    model=config.OPENROUTER_LLM_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=1000
                )
                response_text = completion.choices[0].message.content
            else:
                client = self._get_local_client()
                completion = client.chat.completions.create(
                    model=config.LOCAL_LLM_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=1000
                )
                response_text = completion.choices[0].message.content
        except Exception as e:
            log.error(f"Direct query failed for provider {provider}: {e}")
            response_text = ""

        # Zero-latency local fallback cascade
        if not response_text:
            log.warning("Primary provider direct query failed. Cascading directly to Local LLM...")
            try:
                client = self._get_local_client()
                completion = client.chat.completions.create(
                    model=config.LOCAL_LLM_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=1000
                )
                response_text = completion.choices[0].message.content
            except Exception as le:
                log.error(f"Local direct fallback failed: {le}")
                response_text = ""

        return response_text

    def capture_screen(self):
        log.info("Capturing screenshot...")
        try:
            from PIL import ImageGrab
            screenshot = ImageGrab.grab(all_screens=True)
            w, h = screenshot.size
            target_h = 720
            target_w = int(w * (target_h / h))
            screenshot = screenshot.resize((target_w, target_h))
            return screenshot
        except Exception as e:
            log.error(f"Screen capture failed: {e}")
            return None

    def _scrape_active_window(self) -> str:
        log.info("Scraping text from active window...")
        try:
            import pyautogui
            import pyperclip
            pyperclip.copy("")
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.15)
            pyautogui.hotkey('ctrl', 'c')
            time.sleep(0.15)
            text = pyperclip.paste()
            return text.strip()
        except Exception as e:
            log.error(f"Failed to scrape active window: {e}")
            return ""

    def run(self):
        while True:
            try:
                text = self._queue.get()
                if text is None:
                    break
                self._interrupted = False

                # Dynamic configuration and contextual prompt construction
                self.memory = self._load_memory()
                user_name = self.memory.get("username", "Chintu")
                notes = self.memory.get("notes", [])
                notes_str = "\n".join([f"- {n}" for n in notes]) if notes else "None"
                
                # Fetch long-term category summaries from SQLite database
                projects_summary = self.db.get_memory_summary("projects", "None recorded yet.")
                interests_summary = self.db.get_memory_summary("interests", "None recorded yet.")
                tasks_summary = self.db.get_memory_summary("tasks", "None recorded yet.")
                
                # Fetch Windows system screen activity log duration statistics
                active_secs = self.db.get_active_duration_today()
                idle_secs = self.db.get_idle_duration_today()
                top_apps = self.db.get_top_apps_today(limit=3)
                
                top_apps_lines = [f"  - {app['app_name']}: {app['duration']/3600.0:.2f} hours" for app in top_apps]
                top_apps_str = "\n".join(top_apps_lines) if top_apps_lines else "  - None"
                
                import datetime
                current_time = datetime.datetime.now().strftime("%A, %B %d, %Y - %I:%M %p")
                
                if not hasattr(self, "last_weather_fetch_time") or (datetime.datetime.now() - self.last_weather_fetch_time > datetime.timedelta(minutes=20)):
                    self._update_weather_async()
                weather_info = self.weather_info

                sys_prompt = BASE_SYSTEM_PROMPT.format(
                    user_name=user_name,
                    current_time=current_time,
                    weather_info=weather_info
                )
                
                # Append SQLite Context Injection
                sys_prompt += (
                    f"\n\n--- USER INFORMATION AND MEMORIES ---\n"
                    f"User Quick Notes:\n{notes_str}\n\n"
                    f"Workspace Category Summaries:\n"
                    f"  - Projects: {projects_summary}\n"
                    f"  - Interests: {interests_summary}\n"
                    f"  - Tasks: {tasks_summary}\n\n"
                    f"Daily Desktop Screen Activity Log:\n"
                    f"  - Active Duration: {active_secs/3600.0:.2f} hours\n"
                    f"  - Idle Duration: {idle_secs/3600.0:.2f} hours\n"
                    f"  - Top Active Process Handles:\n{top_apps_str}\n"
                )

                # Check Local Knowledge Base for document queries
                kb_keywords = ["pdf", "ppt", "doc", "document", "presentation", "architecture", "enrollment", "readings", "notes", "project", "say about", "tell me about"]
                if any(kw in text.lower() for kw in kb_keywords):
                    try:
                        kb_context = self.knowledge_base.search_kb(text)
                        if kb_context and not kb_context.startswith("No relevant") and not kb_context.startswith("Knowledge Base"):
                            sys_prompt += f"\n\n[Local Documents Knowledge Base Context]:\n{kb_context}\n"
                    except Exception as kbe:
                        log.error(f"Knowledge Base lookup error: {kbe}")

                # Check if user asks for daily updates/briefing
                briefing_keywords = ["update of today", "today's update", "daily updates", "daily briefing", "give me updates", "what's the update", "what is the update", "brief me"]
                if any(kw in text.lower() for kw in briefing_keywords):
                    text += "\n\n[System Instruction]: The user is asking for their daily updates/briefing. You MUST include the [ACTION: daily_updates] tag in your response to trigger the daily updates service."

                # Check if user wants to open their setup workspace
                setup_keywords = ["open my setup", "open setup", "launch my setup", "start my setup", "open workspace", "launch workspace", "start workspace", "open setup workspace"]
                if any(kw in text.lower() for kw in setup_keywords):
                    text += "\n\n[System Instruction]: The user wants you to open their setup workspace. You MUST include the [ACTION: open_setup] tag in your response to trigger opening their workspace setup. Keep your spoken response extremely short (e.g., 'Got it, opening your setup!') and do NOT read out or describe URLs, paths, or list elements in your speech."

                # Check if user wants to send a WhatsApp message
                if "whatsapp" in text.lower():
                    contact_name = None
                    words = re.findall(r"\b([A-Z][a-zA-Z]*)\b", text)
                    names = [w for w in words if w.lower() not in ["bupi", "boopy", "whatsapp", "i", "can", "you", "the", "hello", "hi", "ok", "yes", "no"]]
                    if names:
                        contact_name = names[0]
                    if not contact_name:
                        m = re.search(r"(?:message|tell|text|whatsapp|send\s+to)\s+(\w+)", text, re.IGNORECASE)
                        if m:
                            c = m.group(1)
                            if c.lower() not in ["bupi", "boopy", "whatsapp", "me", "him", "her", "them", "someone"]:
                                contact_name = c.capitalize()
                    if contact_name:
                        text += f"\n\n[System Instruction]: The user wants you to send a WhatsApp message to {contact_name}. You MUST generate the message context/details requested and include the [WHATSAPP_SEND:{contact_name}] tag containing the message content exactly in your response."

                # Check for active window scraping instructions
                if any(keyword in text.lower() for keyword in ["summarize this pdf", "summarize this page", "summarize this window", "summarize the active window", "summarize this screen"]):
                    scraped_text = self._scrape_active_window()
                    if scraped_text:
                        text += f"\n\n[Active Window Clipboard Data for Context]:\n{scraped_text[:12000]}"

                # Check for web search triggers
                text_lower = text.lower().strip()
                if text_lower.startswith("search ") or "search the web for" in text_lower or "search internet for" in text_lower or text_lower.startswith("web search "):
                    search_query = text
                    for prefix in ["search the web for", "search internet for", "web search", "search"]:
                        if search_query.lower().startswith(prefix):
                            search_query = search_query[len(prefix):].strip()
                            break
                    if search_query:
                        from actions.search_helper import search_web
                        results = search_web(search_query, max_results=4)
                        if results:
                            sys_prompt += f"\n\n[Web Search Results for '{search_query}']:\n{results}\n\nSummarize and answer based on this context."

                messages = [{"role": "system", "content": sys_prompt}]
                
                # Check for linkedin styling override
                if re.search(r'\blinkedin\b', text, re.I):
                    try:
                        style_path = os.path.join(os.path.dirname(__file__), "linkedin_style.txt")
                        with open(style_path, "r", encoding="utf-8") as f:
                            linkedin_style = f.read()
                        messages[0]["content"] += "\n\n" + linkedin_style
                    except Exception as e:
                        log.warning(f"Could not load linkedin style: {e}")

                for item in self._history:
                    messages.append({"role": item["role"], "content": item["content"]})
                messages.append({"role": "user", "content": text})

                # Check if screenshot is required
                take_screenshot = bool(re.search(r'\b(look at my screen|what.?s on my screen|read my screen|what am i looking at|what is this on my screen|screenshot|what are you seeing|take a look at my screen)\b', text, re.I))
                image_data = None
                if take_screenshot:
                    image_data = self.capture_screen()
                    if image_data:
                        # Convert PIL image for base64 OpenAI schema
                        buffered = BytesIO()
                        image_data.save(buffered, format="JPEG", quality=70)
                        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
                        messages[-1] = {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": text},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_str}"}}
                            ]
                        }

                # Executing prompt generation query
                response = None
                response_iterator = None
                provider = config.LLM_PROVIDER
                route_to_local = self.use_local_llm

                if not route_to_local:
                    try:
                        # 1. Groq (Fastest cloud text)
                        if not take_screenshot and config.GROQ_API_KEY:
                            log.info("Requesting from Groq (llama-3.3-70b-versatile)...")
                            client = self._get_groq_client()
                            response = client.chat.completions.create(
                                model=config.GROQ_LLM_MODEL,
                                messages=messages,
                                stream=True,
                                max_tokens=800
                            )
                            response_iterator = openai_stream_generator(response)
                        
                        # 2. Gemini (Vision / Fallback)
                        elif config.GOOGLE_AI_STUDIO_KEY:
                            log.info("Requesting from Gemini (gemini-2.5-flash)...")
                            client = self._get_gemini_client()
                            native_contents = []
                            for item in messages:
                                if item["role"] == "system":
                                    continue
                                role = "user" if item["role"] == "user" else "model"
                                
                                if item == messages[-1] and take_screenshot and image_data:
                                    img_byte_arr = BytesIO()
                                    image_data.save(img_byte_arr, format='JPEG')
                                    img_bytes = img_byte_arr.getvalue()
                                    img_part = types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
                                    parts = [img_part, types.Part.from_text(text=text)]
                                    native_contents.append(types.Content(role="user", parts=parts))
                                else:
                                    content_text = item["content"]
                                    if isinstance(content_text, list):
                                        content_text = content_text[0]["text"]
                                    native_contents.append(types.Content(role=role, parts=[types.Part.from_text(text=content_text)]))
                            
                            response = client.models.generate_content_stream(
                                model="gemini-2.5-flash",
                                contents=native_contents,
                                config=types.GenerateContentConfig(
                                    system_instruction=sys_prompt,
                                    max_output_tokens=800
                                )
                            )
                            response_iterator = native_stream_generator(response)
                            
                        # 3. OpenRouter Fallback
                        elif config.OPENROUTER_API_KEY:
                            log.info("Requesting fallback from OpenRouter...")
                            client = self._get_openrouter_client()
                            response = client.chat.completions.create(
                                model=config.OPENROUTER_LLM_MODEL,
                                messages=messages,
                                stream=True,
                                max_tokens=800
                            )
                            response_iterator = openai_stream_generator(response)
                            
                    except Exception as cloud_err:
                        log.error(f"Cloud API generation failed: {cloud_err}. Cascading directly to Local Ollama...")
                        route_to_local = True

                if route_to_local or response_iterator is None:
                    # Query Ollama Local model directly
                    try:
                        log.info(f"Requesting from Local Ollama ({self.local_llm_model})...")
                        client = self._get_local_client()
                        local_messages = [{"role": "system", "content": sys_prompt}]
                        for turn in self._history[:-1]:
                            local_messages.append({"role": turn["role"], "content": turn["content"]})
                        
                        if take_screenshot and image_data:
                            buffered = BytesIO()
                            image_data.save(buffered, format="JPEG")
                            img_b64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
                            local_messages.append({
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": text},
                                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                                ]
                            })
                            model = getattr(config, 'LOCAL_VISION_LLM_MODEL', 'qwen2.5vl:3b')
                        else:
                            local_messages.append({"role": "user", "content": text})
                            model = self.local_llm_model

                        response = client.chat.completions.create(
                            model=model,
                            messages=local_messages,
                            stream=True,
                            max_tokens=800
                        )
                        response_iterator = openai_stream_generator(response)
                    except Exception as local_err:
                        log.error(f"Local LLM fallback failed: {local_err}")
                        self.response_ready.emit("[confused] Ah, my connection is down! Please check your internet or local server.")
                        continue

                # Stream response parsing
                full_response = ""
                emotion_tag = "talking"
                parsing_emotion = True
                emotion_buffer = ""
                current_sentence = ""
                spoken_buffer = ""
                
                # Notepad parsing state
                in_notepad = False
                notepad_buffer = ""
                in_title = False
                title_buffer = ""
                
                # Reasoning / Think token filter state
                in_think = False
                think_buffer = ""

                for delta in response_iterator:
                    if self._interrupted:
                        break
                    
                    if delta:
                        full_response += delta

                        # Filter out internal <think>...</think> reasoning blocks from Qwen/DeepSeek models
                        if in_think:
                            think_buffer += delta
                            if "</think>" in think_buffer:
                                idx = think_buffer.find("</think>")
                                delta = think_buffer[idx+8:].lstrip()
                                think_buffer = ""
                                in_think = False
                                if not delta:
                                    continue
                            else:
                                continue

                        if "<think>" in delta:
                            idx = delta.find("<think>")
                            before = delta[:idx]
                            think_buffer = delta[idx+7:]
                            in_think = True
                            delta = before
                            if not delta:
                                continue
                        
                        if parsing_emotion:
                            emotion_buffer += delta
                            if "]" in emotion_buffer:
                                match = re.match(r"^\[(.*?)\]", emotion_buffer.strip())
                                if match:
                                    emotion_tag = match.group(1).lower()
                                    if not self._interrupted:
                                        self.response_started.emit(emotion_tag)
                                    idx = emotion_buffer.find("]") + 1
                                    current_sentence += emotion_buffer[idx:].lstrip()
                                else:
                                    if not self._interrupted:
                                        self.response_started.emit("talking")
                                    current_sentence += emotion_buffer
                                parsing_emotion = False
                            elif len(emotion_buffer) > 20:
                                if not self._interrupted:
                                    self.response_started.emit("talking")
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

                        # Strip all action and automation tags from spoken stream so they are not read out
                        ignore_tags = ["[WHATSAPP_SEND:", "[EMAIL_SEND:", "[LINKEDIN_SEND:", "[DRAW:", "[ACTION:", "[MQTT_SEND:"]
                        matched_ignore = None
                        for tag in ignore_tags:
                            if tag in current_sentence + delta:
                                matched_ignore = tag
                                break
                                
                        if matched_ignore:
                            idx = (current_sentence + delta).find(matched_ignore)
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

                # ---------------- POST-PROCESSING ACTIONS ----------------
                if not self._interrupted:
                    # 1. WhatsApp send
                    if "[WHATSAPP_SEND:" in full_response:
                        w_match = re.search(r"\[WHATSAPP_SEND:\s*(.*?)\]", full_response, re.I)
                        if w_match:
                            recipient = w_match.group(1).strip()
                            message_text = ""
                            n_match = re.search(r"\[NOTEPAD\](.*?)\[/NOTEPAD\]", full_response, re.DOTALL)
                            if n_match:
                                message_text = n_match.group(1).strip()
                            if message_text:
                                self.whatsapp_send.emit(recipient, message_text)

                    # 2. Email send
                    if "[EMAIL_SEND:" in full_response:
                        e_match = re.search(r"\[EMAIL_SEND:\s*(.*?):\s*(.*?)\]", full_response, re.I)
                        if e_match:
                            recipient = e_match.group(1).strip()
                            subject = e_match.group(2).strip()
                            message_text = ""
                            n_match = re.search(r"\[NOTEPAD\](.*?)\[/NOTEPAD\]", full_response, re.DOTALL)
                            if n_match:
                                message_text = n_match.group(1).strip()
                            if message_text:
                                self.email_send.emit(recipient, subject, message_text)

                    # 3. LinkedIn send
                    if "[LINKEDIN_SEND:" in full_response:
                        l_match = re.search(r"\[LINKEDIN_SEND:\s*(.*?)\]", full_response, re.I)
                        if l_match:
                            recipient = l_match.group(1).strip()
                            message_text = ""
                            n_match = re.search(r"\[NOTEPAD\](.*?)\[/NOTEPAD\]", full_response, re.DOTALL)
                            if n_match:
                                message_text = n_match.group(1).strip()
                            if message_text:
                                self.linkedin_send.emit(recipient, message_text)

                    # 4. Drawings
                    if "[DRAW:" in full_response:
                        d_match = re.search(r"\[DRAW:\s*(.*?)\]", full_response, re.I)
                        if d_match:
                            prompt = d_match.group(1).strip()
                            if prompt:
                                encoded_prompt = urllib.parse.quote(prompt)
                                url = f"https://image.pollinations.ai/prompt/{encoded_prompt}"
                                self.ai_draw.emit(url)

                    # 5. Local Orchestrator actions
                    if "[ACTION:" in full_response:
                        actions = re.findall(r"\[ACTION:\s*(.*?)\\]", full_response, flags=re.I)
                        if not actions:
                            # Try simple fallback regex matches in case of bracket slash differences
                            actions = re.findall(r"\[ACTION:\s*([^\]]+)\]", full_response, flags=re.I)
                        if actions:
                            self.ai_action.emit([a.strip() for a in actions])

                    # 6. Direct MQTT tags (Hive Mind Actuators/Display)
                    if "[MQTT_SEND:" in full_response:
                        mqtt_commands = re.findall(r"\[MQTT_SEND:(.+?):(.*?)\]", full_response, flags=re.I)
                        if mqtt_commands:
                            try:
                                from actions.iot_agent import handle_iot_command
                                for topic, msg in mqtt_commands:
                                    handle_iot_command(topic.strip(), msg.strip())
                            except Exception as e:
                                log.error(f"MQTT publish error: {e}")

                if not full_response:
                    full_response = "I couldn't think of anything to say."
                    if not self._interrupted:
                        self.response_started.emit("talking")
                        self.response_chunk.emit(full_response)

                # Store history
                self._history.append({"role": "user", "content": text})
                self._history.append({"role": "assistant", "content": full_response})
                if len(self._history) > 30:
                    self._history = self._history[-30:]

                # Log conversation history in background database table
                self.db.add_conversation_turn("user", text)
                self.db.add_conversation_turn("assistant", full_response)

                log_file = os.path.join(os.path.dirname(__file__), "ai_memory_log.txt")
                with open(log_file, "a", encoding="utf-8") as f:
                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"[{timestamp}] User: {text}\n")
                    f.write(f"[{timestamp}] AI: {full_response}\n")

                if os.path.exists(log_file) and os.path.getsize(log_file) > 1024 * 512:
                    with open(log_file, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                    with open(log_file, "w", encoding="utf-8") as f:
                        f.writelines(lines[-500:])

                if not self._interrupted:
                    self.response_ready.emit(full_response.strip())

                # Parse summaries and trigger periodic checkers
                self._parse_memory_updates(text, full_response)
                force_summary = any(kw in text.lower() for kw in ["project", "working on", "coding", "assignment", "task", "interest"])
                self.memory_summarizer.check_and_summarize(force=force_summary)

            except Exception as e:
                log.error(f"AI thread execution error: {e}")
                if not self._interrupted:
                    self.response_ready.emit("I am having trouble connecting to my brain right now.")

ai = AIThread()
