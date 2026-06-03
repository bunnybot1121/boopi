import requests
import json

keys = {
    "OpenAI": "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",
    "Google AI": "AIzaSyCiSKwbO-r-GIo-Omoq3Slb7Y2d9x6DU4I",
    "Ideogram": "xJe91QXFWOqAdrqfnZAGwIhMwI6WaTyJniIx_xWcFKIo6kmu103iDBZ8586SDVh83CT2IShyomsCyM65xjSE-Q",
    "Perplexity": "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",
    "Serper": "eac6ca0900186a216186e76dd05bacbf5d00e978",
    "Speechify": "23OUNvTocA9lP5eSWZOIsBAxzS9PFtMTwfrwFLaBLLQ",
    "Claude": "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"
}

print("=======================================")
print("🧪 TESTING ALL PROVIDED API KEYS")
print("=======================================\n")

# 1. OpenAI
print("--- Testing OpenAI ---")
try:
    resp = requests.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {keys['OpenAI']}"}, timeout=5)
    if resp.status_code == 200:
        print("✅ VALID!")
    else:
        print(f"❌ INVALID (Status {resp.status_code}): {resp.text[:100]}")
except Exception as e:
    print(f"⚠️ Error: {e}")

# 2. Google AI Studio
print("\n--- Testing Google AI Studio ---")
try:
    resp = requests.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={keys['Google AI']}", timeout=5)
    if resp.status_code == 200:
        print("✅ VALID!")
    else:
        print(f"❌ INVALID (Status {resp.status_code}): {resp.text[:100]}")
except Exception as e:
    print(f"⚠️ Error: {e}")

# 3. Perplexity
print("\n--- Testing Perplexity ---")
try:
    payload = {"model": "llama-3-sonar-small-32k-chat", "messages": [{"role": "user", "content": "hello"}]}
    resp = requests.post("https://api.perplexity.ai/chat/completions", headers={"Authorization": f"Bearer {keys['Perplexity']}"}, json=payload, timeout=5)
    if resp.status_code == 200:
        print("✅ VALID!")
    elif resp.status_code == 401:
        print("❌ INVALID (Status 401)")
    else:
        print(f"❓ UNKNOWN STATUS {resp.status_code}: {resp.text[:100]}")
except Exception as e:
    print(f"⚠️ Error: {e}")

# 4. Serper
print("\n--- Testing Serper ---")
try:
    resp = requests.post("https://google.serper.dev/search", headers={"X-API-KEY": keys['Serper']}, json={"q": "apple"}, timeout=5)
    if resp.status_code == 200:
        print("✅ VALID!")
    elif resp.status_code == 403 or resp.status_code == 401:
        print("❌ INVALID (Status 401/403)")
    else:
        print(f"❓ UNKNOWN STATUS {resp.status_code}: {resp.text[:100]}")
except Exception as e:
    print(f"⚠️ Error: {e}")

# 5. Claude
print("\n--- Testing Claude ---")
try:
    headers = {"x-api-key": keys['Claude'], "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
    payload = {"model": "claude-3-5-sonnet-20240620", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 10}
    resp = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=5)
    if resp.status_code == 200:
        print("✅ VALID!")
    elif resp.status_code == 401:
        print("❌ INVALID (Status 401)")
    elif resp.status_code == 403: # Claude often throws 403 if credit is empty but key is valid
        print("⚠️ VALID KEY but likely out of credits/blocked (Status 403)")
        print(f"Details: {resp.text[:100]}")
    else:
        print(f"❓ UNKNOWN STATUS {resp.status_code}: {resp.text[:100]}")
except Exception as e:
    print(f"⚠️ Error: {e}")

# 6. Ideogram
print("\n--- Testing Ideogram ---")
try:
    headers = {"Api-Key": keys['Ideogram']}
    resp = requests.post("https://api.ideogram.ai/generate", headers=headers, json={"prompt": "test"}, timeout=5)
    if resp.status_code in [200, 400]: # 400 means bad request format, but auth passed
        print("✅ VALID!")
    elif resp.status_code == 401:
        print("❌ INVALID (Status 401)")
    else:
        print(f"❓ UNKNOWN STATUS {resp.status_code}: {resp.text[:100]}")
except Exception as e:
    print(f"⚠️ Error: {e}")

# 7. Speechify
print("\n--- Testing Speechify ---")
# Speechify API usually uses Bearer token, trying to hit a generic endpoint just to see the auth response
try:
    headers = {"Authorization": f"Bearer {keys['Speechify']}"}
    resp = requests.get("https://api.sws.speechify.com/v1/voices", headers=headers, timeout=5)
    if resp.status_code == 200:
        print("✅ VALID!")
    elif resp.status_code in [401, 403]:
        print("❌ INVALID (Status 401/403)")
    else:
        print(f"❓ UNKNOWN STATUS {resp.status_code}: {resp.text[:100]}")
except Exception as e:
    print(f"⚠️ Error: {e}")
