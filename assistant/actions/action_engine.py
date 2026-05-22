import re, subprocess, webbrowser, platform, os
from datetime import datetime
from memory import user_memory
from .iot_agent import handle_iot_command

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
        import os
        try:
            os.startfile("spotify:")
        except Exception:
            _run_detached(["start", "spotify:"], use_shell=True)
    elif platform.system() == "Darwin":
        _run_detached(["open", "-a", "Spotify"])
    return "Opening Spotify."

def _open_calculator(match=None):
    if platform.system() == "Windows":
        import os
        try:
            os.startfile("calculator:")
        except Exception:
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
        
        keyword_lower = keyword.lower()
        
        # 1. Direct match: If a window's title contains the keyword (e.g. WhatsApp PWA)
        for w in gw.getAllWindows():
            title_lower = w.title.lower()
            if keyword_lower in title_lower and ('chrome' in title_lower or 'edge' in title_lower or keyword_lower == title_lower or 'whatsapp' in title_lower):
                if w.isMinimized:
                    w.restore()
                if not w.isMaximized:
                    try:
                        w.maximize()
                    except:
                        pass
                try:
                    # Windows focus hack: press Alt twice so it doesn't leave the window menu focused
                    pyautogui.press('alt')
                    pyautogui.press('alt')
                    w.activate()
                except Exception:
                    pass
                time.sleep(0.5)
                return True
                
        # 2. Tab switching: If it's buried in a Chrome window
        browsers = [w for w in gw.getAllWindows() if 'chrome' in w.title.lower() or 'edge' in w.title.lower()]
        if not browsers:
            return False
            
        for win in browsers:
            if win.isMinimized:
                win.restore()
            if not win.isMaximized:
                try:
                    win.maximize()
                except:
                    pass
            try:
                # Windows focus hack: press Alt twice so it doesn't leave the window menu focused
                pyautogui.press('alt')
                pyautogui.press('alt')
                win.activate()
            except Exception:
                pass
            time.sleep(0.3)
            
            initial_title = win.title
            for i in range(25):
                current = win.title
                if keyword_lower in current.lower():
                    return True
                # Explicitly press and release Ctrl to avoid dropped modifiers
                pyautogui.keyDown('ctrl')
                pyautogui.press('tab')
                pyautogui.keyUp('ctrl')
                time.sleep(0.1)
                if win.title == initial_title and i > 0:
                    break
        return False
    except Exception as e:
        print("Tab finding error:", e)
        return False

def _open_in_chrome(url, force_new_tab=False):
    import os, platform, webbrowser
    
    if not force_new_tab:
        try:
            import pygetwindow as gw
            import pyautogui
            import pyperclip
            import time
            browsers = [w for w in gw.getAllWindows() if any(b in w.title for b in ['Google Chrome', 'Edge', 'Brave', 'Firefox', 'Opera'])]
            if browsers:
                active_win = gw.getActiveWindow()
                win = None
                if active_win and any(b in active_win.title for b in ['Google Chrome', 'Edge', 'Brave', 'Firefox', 'Opera']):
                    win = active_win
                else:
                    win = browsers[0]
                    
                if win.isMinimized:
                    win.restore()
                try:
                    win.activate()
                except Exception:
                    pass
                time.sleep(0.3)
                
                old_clip = pyperclip.paste()
                pyperclip.copy(url)
                
                # F6 focuses the address bar
                pyautogui.press('f6')
                time.sleep(0.3)
                
                # Since Ctrl+V is failing on the user's machine, we will type the URL directly!
                # This guarantees the URL is entered into the address bar.
                pyautogui.write(url, interval=0.01)
                time.sleep(0.3)
                pyautogui.press('enter')
                time.sleep(0.1)
                
                if old_clip:
                    pyperclip.copy(old_clip)
                return
        except Exception as e:
            print("Error trying to reuse browser tab:", e)

    if platform.system() == "Windows":
        try:
            # Delegate to Windows Shell to avoid cmd.exe / permission blocks
            os.startfile(url)
        except Exception:
            webbrowser.open(url)
    else:
        webbrowser.open(url)

def _open_youtube(match=None):
    if _find_and_focus_tab("YouTube"):
        return "Focused your open YouTube tab."
    _open_in_chrome("https://www.youtube.com/")
    return "Opening YouTube."

def _open_whatsapp(match=None):
    if _find_and_focus_tab("WhatsApp"):
        return "Focused your open WhatsApp tab."
    _open_in_chrome("https://web.whatsapp.com/")
    return "Opening WhatsApp Web."

