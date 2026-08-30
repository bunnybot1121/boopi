import time
import datetime
import threading
import json
import sys
from logger import log
from brain.db_manager import db_manager
from actions.calendar_helper import get_today_schedule
from event_bus import event_bus

class DailyBriefingService:
  def __init__(self, ai_brain, speaker):
    self.ai_brain = ai_brain
    self.speaker = speaker

  def generate_briefing(self):
    """Generates the briefing context and fires LLM summary generation in background thread."""
    log.info("Triggering Daily Briefing generation...")
    threading.Thread(target=self._run_briefing_generation, daemon=True).start()

  def _run_briefing_generation(self):
    try:
      # 1. Fetch Today's Date
      now_dt = datetime.datetime.now()
      date_str = now_dt.strftime("%A, %B %d, %Y")
      
      # 2. Fetch Today's Reminders
      start_of_today = now_dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
      end_of_today = now_dt.replace(hour=23, minute=59, second=59, microsecond=999).timestamp()
      
      all_reminders = db_manager.get_all_reminders()
      today_reminders = []
      for r in all_reminders:
        if start_of_today <= r["trigger_time"] <= end_of_today:
          today_reminders.append(r)
          
      reminders_text = ""
      if today_reminders:
        reminders_text = "\n".join([
          f"- {time.strftime('%I:%M %p', time.localtime(r['trigger_time']))}: {r['text']} ({'Done' if r['notified'] else 'Pending'})"
          for r in today_reminders
        ])
      else:
        reminders_text = "No reminders scheduled for today."

      # 3. Fetch Google Calendar events
      calendar_text = get_today_schedule()
      
      # 3a. Fetch Gmail updates
      log.info("Daily Briefing: Fetching Gmail updates...")
      try:
        from actions.gmail_helper import get_unread_emails
        gmail_text = get_unread_emails()
      except Exception as ge:
        log.error(f"Failed to fetch Gmail for daily briefing: {ge}")
        gmail_text = "Error loading Gmail updates."
        
      # 3b. Fetch GitHub updates
      log.info("Daily Briefing: Fetching GitHub updates...")
      try:
        from actions.github_helper import get_github_updates
        github_text = get_github_updates()
      except Exception as ghe:
        log.error(f"Failed to fetch GitHub for daily briefing: {ghe}")
        github_text = "Error loading GitHub updates."
        
      # 3c. Fetch LinkedIn updates
      log.info("Daily Briefing: Fetching LinkedIn updates...")
      try:
        from actions.automation_agent import AutomationAgent
        agent = AutomationAgent(ai_brain=self.ai_brain)
        linkedin_text = agent.fetch_linkedin_notifications()
      except Exception as le:
        log.error(f"Failed to fetch LinkedIn for daily briefing: {le}")
        linkedin_text = "Error loading LinkedIn updates."

      # 4. Fetch Recent Projects from Memory Summary
      projects_summary = db_manager.get_memory_summary("projects", "None recorded yet.")
      tasks_summary = db_manager.get_memory_summary("tasks", "None recorded yet.")

      # 5. Fetch Mood Trends
      recent_emotions = db_manager.get_recent_emotion_history(limit=15)
      mood_trends = "Neutral"
      if recent_emotions:
        counts = {}
        for r in recent_emotions:
          mode = r.get("response_mode", "normal")
          counts[mode] = counts.get(mode, 0) + 1
        predominant_mode = max(counts, key=counts.get)
        mood_trends = f"Mostly {predominant_mode} mood patterns recently."

      # Combine into prompt context
      briefing_context = (
        f"Generate a daily briefing for the user.\n"
        f"Today is: {date_str}\n\n"
        f"--- TODAY'S REMINDERS ---\n{reminders_text}\n\n"
        f"--- TODAY'S CALENDAR SCHEDULE ---\n{calendar_text}\n\n"
        f"--- UNREAD EMAILS (GMAIL) ---\n{gmail_text}\n\n"
        f"--- GITHUB NOTIFICATIONS ---\n{github_text}\n\n"
        f"--- LINKEDIN NOTIFICATIONS ---\n{linkedin_text}\n\n"
        f"--- RECENT PROJECTS ---\n{projects_summary}\n\n"
        f"--- PENDING TASKS ---\n{tasks_summary}\n\n"
        f"--- RECENT MOOD TRENDS ---\n{mood_trends}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. You MUST start your response with exactly one status tag: [happy].\n"
        f"2. Keep the spoken response brief, sweet, calm, and cheerful (2-3 sentences), summarizing the day and notifications. Briefly mention if they have unread emails, GitHub updates, or LinkedIn connection requests. Keep it very warm and in Bupi's sweet and calm character.\n"
        f"3. Write the complete, beautiful daily briefing report inside [NOTEPAD] and [/NOTEPAD] tags. The report MUST look extremely premium and highly structured. Use centered decorative headers like '✧ ─── Bupi's Daily Briefing ─── ✧' and border dividers like '──────────────────────────────────────────' or '▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬' between sections. Each section (e.g., 📅 TODAY'S SCHEDULE, 📧 GMAIL INBOX, 🐙 GITHUB UPDATES, 💬 LINKEDIN ACTIVITY, 🧠 MEMORIES & TASKS) must have distinct headings, emojis, and cleanly formatted, readable list entries. Add a sweet closing signature: 'Have an amazing day! ✨ - Bupi'.\n"
        f"   - CRITICAL formatting rule: The notepad is a plain text <textarea> and does NOT render HTML, markdown headers (#), or markdown bold (**). You MUST NOT use any HTML tags (like <table>, <span>, <tr>, <hr>), markdown headers, or markdown bold/italic syntax. Use ONLY plain text with spacing, newlines, emojis, and standard symbols (like ✧, ═, ─, ▬, •, |) to build the visual design. Any HTML or markdown tags will render as raw code and ruin the user experience.\n"
        f"   - If a service has no notifications (e.g. if the raw text says 'No unread emails', 'No recent LinkedIn notifications found', or similar), explicitly output a clean message like: 'You have not received any notifications from LinkedIn.' or 'No unread emails.' in that section.\n"
        f"4. Respond using Bupi's 23-year-old sweet, calm, and friendly anime assistant personality rules."
      )

      # Query AI
      briefing_response = self.ai_brain.direct_query_translate(briefing_context)
      if not briefing_response:
        log.warning("Daily Briefing generation returned empty output.")
        return

      parsed = self.ai_brain.parse_tags(briefing_response)
      
      # 1. Sync report to notepad
      if parsed["notepad_text"] is not None or parsed["notepad_title"] is not None:
        sync_packet = {
          "notepad_text": parsed["notepad_text"],
          "notepad_title": parsed["notepad_title"] or "My Daily Briefing",
          "notepad_clear": parsed["notepad_clear"]
        }
        sys.stdout.write(json.dumps({"type": "notepad", "value": sync_packet}) + "\n")
        sys.stdout.flush()

      # 2. Speak greeting
      if parsed["spoken_text"]:
        # Update state to happy
        from state_manager import state_manager
        state_manager.set_state("happy", parsed["spoken_text"])
        self.speaker.speak(parsed["spoken_text"])
        
    except Exception as e:
      log.error(f"Error compiling daily briefing: {e}")
