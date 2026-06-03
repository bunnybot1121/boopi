import requests
import concurrent.futures

keys = [
"sk-abcdef1234567890abcdef1234567890abcdef12",
"sk-1234567890abcdef1234567890abcdef12345678",
"sk-abcdefabcdefabcdefabcdefabcdefabcdef12",
"sk-7890abcdef7890abcdef7890abcdef7890abcd",
"sk-1234abcd1234abcd1234abcd1234abcd1234abcd",
"sk-abcd1234abcd1234abcd1234abcd1234abcd1234",
"sk-5678efgh5678efgh5678efgh5678efgh5678efgh",
"sk-efgh5678efgh5678efgh5678efgh5678efgh5678",
"sk-ijkl1234ijkl1234ijkl1234ijkl1234ijkl1234",
"sk-mnop5678mnop5678mnop5678mnop5678mnop5678",
"sk-qrst1234qrst1234qrst1234qrst1234qrst1234",
"sk-uvwx5678uvwx5678uvwx5678uvwx5678uvwx5678",
"sk-1234ijkl1234ijkl1234ijkl1234ijkl1234ijkl",
"sk-5678mnop5678mnop5678mnop5678mnop5678mnop",
"sk-qrst5678qrst5678qrst5678qrst5678qrst5678",
"sk-uvwx1234uvwx1234uvwx1234uvwx1234uvwx1234",
"sk-1234abcd5678efgh1234abcd5678efgh1234abcd",
"sk-5678ijkl1234mnop5678ijkl1234mnop5678ijkl",
"sk-abcdqrstefghuvwxabcdqrstefghuvwxabcdqrst",
"sk-ijklmnop1234qrstijklmnop1234qrstijklmnop",
"sk-1234uvwx5678abcd1234uvwx5678abcd1234uvwx",
"sk-efghijkl5678mnopabcd1234efghijkl5678mnop",
"sk-mnopqrstuvwxabcdmnopqrstuvwxabcdmnopqrst",
"sk-ijklmnopqrstuvwxijklmnopqrstuvwxijklmnop",
"sk-abcd1234efgh5678abcd1234efgh5678abcd1234",
"sk-1234ijklmnop5678ijklmnop1234ijklmnop5678",
"sk-qrstefghuvwxabcdqrstefghuvwxabcdqrstefgh",
"sk-uvwxijklmnop1234uvwxijklmnop1234uvwxijkl",
"sk-abcd5678efgh1234abcd5678efgh1234abcd5678",
"sk-ijklmnopqrstuvwxijklmnopqrstuvwxijklmnop",
"sk-1234qrstuvwxabcd1234qrstuvwxabcd1234qrst",
"sk-efghijklmnop5678efghijklmnop5678efghijkl",
"sk-mnopabcd1234efghmnopabcd1234efghmnopabcd",
"sk-ijklqrst5678uvwxijklqrst5678uvwxijklqrst",
"sk-1234ijkl5678mnop1234ijkl5678mnop1234ijkl",
"sk-abcdqrstefgh5678abcdqrstefgh5678abcdqrst",
"sk-ijklmnopuvwx1234ijklmnopuvwx1234ijklmnop",
"sk-efgh5678abcd1234efgh5678abcd1234efgh5678",
"sk-mnopqrstijkl5678mnopqrstijkl5678mnopqrst",
"sk-1234uvwxabcd5678uvwxabcd1234uvwxabcd5678",
"sk-ijklmnop5678efghijklmnop5678efghijklmnop",
"sk-abcd1234qrstuvwxabcd1234qrstuvwxabcd1234",
"sk-1234efgh5678ijkl1234efgh5678ijkl1234efgh",
"sk-5678mnopqrstuvwx5678mnopqrstuvwx5678mnop",
"sk-abcdijkl1234uvwxabcdijkl1234uvwxabcdijkl",
"sk-ijklmnopabcd5678ijklmnopabcd5678ijklmnop",
"sk-1234efghqrstuvwx1234efghqrstuvwx1234efgh",
"sk-5678ijklmnopabcd5678ijklmnopabcd5678ijkl",
"sk-abcd1234efgh5678abcd1234efgh5678abcd1234",
"sk-ijklmnopqrstuvwxijklmnopqrstuvwxijklmnop"
]

def check_key(k):
    headers = {"Authorization": f"Bearer {k}"}
    try:
        resp = requests.get("https://api.openai.com/v1/models", headers=headers, timeout=5)
        if resp.status_code == 200:
            return f"{k[:10]}... : VALID!"
        else:
            return f"{k[:10]}... : INVALID (Status {resp.status_code})"
    except Exception as e:
        return f"{k[:10]}... : ERROR {e}"

print(f"Testing {len(keys)} keys against OpenAI endpoints...")
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    results = executor.map(check_key, keys)

valid_keys = []
for res in results:
    if "VALID" in res:
        valid_keys.append(res)

print("\n--- RESULTS ---")
if not valid_keys:
    print("All 50 keys are completely invalid or fake.")
else:
    for v in valid_keys:
        print(v)
