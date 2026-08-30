import os
import json
import urllib.request
from logger import log

def get_github_updates() -> str:
  """Fetches recent unread GitHub notifications using the personal access token."""
  token = os.getenv("GITHUB_TOKEN")
  if not token:
    return "GitHub integration not configured. Please add GITHUB_TOKEN to your .env file."

  try:
    url = "https://api.github.com/notifications"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "Bupi-Assistant")
    
    with urllib.request.urlopen(req, timeout=8) as response:
      status_code = response.getcode()
      if status_code != 200:
        return f"GitHub API returned status code {status_code}"
      data = json.loads(response.read().decode('utf-8'))
      
    if not data:
      return "No unread GitHub notifications."
      
    notification_lines = []
    for notification in data[:5]: # Top 5 notifications
      repo_name = notification.get("repository", {}).get("full_name", "Unknown Repo")
      subject_title = notification.get("subject", {}).get("title", "(No Title)")
      type_str = notification.get("subject", {}).get("type", "Notification")
      reason = notification.get("reason", "subscription")
      
      notification_lines.append(f"- [{repo_name}] {type_str}: {subject_title} ({reason})")
      
    return "\n".join(notification_lines)
  except Exception as e:
    log.error(f"Failed to fetch GitHub notifications: {e}")
    return f"GitHub API error: {e}"
