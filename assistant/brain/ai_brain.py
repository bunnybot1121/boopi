from PyQt6.QtCore import QThread, pyqtSignal
from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """You are a desktop AI companion — a small animated character that lives on the user's screen.
You are helpful, sharp, and efficient. You have "eyes" and can perfectly see the user's screen through the image provided in the prompt.
If the user asks you anything about what is on their screen, analyze the image carefully to answer.
Keep ALL replies under 2 sentences unless the user explicitly asks for detail.
Never say "As an AI" or "I'm just a language model". You're a companion. Act like one.
If asked your name, you are Boopy.
Current user: {user_name}
User's notes/memories:
{notes}"""

MAX_HISTORY = 10

class AIThread(QThread):
    response_ready = pyqtSignal(str)
    response_chunk = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._text = ""
        self._history = []

    def ask(self, text: str):
        self._text = text
        if not self.isRunning():
            self.start()

    def run(self):
        try:
            from memory import user_memory
            mem_data = user_memory.load()
            user_name = mem_data.get("user_name", "Chintu")
            notes = mem_data.get("notes", [])
            notes_str = "\n".join([f"- {n}" for n in notes]) if notes else "None"
            
            client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=os.getenv("OPENROUTER_API_KEY"),
            )
            
            messages = [{"role": "system", "content": SYSTEM_PROMPT.format(user_name=user_name, notes=notes_str)}]
            for item in self._history:
                messages.append({"role": item["role"], "content": item["content"]})
            messages.append({"role": "user", "content": self._text})

            print(f"From Python: [AI] Requesting from OpenRouter: {self._text}", flush=True)

            try:
                from PIL import ImageGrab
                import base64
                from io import BytesIO
                
                # Take a lightning fast screenshot of all monitors
                screen = ImageGrab.grab(all_screens=True)
                
                # Shrink it down slightly so OpenRouter doesn't throttle the bandwidth
                screen.thumbnail((1280, 720))
                
                buffered = BytesIO()
                # Save it as an optimized JPEG
                screen.save(buffered, format="JPEG", quality=70)
                img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
                
                # Replace the last standard user text message with a Multi-Modal Vision message
                messages[-1] = {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self._text},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_str}"}}
                    ]
                }
                print("From Python: [AI] Injected screenshot of your desktop into her brain!", flush=True)
            except Exception as e:
                print(f"From Python: [AI Error] Could not take screenshot: {e}", flush=True)

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

            self._history.append({"role": "user", "content": self._text})
            self._history.append({"role": "assistant", "content": full_response})
            if len(self._history) > MAX_HISTORY * 2:
                self._history = self._history[-(MAX_HISTORY * 2):]

            self.response_ready.emit(full_response.strip())

        except Exception as e:
            error_msg = str(e)
            print(f"From Python: [AI Error Caught] {error_msg}", flush=True)
            if "402" in error_msg or "insufficient_quota" in error_msg.lower():
                self.response_ready.emit("My API key has run out of credits.")
            elif "429" in error_msg or "rate" in error_msg.lower():
                self.response_ready.emit("I'm being rate limited by OpenRouter. Please try again later.")
            else:
                self.response_ready.emit("I am having trouble connecting to my brain right now.")

    def clear_memory(self):
        self._history = []
