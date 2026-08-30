import os
import sys
import json
import time
import re
import threading
import subprocess
import urllib.parse
import webbrowser
import pyautogui
from logger import log
from brain.db_manager import db_manager
from actions.context_file_resolver import ContextFileResolver
from actions.system_monitor_service import SystemMonitorService
from actions.mode_manager import ModeManager

class ActionEngine:
  def __init__(self):
    self.context_resolver = ContextFileResolver()
    self.system_monitor = SystemMonitorService()
    self.mode_manager = ModeManager(self)

  @property
  def active_mode(self):
    return self.mode_manager.active_mode

  @active_mode.setter
  def active_mode(self, val):
    self.mode_manager.active_mode = val

  @property
  def timer_cancelled(self):
    return self.mode_manager.timer_cancelled

  @timer_cancelled.setter
  def timer_cancelled(self, val):
    self.mode_manager.timer_cancelled = val

  @property
  def focus_duration(self):
    return self.mode_manager.focus_duration

  @focus_duration.setter
  def focus_duration(self, val):
    self.mode_manager.focus_duration = val

  @property
  def timer_thread(self):
    return self.mode_manager.timer_thread

  @timer_thread.setter
  def timer_thread(self, val):
    self.mode_manager.timer_thread = val

  def execute_action(self, action_cmd: str):
    """Executes a matching local app command or media hotkey."""
    log.info(f"Action Engine executing command: '{action_cmd}'")
    
    cmd_lower = action_cmd.lower().strip()
    
    try:
      # Application Spawners
      if cmd_lower == "chrome":
        if os.name == 'nt':
          subprocess.Popen(["cmd", "/c", "start chrome"], shell=True)
        else:
          subprocess.Popen(["google-chrome"])
          
      elif cmd_lower in ["vscode", "code"]:
        if os.name == 'nt':
          subprocess.Popen(["cmd", "/c", "code"], shell=True)
        else:
          subprocess.Popen(["code"])
          
      elif cmd_lower == "spotify":
        if os.name == 'nt':
          subprocess.Popen(["cmd", "/c", "start spotify:"], shell=True)
        else:
          webbrowser.open("https://open.spotify.com")
          
      elif cmd_lower == "notepad":
        # Open Bupi's built-in Electron Notepad editor
        self._sync_to_notepad("Bupi Notepad Editor", "")
        
      elif cmd_lower in ["calculator", "calc"]:
        subprocess.Popen(["calc.exe"] if os.name == 'nt' else ["gnome-calculator"])

      # Media Key Automations
      elif cmd_lower == "volume_up":
        pyautogui.press('volumeup')
      elif cmd_lower == "volume_down":
        pyautogui.press('volumedown')
      elif cmd_lower == "volume_mute":
        pyautogui.press('volumemute')
      elif cmd_lower in ["media_play", "play_pause", "play", "pause"]:
        self.control_media("play_pause")
      elif cmd_lower in ["media_next", "next"]:
        self.control_media("next")
      elif cmd_lower in ["media_prev", "prev"]:
        self.control_media("prev")

      # YouTube Music Routing
      elif cmd_lower.startswith("play_music:"):
        query = action_cmd.split("play_music:")[-1].strip()
        video_id = self._get_first_youtube_video(query)
        if video_id:
          url = f"https://music.youtube.com/watch?v={video_id}"
          log.info(f"Playing query directly on YouTube Music: '{query}' (video_id: {video_id})")
        else:
          encoded_query = urllib.parse.quote(query)
          url = f"https://music.youtube.com/search?q={encoded_query}"
          log.info(f"Fallback to search on YouTube Music: '{query}'")
        webbrowser.open(url)

      # YouTube Play Routing
      elif cmd_lower.startswith("play_youtube:"):
        query = action_cmd.split("play_youtube:")[-1].strip()
        video_id = self._get_first_youtube_video(query)
        if video_id:
          url = f"https://www.youtube.com/watch?v={video_id}"
          log.info(f"Playing video directly on YouTube: '{query}' (video_id: {video_id})")
        else:
          encoded_query = urllib.parse.quote(query)
          url = f"https://www.youtube.com/results?search_query={encoded_query}"
          log.info(f"Fallback to search on YouTube: '{query}'")
        webbrowser.open(url)

      # Robust UIA and App Launching commands
      elif action_cmd.startswith("launch_app:"):
        app_name = action_cmd.split("launch_app:")[-1].strip()
        self.launch_app(app_name)

      elif action_cmd.startswith("ax_list:"):
        app_name = action_cmd.split("ax_list:")[-1].strip()
        self.ax_list(app_name)

      elif action_cmd.startswith("ax_press:"):
        parts = action_cmd.split("ax_press:")[-1].split(":")
        if len(parts) >= 2:
          app_name = parts[0].strip()
          label = parts[1].strip()
          self.ax_press(app_name, label)

      elif action_cmd.startswith("ax_set_value:"):
        parts = action_cmd.split("ax_set_value:")[-1].split(":")
        if len(parts) >= 3:
          app_name = parts[0].strip()
          label = parts[1].strip()
          value = parts[2].strip()
          if len(parts) > 3:
            value = ":".join(parts[2:]).strip()
          self.ax_set_value(app_name, label, value)

      # ---------------- DESKTOP CONTROL & PRODUCTIVITY ACTIONS ----------------
      elif action_cmd.startswith("close_app:"):
        app_name = action_cmd.split("close_app:")[-1].strip()
        success = self.close_app(app_name)
        log.info(f"Close app '{app_name}' status: {success}")

      elif action_cmd.startswith("open_folder:"):
        path = action_cmd.split("open_folder:")[-1].strip()
        self.open_folder(path)

      elif action_cmd.startswith("open_file:"):
        path = action_cmd.split("open_file:")[-1].strip()
        self.open_file(path)

      elif action_cmd.startswith("write_to_notepad:"):
        content = action_cmd.split("write_to_notepad:", 1)[-1].strip()
        self.write_to_notepad(content)

      elif action_cmd.startswith("study_mode"):
        duration = 25
        parts = action_cmd.split(":")
        if len(parts) > 1 and parts[1].strip().isdigit():
          duration = int(parts[1].strip())
        self.mode_manager.activate_study_mode(duration)

      elif action_cmd.startswith("hackathon_mode"):
        self.mode_manager.activate_hackathon_mode()

      elif action_cmd.startswith("meeting_mode"):
        self.activate_meeting_mode()

      elif action_cmd == "stop_mode" or action_cmd == "end_mode":
        self.mode_manager.deactivate_mode()

      elif action_cmd.startswith("coding_mode"):
        self.mode_manager.activate_coding_mode()

      elif action_cmd.startswith("presentation_mode"):
        self.mode_manager.activate_presentation_mode()

      elif action_cmd.startswith("open_context_file:"):
        query = action_cmd.split("open_context_file:")[-1].strip()
        status_msg = self.context_resolver.resolve_and_open(query)
        self._sync_to_notepad("Smart Context File Resolver", status_msg)
        print(json.dumps({"type": "speak", "value": status_msg}), flush=True)

      elif action_cmd == "show_system_health":
        stats = self.system_monitor.get_system_status()
        self._sync_to_notepad("System Monitor Health Check", stats)
        print(json.dumps({"type": "speak", "value": "I have checked your system health and displayed the statistics in your Notepad."}), flush=True)

      elif action_cmd == "daily_updates" or action_cmd == "daily_briefing":
        print(json.dumps({"type": "trigger_briefing", "value": True}), flush=True)

      elif action_cmd == "open_setup":
        self.open_setup()

      elif action_cmd.startswith("create_folder:"):
        path = action_cmd.split("create_folder:")[-1].strip()
        self.create_folder(path)

      elif action_cmd.startswith("create_file:"):
        parts = action_cmd.split("create_file:")[-1].split(":", 1)
        if len(parts) >= 2:
          path = parts[0].strip()
          content = parts[1].strip()
          self.create_file(path, content)

      elif action_cmd.startswith("search_files:"):
        query = action_cmd.split("search_files:")[-1].strip()
        matches = self.search_files(query)
        if matches:
          text = f"Found {len(matches)} files matching '{query}':\n\n" + "\n".join([f"- {m}" for m in matches])
        else:
          text = f"No files found matching '{query}' in user folders."
        self._sync_to_notepad(f"File Search: '{query}'", text)

      # ---------------- GOOGLE CALENDAR ACTIONS ----------------
      elif action_cmd.startswith("calendar_today"):
        from actions.calendar_helper import get_today_schedule
        schedule = get_today_schedule()
        self._sync_to_notepad("Today's Schedule", schedule)
        spoken_text = "I've pulled up today's schedule on your notepad, Chintu!"
        if "no events" in schedule.lower():
          spoken_text = "You have no events scheduled for today, Chintu!"
        print(json.dumps({"type": "speak", "value": spoken_text}), flush=True)

      elif action_cmd.startswith("calendar_create:"):
        args_str = action_cmd.split("calendar_create:", 1)[-1].strip()
        parts = [p.strip() for p in args_str.split(":")]
        summary = ""
        start_time = ""
        duration = 30
        description = ""
        
        if len(parts) >= 3 and parts[-1].isdigit():
          summary = parts[0]
          duration = int(parts[-1])
          start_time = ":".join(parts[1:-1])
          description = ""
        elif len(parts) >= 4 and parts[-2].isdigit():
          summary = parts[0]
          duration = int(parts[-2])
          start_time = ":".join(parts[1:-2])
          description = parts[-1]
        elif len(parts) >= 2:
          summary = parts[0]
          start_time = ":".join(parts[1:])
          duration = 30
          description = ""
          
        if summary and start_time:
          from actions.calendar_helper import create_calendar_event
          res = create_calendar_event(summary, start_time, duration, description)
          self._sync_to_notepad("Calendar Event Creation", res)

      elif action_cmd.startswith("calendar_view"):
        from actions.calendar_helper import list_upcoming_events
        max_res = 5
        parts = action_cmd.split(":")
        if len(parts) > 1 and parts[1].strip().isdigit():
          max_res = int(parts[1].strip())
        upcoming = list_upcoming_events(max_results=max_res)
        self._sync_to_notepad("Upcoming Events", upcoming)
        spoken_text = "I have displayed your upcoming calendar events on the notepad, Chintu!"
        if "no upcoming" in upcoming.lower():
          spoken_text = "There are no upcoming events found on your calendar."
        print(json.dumps({"type": "speak", "value": spoken_text}), flush=True)

      # ---------------- INTERNET SEARCH ACTIONS ----------------
      elif action_cmd.startswith("search_web:"):
        query = action_cmd.split("search_web:", 1)[-1].strip()
        from actions.search_helper import search_web
        results = search_web(query, max_results=4)
        self._sync_to_notepad(f"Web Search: '{query}'", results)

      # ---------------- MEMORY / PREFERENCE ACTIONS ----------------
      elif action_cmd.startswith("set_preference:"):
        parts = action_cmd.split("set_preference:", 1)[-1].split(":", 1)
        if len(parts) >= 2:
          key = parts[0].strip()
          val = parts[1].strip()
          db_manager.set_preference(key, val)
          log.info(f"Preference '{key}' set to '{val}' via action.")

      elif action_cmd == "print_memory" or action_cmd == "view_memory":
        # Get username and notes
        username = db_manager.get_preference("username", "User")
        notes_json = db_manager.get_preference("notes", "[]")
        try:
          notes = json.loads(notes_json)
        except:
          notes = []
          
        # Get summaries
        projects = db_manager.get_memory_summary("projects", "None recorded yet.")
        interests = db_manager.get_memory_summary("interests", "None recorded yet.")
        tasks = db_manager.get_memory_summary("tasks", "None recorded yet.")
        
        mem_lines = []
        mem_lines.append("=== BUPI LONG-TERM MEMORY ===")
        mem_lines.append(f"User Name: {username}")
        
        mem_lines.append("\n--- Quick Notes ---")
        if notes:
          for n in notes:
            mem_lines.append(f"- {n}")
        else:
          mem_lines.append("- No quick notes recorded.")
          
        mem_lines.append("\n--- Long-Term Summaries ---")
        mem_lines.append(f"Projects: {projects}")
        mem_lines.append(f"Interests: {interests}")
        mem_lines.append(f"Tasks: {tasks}")
        
        notepad_text = "\n".join(mem_lines)
        self._sync_to_notepad("Bupi Memory Summary", notepad_text)
        print(json.dumps({"type": "speak", "value": "I have printed everything I know about you on the notepad, Chintu!"}), flush=True)

      elif action_cmd == "clear_memory":
        db_manager.clear_memory()
        print(json.dumps({"type": "speak", "value": "I have cleared my memory and forgotten everything, Chintu!"}), flush=True)
        self._sync_to_notepad("Memory Cleared", "My memory has been wiped clean!")

      # ---------------- REMINDER ACTIONS ----------------
      elif action_cmd.startswith("add_reminder:"):
        args_str = action_cmd.split("add_reminder:", 1)[-1].strip()
        parts = args_str.split(":", 1)
        if len(parts) == 2:
          text = parts[0].strip()
          trigger_val = parts[1].strip()
          try:
            if trigger_val.replace('.', '', 1).isdigit():
              trigger_time = time.time() + float(trigger_val)
            else:
              import dateutil.parser
              trigger_time = dateutil.parser.parse(trigger_val).timestamp()
          except Exception as ex:
            log.error(f"Failed to parse reminder trigger time '{trigger_val}': {ex}")
            trigger_time = time.time() + 60.0  # default to 1 min
          db_manager.add_reminder(text, trigger_time)
          log.info(f"Added reminder '{text}' trigger_time={trigger_time}")

      elif action_cmd.startswith("list_reminders"):
        reminders = db_manager.get_all_reminders()
        if reminders:
          lines = []
          for r in reminders:
            status = "Notified" if r["notified"] else "Active"
            t_str = time.strftime("%Y-%m-%d %I:%M %p", time.localtime(r["trigger_time"]))
            lines.append(f"[{r['id']}] {t_str} - {r['text']} ({status})")
          text = "\n".join(lines)
          spoken_text = "Here are your active reminders on the notepad, Chintu!"
        else:
          text = "No reminders configured."
          spoken_text = "You don't have any reminders set right now, Chintu."
        self._sync_to_notepad("My Reminders", text)
        print(json.dumps({"type": "speak", "value": spoken_text}), flush=True)

      elif action_cmd.startswith("delete_reminder:"):
        rem_id = action_cmd.split("delete_reminder:")[-1].strip()
        if rem_id.isdigit():
          db_manager.delete_reminder(int(rem_id))
          log.info(f"Deleted reminder ID {rem_id}")

      else:
        log.warning(f"Unknown action command: {action_cmd}")

    except Exception as e:
      log.error(f"Failed to execute action '{action_cmd}': {e}")

  def launch_app(self, app_name: str):
    log.info(f"Action Engine launching app: '{app_name}'")
    try:
      app_name_clean = app_name.lower().strip()
      if app_name_clean == "notepad":
        self._sync_to_notepad("Bupi Notepad Editor", "")
        return

      web_mappings = {
          "linkedin": "https://www.linkedin.com/",
          "gmail": "https://mail.google.com/",
          "google mail": "https://mail.google.com/",
          "whatsapp": "https://web.whatsapp.com/",
          "github": "https://github.com/",
          "calendar": "https://calendar.google.com/",
          "google calendar": "https://calendar.google.com/"
      }
      if app_name_clean in web_mappings:
        url = web_mappings[app_name_clean]
        webbrowser.open(url)
        return

      if ":" in app_name and not app_name.startswith("C:"):
        os.startfile(app_name)
        return

      if os.name == 'nt':
        try:
          ps_cmd = f'Get-StartApps | Where-Object {{ $_.Name -like "*{app_name}*" }} | Select-Object -First 1 -ExpandProperty AppID'
          proc = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, check=True)
          appid = proc.stdout.strip()
          if appid:
            subprocess.Popen(["cmd", "/c", f"start shell:AppsFolder\\{appid}"], shell=True)
            return
        except:
          pass
        subprocess.Popen(["cmd", "/c", f"start {app_name}"], shell=True)
      else:
        webbrowser.open(app_name)
    except Exception as e:
      log.error(f"Failed to launch app '{app_name}': {e}")

  def ax_list(self, app_name: str):
    try:
      from actions.windows_uia import WindowsUIA
      uia = WindowsUIA()
      elements = uia.list_elements(app_name)
      if elements:
        notepad_text = "\n".join([f"- {el}" for el in elements])
        notepad_title = f"UIA Elements: {app_name}"
      else:
        notepad_text = f"No interactive elements found for app '{app_name}' or application not running."
        notepad_title = f"UIA Elements: {app_name} (Empty)"
      self._sync_to_notepad(notepad_title, notepad_text)
    except Exception as e:
      log.error(f"Failed to perform ax_list: {e}")

  def ax_press(self, app_name: str, label: str):
    try:
      from actions.windows_uia import WindowsUIA
      uia = WindowsUIA()
      uia.press_element(app_name, label)
    except Exception as e:
      log.error(f"Failed to perform ax_press: {e}")

  def ax_set_value(self, app_name: str, label: str, value: str):
    try:
      from actions.windows_uia import WindowsUIA
      uia = WindowsUIA()
      uia.set_value(app_name, label, value)
    except Exception as e:
      log.error(f"Failed to perform ax_set_value: {e}")

  def close_app(self, app_name: str) -> bool:
    import psutil
    closed_any = False
    for proc in proc_iter(['pid', 'name']):
      try:
        name = proc.info['name'] or ''
        if app_name.lower() in name.lower():
          proc.terminate()
          closed_any = True
      except:
        continue
    return closed_any

  def open_folder(self, path: str) -> bool:
    is_code = False
    if path.lower().startswith("code:"):
      is_code = True
      path = path[5:].strip()

    resolved = self._resolve_standard_path(path)
    if os.path.exists(resolved) and os.path.isdir(resolved):
      try:
        if is_code:
          subprocess.Popen(["cmd", "/c", f"code \"{resolved}\""], shell=True) if os.name == 'nt' else subprocess.Popen(["code", resolved])
        else:
          os.startfile(resolved)
        return True
      except Exception as e:
        log.error(f"Failed to open folder: {e}")
        return False

    best_match, is_dir, score = self.context_resolver.resolve_path(path, resolve_type="dir")
    if best_match and score >= 40:
      try:
        if is_code:
          subprocess.Popen(["cmd", "/c", f"code \"{best_match}\""], shell=True) if os.name == 'nt' else subprocess.Popen(["code", best_match])
        else:
          os.startfile(best_match)
        return True
      except Exception as e:
        log.error(f"Failed to open resolved folder: {e}")
    return False

  def create_folder(self, path: str) -> bool:
    resolved = self._resolve_standard_path(path)
    try:
      os.makedirs(resolved, exist_ok=True)
      return True
    except Exception as e:
      log.error(f"Failed to create folder: {e}")
      return False

  def create_file(self, path: str, content: str) -> bool:
    resolved = self._resolve_standard_path(path)
    try:
      os.makedirs(os.path.dirname(resolved), exist_ok=True)
      with open(resolved, 'w', encoding='utf-8') as f:
        f.write(content)
      return True
    except Exception as e:
      log.error(f"Failed to create file: {e}")
      return False

  def search_files(self, query: str) -> list:
    root_dirs = [
      os.path.expanduser("~/Downloads"),
      os.path.expanduser("~/Documents"),
      os.path.expanduser("~/Desktop")
    ]
    matches = []
    for root_dir in root_dirs:
      if not os.path.exists(root_dir):
        continue
      try:
        for root, dirs, files in os.walk(root_dir):
          for file in files:
            if query.lower() in file.lower():
              matches.append(os.path.join(root, file))
              if len(matches) >= 20:
                break
          if len(matches) >= 20:
            break
      except:
        continue
    return matches

  def _resolve_standard_path(self, path_str: str) -> str:
    path_str_lower = path_str.lower().strip()
    user_home = os.path.expanduser("~")
    if path_str_lower == "downloads":
      return os.path.join(user_home, "Downloads")
    elif path_str_lower == "documents":
      return os.path.join(user_home, "Documents")
    elif path_str_lower == "desktop":
      return os.path.join(user_home, "Desktop")
    elif path_str_lower.startswith("downloads/") or path_str_lower.startswith("downloads\\"):
      return os.path.join(os.path.join(user_home, "Downloads"), path_str[10:])
    elif path_str_lower.startswith("documents/") or path_str_lower.startswith("documents\\"):
      return os.path.join(os.path.join(user_home, "Documents"), path_str[10:])
    elif path_str_lower.startswith("desktop/") or path_str_lower.startswith("desktop\\"):
      return os.path.join(os.path.join(user_home, "Desktop"), path_str[8:])
    return os.path.abspath(path_str)

  def _sync_to_notepad(self, title: str, text: str):
    print(json.dumps({"type": "notepad_clear", "value": True}), flush=True)
    print(json.dumps({"type": "notepad_title", "value": title}), flush=True)
    print(json.dumps({"type": "notepad_insert", "value": text}), flush=True)

  def open_file(self, path: str) -> bool:
    is_code = False
    if path.lower().startswith("code:"):
      is_code = True
      path = path[5:].strip()

    resolved = self._resolve_standard_path(path)
    if os.path.exists(resolved) and os.path.isfile(resolved):
      try:
        if is_code:
          subprocess.Popen(["cmd", "/c", f"code \"{resolved}\""], shell=True) if os.name == 'nt' else subprocess.Popen(["code", resolved])
        else:
          os.startfile(resolved)
        return True
      except Exception as e:
        log.error(f"Failed to open file: {e}")
        return False

    best_match, is_dir, score = self.context_resolver.resolve_path(path, resolve_type="file")
    if best_match and score >= 40:
      try:
        if is_code:
          subprocess.Popen(["cmd", "/c", f"code \"{best_match}\""], shell=True) if os.name == 'nt' else subprocess.Popen(["code", best_match])
        else:
          os.startfile(best_match)
        return True
      except Exception as e:
        log.error(f"Failed to open resolved file: {e}")
    return False

  def write_to_notepad(self, content: str):
    self._sync_to_notepad("Bupi Notepad Editor", content)

  def activate_meeting_mode(self):
    self.mode_manager.deactivate_mode()
    self.mode_manager.active_mode = "meeting"
    print(json.dumps({"type": "mode-changed", "value": 2}), flush=True)
    webbrowser.open("https://meet.google.com")
    self._sync_to_notepad("Meeting Notes", "Meeting Mode active. Taking notes here...\nSystem volume muted for focus.")
    pyautogui.press('volumemute')
    self.close_app("spotify")

  def open_setup(self):
    setup_config = db_manager.get_preference("user_setup", None)
    if not setup_config:
      setup_config = "https://chatgpt.com,https://web.whatsapp.com,https://claude.ai"
      
    items = [item.strip() for item in setup_config.split(",") if item.strip()]
    for item in items:
      try:
        if item.startswith("code:"):
          folder_path = item[5:].strip()
          resolved = self._resolve_standard_path(folder_path)
          if not os.path.exists(resolved):
            best_match, is_dir, score = self.context_resolver.resolve_path(folder_path, resolve_type="dir")
            if best_match and score >= 40:
              resolved = best_match
          subprocess.Popen(["cmd", "/c", f"code \"{resolved}\""], shell=True) if os.name == 'nt' else subprocess.Popen(["code", resolved])
        elif item.startswith("http://") or item.startswith("https://"):
          if "whatsapp.com" in item:
            from actions.automation_agent import AutomationAgent
            agent = AutomationAgent()
            if not agent.send_whatsapp_via_existing_tab("", ""):
              webbrowser.open(item)
          else:
            webbrowser.open(item)
        else:
          self.launch_app(item)
      except Exception as e:
        log.error(f"Failed to open setup item: {e}")

  def control_media(self, cmd: str):
    try:
      import pygetwindow as gw
      windows = gw.getAllWindows()
      focused = False
      target_win = None
      media_app = None
      
      for w in windows:
        if not w.title:
          continue
        t_low = w.title.lower()
        if "youtube music" in t_low:
          target_win = w
          media_app = "youtube_music"
          break
        elif "youtube" in t_low:
          target_win = w
          media_app = "youtube"
          break
        elif "spotify" in t_low:
          target_win = w
          media_app = "spotify"
      
      if target_win:
        try:
          target_win.restore()
          target_win.activate()
          time.sleep(0.5)
          focused = True
        except:
          pass
          
      if cmd in ["play", "pause", "play_pause"]:
        if focused and media_app in ["youtube", "youtube_music"]:
          pyautogui.press('k')
        elif focused and media_app == "spotify":
          pyautogui.press('space')
        else:
          pyautogui.press('playpause')
      elif cmd == "next":
        if focused and media_app in ["youtube", "youtube_music"]:
          pyautogui.hotkey('shift', 'n')
        elif focused and media_app == "spotify":
          pyautogui.hotkey('ctrl', 'right')
        else:
          pyautogui.press('nexttrack')
      elif cmd == "prev":
        if focused and media_app in ["youtube", "youtube_music"]:
          pyautogui.hotkey('shift', 'p')
        elif focused and media_app == "spotify":
          pyautogui.hotkey('ctrl', 'left')
        else:
          pyautogui.press('prevtrack')
    except Exception as e:
      log.error(f"Media control error: {e}")

  def _get_first_youtube_video(self, query: str) -> str:
    import urllib.request
    import re
    query_encoded = urllib.parse.quote(query)
    url = f"https://www.youtube.com/results?search_query={query_encoded}"
    req = urllib.request.Request(
      url, 
      headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    )
    try:
      with urllib.request.urlopen(req, timeout=5) as response:
        html = response.read().decode('utf-8', errors='ignore')
        video_ids = re.findall(r"\"videoId\":\"([a-zA-Z0-9_-]{11})\"", html)
        if video_ids:
          return video_ids[0]
        video_ids = re.findall(r"/watch\?v=([a-zA-Z0-9_-]{11})", html)
        if video_ids:
          return video_ids[0]
    except Exception as e:
      log.error(f"Failed to fetch YouTube ID: {e}")
    return None


