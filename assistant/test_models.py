import os
import requests
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

def find_openrouter_free_models():
    print("Fetching OpenRouter models...")
    resp = requests.get("https://openrouter.ai/api/v1/models")
    if resp.status_code == 200:
        models = resp.json().get("data", [])
        free_models = [m["id"] for m in models if m.get("pricing", {}).get("prompt") == "0" or m["id"].endswith(":free")]
        print("Free Models on OpenRouter:", free_models[:10]) # Just print top 10
        return free_models
    return []

def test_gemini_models():
    print("\nTesting Gemini models directly...")
    key = os.environ.get("GOOGLE_AI_STUDIO_KEY")
    if not key: return
    
    models_to_try = [
        "gemini-1.5-flash-latest",
        "gemini-1.5-flash-8b",
        "gemini-2.0-flash-exp",
        "gemini-2.0-flash",
        "gemini-1.5-pro",
        "models/gemini-1.5-flash"
    ]
    
    client = OpenAI(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key=key
    )
    
    for m in models_to_try:
        try:
            resp = client.chat.completions.create(
                model=m,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=10
            )
            print(f"{m}: SUCCESS - {resp.choices[0].message.content}")
        except Exception as e:
            print(f"{m}: FAILED - {e}")

find_openrouter_free_models()
test_gemini_models()
