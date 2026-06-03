import os
import json
import time
from openai import OpenAI
from google import genai
from google.genai import types
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
    use_local_llm = os.environ.get("USE_LOCAL_LLM", "false").lower() == "true"
    
    if use_local_llm:
        # Use local LLM (Ollama)
        local_llm_url = os.environ.get("LOCAL_LLM_URL", "http://localhost:11434/v1")
        local_model = os.environ.get("LOCAL_LLM_MODEL", "llama3.2")
        client = OpenAI(base_url=local_llm_url, api_key="ollama")
        try:
            response = client.chat.completions.create(
                model=local_model,
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
            print(f"[Automation Agent] Parsing error with local LLM: {e}")
            return {}
    else:
        # Use Google GenAI Native SDK
        google_key = os.environ.get("GOOGLE_AI_STUDIO_KEY")
        if not google_key:
            print("[Automation Agent] Error: No GOOGLE_AI_STUDIO_KEY found.")
            return {}
        try:
            client = genai.Client(api_key=google_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=task_text,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                )
            )
            return json.loads(response.text)
        except Exception as e:
            print(f"[Automation Agent] Parsing error with Google native SDK: {e}")
            return {}

def verify_contact_with_vision(recipient: str) -> bool:
    print("[Automation Agent] Taking screenshot for vision verification...")
    try:
        from PIL import ImageGrab
        import os

        # Take screenshot
        screen = ImageGrab.grab(all_screens=True)
        # Resize to save bandwidth but keep UI text readable
        screen.thumbnail((1280, 720))

        use_local_llm = os.environ.get("USE_LOCAL_LLM", "false").lower() == "true"
        local_llm_url = os.environ.get("LOCAL_LLM_URL", "http://localhost:11434/v1")
        
        prompt = f"I searched for '{recipient}' on WhatsApp. Look at the UI in the screenshot. Are there valid search results for a contact with this name to click on, or does it say 'No results found' / display an empty list? Reply with exactly 'FOUND' if a valid chat is available to be opened, or 'NOT_FOUND' if there are no results."
        
        if use_local_llm:
            from io import BytesIO
            import base64
            buffered = BytesIO()
            screen.save(buffered, format="JPEG", quality=70)
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            print("[Automation Agent] Using Local Vision Model (Llava) for verification...")
            client = OpenAI(base_url=local_llm_url, api_key="ollama")
            response = client.chat.completions.create(
                model="llava", # Default vision model for ollama
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_str}"}}
                        ]
                    }
                ],
                max_tokens=10
            )
            content = response.choices[0].message.content.strip().upper()
        else:
            google_key = os.environ.get("GOOGLE_AI_STUDIO_KEY")
            if not google_key:
                print("[Automation Agent] No Google API key found. Assuming contact found.")
                return True
                
            print("[Automation Agent] Using Cloud Vision Model (Google GenAI Native) for verification...")
            client = genai.Client(api_key=google_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[screen, prompt]
            )
            content = response.text.strip().upper()
        
        print(f"[Automation Agent] Vision Agent response: {content}")
        if "NOT_FOUND" in content:
            return False
        return True
    except Exception as e:
        print(f"[Automation Agent] Vision verification error: {e}. Falling back to assuming contact found.")
        return True

def send_whatsapp_native(recipient: str, message: str):
    print(f"[Automation Agent] Using Native Automation to send WhatsApp to {recipient}...")
    import time
    import pyautogui
    from actions.action_engine import _find_and_focus_tab, _open_in_chrome
    
    try:
        # Try to focus an existing WhatsApp tab or app first
        if not _find_and_focus_tab("WhatsApp"):
            print("[Automation Agent] WhatsApp not found, opening in Chrome...")
            _open_in_chrome("https://web.whatsapp.com/")
            time.sleep(3.5) # Reduced from 6s. Wait for WhatsApp Web to load
        else:
            time.sleep(0.5) # Wait for focus
            
        # We are now focused on WhatsApp.
        
        # 0. Crucial Fix: Back out of any currently open chats, text boxes, or popups
        # If a chat is open and the text box is focused, the search hotkey gets swallowed.
        for _ in range(3):
            pyautogui.press('escape')
            time.sleep(0.2)
            
        # 1. Focus search bar
        # Ctrl+Alt+/ focuses the search bar on WhatsApp Web and Desktop.
        pyautogui.hotkey('ctrl', 'alt', '/')
        time.sleep(0.5)
        
        # Clear anything existing in the search bar
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.press('backspace')
        time.sleep(0.2)
        
        # 2. Type recipient name
        pyautogui.write(recipient, interval=0.01)
        time.sleep(1.5) # Reduced from 2.5s. Wait for search results to filter
        
        # Verify with Vision Agent
        if not verify_contact_with_vision(recipient):
            print(f"[Automation Agent] Vision Agent aborted: {recipient} not found.")
            # Back out by pressing escape to clear the search
            for _ in range(3):
                pyautogui.press('escape')
                time.sleep(0.1)
            return f"Error: I could not find any contact named '{recipient}' on your WhatsApp screen. Please check the name."

        # 3. Press Enter to open the chat
        pyautogui.press('enter')
        time.sleep(1.5) # Wait for chat to open
        
        if message:
            # 4. Type the message
            # When a chat opens, the text box is automatically focused
            pyautogui.write(message, interval=0.01)
            time.sleep(0.5)
            pyautogui.press('enter')
            return f"Sent '{message}' to {recipient} on WhatsApp natively."
        else:
            return f"Opened WhatsApp chat for {recipient}."
            
    except Exception as e:
        print(f"[Automation Agent] Native automation error: {e}")
        return "An error occurred while trying to automate WhatsApp natively."

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
        return send_whatsapp_native(recipient, message)
        
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
            
            # Verify chat opened
            chat_opened = False
            try:
                msg_box = page.locator('div[aria-label="Write a message…"]').first
                msg_box.wait_for(timeout=3000)
                chat_opened = True
            except Exception:
                print(f"[Automation Agent] Could not find message box for '{recipient}'.")
                
            if not chat_opened:
                browser.close()
                return f"Error: I could not find any connection named '{recipient}' on LinkedIn. Please ask the user for the exact connection name."
            
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
