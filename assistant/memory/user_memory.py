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

def sync_notes_to_obsidian(data: dict):
    try:
        notes = data.get("notes", [])
        wiki_dir = Path(get_base_path()) / "memory" / "obsidian_wiki"
        wiki_dir.mkdir(parents=True, exist_ok=True)
        
        index_content = "# Bupi Assistant Obsidian Vault\n\n## Permanent Memories\n"
        for i, note in enumerate(notes):
            filename = f"memory_{i+1}.md"
            note_path = wiki_dir / filename
            with open(note_path, 'w', encoding='utf-8') as f:
                f.write(f"# Memory {i+1}\n\n{note}\n")
            index_content += f"- [[{filename[:-3]}]]\n"
            
        with open(wiki_dir / "index.md", 'w', encoding='utf-8') as f:
            f.write(index_content)
    except Exception as e:
        print(f"[Memory Warning] Failed to sync Obsidian wiki: {e}")

def save(data: dict):
    MEMORY_PATH.parent.mkdir(exist_ok=True)
    with open(MEMORY_PATH, 'w') as f:
        json.dump(data, f, indent=2)
    sync_notes_to_obsidian(data)

def get(key: str, default=None):
    return load().get(key, default)

def set_val(key: str, value):
    data = load()
    data[key] = value
    save(data)
