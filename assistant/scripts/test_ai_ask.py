import os
import sys
import time

sys.path.insert(0, os.path.abspath("."))
import config
from brain.db_manager import db_manager

print("Testing database queries in ai_brain...")
try:
    p = db_manager.get_memory_summary("projects", "None")
    print(f"projects: {p}")
    i = db_manager.get_memory_summary("interests", "None")
    print(f"interests: {i}")
    t = db_manager.get_memory_summary("tasks", "None")
    print(f"tasks: {t}")
    a = db_manager.get_active_duration_today()
    print(f"active_secs: {a}")
    idle = db_manager.get_idle_duration_today()
    print(f"idle_secs: {idle}")
    apps = db_manager.get_top_apps_today(limit=3)
    print(f"top_apps: {apps}")
    print("DB queries OK!")
except Exception as e:
    print(f"DB Query failed: {e}")

print("Testing Groq API key...")
print(f"GROQ_API_KEY present: {bool(config.GROQ_API_KEY)}")
print(f"GOOGLE_AI_STUDIO_KEY present: {bool(config.GOOGLE_AI_STUDIO_KEY)}")
print(f"OPENROUTER_API_KEY present: {bool(config.OPENROUTER_API_KEY)}")

if config.GROQ_API_KEY:
    from openai import OpenAI
    client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=config.GROQ_API_KEY, timeout=10)
    try:
        t0 = time.time()
        res = client.chat.completions.create(
            model=config.GROQ_LLM_MODEL,
            messages=[{"role": "user", "content": "Say hello in 3 words"}],
            max_tokens=20
        )
        print(f"Groq test response in {time.time()-t0:.2f}s: {res.choices[0].message.content}")
    except Exception as ge:
        print(f"Groq failed: {ge}")