# ---------------- LEGACY OFFLINE PATTERN MATCHERS ----------------

def _set_name(match):
  name = match.group(1).strip().capitalize()
  db_manager.set_preference("username", name)
  return f"Got it! I will call you {name}."

def _remember_fact(match):
  fact = match.group(1).strip()
  notes_json = db_manager.get_preference("notes", "[]")
  try:
    notes = json.loads(notes_json)
  except:
    notes = []
  if fact not in notes:
    notes.append(fact)
    db_manager.set_preference("notes", json.dumps(notes))
  return f"I've noted that: {fact}"

def _google_search(match):
  query = match.group(1).strip()
  webbrowser.open(f"https://www.google.com/search?q={urllib.parse.quote(query)}")
  return f"Searching Google for: {query}"

def _open_browser(match=None):
  if os.name == 'nt':
    subprocess.Popen(["cmd", "/c", "start chrome"], shell=True)
  else:
    subprocess.Popen(["google-chrome"])
  return "Opening Google Chrome."

def _open_vscode(match=None):
  if os.name == 'nt':
    subprocess.Popen(["cmd", "/c", "code"], shell=True)
  else:
    subprocess.Popen(["code"])
  return "Opening VS Code."

def _open_notepad(match=None):
  print(json.dumps({"type": "command", "value": "open_notepad"}), flush=True)
  return "Opening Notepad editor."

