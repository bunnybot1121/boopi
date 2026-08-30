import subprocess
import os
import pyautogui
import pyperclip
import time
from logger import log

class WindowsUIA:
  def __init__(self):
    self.ps_script = os.path.join(os.path.dirname(__file__), 'uia_helper.ps1')

  def list_elements(self, app_name: str):
    """Lists interactive elements in the target app window."""
    log.info(f"Listing UIA elements for app: '{app_name}'")
    try:
      cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", self.ps_script, "-Action", "list", "-App", app_name]
      proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
      lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
      return lines
    except Exception as e:
      log.error(f"UIA list failed: {e}")
      return []

  def press_element(self, app_name: str, label: str):
    """Presses/invokes an element matching label."""
    log.info(f"UIA pressing element '{label}' in app '{app_name}'")
    try:
      cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", self.ps_script, "-Action", "press", "-App", app_name, "-Label", label]
      proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
      output = proc.stdout.strip()
      
      if output.startswith("Coordinates|"):
        _, x_str, y_str = output.split("|")
        x, y = int(x_str), int(y_str)
        log.info(f"UIA element clicked via coordinates: ({x}, {y})")
        pyautogui.click(x, y)
        return f"Clicked element '{label}' at ({x}, {y})"
      
      return output
    except Exception as e:
      log.error(f"UIA press failed: {e}")
      return f"Error: {e}"

  def set_value(self, app_name: str, label: str, value: str):
    """Sets text value of element matching label."""
    log.info(f"UIA setting value of '{label}' to '{value}' in app '{app_name}'")
    try:
      cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", self.ps_script, "-Action", "set_value", "-App", app_name, "-Label", label, "-Value", value]
      proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
      output = proc.stdout.strip()
      
      if output.startswith("SendKeys|"):
        _, val = output.split("|", 1)
        log.info(f"UIA element focused, typing value via pyautogui...")
        # Use clipboard paste to send text safely, preserving casing/Unicode
        pyperclip.copy(val)
        time.sleep(0.1)
        pyautogui.hotkey('ctrl', 'v')
        return f"Typed value '{val}' via clipboard paste"
      
      return output
    except Exception as e:
      log.error(f"UIA set_value failed: {e}")
      return f"Error: {e}"
