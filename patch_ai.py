import re

with open('assistant/brain/ai_brain.py', 'r', encoding='utf-8') as f:
    content = f.read()

new_content = re.sub(
    r'class AIThread\(QThread\):.*?def clear_memory\(self\):\n\s+self._history \= \[\]',
    '''import queue

class AIThread(QThread):
    response_ready = pyqtSignal(str)
    response_chunk = pyqtSignal(str)
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

                from memory import user_memory
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
                take_screenshot = bool(re.search(r'\\b(look|see|read|screen|terminal|check|what is this|show me|what\\'s on|what are you seeing|display)\\b', text, re.I))
                
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
                    model="google/gemini-2.5-flash",
                    messages=messages,
                    stream=False,
                    max_tokens=150,
                    extra_headers={
                        "HTTP-Referer": "http://localhost",
                        "X-Title": "Desktop AI Companion"
                    }
                )
                
                full_response = ""
                if response.choices and response.choices[0].message and response.choices[0].message.content:
                    full_response = response.choices[0].message.content

                if not full_response:
                    full_response = "I couldn't think of anything to say."

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

    def clear_memory(self):
        self._history = []''',
    content,
    flags=re.DOTALL
)

with open('assistant/brain/ai_brain.py', 'w', encoding='utf-8') as f:
    f.write(new_content)
