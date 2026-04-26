import re, subprocess, webbrowser, platform, os
from datetime import datetime
from memory import user_memory

def _run_detached(cmd_list, use_shell=False):
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "shell": use_shell
    }
    if platform.system() == "Windows":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(cmd_list, **kwargs)

def _open_browser(match=None):
    webbrowser.open("https://www.google.com")
    return "Opening your browser."

def _google_search(match):
    query = match.group(2).strip()
    webbrowser.open(f"https://www.google.com/search?q={query.replace(' ', '+')}")
    return f"Searching for {query}."

def _open_vscode(match=None):
    try:
        _run_detached(["code", "."], use_shell=(platform.system() == "Windows"))
    except FileNotFoundError:
        return "VS Code not found in PATH."
    return "Opening VS Code."

def _open_notepad(match=None):
    if platform.system() == "Windows":
        _run_detached(["notepad.exe"])
    elif platform.system() == "Darwin":
        _run_detached(["open", "-a", "TextEdit"])
    else:
        _run_detached(["gedit"])
    return "Opening notes."

def _open_spotify(match=None):
    if platform.system() == "Windows":
        _run_detached(["start", "spotify:"], use_shell=True)
    elif platform.system() == "Darwin":
        _run_detached(["open", "-a", "Spotify"])
    return "Opening Spotify."

def _open_calculator(match=None):
    if platform.system() == "Windows":
        _run_detached(["calc.exe"])
    elif platform.system() == "Darwin":
        _run_detached(["open", "-a", "Calculator"])
    return "Opening calculator."

def _get_time(match=None):
    return f"It's {datetime.now().strftime('%I:%M %p')}."

def _get_date(match=None):
    return f"Today is {datetime.now().strftime('%A, %B %d')}."

def _take_screenshot(match=None):
    try:
        import pyautogui
        path = f"screenshot_{datetime.now().strftime('%H%M%S')}.png"
        pyautogui.screenshot(path)
        return f"Screenshot saved as {path}."
    except ImportError:
        return "Install pyautogui to use screenshots."

def _set_name(match):
    name = match.group(1) or match.group(2)
    name = name.strip()
    user_memory.set_val("user_name", name)
    return f"Got it. I will call you {name} from now on."

def _remember_fact(match):
    fact = match.group(1).strip()
    notes = user_memory.get("notes", [])
    notes.append(fact)
    user_memory.set_val("notes", notes)
    return f"I'll remember that {fact}."

def _play_music(match):
    import pywhatkit
    query = match.group(1).strip()
    # Handle generic requests
    if query.lower() in ["music", "some music", "a song"]:
        webbrowser.open("https://music.youtube.com/")
        return "Opening YouTube Music."
    
    # Strip out trailing words if present
    clean_query = re.sub(r'(?i)\s+(on youtube|on youtube music)', '', query).strip()
    
    try:
        pywhatkit.playonyt(clean_query)
        return f"Playing {clean_query} on YouTube."
    except Exception as e:
        webbrowser.open(f"https://www.youtube.com/results?search_query={clean_query.replace(' ', '+')}")
        return f"Searching for {clean_query} on YouTube."

PATTERNS = [
    (re.compile(r"call me (.+)|my name is (.+)",     re.I), _set_name),
    (re.compile(r"remember that (.+)",               re.I), _remember_fact),
    (re.compile(r"(search|google)\s+(.+)",           re.I), _google_search),
    (re.compile(r"open\s+(chrome|browser|firefox)",  re.I), _open_browser),
    (re.compile(r"open\s+(vs\s?code|code editor)",   re.I), _open_vscode),
    (re.compile(r"open\s+(notepad|notes|text)",      re.I), _open_notepad),
    (re.compile(r"open\s+spotify",                   re.I), _open_spotify),
    (re.compile(r"open\s+(calculator|calc)",         re.I), _open_calculator),
    (re.compile(r"play\s+(.+)",                      re.I), _play_music),
    (re.compile(r"(what.?s the time|current time|time now|what time)", re.I), _get_time),
    (re.compile(r"(what.?s today|what day|today.?s date)", re.I), _get_date),
    (re.compile(r"(take a screenshot|screenshot)",   re.I), _take_screenshot),
]

def detect_and_run(text: str) -> tuple[bool, str]:
    """Returns (handled, response_text). If handled=True, skip Gemini."""
    for pattern, handler in PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                return True, handler(match) or "Done."
            except Exception as e:
                return True, f"I tried but hit an error: {str(e)}"
    return False, ""
