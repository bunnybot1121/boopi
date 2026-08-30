import re
from logger import log

class ConversationFollowupEngine:
  def __init__(self):
    pass

  def get_followup_instructions(self, prompt: str) -> str:
    """Analyzes the user prompt for failure/problem/milestone markers and returns guidelines."""
    prompt_lower = prompt.lower()
    
    # 1. Failure/issue markers
    failures = ["fail", "error", "bug", "crash", "broken", "issue", "problem", "wrong", "cannot", "can't", "failed", "failing", "not working", "gaya"]
    has_failure = any(f in prompt_lower for f in failures) or "dikkat" in prompt_lower or "kharab" in prompt_lower
    
    # 2. Project milestones/progress markers
    milestones = ["finished", "done", "complete", "completed", "built", "implemented", "achieved", "solved", "ended", "ho gaya"]
    has_milestone = any(m in prompt_lower for m in milestones)
    
    guidelines = []
    
    if has_failure:
      guidelines.append(
        "- The user is experiencing a problem, error, or failure. "
        "You MUST ask a natural, helpful, and sweet, calm follow-up question to dig deeper into the issue "
        "(e.g., 'What part failed?', 'Did the issue appear after recent changes?', or 'Can you show me the logs?'). "
        "Do not just apologize or give a solution immediately; prompt them to diagnose it with you."
      )
    elif has_milestone:
      guidelines.append(
        "- The user finished or accomplished a task or project milestone. "
        "You MUST celebrate with them first (e.g. [excited], [proud]) and ask a follow-up question about the next step or how it went "
        "(e.g., 'What are we working on next?', 'Did you run tests on it?')."
      )
    else:
      # General interactive follow-up to make the conversation feel alive
      guidelines.append(
        "- Keep the conversation interactive and open. Ask a relevant, short follow-up question if appropriate to keep the dialogue going naturally."
      )
      
    if guidelines:
      return (
        "--- CONVERSATION FOLLOW-UP INSTRUCTIONS ---\n"
        + "\n".join(guidelines) + "\n"
      )
    return ""

  def post_process_response(self, prompt: str, response: str) -> str:
    """Validates the LLM's response to ensure it contains a follow-up question if a problem was discussed."""
    prompt_lower = prompt.lower()
    response_lower = response.lower()
    
    failures = ["fail", "error", "bug", "crash", "broken", "issue", "problem", "wrong", "cannot", "can't", "failed", "failing", "not working"]
    has_failure = any(f in prompt_lower for f in failures)
    
    # If a failure was discussed but Bupi's response has no question mark, append a natural follow-up question
    if has_failure and "?" not in response:
      log.info("Post-processing: Appending follow-up question to Bupi's response.")
      # Simple set of natural, context-free follow-up queries based on standard failures
      if "model" in prompt_lower or "llm" in prompt_lower or "ai" in prompt_lower:
        followup = " Did the issue start after recent changes to the prompt or hyperparameters?"
      elif "code" in prompt_lower or "run" in prompt_lower or "compile" in prompt_lower:
        followup = " Did you see any error stack trace in the terminal or logs?"
      else:
        followup = " What error message or symptom did you get?"
        
      # Make sure we don't duplicate existing closing text
      response = response.strip()
      if response.endswith("]"): # trailing tag
        response += followup
      else:
        response += followup
        
    return response
