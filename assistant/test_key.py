import base64
import requests
import json

key = "ABSKQmVkcm9ja0FQSUtleS1vZTNvLWF0LTI0NTU5NDcyODMwNTpuVHNnYzBLK0RzcC84ajVLMFkxKzZaeCsrUG1wT25BaDhDUDlnQTNQZnlIREVlSW0zcmxUdDh5NUtaND0="

# Decode the base64 part
b64_part = key[4:]
# pad it
b64_part += "=" * ((4 - len(b64_part) % 4) % 4)
decoded = base64.b64decode(b64_part).decode('utf-8', errors='replace')
print("Decoded Key Info:", decoded)

headers = {
    "Authorization": f"Bearer {key}",
    "Content-Type": "application/json"
}

payload = {
    "model": "claude-3-5-sonnet-20240620",
    "messages": [{"role": "user", "content": "Say 'hello world'"}],
    "max_tokens": 10
}

# Try OpenRouter
print("\n--- Testing OpenRouter ---")
try:
    resp = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=5)
    print("OpenRouter Status:", resp.status_code)
    print("Response:", resp.text[:200])
except Exception as e:
    print("OpenRouter Error:", e)

# Try anthropic directly with x-api-key
headers_anthropic = {
    "x-api-key": key,
    "anthropic-version": "2023-06-01",
    "Content-Type": "application/json"
}
print("\n--- Testing Anthropic API ---")
try:
    resp = requests.post("https://api.anthropic.com/v1/messages", headers=headers_anthropic, json=payload, timeout=5)
    print("Anthropic Status:", resp.status_code)
    print("Response:", resp.text[:200])
except Exception as e:
    print("Anthropic Error:", e)

# Try generic OpenAI compatible (like api.oe3o.com if it exists)
print("\n--- Testing api.oe3o.com ---")
try:
    resp = requests.post("https://api.oe3o.com/v1/chat/completions", headers=headers, json=payload, timeout=5)
    print("oe3o Status:", resp.status_code)
    print("Response:", resp.text[:200])
except Exception as e:
    print("oe3o Error:", e)

