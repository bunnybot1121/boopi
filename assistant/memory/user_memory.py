import json
from pathlib import Path
import sys
import os

def get_base_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MEMORY_PATH = Path(get_base_path()) / "memory" / "user_data.json"

def load() -> dict:
    if MEMORY_PATH.exists():
        with open(MEMORY_PATH) as f:
            return json.load(f)
    return {"user_name": "Chintu", "notes": [], "preferences": {}}

def save(data: dict):
    MEMORY_PATH.parent.mkdir(exist_ok=True)
    with open(MEMORY_PATH, 'w') as f:
        json.dump(data, f, indent=2)

def get(key: str, default=None):
    return load().get(key, default)

def set_val(key: str, value):
    data = load()
    data[key] = value
    save(data)
