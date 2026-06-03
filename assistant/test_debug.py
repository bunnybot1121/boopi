import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

def test_gemini():
    print("Testing Gemini directly...")
    for i in range(1, 5):
        key_name = f"GOOGLE_AI_STUDIO_KEY_{i}" if i > 1 else "GOOGLE_AI_STUDIO_KEY"
        key = os.environ.get(key_name)
        if not key: continue
        
        client = OpenAI(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=key
        )
        try:
            resp = client.chat.completions.create(
                model="gemini-1.5-flash",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=10
            )
            print(f"{key_name}: SUCCESS - {resp.choices[0].message.content}")
        except Exception as e:
            print(f"{key_name}: FAILED - {e}")

def test_openrouter():
    print("\nTesting OpenRouter...")
    keys = []
    for k, v in os.environ.items():
        if k.startswith("OPENROUTER_API_KEY") and v.strip():
            keys.append((k, v.strip()))
            
    for k, v in keys:
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=v
        )
        try:
            resp = client.chat.completions.create(
                model="google/gemini-2.0-flash-exp:free",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=10
            )
            print(f"{k} with google/gemini-2.0-flash-exp:free: SUCCESS - {resp.choices[0].message.content}")
        except Exception as e:
            print(f"{k} with google/gemini-2.0-flash-exp:free: FAILED - {e}")

test_gemini()
test_openrouter()
