import time
import ctypes
import threading
import psutil
from logger import log
from brain.db_manager import db_manager

class LASTINPUTINFO(ctypes.Structure):
  _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

class ActivityMonitorService:
  def __init__(self, check_interval=5.0, idle_threshold=60.0):
    self.check_interval = check_interval
    self.idle_threshold = idle_threshold # seconds before marked as idle
    self.running = False
    self.thread = None
    self._stop_event = threading.Event()

  def get_idle_time(self) -> float:
    """Returns the time in seconds since the last keyboard/mouse input on Windows."""
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
      # GetTickCount returns system uptime in milliseconds
      uptime_ms = ctypes.windll.kernel32.GetTickCount()
      last_input_ms = lii.dwTime
      # Handle tick count overflow (resets every 49.7 days)
      if uptime_ms >= last_input_ms:
        millis = uptime_ms - last_input_ms
      else:
        millis = (0xFFFFFFFF - last_input_ms) + uptime_ms
      return millis / 1000.0
    return 0.0

  def get_active_window_info(self):
    """Retrieves the foreground window title and process name."""
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
      return "None", "None"

    # Get Window Title
    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
    title = buf.value or "Unknown"

    # Get Process Name from Process ID
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    
    app_name = "Unknown"
    if pid.value > 0:
      try:
        proc = psutil.Process(pid.value)
        app_name = proc.name()
        # Clean up common application names for cleaner display
        if app_name.lower() in ["code.exe", "code"]:
          app_name = "VS Code"
        elif app_name.lower() in ["chrome.exe", "chrome"]:
          app_name = "Chrome"
        elif app_name.lower() in ["firefox.exe", "firefox"]:
          app_name = "Firefox"
        elif app_name.lower() in ["msedge.exe", "msedge"]:
          app_name = "Edge"
        elif app_name.lower() in ["spotify.exe", "spotify"]:
          app_name = "Spotify"
        elif app_name.lower() in ["notepad.exe", "notepad"]:
          app_name = "Notepad"
        elif app_name.lower() in ["cmd.exe", "powershell.exe", "powershell", "wt.exe", "terminal"]:
          app_name = "Terminal"
        elif app_name.lower().endswith(".exe"):
          app_name = app_name[:-4] # strip extension
      except Exception:
        app_name = "System"

    return title, app_name

  def start(self):
    if self.running:
      return
    log.info("Starting ActivityMonitorService...")
    self.running = True
    self._stop_event.clear()
    self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
    self.thread.start()

  def stop(self):
    if not self.running:
      return
    log.info("Stopping ActivityMonitorService...")
    self.running = False
    self._stop_event.set()
    if self.thread:
      self.thread.join(timeout=2.0)

  def _monitor_loop(self):
    while not self._stop_event.is_set():
      try:
        idle_time = self.get_idle_time()
        is_idle = idle_time >= self.idle_threshold
        
        if is_idle:
          app_name = "Idle"
          window_title = f"Idle for {int(idle_time)}s"
        else:
          window_title, app_name = self.get_active_window_info()
          
        db_manager.log_activity(
          app_name=app_name,
          window_title=window_title,
          duration=self.check_interval,
          is_idle=1 if is_idle else 0
        )
      except Exception as e:
        log.error(f"Error in ActivityMonitorService loop: {e}")
        
      # Sleep but support quick stopping
      self._stop_event.wait(self.check_interval)
