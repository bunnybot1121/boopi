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
    import json
    print(json.dumps({"type": "command", "value": "open_notepad"}), flush=True)
    return "Opening my notepad for you."

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

def _find_and_focus_tab(keyword):
    try:
        import pygetwindow as gw
        import pyautogui
        import time
        
        # Check active tabs first
        for w in gw.getAllWindows():
            if keyword.lower() in w.title.lower() and ('Google Chrome' in w.title or 'Edge' in w.title):
                if w.isMinimized:
                    w.restore()
                w.activate()
                time.sleep(0.5)
                return True
                
        browsers = [w for w in gw.getAllWindows() if 'Google Chrome' in w.title or 'Edge' in w.title]
        if not browsers:
            return False
            
        win = browsers[0]
        if win.isMinimized:
            win.restore()
        win.activate()
        time.sleep(0.5)
        
        initial_title = win.title
        for i in range(20):
            current = win.title
            if keyword.lower() in current.lower():
                return True
            pyautogui.hotkey('ctrl', 'tab')
            time.sleep(0.2)
            if win.title == initial_title and i > 0:
                break
        return False
    except Exception as e:
        print("Tab finding error:", e)
        return False

def _open_whatsapp(match=None):
    if _find_and_focus_tab("WhatsApp"):
        return "Focused your open WhatsApp tab."
    webbrowser.open("https://web.whatsapp.com/")
    return "Opening WhatsApp Web."

def _open_email(match):
    text = match.string
    
    # Try to extract recipient email
    recipient = ""
    rec_match = re.search(r"to\s+([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,})", text, re.I)
    if rec_match:
        recipient = rec_match.group(1)
    else:
        # Check if they just provided a name
        name_match = re.search(r"to\s+([a-zA-Z]+)", text, re.I)
        if name_match and name_match.group(1).lower() not in ["send", "write", "draft", "open", "an", "email"]:
            recipient = name_match.group(1)
            
    # Try to extract subject
    subject = ""
    sub_match = re.search(r"(?:about|regarding|subject|saying)\s+(.+)", text, re.I)
    if sub_match:
        subject = sub_match.group(1).strip()
        
    import urllib.parse
    
    if _find_and_focus_tab("Gmail") or _find_and_focus_tab("Mail"):
        try:
            import pyautogui
            import time
            pyautogui.press('c') # Gmail shortcut for compose
            time.sleep(1.0)
            if recipient:
                pyautogui.write(recipient)
                time.sleep(0.5)
                pyautogui.press('enter')
                time.sleep(0.2)
                pyautogui.press('tab')
                if subject:
                    pyautogui.write(subject)
                pyautogui.press('tab')
            return "Opened email compose window."
        except Exception:
            pass
            
    url = f"mailto:{recipient}"
    if subject:
        url += f"?subject={urllib.parse.quote(subject)}"
        
    webbrowser.open(url)
    return "Opening your email client to draft the mail."

def _send_whatsapp(match):
    message = match.group(1).strip()
    # Strip common fluff from speech-to-text
    message = re.sub(r'^(a\s+)?message\s+(saying\s+)?', '', message, flags=re.I)
    
    recipient = match.group(2)
    recipient_text = f" to {recipient.strip()}" if recipient else ""
    
    import urllib.parse
    encoded = urllib.parse.quote(message)
    
    if _find_and_focus_tab("WhatsApp"):
        try:
            import pyautogui
            import time
            # Focus search bar
            pyautogui.hotkey('ctrl', 'alt', '/')
            time.sleep(0.5)
            if recipient:
                pyautogui.write(recipient.strip())
                time.sleep(1.0) # wait for search results
                pyautogui.press('enter')
                time.sleep(0.5)
            if message:
                pyautogui.write(message)
                time.sleep(0.2)
                pyautogui.press('enter')
                return f"Sent '{message}'{recipient_text} on WhatsApp."
            return f"Opened WhatsApp chat for {recipient.strip()}."
        except Exception:
            pass
            
    webbrowser.open(f"https://web.whatsapp.com/send?text={encoded}")
    return f"Opening WhatsApp. Please select the contact to send '{message}'{recipient_text}."

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
    (re.compile(r"^(call me|my name is)\s+(.+)$",     re.I), _set_name),
    (re.compile(r"^remember that (.+)$",             re.I), _remember_fact),
    (re.compile(r"^(search|google)\s+(.+)$",         re.I), _google_search),
    (re.compile(r"^open\s+(chrome|browser|firefox)$",re.I), _open_browser),
    (re.compile(r"^open\s+(vs\s?code|code editor)$", re.I), _open_vscode),
    (re.compile(r"^open\s+(my\s+)?(notepad|notes|text)$", re.I), _open_notepad),
    (re.compile(r"^open\s+spotify$",                 re.I), _open_spotify),
    (re.compile(r"^open\s+(calculator|calc)$",       re.I), _open_calculator),
    (re.compile(r"(?:send|write|message)\s+(.+?)(?:\s+to\s+(.+?))?\s+on\s+whatsapp", re.I), _send_whatsapp),
    (re.compile(r"(?:open\s+whatsapp|check\s+whatsapp)",                re.I), _open_whatsapp),
    (re.compile(r"(?:open\s+email|draft\s+an?\s+email|send\s+an?\s+email|write\s+an?\s+email)", re.I), _open_email),
    (re.compile(r"^play\s+(.+)$",                    re.I), _play_music),
    (re.compile(r"^(what.?s the time|current time|time now|what time)$", re.I), _get_time),
    (re.compile(r"^(what.?s today|what day|today.?s date)$", re.I), _get_date),
    (re.compile(r"^(take a screenshot|screenshot)$", re.I), _take_screenshot),
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
