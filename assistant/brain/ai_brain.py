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
Current user: {user_name}
User's notes/memories:
{notes}"""

MAX_HISTORY = 10

class AIThread(QThread):
    response_ready = pyqtSignal(str)
    response_chunk = pyqtSignal(str)
    response_started = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._queue = queue.Queue()
        self._history = []
        self._interrupted = False
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
                
                client = OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=os.getenv("OPENROUTER_API_KEY"),
                )
                
                messages = [{"role": "system", "content": SYSTEM_PROMPT.format(user_name=user_name, notes=notes_str)}]
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

                response = client.chat.completions.create(
                    model="openai/gpt-4o-mini",
                    messages=messages,
                    stream=True,
                    max_tokens=150,
                    extra_headers={
                        "HTTP-Referer": "http://localhost",
                        "X-Title": "Desktop AI Companion"
                    }
                )
                
                full_response = ""
                emotion_tag = "talking"
                parsing_emotion = True
                emotion_buffer = ""
                current_sentence = ""

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
                            elif len(emotion_buffer) > 20: # Fallback if no tag found soon
                                if not self._interrupted: self.response_started.emit("talking")
                                current_sentence += emotion_buffer
                                parsing_emotion = False
                            continue
                            
                        current_sentence += delta
                        if re.search(r'[.!?\n]\s*$', current_sentence) or delta.endswith('\n'):
                            text_to_emit = current_sentence.strip()
                            if text_to_emit and not self._interrupted:
                                self.response_chunk.emit(text_to_emit)
                            current_sentence = ""
                            
                if current_sentence.strip() and not self._interrupted:
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
