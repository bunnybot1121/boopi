import os
import time
import urllib.parse
import webbrowser
from PIL import Image
from io import BytesIO
from playwright.sync_api import sync_playwright
import pyautogui

from logger import log
import config

class AutomationAgent:
  def __init__(self, ai_brain=None):
    self.ai_brain = ai_brain
    self.user_data_dir = os.path.join(os.path.dirname(__file__), 'browser_data')
    os.makedirs(self.user_data_dir, exist_ok=True)

  def open_gmail_compose(self, recipient: str, subject: str, body: str):
    """Opens a Gmail compose window prepopulated with parameters, leaving it open for user review."""
    log.info(f"Opening Gmail draft to: {recipient}, subject: {subject}")
    try:
      # URL-encode parameters
      enc_to = urllib.parse.quote(recipient)
      enc_su = urllib.parse.quote(subject)
      enc_body = urllib.parse.quote(body)
      
      # Gmail standard compose URL format
      compose_url = f"https://mail.google.com/mail/?view=cm&fs=1&to={enc_to}&su={enc_su}&body={enc_body}"
      
      # Open in default system browser so they use their active login session
      webbrowser.open(compose_url)
      log.info("Gmail compose opened in user's default browser.")
      return True
    except Exception as e:
      log.error(f"Failed to open Gmail compose: {e}")
      return False

  def send_linkedin_message(self, contact_name: str, message_text: str):
    """Launches Playwright with user data context, searches for contact, drafts message."""
    log.info(f"Preparing to send LinkedIn message to '{contact_name}'...")
    
    # Run Playwright in a sync block
    with sync_playwright() as p:
      try:
        # Launch persistent browser context (user login session will persist)
        context = p.chromium.launch_persistent_context(
          user_data_dir=self.user_data_dir,
          headless=False,
          args=["--start-maximized"]
        )
        page = context.new_page()
        
        # Navigate to LinkedIn messaging
        page.goto("https://www.linkedin.com/messaging/", wait_until="load")
        log.info("Loaded LinkedIn messaging. Please ensure you are logged in.")
        
        # Wait a moment for page to render fully
        time.sleep(3)
        
        # Try to find the 'Compose new message' button (selector: pencil/edit icon or new message link)
        new_msg_btn = page.locator("a[href*='/messaging/thread/new/']").first
        if new_msg_btn.is_visible():
          new_msg_btn.click()
        else:
          # Try search input
          search_input = page.locator("input[placeholder*='Search messages']").first
          if search_input.is_visible():
            search_input.click()
            search_input.fill(contact_name)
            time.sleep(2)
            # Select first search result
            first_result = page.locator(".msg-conversations-container__convo-item").first
            if first_result.is_visible():
              first_result.click()
            else:
              log.warning("No existing thread found, searching global contacts...")
              
        # Enter contact name into 'To:' field if starting a new message
        to_field = page.locator("input[name='searchTerm']").first
        if to_field.is_visible():
          to_field.fill(contact_name)
          time.sleep(2)
          # Click the first autocomplete recommendation
          page.keyboard.press("ArrowDown")
          page.keyboard.press("Enter")
          time.sleep(1)

        # Focus message text area and fill
        text_area = page.locator("div[role='textbox'][aria-label*='Write a message']").first
        if text_area.is_visible():
          text_area.click()
          text_area.fill(message_text)
          log.info("Message draft filled. Waiting for user review before closing browser context...")
          
          # Leave open for 10 seconds for user review and manual sending (to prevent automated spam bans)
          time.sleep(10)
        else:
          log.error("Could not locate message textbox on LinkedIn.")
          
        context.close()
        return True
      except Exception as e:
        log.error(f"LinkedIn automation error: {e}")
        return False

  def find_and_activate_whatsapp_tab(self) -> bool:
    """Attempts to find and focus an existing WhatsApp Web tab using window titles, PowerShell UI Automation, and keyboard tab searching."""
    import pygetwindow as gw
    import pyautogui
    import time
    
    # 1. Quick check: Is there a window that already has "WhatsApp" in its title?
    try:
      windows = gw.getAllWindows()
      for w in windows:
        if w.title and "whatsapp" in w.title.lower():
          log.info(f"Found window with 'WhatsApp' in title: '{w.title}'. Activating...")
          w.restore()
          w.activate()
          time.sleep(0.5)
          return True
    except Exception as e:
      log.warning(f"Error checking window titles: {e}")

    # 2. Try the PowerShell UI Automation script (original method)
    log.info("Checking for WhatsApp tab via PowerShell UI Automation...")
    import subprocess
    ps_cmd = """
    Add-Type -TypeDefinition @"
    using System;
    using System.Runtime.InteropServices;
    public class Win32Utils {
        [DllImport("user32.dll")]
        public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
        [DllImport("user32.dll")]
        public static extern bool SetForegroundWindow(IntPtr hWnd);
    }
"@
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    
    $procs = Get-Process | Where-Object { $_.Name -eq "chrome" -or $_.Name -eq "msedge" -or $_.Name -eq "firefox" -or $_.Name -eq "brave" -or $_.Name -eq "opera" -or $_.Name -eq "vivaldi" }
    foreach ($p in $procs) {
        $hwnd = $p.MainWindowHandle
        if ($hwnd -eq 0 -or $hwnd -eq [IntPtr]::Zero) { continue }
        
        $ae = [System.Windows.Automation.AutomationElement]::FromHandle($hwnd)
        if (-not $ae) { continue }
        
        $condition = New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::TabItem
        )
        
        $tabs = $ae.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
        foreach ($tab in $tabs) {
            if ($tab.Current.Name -like "*WhatsApp*") {
                Write-Output "FOUND_TAB|$($p.Name)|$($p.Id)|$($tab.Current.Name)"
                [Win32Utils]::ShowWindow($hwnd, 9)
                [Win32Utils]::SetForegroundWindow($hwnd)
                Start-Sleep -Milliseconds 400
                
                $selectPattern = $null
                if ($tab.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$selectPattern)) {
                    $selectPattern.Select()
                    Write-Output "SUCCESS_SELECT"
                    return
                } else {
                    try {
                        $pt = $tab.GetClickablePoint()
                        Write-Output "CLICK_COORDS|$($pt.X)|$($pt.Y)"
                        return
                    } catch {}
                }
            }
        }
        if ($p.MainWindowTitle -like "*WhatsApp*") {
            Write-Output "FOUND_ACTIVE_TAB|$($p.Name)|$($p.Id)"
            [Win32Utils]::ShowWindow($hwnd, 9)
            [Win32Utils]::SetForegroundWindow($hwnd)
            return
        }
    }
    Write-Output "NOT_FOUND"
    """
    
    try:
      proc = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=10)
      output = proc.stdout.strip()
      log.info(f"PowerShell WhatsApp check result: {output}")
      if "FOUND_TAB" in output or "FOUND_ACTIVE_TAB" in output or "SUCCESS_SELECT" in output:
        if "CLICK_COORDS" in output:
          for line in output.splitlines():
            if line.startswith("CLICK_COORDS"):
              _, x_str, y_str = line.split("|")
              pyautogui.click(int(x_str), int(y_str))
              time.sleep(0.5)
              break
        return True
    except Exception as e:
      log.warning(f"PowerShell check failed: {e}")

    # 3. Fallback: Search tabs in all open browser windows using keyboard shortcuts
    log.info("PowerShell check didn't succeed. Trying active window keyboard search tab fallback...")
    try:
      windows = gw.getAllWindows()
      browser_keywords = ["chrome", "edge", "brave", "firefox", "opera", "vivaldi"]
      
      for w in windows:
        if not w.title:
          continue
        
        is_browser = any(kw in w.title.lower() for kw in browser_keywords)
        if not is_browser:
          continue
          
        log.info(f"Activating browser window '{w.title}' to search tabs...")
        try:
          w.restore()
          w.activate()
          time.sleep(0.6)
          
          # Universal Chromium Tab Search shortcut
          pyautogui.hotkey('ctrl', 'shift', 'a')
          time.sleep(0.3)
          pyautogui.write('whatsapp')
          time.sleep(0.3)
          pyautogui.press('enter')
          time.sleep(0.8)
          
          # Refresh active window
          active_w = gw.getActiveWindow()
          if active_w and "whatsapp" in active_w.title.lower():
            log.info("Successfully activated WhatsApp tab via tab search!")
            return True
            
          # Escape search list if not found
          pyautogui.press('esc')
          time.sleep(0.2)
        except Exception as win_err:
          log.warning(f"Failed to search tabs in window '{w.title}': {win_err}")
    except Exception as e:
      log.warning(f"Keyboard tab search fallback failed: {e}")
      
    return False

  def send_whatsapp_via_existing_tab(self, contact_name: str, message_text: str) -> bool:
    """Attempts to find an open WhatsApp Web tab, bring it to focus, and send the message using keyboard automation."""
    log.info(f"Checking for existing WhatsApp tab in open browsers...")
    import pyperclip
    import pyautogui
    import time
    
    # Use our robust helper to find and focus the tab
    if not self.find_and_activate_whatsapp_tab():
      log.info("No open WhatsApp tab found in running browsers.")
      return False
      
    if not contact_name and not message_text:
      log.info("WhatsApp tab activated successfully (view-only mode).")
      return True
      
    log.info("WhatsApp tab found and activated. Automating search and message inputs...")
    time.sleep(1.0) # Wait for focus to settle
    
    # Force page document focus by clicking in the body area
    try:
      import pygetwindow as gw
      active_w = gw.getActiveWindow()
      if active_w:
        click_x = active_w.left + int(active_w.width * 0.3)
        click_y = active_w.top + int(active_w.height * 0.5)
        log.info(f"Clicking at ({click_x}, {click_y}) to focus WhatsApp Web page body...")
        pyautogui.click(click_x, click_y)
        time.sleep(0.5)
    except Exception as click_err:
      log.warning(f"Failed to click focus page body: {click_err}")
      
    # Save clipboard and clear to prepare
    old_clip = pyperclip.paste()
    
    # Press escape 3 times before search to clear any active chat selection or search state
    for _ in range(3):
      pyautogui.press('esc')
      time.sleep(0.15)
    
    # Focus search input using shortcut (Ctrl + Alt + /, Ctrl + Alt + Shift + F, or Alt + K)
    log.info("Sending shortcuts to focus search input...")
    pyautogui.hotkey('ctrl', 'alt', '/')
    time.sleep(0.15)
    pyautogui.hotkey('ctrl', 'alt', 'shift', 'f')
    time.sleep(0.15)
    pyautogui.hotkey('alt', 'k')
    time.sleep(0.5)
    
    # Paste contact name
    pyperclip.copy(contact_name)
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(1.5) # Wait for contacts list to update
    
    # Press Enter to open the chat
    pyautogui.press('enter')
    time.sleep(1.0) # Wait for chat to open
    
    # Copy message text and paste
    pyperclip.copy(message_text)
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.5)
    
    # Send message
    pyautogui.press('enter')
    log.info("Message sent successfully using keyboard automation on existing tab!")
    
    # Press escape 3 times to exit the chat focus and clear the search input
    time.sleep(0.5)
    for _ in range(3):
      pyautogui.press('esc')
      time.sleep(0.2)
    
    # Restore clipboard
    pyperclip.copy(old_clip)
    return True

  def send_whatsapp_message(self, contact_name: str, message_text: str) -> bool:
    """Uses existing WhatsApp Web tab if present, otherwise opens WhatsApp in default browser and automates it."""
    log.info(f"Preparing WhatsApp message to '{contact_name}'...")
    
    # Try sending via existing tab first
    if self.send_whatsapp_via_existing_tab(contact_name, message_text):
      return True
      
    log.info("No active WhatsApp tab found. Opening WhatsApp Web in default browser...")
    webbrowser.open("https://web.whatsapp.com/")
    
    # Wait for tab to open and load
    time.sleep(8)
    
    # Try automating the newly opened tab (up to 3 retries)
    for attempt in range(3):
      log.info(f"Attempting to automate newly opened WhatsApp tab (attempt {attempt+1}/3)...")
      if self.send_whatsapp_via_existing_tab(contact_name, message_text):
        return True
      time.sleep(3)
      
    log.error("Failed to automate WhatsApp in default browser.")
    return False


  def fetch_linkedin_notifications(self) -> str:
    """Launches Playwright with user data context, opens LinkedIn notifications, and scrapes updates."""
    log.info("Fetching LinkedIn notifications via Playwright...")
    with sync_playwright() as p:
      try:
        context = p.chromium.launch_persistent_context(
          user_data_dir=self.user_data_dir,
          headless=True
        )
        page = context.new_page()
        page.goto("https://www.linkedin.com/notifications/", wait_until="load")
        
        # Wait for notifications container or login redirect
        time.sleep(3.5)
        
        if "login" in page.url or "signin" in page.url:
          log.warning("LinkedIn: User is not logged in browser_data session.")
          context.close()
          return "Not logged into LinkedIn. Run scratch/login_linkedin.py to log in."
          
        # Extract notification list texts
        selectors = [
          "[data-test-nt-card]",
          ".nt-card__content",
          ".nt-card",
          "article.nt-card",
          ".notifications-card",
          ".artdeco-list__item",
          "[class*='nt-card']",
          ".nt-card__text"
        ]
        cards = []
        for selector in selectors:
          try:
            cards = page.locator(selector).all()
            if cards:
              log.info(f"LinkedIn: Found notifications using selector: {selector}")
              break
          except:
            continue
            
        if not cards:
          log.warning("LinkedIn: Notification card selectors not visible. Checking generic content...")
          body_text = page.locator("body").inner_text()
          if "notification" in body_text.lower():
            context.close()
            return "No unread notifications parsed."
          context.close()
          return "No notifications visible. Ensure you are logged in."

        notification_texts = []
        for card in cards[:5]: # Extract top 5
          try:
            text = card.inner_text().strip()
            if text:
              clean_text = " ".join(text.split())
              # Clean metadata/button texts from the card snippet
              if " See more" in clean_text:
                clean_text = clean_text.split(" See more")[0]
              notification_texts.append(f"- {clean_text}")
          except Exception as inner_e:
            continue
            
        context.close()
        if not notification_texts:
          return "No recent LinkedIn notifications found."
        return "\n".join(notification_texts)
      except Exception as e:
        log.error(f"Failed to fetch LinkedIn notifications: {e}")
        return f"LinkedIn automation error: {e}"
