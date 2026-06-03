import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

key = os.environ.get("OPENROUTER_API_KEY")

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=key
)

try:
    resp = client.chat.completions.create(
        model="google/gemini-2.0-pro-exp-02-05:free",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=10
    )
    print("SUCCESS -", resp.choices[0].message.content)
except Exception as e:
    print("FAILED -", e)
