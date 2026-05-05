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
        
    _open_in_chrome(url)
    return "Opening your email client to draft the mail."

def _send_whatsapp(match):
    # Depending on the regex that hit, the groups might be different.
    # We will pass the full text and parse it inside the function for robustness.
    text = match.string
    
    recipient = ""
    message = ""
    
    # Try: "whatsapp <name> saying <message>"
    m1 = re.search(r"whatsapp\s+(.+?)(?:\s+saying\s+|\s+that\s+)(.+)", text, re.I)
    if m1:
        recipient = m1.group(1)
        message = m1.group(2)
    else:
        # Try: "send a (whatsapp) message to <name> saying <message>"
        m2 = re.search(r"(?:send|write|message|text)\s+(?:a\s+)?(?:whatsapp\s+)?message\s+to\s+(.+?)(?:\s+saying\s+|\s+that\s+)(.+)", text, re.I)
        if m2:
            recipient = m2.group(1)
            message = m2.group(2)
        else:
            # Try: "send <message> to <name> (on whatsapp)"
            m3 = re.search(r"(?:send|write|message|text)\s+(.+?)\s+to\s+(.+?)(?:\s+on\s+whatsapp)?$", text, re.I)
            if m3 and m3.group(1).lower() not in ["a message", "a whatsapp message", "message"]:
                message = m3.group(1)
                recipient = m3.group(2)
            else:
                # Just "send a message to <name>"
                m4 = re.search(r"(?:send|write|message|text)\s+(?:a\s+)?(?:whatsapp\s+)?message\s+to\s+(.+?)(?:\s+on\s+whatsapp)?$", text, re.I)
                if m4:
                    recipient = m4.group(1)
    
    recipient = recipient.strip()
    message = message.strip()
    return send_whatsapp_message(recipient, message)

def send_whatsapp_message(recipient, message):
    recipient_text = f" to {recipient}" if recipient else ""
    
    import urllib.parse
    if _find_and_focus_tab("WhatsApp"):
        try:
            import pyautogui
            import time
            
            def slow_hotkey(*keys):
                """Press keys with a slight delay to prevent Windows from dropping modifiers."""
                for key in keys:
                    pyautogui.keyDown(key)
                    time.sleep(0.05)
                for key in reversed(keys):
                    pyautogui.keyUp(key)
                    time.sleep(0.05)

            # Ensure the web page DOM has actual keyboard focus by clicking the center of the screen.
            # This clicks the chat background, which is safe.
            screen_width, screen_height = pyautogui.size()
            pyautogui.click(screen_width // 2, screen_height // 2)
            time.sleep(0.5) # Give it a moment to stabilize
            
            # --- VISION AI AGENT: Check if chat is locked ---
            print("From Python: [Vision AI] Taking screenshot to analyze WhatsApp state...", flush=True)
            import os, base64
            from io import BytesIO
            from PIL import ImageGrab
            from openai import OpenAI
            
            screen = ImageGrab.grab(all_screens=True)
            screen.thumbnail((1280, 720)) # Optimize for speed
            buffered = BytesIO()
            screen.save(buffered, format="JPEG", quality=70)
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            
            api_key = None
            for k, v in os.environ.items():
                if k.startswith("OPENROUTER_API_KEY") and v.strip():
                    api_key = v.strip()
                    break
                    
            if api_key:
                client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
                try:
                    resp = client.chat.completions.create(
                        model="openai/gpt-4o-mini",
                        messages=[{
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "Look at this screenshot of WhatsApp Web. Is there a security lock, PIN code prompt, password screen, or 'Enter your lock screen password' dialog currently displayed blocking the chat? Respond with exactly one word: YES or NO."},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_str}"}}
                            ]
                        }],
                        max_tokens=10
                    )
                    is_locked = "YES" in resp.choices[0].message.content.strip().upper()
                    if is_locked:
                        print("From Python: [Vision AI] Detected locked chat!", flush=True)
                        return f"Your WhatsApp is currently locked. Please enter your security code to unlock it, and then I can send the message!"
                    else:
                        print("From Python: [Vision AI] Chat is unlocked. Proceeding with automation.", flush=True)
                except Exception as e:
                    print(f"From Python: [Vision AI Error] {e}", flush=True)
            # ------------------------------------------------
            
            # Press ESC repeatedly to close any active chat text boxes or emoji panels.
            pyautogui.press('esc', presses=3, interval=0.1)
            time.sleep(0.3)
            
            # Use the WhatsApp Web search shortcut
            slow_hotkey('ctrl', 'alt', '/')
            time.sleep(0.3)
            
            # Press backspace to clear the '/' in case Windows drops the modifiers
            pyautogui.press('backspace')
            time.sleep(0.2)
            
            if recipient:
                print(f"From Python: [DEBUG] Typing recipient exactly as: '{recipient}'", flush=True)
                # Type the name to search
                pyautogui.write(recipient, interval=0.02)
                time.sleep(2.0) # wait for search results to filter
                pyautogui.press('enter')
                time.sleep(1.0) # wait for the chat to open
                
            if message:
                pyautogui.write(message, interval=0.01)
                time.sleep(0.2)
                pyautogui.press('enter')
                return f"Sent '{message}'{recipient_text} on WhatsApp."
                
            return f"Opened WhatsApp chat for {recipient}."
        except Exception as e:
            print(f"WhatsApp sending error: {e}")
            pass
            
    # Absolute Fallback if no WhatsApp tab exists at all
    encoded = urllib.parse.quote(message)
    url = f"https://web.whatsapp.com/send?text={encoded}"
    _open_in_chrome(url, force_new_tab=True)
    if recipient and message:
        import pyautogui
        import time
        time.sleep(8.0) 
        pyautogui.write(recipient)
        time.sleep(2.0)
        pyautogui.press('enter')
        time.sleep(1.0)
        pyautogui.press('enter')
        return f"Sent '{message}'{recipient_text} on WhatsApp."
        
    return f"Opening WhatsApp Web. Please select the contact to send '{message}'{recipient_text}."

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

