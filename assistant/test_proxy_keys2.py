import requests
import json

claude_key = "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"
claude_proxy = "https://funni.cn"

print("\n--- Testing Claude Proxy (OpenAI Format) ---")
try:
    headers = {
        "Authorization": f"Bearer {claude_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "claude-3-5-sonnet-20240620",
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 10
    }
    resp = requests.post(f"{claude_proxy}/v1/chat/completions", headers=headers, json=payload, timeout=10)
    print("Status:", resp.status_code)
    if resp.status_code == 200:
        print("Result: VALID!")
    else:
        print("Result: INVALID or ERROR")
        print("Response:", resp.text[:200])
except Exception as e:
    print("Error:", e)