def _open_spotify(match=None):
  if os.name == 'nt':
    subprocess.Popen(["cmd", "/c", "start spotify:"], shell=True)
  else:
    webbrowser.open("https://open.spotify.com")
  return "Opening Spotify."

def _open_calculator(match=None):
  subprocess.Popen(["calc.exe"] if os.name == 'nt' else ["gnome-calculator"])
  return "Opening Calculator."

def _open_whatsapp(match=None):
  webbrowser.open("https://web.whatsapp.com/")
  return "Opening WhatsApp Web."

def _send_whatsapp(match):
  webbrowser.open("https://web.whatsapp.com/")
  return "Opening WhatsApp Web so you can send your message!"

def _open_email(match):
  webbrowser.open("https://mail.google.com/")
  return "Opening Gmail."

def _send_linkedin(match):
  webbrowser.open("https://www.linkedin.com/")
  return "Opening LinkedIn."

def _play_music(match):
  query = match.group(1).strip()
  webbrowser.open(f"https://music.youtube.com/search?q={urllib.parse.quote(query)}")
  return f"Searching YouTube Music for: {query}"

def _open_youtube(match=None):
  webbrowser.open("https://www.youtube.com")
  return "Opening YouTube."

def _get_time(match=None):
  t_str = time.strftime("%I:%M %p")
  return f"The current time is {t_str}."

