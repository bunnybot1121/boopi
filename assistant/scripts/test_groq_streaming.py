import os
import sys
import time

sys.path.insert(0, os.path.abspath("."))
import config
from openai import OpenAI
from brain.ai_brain import BASE_SYSTEM_PROMPT

client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=config.GROQ_API_KEY)

sys_prompt = BASE_SYSTEM_PROMPT.format(
    user_name="Chintu",
    current_time="Saturday, September 05, 2026",
    weather_info="Sunny 24C"
)

messages = [
    {"role": "system", "content": sys_prompt},
    {"role": "user", "content": "How are you?"}
]

for model in ["qwen/qwen3.8-27b", "groq/compound-mini", "openai/gpt-oss-120b"]:
    t0 = time.time()
    try:
        stream = client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            max_tokens=200
        )
        first_token_time = None
        full = ""
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                if first_token_time is None:
                    first_token_time = time.time() - t0
                full += chunk.choices[0].delta.content
        total_time = time.time() - t0
        print(f"\n--- Model {model} ---")
        print(f"Time to First Token (TTFT): {first_token_time:.2f}s | Total: {total_time:.2f}s")
        print(f"Response:\n{full[:200]}")
    except Exception as e:
        print(f"Model {model} failed: {e}")
