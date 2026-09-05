import os
import sys
import time

sys.path.insert(0, os.path.abspath("."))
import config
from openai import OpenAI

client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=config.GROQ_API_KEY)

for model in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen/qwen-2.5-32b", "mixtral-8x7b-32768"]:
    try:
        t0 = time.time()
        res = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Say hello in 3 words"}],
            max_tokens=20
        )
        print(f"Model {model}: {time.time()-t0:.2f}s -> {res.choices[0].message.content.strip()}")
    except Exception as e:
        print(f"Model {model} failed: {e}")