def _get_date(match=None):
  d_str = time.strftime("%A, %B %d, %Y")
  return f"Today is {d_str}."

def _take_screenshot(match=None):
  try:
    from PIL import ImageGrab
    os.makedirs("screenshots", exist_ok=True)
    filename = f"screenshots/screenshot_{int(time.time())}.png"
    screenshot = ImageGrab.grab()
    screenshot.save(filename)
    # Open screenshot
    os.startfile(filename)
    return "I've taken a screenshot and saved it to the screenshots folder."
  except Exception as e:
    return f"Failed to take screenshot: {e}"

def _keyboard_type(match):
  text = match.group(1)
  pyautogui.write(text, interval=0.01)
  return f"Typed: {text}"

def _keyboard_press(match):
  key = match.group(1).strip().lower().replace(" ", "")
  if "+" in key:
    keys = key.split("+")
    pyautogui.hotkey(*keys)
  else:
    pyautogui.press(key)
  return f"Pressed: {key}"

def _switch_window(match):
  win_title = match.group(1).strip()
  try:
    import pygetwindow as gw
    windows = gw.getWindowsWithTitle(win_title)
    if windows:
      win = windows[0]
      win.restore()
      win.activate()
      return f"Switched focus to window: '{win.title}'"
    else:
      return f"Could not find any window matching: '{win_title}'"
  except Exception as e:
    return f"Failed to switch windows: {e}"