def _open_email(match):
    text = match.string
    print(f"[Action Engine] Routing Email command to Automation Agent: {text}", flush=True)
    try:
        from actions.automation_agent import run_automation_agent
        return run_automation_agent(text)
    except ImportError:
        return "Automation Agent is not properly installed or imported."
    except Exception as e:
        print(f"Automation agent failed: {e}")
        return f"Failed to run the automation agent: {e}"

def _send_linkedin(match):
    text = match.string
    print(f"[Action Engine] Routing LinkedIn command to Automation Agent: {text}", flush=True)
    try:
        from actions.automation_agent import run_automation_agent
        return run_automation_agent(text)
    except ImportError:
        return "Automation Agent is not properly installed or imported."
    except Exception as e:
        print(f"Automation agent failed: {e}")
        return f"Failed to run the automation agent: {e}"
    return "Opening your email client to draft the mail as a fallback."

def _send_whatsapp(match):
    text = match.string
    print(f"[Action Engine] Routing WhatsApp command to Automation Agent: {text}", flush=True)
    try:
        from actions.automation_agent import run_automation_agent
        return run_automation_agent(text)
    except ImportError:
        return "Automation Agent is not properly installed or imported."
    except Exception as e:
        print(f"Automation agent failed: {e}")
        return f"Failed to run the automation agent: {e}"

def send_whatsapp_message(recipient, message):
    print(f"[Action Engine] AI Triggered WhatsApp routing to Automation Agent: to {recipient}", flush=True)
    try:
        from actions.automation_agent import send_whatsapp_playwright
        return send_whatsapp_playwright(recipient, message)
    except ImportError:
        return "Automation Agent is not properly installed or imported."
    except Exception as e:
        print(f"Automation agent failed: {e}")
        return f"Failed to run the automation agent: {e}"

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
    query = match.group(1).strip()
    # Handle generic requests
    if query.lower() in ["music", "some music", "a song"]:
        if not _find_and_focus_tab("YouTube Music"):
            _find_and_focus_tab("YouTube")
        _open_in_chrome("https://music.youtube.com/")
        return "Opening YouTube Music."
    
    # Strip out trailing words if present
    clean_query = re.sub(r'(?i)\s+(on youtube|on youtube music)', '', query).strip()
    
    import urllib.parse
    import urllib.request
    
    encoded = urllib.parse.quote(clean_query)
    try:
        req = urllib.request.Request(f"https://www.youtube.com/results?search_query={encoded}", headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req).read().decode()
        video_ids = re.findall(r"watch\?v=(\S{11})", html)
        if video_ids:
            url = f"https://www.youtube.com/watch?v={video_ids[0]}"
            _find_and_focus_tab("YouTube")
            _open_in_chrome(url)
            return f"Playing {clean_query} on YouTube."
    except Exception as e:
        pass
        
    _find_and_focus_tab("YouTube")
    _open_in_chrome(f"https://www.youtube.com/results?search_query={encoded}")
    return f"Searching for {clean_query} on YouTube."

def _keyboard_type(match):
    text = match.group(1).strip()
    try:
        import pyautogui
        # remove trailing quotes if any
        if text.startswith(('"', "'")) and text.endswith(('"', "'")):
            text = text[1:-1]
        pyautogui.write(text, interval=0.02)
        return "" # Do not speak to avoid interrupting
    except Exception as e:
        return f"Error typing: {e}"

def _keyboard_press(match):
    key = match.group(1).strip().lower()
    try:
        import pyautogui
        # Map common spoken keys to pyautogui keys
        key_map = {
            "enter": "enter",
            "return": "enter",
            "escape": "esc",
            "esc": "esc",
            "tab": "tab",
            "space": "space",
            "spacebar": "space",
            "backspace": "backspace",
            "delete": "delete",
            "up": "up",
            "down": "down",
            "left": "left",
            "right": "right"
        }
        target_key = key_map.get(key, key)
        pyautogui.press(target_key)
        return "" # Do not speak
    except Exception as e:
        return f"Error pressing key: {e}"

def _birthday_surprise(match=None):
    import json
    from PyQt6.QtCore import QTimer
    from state_manager import state_mgr
    
    # We delay the excited state so that it overwrites the 'talking' state set by main.py
    QTimer.singleShot(100, lambda: state_mgr.force("excited"))
    
    # Open notepad and clear it
    print(json.dumps({"type": "command", "value": "open_notepad"}), flush=True)
    QTimer.singleShot(200, lambda: print(json.dumps({"type": "notepad_clear"}), flush=True))
    QTimer.singleShot(300, lambda: print(json.dumps({"type": "notepad_title", "value": "🎉 Happy Birthday! 🎉"}), flush=True))
    
    cake_art = (
        "\n\n"
        "             ,,,,\n"
        "            _||||_\n"
        "           {~*~*~*~}\n"
        "         __{*~*~*~*}__\n"
        "        `-------------`\n"
        "\n"
        "  ✨ Happy Birthday! ✨\n"
        "  Wishing you a fantastic day\n"
        "  filled with joy and happiness!\n"
        "  Boopi loves you! 💖\n"
    )
    QTimer.singleShot(400, lambda: print(json.dumps({"type": "notepad_insert", "value": cake_art}), flush=True))
    
    # Play a Happy Birthday song on YouTube directly
    class FakeMatch:
        def group(self, i):
            return "happy birthday song"
    QTimer.singleShot(500, lambda: _play_music(FakeMatch()))
    
    return "Happy birthday to you! I prepared a little surprise with a cake, and I am putting on some music for you!"

