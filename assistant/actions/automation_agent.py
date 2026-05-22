import os
import json
import time
from openai import OpenAI
from playwright.sync_api import sync_playwright

SYSTEM_PROMPT = """You are an Intelligent Automation Agent for Bupi.
You have a deep understanding of WhatsApp, Email, and LinkedIn.
The user will give you an instruction like "message Hi to Chintu on WhatsApp".
Your job is to parse their request into a structured JSON action.

Valid Platforms: "whatsapp", "email", "linkedin"

Output ONLY valid JSON in this exact format:
{
    "platform": "whatsapp" | "email" | "linkedin",
    "recipient": "Contact Name or Email",
    "subject": "The subject (for emails only)",
    "message": "The message to send"
}
"""

def parse_intent(task_text: str) -> dict:
    # Use OpenRouter to intelligently parse the request
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("[Automation Agent] Error: No OpenRouter API Key found.")
        return {}

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
    
    try:
        response = client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": task_text}
            ],
            response_format={"type": "json_object"},
            max_tokens=150
        )
        content = response.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        print(f"[Automation Agent] Parsing error: {e}")
        return {}

def send_whatsapp_playwright(recipient: str, message: str):
    print(f"[Automation Agent] Opening Playwright to send WhatsApp to {recipient}...")
    user_data_dir = os.path.join(os.path.dirname(__file__), "browser_data")
    
    try:
        with sync_playwright() as p:
            # Launch persistent context to save login session
            browser = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False, # Show browser so user can see it happen
                channel="chrome", # Use actual chrome
                args=["--start-maximized"],
                no_viewport=True
            )
            
            page = browser.pages[0]
            if not page:
                page = browser.new_page()
                
            page.goto("https://web.whatsapp.com/")
            
            # Wait for either the chat list (logged in) or QR code (logged out)
            try:
                # Wait up to 10 seconds to see if the chat list appears quickly (already logged in)
                page.wait_for_selector('#pane-side', timeout=10000)
            except Exception:
                print("[Automation Agent] Could not find chat list immediately. Checking if QR code scan is needed...")
                try:
                    # Give the user a massive 120 seconds to scan the QR code if they are logged out
                    print(">>> PLEASE SCAN THE WHATSAPP QR CODE IN THE BROWSER WINDOW <<<", flush=True)
                    page.wait_for_selector('#pane-side', timeout=120000)
                    print("[Automation Agent] Login successful! Session is now saved permanently.", flush=True)
                except Exception:
                    print("[Automation Agent] WhatsApp login timeout. You didn't scan the QR code in time.")
                    browser.close()
                    return "I couldn't access WhatsApp. Please make sure you are logged in on the browser."
            # Press Escape multiple times to close any existing open chats
            for _ in range(3):
                page.keyboard.press("Escape")
                time.sleep(0.1)

            time.sleep(1) # Give the chat list a moment to load fully
            
            # 1. Search for recipient
            # We use structural selectors (#side for the left pane) which are immune to WhatsApp's class name updates
            try:
                search_box = page.locator('#side div[contenteditable="true"]').first
                search_box.click(timeout=5000)
                search_box.fill(recipient)
            except Exception as e:
                print(f"[Automation Agent] Structural search box selector failed: {e}")
                # Fallback: universal shortcut to focus search, then type
                page.keyboard.press("Control+Alt+/")
                time.sleep(0.5)
                page.keyboard.type(recipient, delay=50)
                
            time.sleep(1.5) # Wait for search results
            
            # Press enter to open the first chat result
            page.keyboard.press("Enter")
            time.sleep(1.5) # Wait for chat to open
            
            # Verify we are in the correct chat by checking the header title
            try:
                # The chat header has a span with the contact's name inside it
                header_title = page.locator('header span[title]').first.get_attribute('title', timeout=2000)
                if header_title:
                    print(f"[Automation Agent] Opened chat with: {header_title}")
                    # Only do a warning if it doesn't match perfectly, because contact names might have emojis or last names
                    if recipient.lower() not in header_title.lower():
                        print(f"[Automation Agent] Warning: Expected '{recipient}' but chat header says '{header_title}'.")
            except Exception as e:
                print(f"[Automation Agent] Could not verify chat header: {e}")
                
            # 2. Type and send the message
            # If the user actually wanted to send a message, type it out
            if message:
                try:
                    # Structural selector for the main chat area footer
                    message_box = page.locator('#main footer div[contenteditable="true"]').first
                    message_box.click(timeout=5000)
                    message_box.fill(message)
                except Exception as e:
                    print(f"[Automation Agent] Structural message box selector failed: {e}")
                    # Fallback: it should already be focused by default when the chat opens
                    page.keyboard.type(message, delay=10)
                
                time.sleep(0.5)
                page.keyboard.press("Enter")
                result_str = f"Sent '{message}' to {recipient} on WhatsApp."
            else:
                result_str = f"Opened WhatsApp chat for {recipient}."
                
            time.sleep(2) # Give time for message to send before closing
            browser.close()
            return result_str
            
    except Exception as e:
        print(f"[Automation Agent] Playwright error: {e}")
        return "An error occurred while trying to automate WhatsApp."

