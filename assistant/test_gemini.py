import requests
keys = [
    'AIzaSyCROXNS014lWoX7pICXw4CWxZCSfx7fLgc', 
    'AIzaSyAvV0lpPO4ON05A5bf1o8Q17nt4cfi3CdU', 
    'AIzaSyDJYsvlO5ZvRILZF6HibDg-kjw_T6qQAQY', 
    'AIzaSyBod7w6oje1Sl3AWHkU8IQQRzJ-aJbyXdg'
]
for k in keys:
    try:
        resp = requests.get(
            f'https://generativelanguage.googleapis.com/v1beta/models?key={k}',
            timeout=10
        )
        print(f'Key {k[:15]}... -> {resp.status_code}')
        if resp.status_code == 200:
            models = resp.json().get('models', [])
            names = [m['name'] for m in models]
            print(f'  Models: {names}')
        else:
            print(f'  Response: {resp.text[:200]}')
    except Exception as e:
        print(f'Key {k[:15]}... -> ERROR {e}')

