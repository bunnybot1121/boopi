import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain.ai_brain import AIThread

ai = AIThread()

text = "What are you doing?"
print(f"Testing execution latency for query: '{text}'")

t0 = time.time()
mem = ai._load_memory()
t1 = time.time()
print(f"Step 1: _load_memory: {(t1 - t0)*1000:.2f} ms")

p_sum = ai.db.get_memory_summary("projects", "None recorded yet.")
i_sum = ai.db.get_memory_summary("interests", "None recorded yet.")
t_sum = ai.db.get_memory_summary("tasks", "None recorded yet.")
t2 = time.time()
print(f"Step 2: memory summaries: {(t2 - t1)*1000:.2f} ms")

active_secs = ai.db.get_active_duration_today()
idle_secs = ai.db.get_idle_duration_today()
top_apps = ai.db.get_top_apps_today(limit=3)
t3 = time.time()
print(f"Step 3: screen activity: {(t3 - t2)*1000:.2f} ms")

try:
    from actions.hardware_tools import get_connected_nodes, get_world_state
    raw_nodes = get_connected_nodes()
    ws = get_world_state()
except Exception as e:
    print(f"Hardware state error: {e}")
t4 = time.time()
print(f"Step 4: hardware tools: {(t4 - t3)*1000:.2f} ms")

# Groq API check
import config
client = ai._get_groq_client()
t5 = time.time()
resp = client.chat.completions.create(
    model=config.GROQ_LLM_MODEL,
    messages=[{"role": "user", "content": text}],
    temperature=0.7,
    max_tokens=600,
    stream=True
)
for chunk in resp:
    delta = chunk.choices[0].delta.content
    if delta:
        t6 = time.time()
        print(f"Step 5: Groq first token latency: {(t6 - t5)*1000:.2f} ms")
        break

print("All benchmark steps finished successfully!")
