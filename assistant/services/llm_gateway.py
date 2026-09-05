import os
import json
try:
    import google.generativeai as genai
    from google.api_core.exceptions import ResourceExhausted
except ImportError:
    genai = None
    ResourceExhausted = Exception
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

class LLMGateway:
    def __init__(self):
        # Gather all GROQ_API_KEYs from the environment
        self.groq_keys = []
        if os.environ.get("GROQ_API_KEY"):
            self.groq_keys.append(os.environ.get("GROQ_API_KEY"))
        for i in range(2, 11):
            key = os.environ.get(f"GROQ_API_KEY_{i}")
            if key:
                self.groq_keys.append(key)

        # Gather all GOOGLE_AI_STUDIO_KEYs from the environment
        # e.g., GOOGLE_AI_STUDIO_KEY, GOOGLE_AI_STUDIO_KEY_2, GOOGLE_AI_STUDIO_KEY_3, etc.
        self.gemini_keys = []
        
        # Check standard GOOGLE_AI_STUDIO_KEY
        if os.environ.get("GOOGLE_AI_STUDIO_KEY"):
            self.gemini_keys.append(os.environ.get("GOOGLE_AI_STUDIO_KEY"))
            
        # Check extensions (_2, _3, _4, etc.) up to 10 just in case
        for i in range(2, 11):
            key = os.environ.get(f"GOOGLE_AI_STUDIO_KEY_{i}")
            if key:
                self.gemini_keys.append(key)
                
        # We know that 'gemini-flash-latest' routes correctly on the preview keys
        self.model_name = "gemini-flash-latest"

    async def classify_intent(self, user_utterance: str) -> dict:
        """
        Takes a natural language string and returns a structured JSON intent.
        """
        system_prompt = """
        You are the Intent Router for BUPI, a smart home desktop companion and physical robotics hive mind.
        Your job is to classify the user's utterance and return ONLY a JSON object belonging to one of the following 4 types:

        1. Physical Hardware & Robotics (motors, LCD display, relays, gas/distance/IMU sensors):
        {
          "type": "hardware_intent",
          "payload": {
             "device": "motors" | "lcd" | "relay" | "sensors" | "general",
             "action": "ON" | "OFF" | "MOVE" | "READ" | "DISPLAY",
             "direction": "forward" | "reverse" | "left" | "right" | "stop",
             "text": "<optional text to display>"
          }
        }

        2. Desktop & Windows OS Automation (opening apps, browser, Gmail, WhatsApp, LinkedIn, Notepad, reminders):
        {
          "type": "desktop_automation",
          "payload": {
             "target": "whatsapp" | "gmail" | "linkedin" | "notepad" | "browser" | "app",
             "action": "send_message" | "open_draft" | "search" | "launch",
             "recipient": "<optional recipient name>",
             "text": "<message or search text>"
          }
        }

        3. Technical Knowledge & Hardware Search (datasheets, pinouts, Arduino libraries, hardware specs, wiring):
        {
          "type": "rag_search",
          "payload": {
             "query": "<hardware module or datasheet query string>"
          }
        }

        4. General Conversation & Spoken Chat:
        {
          "type": "chat_response",
          "payload": {
             "text": "<A brief, friendly companion response>"
          }
        }

        Respond ONLY with raw JSON, no markdown code blocks.
        """
        
        if not self.gemini_keys:
            print("[LLM Gateway] No keys found in .env!")
            return {"type": "chat_response", "payload": {"text": "I don't have any API keys configured to think with."}}

        # 1. Attempt using Gemini keys first rotating through all available keys
        for idx, key in enumerate(self.gemini_keys):
            try:
                genai.configure(api_key=key)
                # Setting generation config to require JSON output format
                model = genai.GenerativeModel(
                    model_name=self.model_name,
                    system_instruction=system_prompt,
                    generation_config=genai.GenerationConfig(
                        temperature=0.0,
                        max_output_tokens=150
                    )
                )
                
                response = await model.generate_content_async(user_utterance)
                raw_text = response.text.strip()
                
                # Strip markdown if the LLM added it despite instructions
                if raw_text.startswith("```json"):
                    raw_text = raw_text.split("```json")[1].split("```")[0].strip()
                elif raw_text.startswith("```"):
                    raw_text = raw_text.split("```")[1].strip()
                    
                return json.loads(raw_text)
                
            except ResourceExhausted:
                print(f"[LLM Gateway] Gemini Key {idx + 1} exhausted! Falling back to next key...")
                continue
            except Exception as e:
                print(f"[LLM Gateway] Gemini error with Key {idx + 1}: {e}")
                # For non-quota errors, we also try the next key just in case
                continue

        # 3. Fallback to Local Ollama (llama3.2:3b or llama3.1:8b)
        try:
            print("[LLM Gateway] Attempting intent classification via local Ollama...", flush=True)
            client = AsyncOpenAI(
                base_url="http://localhost:11434/v1",
                api_key="ollama"
            )
            
            # Try llama3.2:3b first (super fast), fallback to llama3.1:8b
            for local_model in ["llama3.2:3b", "llama3.1:8b", "llama3.2:latest"]:
                try:
                    response = await client.chat.completions.create(
                        model=local_model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_utterance}
                        ],
                        temperature=0.0,
                        max_tokens=250,
                        response_format={"type": "json_object"}
                    )
                    raw_text = response.choices[0].message.content.strip()
                    if raw_text.startswith("```json"):
                        raw_text = raw_text.split("```json")[1].split("```")[0].strip()
                    elif raw_text.startswith("```"):
                        raw_text = raw_text.split("```")[1].strip()
                    
                    parsed = json.loads(raw_text)
                    print(f"[LLM Gateway] Local Ollama ({local_model}) intent classification successful!", flush=True)
                    return parsed
                except Exception as local_err:
                    print(f"[LLM Gateway Warning] Local Ollama model '{local_model}' failed: {local_err}", flush=True)
                    continue

        except Exception as e:
            print(f"[LLM Gateway Error] Local Ollama fallback failed: {e}", flush=True)

        # If everything fails
        print("[LLM Gateway] All cloud and local Ollama intent routing attempts failed!")
        return {"type": "chat_response", "payload": {"text": "I'm having trouble processing that intent right now."}}