def run_automation_agent(task_text: str) -> str:
    print(f"[Automation Agent] Analyzing task: '{task_text}'")
    intent = parse_intent(task_text)
    
    if not intent:
        return "Sorry, I couldn't understand the automation request."
        
    platform = intent.get("platform", "").lower()
    recipient = intent.get("recipient", "")
    subject = intent.get("subject", "")
    message = intent.get("message", "")
    
    if platform == "whatsapp":
        if not recipient:
            return "Who do you want me to message on WhatsApp?"
        return send_whatsapp_playwright(recipient, message)
        
    elif platform == "email":
        if not recipient:
            return "Who do you want me to email?"
        return send_email_playwright(recipient, subject, message)
        
    elif platform == "linkedin":
        if not recipient:
            return "Who do you want me to message on LinkedIn?"
        return send_linkedin_playwright(recipient, message)
        
    else:
        return f"Sorry, I don't know how to automate {platform} yet."

def send_email_playwright(recipient: str, subject: str, message: str):
    import urllib.parse
    print(f"[Automation Agent] Opening Playwright to send Email to {recipient}...")
    user_data_dir = os.path.join(os.path.dirname(__file__), "browser_data")
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                channel="chrome",
                args=["--start-maximized"],
                no_viewport=True
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            
            # Use Gmail compose URL structure
            url = f"https://mail.google.com/mail/u/0/?view=cm&fs=1&to={urllib.parse.quote(recipient)}"
            if subject: url += f"&su={urllib.parse.quote(subject)}"
            if message: url += f"&body={urllib.parse.quote(message)}"
            
            page.goto(url)
            
            # Wait for compose window to load
            try:
                page.wait_for_selector('div[aria-label="Message Body"]', timeout=20000)
            except Exception:
                browser.close()
                return "I couldn't access Gmail. Please ensure you are logged in."

            time.sleep(2)
            # We will NOT press send automatically for emails to be safe. We let the user hit send.
            browser.close()
            return f"Drafted email to {recipient}."
            
    except Exception as e:
        print(f"[Automation Agent] Playwright error: {e}")
        return "An error occurred while trying to automate Email."

def send_linkedin_playwright(recipient: str, message: str):
    print(f"[Automation Agent] Opening Playwright to send LinkedIn message to {recipient}...")
    user_data_dir = os.path.join(os.path.dirname(__file__), "browser_data")
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                channel="chrome",
                args=["--start-maximized"],
                no_viewport=True
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            
            page.goto("https://www.linkedin.com/messaging/")
            
            try:
                # Wait for messaging search box
                search_input = page.wait_for_selector('input.msg-search-form__search-field', timeout=20000)
            except Exception:
                browser.close()
                return "I couldn't access LinkedIn. Please ensure you are logged in."
                
            search_input.click()
            search_input.fill(recipient)
            time.sleep(2) # wait for dropdown
            
            page.keyboard.press("ArrowDown")
            page.keyboard.press("Enter")
            time.sleep(1.5)
            
            if message:
                msg_box = page.locator('div[aria-label="Write a message…"]')
                msg_box.click()
                msg_box.fill(message)
                time.sleep(0.5)
                page.keyboard.press("Enter")
                res = f"Sent '{message}' to {recipient} on LinkedIn."
            else:
                res = f"Opened LinkedIn chat for {recipient}."
                
            time.sleep(2)
            browser.close()
            return res
            
    except Exception as e:
        print(f"[Automation Agent] Playwright error: {e}")
        return "An error occurred while trying to automate LinkedIn."

if __name__ == "__main__":
    # Test script locally
    res = run_automation_agent("message Hi to Chintu on WhatsApp")
    print(res)
