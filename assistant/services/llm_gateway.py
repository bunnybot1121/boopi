import os
import json
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted
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
        You are the Intent Router for BUPI, a smart home AI.
        Your job is to classify the user's utterance and return ONLY a JSON object.
        If the user wants to control hardware (lights, etc.), output:
        {
          "type": "hardware_intent",
          "payload": {
             "device": "lights",
             "action": "ON" | "OFF"
          }
        }
        
        If the user is just chatting or asking a general question, output:
        {
          "type": "chat_response",
          "payload": {
             "text": "<A brief, friendly response>"
          }
        }
        
        Respond ONLY with raw JSON, no markdown blocks.
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

        # 2. Fallback to Groq keys
        if self.groq_keys:
            for idx, key in enumerate(self.groq_keys):
                try:
                    client = AsyncOpenAI(
                        base_url="https://api.groq.com/openai/v1",
                        api_key=key
                    )
                    response = await client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_utterance}
                        ],
                        temperature=0.0,
                        max_tokens=150,
                        response_format={"type": "json_object"}
                    )
                    raw_text = response.choices[0].message.content.strip()
                    return json.loads(raw_text)
                except Exception as e:
                    print(f"[LLM Gateway] Groq error with Key {idx + 1}: {e}")
                    # Try next Groq key
                    continue

        # If the loop finishes, it means ALL keys failed or were exhausted
        print("[LLM Gateway] ALL Groq and Gemini keys have been exhausted or failed!")
        return {"type": "chat_response", "payload": {"text": "My API keys are completely exhausted. Please top me up!"}}

