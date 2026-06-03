import requests
import json

openai_key = "sk-K4h3JQgRAzebsuCF518d450f840245A69394Fc41De141767"
openai_proxy = "https://key.gpt4api.cc/v1"

claude_key = "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"
claude_proxy = "https://funni.cn"

print("--- Testing OpenAI Proxy ---")
try:
    headers = {"Authorization": f"Bearer {openai_key}"}
    resp = requests.get(f"{openai_proxy}/models", headers=headers, timeout=10)
    print("Status:", resp.status_code)
    if resp.status_code == 200:
        print("Result: VALID!")
    else:
        print("Result: INVALID or ERROR")
        print("Response:", resp.text[:200])
except Exception as e:
    print("Error:", e)

print("\n--- Testing Claude Proxy (Anthropic Format) ---")
try:
    headers = {
        "x-api-key": claude_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "claude-3-5-sonnet-20240620",
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 10
    }
    resp = requests.post(f"{claude_proxy}/v1/messages", headers=headers, json=payload, timeout=10)
    print("Status:", resp.status_code)
    if resp.status_code == 200:
        print("Result: VALID!")
    else:
        print("Result: INVALID or ERROR")
        print("Response:", resp.text[:200])
except Exception as e:
    print("Error:", e)
