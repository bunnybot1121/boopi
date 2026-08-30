import os
import sys
import time
import subprocess
import threading
import pyautogui
import webbrowser
from logger import log
from event_bus import event_bus

class ModeManager:
  def __init__(self, action_engine):
    self.action_engine = action_engine
    self.active_mode = None
    self.timer_cancelled = False
    self.focus_duration = 25
    self.timer_thread = None

  def _set_mascot_mode(self, mode_num: int):
    import json
    sys.stdout.write(json.dumps({"type": "mode-changed", "value": mode_num}) + "\n")
    sys.stdout.flush()

  def _sync_to_notepad(self, title: str, text: str):
    import json
    sync_packet = {
      "notepad_text": text,
      "notepad_title": title,
      "notepad_clear": False
    }
    sys.stdout.write(json.dumps({"type": "notepad", "value": sync_packet}) + "\n")
    sys.stdout.flush()

  def activate_hackathon_mode(self):
    log.info("Activating Hackathon Mode...")
    self.deactivate_mode()
    self.active_mode = "hackathon"
    self._set_mascot_mode(2) # Switch to skyBlue focus palette
    
    # Open VS Code, Chrome, and project folder
    self.action_engine.launch_app("code")
    self.action_engine.launch_app("chrome")
    self.action_engine.open_folder("c:\\Users\\Sachin\\hackathon")
    
    # Mute distractions (pyautogui volume mute + close spotify)
    pyautogui.press('volumemute')
    self.action_engine.close_app("spotify")
    
    self._sync_to_notepad(
      "Hackathon Mode Active", 
      "HACKATHON MODE ACTIVE\n\n"
      "- VS Code, Chrome, and project folder opened.\n"
      "- Distractions muted (Spotify closed, system muted)."
    )

  def activate_study_mode(self, duration: int = 25):
    log.info(f"Activating Study Mode for {duration} minutes...")
    self.deactivate_mode()
    self.active_mode = "study"
    self._set_mascot_mode(2) # Switch to skyBlue focus palette
    
    # Create study directory if not exists, and open it
    study_dir = os.path.expanduser("~/Documents/Study")
    os.makedirs(study_dir, exist_ok=True)
    self.action_engine.open_folder(study_dir)
    
    # Mute distractions
    pyautogui.press('volumemute')
    self.action_engine.close_app("spotify")
    
    # Start focus timer thread
    self.timer_cancelled = False
    self.focus_duration = duration
    self.timer_thread = threading.Thread(target=self._run_focus_timer, daemon=True)
    self.timer_thread.start()
    
    self._sync_to_notepad(
      "Study Mode Active", 
      f"STUDY MODE ACTIVE\n\n"
      f"- Focus Timer: {duration} minutes remaining.\n"
      f"- Study folder opened at '{study_dir}'.\n"
      f"- System muted to prevent distractions.\n\n"
      f"Study notes template:\n"
      f"Topic:\n"
      f"Key Concepts:\n"
      f"Questions to research:"
    )

  def activate_presentation_mode(self):
    log.info("Activating Presentation Mode...")
    self.deactivate_mode()
    self.active_mode = "presentation"
    self._set_mascot_mode(2)
    
    # Open PPT: search for a presentation file in Documents/Downloads
    ppt_file = None
    search_dirs = [os.path.expanduser("~/Documents"), os.path.expanduser("~/Downloads")]
    for search_dir in search_dirs:
      if os.path.exists(search_dir):
        files = [os.path.join(search_dir, f) for f in os.listdir(search_dir) if f.endswith(".pptx")]
        if files:
          # sort by modified time
          files.sort(key=os.path.getmtime, reverse=True)
          ppt_file = files[0]
          break
          
    if ppt_file:
      log.info(f"Opening presentation file: {ppt_file}")
      os.startfile(ppt_file)
    else:
      log.info("No PPTX files found in standard folders. Launching PowerPoint/slides search in browser.")
      webbrowser.open("https://slides.google.com")
      
    # Open Browser Chrome/Edge
    self.action_engine.launch_app("chrome")
    
    # Enable Do Not Disturb (mute volume/notifications)
    pyautogui.press('volumemute')
    
    self._sync_to_notepad(
      "Presentation Mode Active",
      "PRESENTATION MODE ACTIVE\n\n"
      f"- Presentation file opened: {os.path.basename(ppt_file) if ppt_file else 'Google Slides browser window'}\n"
      "- Browser window launched.\n"
      "- Do Not Disturb enabled (system sound muted)."
    )

  def activate_coding_mode(self):
    log.info("Activating Coding Mode...")
    self.deactivate_mode()
    self.active_mode = "coding"
    self._set_mascot_mode(2)
    
    # Open VS Code
    self.action_engine.launch_app("code")
    
    # Open Terminal (PowerShell or command prompt)
    if os.name == 'nt':
      subprocess.Popen(["cmd.exe", "/k", "start powershell.exe"], shell=True)
    else:
      subprocess.Popen(["x-terminal-emulator"])
      
    # Open GitHub
    webbrowser.open("https://github.com")
    
    self._sync_to_notepad(
      "Coding Mode Active",
      "CODING MODE ACTIVE\n\n"
      "- VS Code launched.\n"
      "- PowerShell terminal spawned.\n"
      "- GitHub opened in browser."
    )

  def deactivate_mode(self):
    if self.active_mode:
      log.info(f"Deactivating active mode: {self.active_mode}")
      # If study mode timer is running, cancel it
      self.timer_cancelled = True
      
      self.active_mode = None
      self._set_mascot_mode(1) # Revert to normal yellow mascot
      
      # Unmute system volume (press volumemute again)
      pyautogui.press('volumemute')
      
      self._sync_to_notepad("Mode Deactivated", "All special modes deactivated. Returned to normal mode.")

  def _run_focus_timer(self):
    seconds = self.focus_duration * 60
    for i in range(seconds):
      if self.timer_cancelled:
        return
      time.sleep(1)
      
      # Update notepad every 60 seconds
      if (seconds - i - 1) % 60 == 0:
        mins_left = (seconds - i - 1) // 60
        if mins_left > 0:
          self._sync_to_notepad(
            "Study Mode Active", 
            f"STUDY MODE ACTIVE\n\n"
            f"- Focus Timer: {mins_left} minutes remaining.\n"
            f"- System muted to prevent distractions."
          )
          
    # Focus session completed
    self.active_mode = None
    self._set_mascot_mode(1)
    
    # Unmute system
    pyautogui.press('volumemute')
    
    # Emit events to speak and set state
    event_bus.emit('speak', "Great job! Your focus session is complete. Time to take a break!")
    event_bus.emit('set_state', 'proud', "Focus session complete!")
    self._sync_to_notepad("Focus Session Complete", "Focus session complete!\n\nTake a short break and rest.")