def _print_on_esp(match):
    text = match.group(1).strip()
    try:
        from bupi_node_server import send_to_esp32
        if len(text) > 16:
            send_to_esp32(text[:16], text[16:32], duration=8)
        else:
            send_to_esp32(text, "", duration=8)
        return f"Printed '{text}' on the screen."
    except Exception as e:
        return f"Error printing to ESP: {e}"

def _print_on_esp_alt(match):
    text = match.group(1).strip()
    try:
        from bupi_node_server import send_to_esp32
        if len(text) > 16:
            send_to_esp32(text[:16], text[16:32], duration=8)
        else:
            send_to_esp32(text, "", duration=8)
        return f"Printed '{text}' on the screen."
    except Exception as e:
        return f"Error printing to ESP: {e}"

def _send_mqtt(match):
    topic = match.group(1).strip()
    message = match.group(2).strip()
    return handle_iot_command(topic, message)

PATTERNS = [
    (re.compile(r"\[MQTT_SEND:(.+?):(.+)\]", re.I), _send_mqtt),
    (re.compile(r"(?:call me|my name is)\s+(.+)",     re.I), _set_name),
    (re.compile(r"(?:remember that|note that)\s+(.+)",             re.I), _remember_fact),
    (re.compile(r"(?:search|google)\s+(?:for\s+)?(.+)",         re.I), _google_search),
    (re.compile(r"(?:open|start|launch)\s+(?:up\s+)?(?:chrome|browser|firefox)",re.I), _open_browser),
    (re.compile(r"(?:open|start|launch)\s+(?:up\s+)?(?:vs\s?code|code editor)", re.I), _open_vscode),
    (re.compile(r"(?:open|start|launch)\s+(?:up\s+)?(?:my\s+)?(?:notepad|notes|text)", re.I), _open_notepad),
    (re.compile(r"(?:open|start|launch)\s+(?:up\s+)?spotify",                 re.I), _open_spotify),
    (re.compile(r"(?:open|start|launch)\s+(?:up\s+)?(?:calculator|calc)",       re.I), _open_calculator),
    (re.compile(r"(?:open|check)\s+(?:my\s+)?whatsapp",                re.I), _open_whatsapp),
    (re.compile(r"(?:send|write|message|text)\s+.*whatsapp.*", re.I), _send_whatsapp),
    (re.compile(r"(?:whatsapp)\s+(.+?)\s+(?:saying\s+|that\s+)", re.I), _send_whatsapp),
    (re.compile(r"(?:send|write|message|text)\s+.*linkedin.*", re.I), _send_linkedin),
    (re.compile(r"(?:linkedin)\s+(.+?)\s+(?:saying\s+|that\s+)", re.I), _send_linkedin),
    (re.compile(r"(?:play|listen\s+to|stream)\s+(.+)",                 re.I), _play_music),
    (re.compile(r"(?:open|start|launch)\s+(?:up\s+)?(?:youtube|yt)",                    re.I), _open_youtube),
    (re.compile(r"(?:open|draft|send|write)\s+(?:my\s+|an?\s+|the\s+)?(?:email|mail|emails)", re.I), _open_email),
    (re.compile(r"(?:what.?s the time|current time|time now|what time)", re.I), _get_time),
    (re.compile(r"(?:what.?s today|what day|today.?s date)", re.I), _get_date),
    (re.compile(r"(?:take a screenshot|take screenshot|take a picture of my screen)", re.I), _take_screenshot),
    (re.compile(r"^(?:type|write|enter)\s+(.+)", re.I), _keyboard_type),
    (re.compile(r"^(?:press|hit)\s+(?:the\s+)?([a-z0-9]+)\s+(?:key|button)?", re.I), _keyboard_press),
    (re.compile(r".*(?:birthday).*", re.I), lambda m: _birthday_surprise(m)),
]




def detect_and_run(text: str) -> tuple[bool, str]:
    """Returns (handled, response_text). If handled=True, skip Gemini."""
    for pattern, handler in PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                return True, handler(match) or "Done."
            except Exception as e:
                return True, f"Error: {str(e)}"
    return False, ""
