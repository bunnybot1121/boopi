import os
import json
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None
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
        self.gemini_keys = []
        if os.environ.get("GOOGLE_AI_STUDIO_KEY"):
            self.gemini_keys.append(os.environ.get("GOOGLE_AI_STUDIO_KEY"))
        for i in range(2, 11):
            key = os.environ.get(f"GOOGLE_AI_STUDIO_KEY_{i}")
            if key:
                self.gemini_keys.append(key)

        # Gather OpenRouter keys
        self.openrouter_keys = []
        if os.environ.get("OPENROUTER_API_KEY"):
            self.openrouter_keys.append(os.environ.get("OPENROUTER_API_KEY"))
        for i in range(2, 11):
            key = os.environ.get(f"OPENROUTER_API_KEY_{i}")
            if key:
                self.openrouter_keys.append(key)
                
        self.model_name = "gemini-2.5-flash"

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
        
        use_local = os.environ.get("USE_LOCAL_LLM", "false").lower() == "true"

        # 1. If explicitly configured for local LLM, run on RTX 4050 GPU via Ollama
        if use_local:
            local_result = await self._classify_via_ollama(user_utterance, system_prompt)
            if local_result:
                return local_result
            print("[LLM Gateway] Local Ollama classification failed. Cascading to cloud...", flush=True)

        # 2. Fast Cloud Groq (Llama-3.3-70b-versatile, ~300ms latency)
        if self.groq_keys:
            for idx, key in enumerate(self.groq_keys):
                try:
                    groq_client = AsyncOpenAI(
                        base_url="https://api.groq.com/openai/v1",
                        api_key=key,
                        timeout=3.5
                    )
                    response = await groq_client.chat.completions.create(
                        model=os.getenv("GROQ_LLM_MODEL", "qwen/qwen3.8-27b"),
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_utterance}
                        ],
                        temperature=0.0,
                        max_tokens=200,
                        response_format={"type": "json_object"}
                    )
                    raw_text = response.choices[0].message.content.strip()
                    if raw_text.startswith("```json"):
                        raw_text = raw_text.split("```json")[1].split("```")[0].strip()
                    elif raw_text.startswith("```"):
                        raw_text = raw_text.split("```")[1].strip()
                    return json.loads(raw_text)
                except Exception as ge:
                    print(f"[LLM Gateway] Groq error with Key {idx + 1}: {ge}")
                    continue

        # 3. Cloud Gemini 2.5 Flash
        if self.gemini_keys and genai is not None:
            for idx, key in enumerate(self.gemini_keys):
                try:
                    client = genai.Client(api_key=key)
                    response = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=f"{system_prompt}\n\nUser utterance: \"{user_utterance}\"\nReturn ONLY the JSON object.",
                        config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=150)
                    )
                    raw_text = response.text.strip()
                    if raw_text.startswith("```json"):
                        raw_text = raw_text.split("```json")[1].split("```")[0].strip()
                    elif raw_text.startswith("```"):
                        raw_text = raw_text.split("```")[1].strip()
                    return json.loads(raw_text)
                except Exception as e:
                    print(f"[LLM Gateway] Gemini error with Key {idx + 1}: {e}")
                    continue

        # 4. Cloud OpenRouter Fallback
        if self.openrouter_keys:
            for idx, key in enumerate(self.openrouter_keys):
                try:
                    or_client = AsyncOpenAI(
                        base_url="https://openrouter.ai/api/v1",
                        api_key=key,
                        timeout=4.0
                    )
                    response = await or_client.chat.completions.create(
                        model=os.getenv("OPENROUTER_LLM_MODEL", "google/gemini-2.5-flash"),
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_utterance}
                        ],
                        temperature=0.0,
                        max_tokens=200,
                        response_format={"type": "json_object"}
                    )
                    raw_text = response.choices[0].message.content.strip()
                    if raw_text.startswith("```json"):
                        raw_text = raw_text.split("```json")[1].split("```")[0].strip()
                    elif raw_text.startswith("```"):
                        raw_text = raw_text.split("```")[1].strip()
                    return json.loads(raw_text)
                except Exception as oe:
                    print(f"[LLM Gateway] OpenRouter error with Key {idx + 1}: {oe}")
                    continue

        # 5. Fallback to Local Ollama on RTX 4050 (Zero-latency offline backup)
        if not use_local:
            local_result = await self._classify_via_ollama(user_utterance, system_prompt)
            if local_result:
                return local_result


        # If everything fails
        print("[LLM Gateway] All cloud and local Ollama intent routing attempts failed!")
        return {"type": "chat_response", "payload": {"text": "I'm having trouble processing that intent right now."}}

    async def _classify_via_ollama(self, user_utterance: str, system_prompt: str) -> dict:
        try:
            print("[LLM Gateway] Running intent classification on RTX 4050 GPU via Ollama...", flush=True)
            client = AsyncOpenAI(
                base_url="http://localhost:11434/v1",
                api_key="ollama",
                timeout=10.0
            )
            for local_model in ["llama3.2:3b", "llama3.2:latest", "llama3.1:8b"]:
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
                    print(f"[LLM Gateway] RTX 4050 Ollama ({local_model}) intent classification successful: {parsed.get('type')}", flush=True)
                    return parsed
                except Exception as local_err:
                    print(f"[LLM Gateway Warning] Local Ollama model '{local_model}' failed: {local_err}", flush=True)
                    continue
        except Exception as e:
            print(f"[LLM Gateway Error] Local Ollama inference failed: {e}", flush=True)
        return None

