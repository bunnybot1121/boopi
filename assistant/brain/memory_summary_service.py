import time
import json
import threading
from logger import log
from brain.db_manager import db_manager

class MemorySummaryService:
  def __init__(self, ai_brain, summarize_every_turns=2):
    self.ai_brain = ai_brain
    self.summarize_every_turns = summarize_every_turns
    self.turns_since_last_summary = 0

  def check_and_summarize(self, force=False):
    """Increments the turn counter and runs summarization in a background thread if threshold met."""
    self.turns_since_last_summary += 1
    if force or self.turns_since_last_summary >= self.summarize_every_turns:
      self.turns_since_last_summary = 0
      log.info("Triggering periodic memory summarization in the background...")
      threading.Thread(target=self._run_summarization, daemon=True).start()

  def _run_summarization(self):
    try:
      # Retrieve recent conversation turns (up to 40)
      recent_turns = db_manager.get_recent_conversations(limit=40)
      if len(recent_turns) < 3:
        log.info("Not enough conversation turns to summarize memory.")
        return

      # Construct turn history string
      history_lines = []
      for turn in recent_turns:
        role = "User" if turn["role"] == "user" else "Bupi"
        history_lines.append(f"{role}: {turn['content']}")
      history_str = "\n".join(history_lines)

      # Query the AI directly with a dedicated translation/utility query
      prompt = (
        f"You are a background memory summarizer for Bupi. "
        f"Analyze the following conversation history and extract/update the user's long-term categories. "
        f"Respond ONLY with a clean JSON object containing keys: 'projects', 'interests', and 'tasks'.\n"
        f"Format:\n"
        f"{{\n"
        f"  \"projects\": \"List of active projects user is coding/working on, e.g. Bupi, NHAI FaceID.\",\n"
        f"  \"interests\": \"List of user's key technological or general interests mentioned, e.g. Emotional AI, Robotics.\",\n"
        f"  \"tasks\": \"List of upcoming or pending tasks and goals user is planning, e.g. Hackathon.\"\n"
        f"}}\n"
        f"If a category is empty or not mentioned, return a blank string. "
        f"Do NOT include any markdown packaging like ```json, headers, or explanations. Just return the raw JSON string.\n\n"
        f"--- CONVERSATION HISTORY ---\n{history_str}"
      )

      raw_response = self.ai_brain.direct_query_translate(prompt)
      if not raw_response:
        log.warning("Memory summarization failed: LLM returned empty response.")
        return
        
      # Strip code block wrappers if any
      clean_resp = raw_response.strip()
      if clean_resp.startswith("```"):
        # Remove first line
        lines = clean_resp.split("\n")
        if lines[0].startswith("```"):
          lines = lines[1:]
        if lines[-1].startswith("```"):
          lines = lines[:-1]
        clean_resp = "\n".join(lines).strip()

      data = json.loads(clean_resp)
      
      # Save extracted summaries
      if "projects" in data:
        val = data["projects"]
        if isinstance(val, list):
          val = ", ".join(val)
        db_manager.set_memory_summary("projects", str(val).strip())
      if "interests" in data:
        val = data["interests"]
        if isinstance(val, list):
          val = ", ".join(val)
        db_manager.set_memory_summary("interests", str(val).strip())
      if "tasks" in data:
        val = data["tasks"]
        if isinstance(val, list):
          val = ", ".join(val)
        db_manager.set_memory_summary("tasks", str(val).strip())
        
      log.info("Successfully updated memory summaries in SQLite database.")
    except json.JSONDecodeError as je:
      log.error(f"Failed to parse memory summary JSON: {je}. Raw: '{raw_response}'")
    except Exception as e:
      log.error(f"Error executing memory summarization: {e}")
