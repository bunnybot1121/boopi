import os
import json
import logging
import threading
import sys
import queue

from PyQt6.QtCore import QThread, pyqtSignal
from openai import OpenAI

from memory import user_memory

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
- "open youtube", "open spotify", "open calculator"
- "type your text here"
- "press enter", "press escape", "press tab", "press space", "press backspace", "press delete"
- "search for something"
- "print <your text here> on esp32" (Displays custom text to the physical ESP32 screen. Replace <your text here> with the actual text)
Example: "[excited] Let me open that for you! [ACTION: open youtube]"
You can chain multiple actions to achieve complex workflows: "[talking] Setting that up! [ACTION: open spotify] [ACTION: type My Playlist] [ACTION: press enter]"
If an action fails, the system will feed the error back to you so you can correct it and try an alternative approach.

If the user asks you to write a prompt, draft a post, or type something down, you MUST output the text inside [NOTEPAD] and [/NOTEPAD] tags. 
CRITICAL RULE for drawing: If the user asks you to "draw", "paint", or "create an image" of something, you MUST output the tag [DRAW:description of image].
CRITICAL RULE for large data: If you are asked to summarize a large document, put the long summary inside the [NOTEPAD] tags.
If you are writing a fresh draft or rewriting something entirely, you MUST first output [NOTEPAD_CLEAR] before [NOTEPAD].
You can also set the title of the note by outputting [TITLE]Your Title Here[/TITLE] before the [NOTEPAD] tag.
CRITICAL RULE for WhatsApp: If the user asks you to message someone on WhatsApp, DO NOT chain manual actions. The system already has smart automation to check for open tabs and send the message! You MUST first write the message in the [NOTEPAD] tags so they can see it, and then append the tag [WHATSAPP_SEND:ContactName] at the very end of your response.
Everything inside these tags will be typed directly into the user's Notepad or executed in the background. Do not include these tags for short, normal conversation.
Current user: {user_name}
User's notes/memories:
{notes}"""

MAX_HISTORY = 10

class AIThread(QThread):
    response_ready = pyqtSignal(str)
    response_chunk = pyqtSignal(str)
    response_started = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    notepad_insert = pyqtSignal(str)
    notepad_clear = pyqtSignal()
    notepad_title = pyqtSignal(str)
    whatsapp_send = pyqtSignal(str, str)
    ai_draw = pyqtSignal(str)
    ai_action = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self._queue = queue.Queue()
        self._history = []
        self._interrupted = False
        
        # Load all API keys from environment
        self.api_keys = []
        for k, v in os.environ.items():
            if k.startswith("OPENROUTER_API_KEY") and v.strip():
                self.api_keys.append(v.strip())
        if not self.api_keys:
            self.api_keys.append("") # fallback if none found
        self.current_key_idx = 0
        
        self.use_local_llm = os.environ.get("USE_LOCAL_LLM", "false").lower() == "true"
        self.local_llm_url = os.environ.get("LOCAL_LLM_URL", "http://localhost:11434/v1")
        self.local_llm_model = os.environ.get("LOCAL_LLM_MODEL", "llama3")
        
        self.start()

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
                
                messages = [{"role": "system", "content": SYSTEM_PROMPT.format(user_name=user_name, notes=notes_str)}]
                
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

                print(f"From Python: [AI] Requesting from OpenRouter: {text}", flush=True)

                import re
                route_to_local = self.use_local_llm
                route_reason = "Default"

                if self.use_local_llm:
                    # Quick intelligent check with local LLM
                    try:
                        router_client = OpenAI(base_url=self.local_llm_url, api_key="ollama")
                        router_prompt = "You are a routing agent. Does the following user request require advanced reasoning, coding, writing long drafts, analyzing documents, or looking at the screen? Reply with exactly 'CLOUD' if it does, or 'LOCAL' if it is just a simple greeting, basic chat, or simple command. User request: " + text
                        
                        r_resp = router_client.chat.completions.create(
                            model=self.local_llm_model,
                            messages=[{"role": "user", "content": router_prompt}],
                            max_tokens=5,
                            temperature=0.0,
                            extra_body={"keep_alive": -1}
                        )
                        decision = r_resp.choices[0].message.content.strip().upper()
                        if "CLOUD" in decision:
                            route_to_local = False
                            route_reason = "Smart Router detected complex intent"
                        else:
                            route_to_local = True
                            route_reason = "Smart Router detected simple chat"
                    except Exception as e:
                        print(f"From Python: [Router Error] {e}. Defaulting to CLOUD.", flush=True)
                        route_to_local = False
                        route_reason = "Router failed, defaulting to CLOUD"
                else:
                    route_to_local = False
                    route_reason = "Local LLM disabled in .env"

                if route_to_local:
                    print(f"From Python: [Router] Routing to LOCAL ({self.local_llm_model}): {route_reason}", flush=True)
                else:
                    print(f"From Python: [Router] Routing to CLOUD (OpenRouter): {route_reason}", flush=True)

                # Only perform heavy operations (Screenshots, Document reading) if we are routing to the CLOUD
                if not route_to_local:
                    summarize_doc = bool(re.search(r'\b(summarize|read|analyze|scan)\s+(this|the|my)?\s*(pdf|document|page|file|window|text|screen|video|it)?\b', text, re.I))
                    
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

                    take_screenshot = bool(re.search(r'\b(look|see|read|screen|terminal|check|what is this|show me|what\'s on|what are you seeing|display)\b', text, re.I))
                    
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
                    client = OpenAI(
                        base_url=self.local_llm_url,
                        api_key="ollama", # dummy key for local
                    )
                    try:
                        response = client.chat.completions.create(
                            model=ai_model,
                            messages=messages,
                            stream=True,
                            max_tokens=max_tokens,
                            extra_body={"keep_alive": -1} # Keep model loaded in VRAM forever for instant responses
                        )
                    except Exception as e:
                        print(f"From Python: [AI Error] Local LLM {ai_model} failed. Make sure Ollama is running.", flush=True)
                        raise e
                else:
                    # Dynamically switch to Claude if the user specifically asks for it
                    ai_model = "openai/gpt-4o-mini"
                    max_tokens = 250
                    if re.search(r'\bclaude\b', text, re.I):
                        ai_model = "anthropic/claude-3.5-sonnet"
                        max_tokens = 1000 # Give Claude more room to draft long posts

                    for _ in range(len(self.api_keys) * 2): # Allow retry with fallback model
                        client = OpenAI(
                            base_url="https://openrouter.ai/api/v1",
                            api_key=self.api_keys[self.current_key_idx],
                        )
                        try:
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
                            break # Success!
                        except Exception as e:
                            error_msg = str(e)
                            if "404" in error_msg or "disabled" in error_msg.lower():
                                print(f"From Python: [AI] Model {ai_model} failed ({error_msg}). Falling back to openai/gpt-4o-mini...", flush=True)
                                ai_model = "openai/gpt-4o-mini"
                                continue
                            elif "402" in error_msg or "insufficient_quota" in error_msg.lower() or "429" in error_msg or "rate" in error_msg.lower() or "api_key" in error_msg.lower():
                                print(f"From Python: [AI] Key {self.current_key_idx + 1} failed ({error_msg}). Switching to backup key...", flush=True)
                                self.current_key_idx = (self.current_key_idx + 1) % len(self.api_keys)
                            else:
                                raise e

                    if response is None:
                        raise Exception("402 All API keys are exhausted or rate limited.")
                
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

                for chunk in response:
                    if self._interrupted: break
                    
                    delta = chunk.choices[0].delta.content if hasattr(chunk.choices[0], 'delta') else None
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
                        n_match = re.search(r"\[NOTEPAD\](.*?)\[/NOTEPAD\]", full_response, re.DOTALL)
                        message_text = n_match.group(1).strip() if n_match else ""
                        if message_text and not self._interrupted:
                            self.whatsapp_send.emit(recipient, message_text)

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