PATTERNS = [
    (re.compile(r"(?:call me|my name is)\s+(.+)",     re.I), _set_name),
    (re.compile(r"(?:remember that|note that)\s+(.+)",             re.I), _remember_fact),
    (re.compile(r"(?:search|google)\s+(?:for\s+)?(.+)",         re.I), _google_search),
    (re.compile(r"(?:open|start|launch)\s+(?:up\s+)?(?:chrome|browser|firefox)",re.I), _open_browser),
    (re.compile(r"(?:open|start|launch)\s+(?:up\s+)?(?:vs\s?code|code editor)", re.I), _open_vscode),
    (re.compile(r"(?:open|start|launch)\s+(?:up\s+)?(?:my\s+)?(?:notepad|notes|text)", re.I), _open_notepad),
    (re.compile(r"(?:open|start|launch)\s+(?:up\s+)?spotify",                 re.I), _open_spotify),
    (re.compile(r"(?:open|start|launch)\s+(?:up\s+)?(?:calculator|calc)",       re.I), _open_calculator),
    # WhatsApp regexes removed to allow ai_brain.py (NLP LLM) to seamlessly parse intent,
    # draft the message in Bupi Hub, and trigger the action intelligently!
    # (re.compile(r"^(?:send|write|message|text)\s+(?:a\s+)?(?:whatsapp\s+)?message\s+to\s+", re.I), _send_whatsapp),
    # (re.compile(r"^(?:send|write|message|text)\s+.+?\s+to\s+.+?(?:\s+on\s+whatsapp)?$", re.I), _send_whatsapp),
    # (re.compile(r"^whatsapp\s+.+?\s+(?:saying|that)\s+", re.I), _send_whatsapp),
    (re.compile(r"(?:open|check)\s+(?:my\s+)?whatsapp",                re.I), _open_whatsapp),
    (re.compile(r"(?:play|listen\s+to|stream)\s+(.+)",                 re.I), _play_music),
    (re.compile(r"(?:open|start|launch)\s+(?:up\s+)?(?:youtube|yt)",                    re.I), _open_youtube),
    (re.compile(r"(?:open|draft|send|write)\s+(?:my\s+|an?\s+|the\s+)?(?:email|mail|emails)", re.I), _open_email),
    (re.compile(r"(?:what.?s the time|current time|time now|what time)", re.I), _get_time),
    (re.compile(r"(?:what.?s today|what day|today.?s date)", re.I), _get_date),
    (re.compile(r"(?:take a screenshot|take screenshot|take a picture of my screen)", re.I), _take_screenshot),
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
