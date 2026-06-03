import requests
keys = [
    'AIzaSyCROXNS014lWoX7pICXw4CWxZCSfx7fLgc', 
    'AIzaSyAvV0lpPO4ON05A5bf1o8Q17nt4cfi3CdU', 
    'AIzaSyDJYsvlO5ZvRILZF6HibDg-kjw_T6qQAQY', 
    'AIzaSyBod7w6oje1Sl3AWHkU8IQQRzJ-aJbyXdg'
]
for k in keys:
    try:
        resp = requests.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={k}', 
            json={'contents': [{'parts': [{'text': 'hi'}]}]}, 
            headers={'Content-Type': 'application/json'}, 
            timeout=10
        )
        print(f'Key {k[:15]}... -> {resp.status_code} {resp.text[:150]}')
    except Exception as e:
        print(f'Key {k[:15]}... -> ERROR {e}')
