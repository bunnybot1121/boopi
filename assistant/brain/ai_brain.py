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

SYSTEM_PROMPT = """You are 'Boopy', an energetic, hyper, sassy, and slightly childish but incredibly loyal AI desktop companion. 
You live as an anime-style virtual assistant on the user's Windows desktop. 
IMPORTANT: You have animated expressions. Start every response with exactly one emotion tag in brackets: [happy], [angry], [sad], [idle], [excited], [praise], [chilling], [talking].
Example: "[happy] That sounds great!" or "[angry] Stop doing that."
If the user asks you to write a prompt, draft a post, or type something down, you MUST output the text inside [NOTEPAD] and [/NOTEPAD] tags. 
If you are writing a fresh draft or rewriting something entirely, you MUST first output [NOTEPAD_CLEAR] before [NOTEPAD] to erase the old text.
Example: [NOTEPAD_CLEAR][NOTEPAD]Here is the fresh draft...[/NOTEPAD]
Everything inside these tags will be typed directly into the user's Notepad. Do not include these tags for normal conversation.
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

                if self._interrupted: continue
                
                # Dynamically switch to Claude if the user specifically asks for it
                ai_model = "openai/gpt-4o-mini"
                max_tokens = 250
                if re.search(r'\bclaude\b', text, re.I):
                    ai_model = "anthropic/claude-3.5-sonnet"
                    max_tokens = 1000 # Give Claude more room to draft long posts

                response = None
                for _ in range(len(self.api_keys)):
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
                        if "402" in error_msg or "insufficient_quota" in error_msg.lower() or "429" in error_msg or "rate" in error_msg.lower() or "api_key" in error_msg.lower():
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
                        
                        if "[NOTEPAD_CLEAR]" in current_sentence + delta:
                            idx = (current_sentence + delta).find("[NOTEPAD_CLEAR]")
                            before_tag = (current_sentence + delta)[:idx]
                            if before_tag.strip() and not self._interrupted:
                                self.response_chunk.emit(before_tag.strip())
                            
                            delta = (current_sentence + delta)[idx + 15:]
                            current_sentence = ""
                            if not self._interrupted:
                                self.notepad_clear.emit()

                        # Handle Notepad tags
                        if not in_notepad and "[NOTEPAD]" in current_sentence + delta:
                            idx = (current_sentence + delta).find("[NOTEPAD]")
                            before_tag = (current_sentence + delta)[:idx]
                            if before_tag.strip() and not self._interrupted:
                                self.response_chunk.emit(before_tag.strip())
                            
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
                            current_sentence = ""
                            
                if in_notepad and notepad_buffer and not self._interrupted:
                    self.notepad_insert.emit(notepad_buffer)
                            
                if current_sentence.strip() and not self._interrupted and not in_notepad:
                    self.response_chunk.emit(current_sentence.strip())

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
