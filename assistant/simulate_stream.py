import sys
import time
import json

def simulate():
    print(json.dumps({"type": "command", "value": "open_notepad"}), flush=True)
    time.sleep(1) # wait for window to open
    
    text = "This is a test of the streaming notepad system. Let's see if it drops characters!"
    for i in range(len(text)):
        print(json.dumps({"type": "notepad_insert", "value": text[i]}), flush=True)
        time.sleep(0.05)
        
simulate()