def _birthday_surprise(match=None):
  from PyQt6.QtCore import QTimer
  from state_manager import state_mgr
  QTimer.singleShot(100, lambda: state_mgr.force("excited"))
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
  
  class FakeMatch:
    def group(self, i):
      return "happy birthday song"
  QTimer.singleShot(500, lambda: _play_music(FakeMatch()))
  return "Happy birthday to you! I prepared a little surprise with a cake, and I am putting on some music for you!"

PATTERNS = [
    (re.compile(r"(?:call me|my name is)\s+(.+)",     re.I), _set_name),
    (re.compile(r"(?:remember that|note that)\s+(.+)",             re.I), _remember_fact),
    (re.compile(r"(?:search|google)\s+(?:for\s+)?(.+)",         re.I), _google_search),
    (re.compile(r"(?:open|start|launch)\s+(?:up\s+|the\s+|google\s+)*(?:chrome|browser|firefox)",re.I), _open_browser),
    (re.compile(r"(?:open|start|launch)\s+(?:up\s+|the\s+)*(?:vs\s?code|code editor)", re.I), _open_vscode),
    (re.compile(r"(?:open|start|launch)\s+(?:up\s+|the\s+|my\s+)*(?:notepad|notes|text)", re.I), _open_notepad),
    (re.compile(r"(?:open|start|launch)\s+(?:up\s+|the\s+)*spotify",                 re.I), _open_spotify),
    (re.compile(r"(?:open|start|launch)\s+(?:up\s+|the\s+)*(?:calculator|calc)",       re.I), _open_calculator),
    (re.compile(r"(?:open|check)\s+(?:the\s+|my\s+)*whatsapp",                re.I), _open_whatsapp),
    (re.compile(r"(?:send|message|text|whatsapp).*(?:on whatsapp|to)", re.I), _send_whatsapp),
    (re.compile(r"(?:send|email|mail).*(?:email|mail)", re.I), _open_email),
    (re.compile(r"(?:send|message).*(?:on linkedin)", re.I), _send_linkedin),
    (re.compile(r"(?:play|listen\s+to|stream)\s+(.+)",                 re.I), _play_music),
    (re.compile(r"(?:open|start|launch)\s+(?:up\s+|the\s+)*(?:youtube|yt)",                    re.I), _open_youtube),
    (re.compile(r"(?:what.?s the time|current time|time now|what time)", re.I), _get_time),
    (re.compile(r"(?:what.?s today|what day|today.?s date)", re.I), _get_date),
    (re.compile(r"(?:take a screenshot|take screenshot|take a picture of my screen)", re.I), _take_screenshot),
    (re.compile(r"^(?:type|write|enter)\s+(.+)", re.I), _keyboard_type),
    (re.compile(r"^(?:press|hit)\s+(?:the\s+)?([a-z0-9\+\s]+?)\s*(?:key|button)?$", re.I), _keyboard_press),
    (re.compile(r"^(?:switch|focus)\s+(?:to\s+)?(?:the\s+)?(.+?)(?:\s+window)?$", re.I), _switch_window),
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
