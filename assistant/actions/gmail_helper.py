import os
from googleapiclient.discovery import build
from logger import log
from actions.calendar_helper import get_google_credentials

def get_gmail_service():
  """Returns the Google Gmail API service instance."""
  creds = get_google_credentials()
  if not creds:
    log.warning("Gmail: OAuth credentials not available.")
    return None
  try:
    return build('gmail', 'v1', credentials=creds)
  except Exception as e:
    log.error(f"Failed to build Gmail service: {e}")
    return None

def get_unread_emails() -> str:
  """Fetches up to 5 unread emails from the inbox and returns formatted subjects/senders."""
  service = get_gmail_service()
  if not service:
    return "Gmail integration is not authorized or credentials.json is missing."

  try:
    # Query for unread emails in inbox
    results = service.users().messages().list(
      userId='me',
      q='is:unread category:primary', # Focus on primary inbox unread messages to avoid spam/promotions
      maxResults=5
    ).execute()
    
    messages = results.get('messages', [])
    if not messages:
      return "No unread primary emails."

    email_lines = []
    for msg in messages:
      try:
        msg_detail = service.users().messages().get(
          userId='me', 
          id=msg['id'], 
          format='metadata', 
          metadataHeaders=['From', 'Subject', 'Date']
        ).execute()
        
        # Parse headers
        headers = msg_detail.get('payload', {}).get('headers', [])
        sender = "Unknown Sender"
        subject = "(No Subject)"
        
        for h in headers:
          if h['name'].lower() == 'from':
            sender = h['value']
          elif h['name'].lower() == 'subject':
            subject = h['value']
            
        snippet = msg_detail.get('snippet', '')
        # Clean sender format (e.g. "John Doe <john@example.com>" to "John Doe")
        if " <" in sender:
          sender = sender.split(" <")[0]
          
        email_lines.append(f"- From: {sender} | Subject: {subject}\n  Brief: {snippet[:120]}")
      except Exception as inner_e:
        log.error(f"Failed to fetch detailed gmail message: {inner_e}")
        
    return "\n".join(email_lines)
  except Exception as e:
    log.error(f"Failed to list gmail messages: {e}")
    return f"Gmail API error: {e}"
