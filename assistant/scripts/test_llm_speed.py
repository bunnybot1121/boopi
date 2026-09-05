import os
import sys
import time

sys.path.insert(0, os.path.abspath("."))
import config
from openai import OpenAI

client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=config.GROQ_API_KEY)

for model in ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b", "groq/compound-mini"]:
    try:
        t0 = time.time()
        res = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "How are you? Answer in 1 short sentence."}],
            max_tokens=50
        )
        dt = time.time() - t0
        print(f"Model {model} in {dt:.2f}s: {res.choices[0].message.content.strip()[:100]}")
    except Exception as e:
        print(f"Model {model} failed: {e}")

print("\nTesting Gemini...")
try:
    from google import genai
    from google.genai import types
    gclient = genai.Client(api_key=config.GOOGLE_AI_STUDIO_KEY)
    t0 = time.time()
    resp = gclient.models.generate_content(
        model="gemini-2.5-flash",
        contents="How are you? Answer in 1 short sentence."
    )
    print(f"Gemini 2.5 flash in {time.time()-t0:.2f}s: {resp.text.strip()}")
except Exception as ge:
    print(f"Gemini failed: {ge}")
