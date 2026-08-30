import os
import datetime
import dateutil.parser
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from logger import log

SCOPES = [
  'https://www.googleapis.com/auth/calendar',
  'https://www.googleapis.com/auth/gmail.readonly'
]

def get_google_credentials():
  """Authenticates and returns valid OAuth2 credentials, prompting the user if needed."""
  creds = None
  token_path = os.path.join(os.path.dirname(__file__), '..', 'token.json')
  creds_path = os.path.join(os.path.dirname(__file__), '..', 'credentials.json')

  if os.path.exists(token_path):
    try:
      creds = Credentials.from_authorized_user_file(token_path, SCOPES)
      # If the existing token doesn't include the newly added Gmail scope, clear it to force re-auth
      if creds and (not creds.scopes or 'https://www.googleapis.com/auth/gmail.readonly' not in creds.scopes):
        log.info("Existing token.json is missing Gmail scope. Clearing to trigger re-authentication...")
        creds = None
        try:
          os.remove(token_path)
        except Exception as remove_err:
          log.warning(f"Could not remove old token.json: {remove_err}")
    except Exception as e:
      log.error(f"Failed to load OAuth token: {e}")

  # If credentials are not valid or expired, refresh or request new
  if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
      try:
        creds.refresh(Request())
        with open(token_path, 'w') as token:
          token.write(creds.to_json())
      except Exception as e:
        log.error(f"Failed to refresh OAuth token: {e}")
        creds = None

    if not creds:
      if not os.path.exists(creds_path):
        log.warning("credentials.json not found in workspace.")
        return None

      try:
        flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as token:
          token.write(creds.to_json())
      except Exception as e:
        log.error(f"Google OAuth flow failed: {e}")
        return None

  return creds

def get_calendar_service():
  """Authenticates and returns the Google Calendar API service instance.
  Returns None if credentials.json is missing or authentication fails.
  """
  creds = get_google_credentials()
  if not creds:
    # Check for developer API key fallback
    import config
    api_key = config.CALENDAR_API_KEY
    if api_key:
      try:
        service = build('calendar', 'v3', developerKey=api_key)
        log.info("Successfully loaded Google Calendar service using developer API key fallback.")
        return service
      except Exception as e:
        log.error(f"Failed to load Google Calendar service with developerKey fallback: {e}")
    return None

  try:
    service = build('calendar', 'v3', credentials=creds)
    return service
  except Exception as e:
    log.error(f"Failed to build Google Calendar service: {e}")
    return None

def get_today_schedule() -> str:
  """Retrieves events for the current day from the primary Google Calendar."""
  service = get_calendar_service()
  if not service:
    return "Google Calendar integration is not configured. Please place credentials.json in the project root folder."

  try:
    now = datetime.datetime.now()
    # Today's boundaries in local timezone
    local_start = datetime.datetime(now.year, now.month, now.day, 0, 0, 0).astimezone()
    local_end = datetime.datetime(now.year, now.month, now.day, 23, 59, 59).astimezone()
    today_start = local_start.isoformat()
    today_end = local_end.isoformat()

    log.info(f"Fetching calendar events between {today_start} and {today_end}")
    
    events_result = service.events().list(
      calendarId='primary', 
      timeMin=today_start,
      timeMax=today_end,
      singleEvents=True,
      orderBy='startTime'
    ).execute()
    
    events = events_result.get('items', [])
    if not events:
      return "You have no events scheduled for today."

    formatted = ["Today's Schedule:"]
    for event in events:
      start = event['start'].get('dateTime', event['start'].get('date'))
      summary = event.get('summary', 'Untitled Event')
      # Format timestamp slightly
      try:
        dt = dateutil.parser.isoparse(start)
        dt_local = dt.astimezone()
        start_str = dt_local.strftime("%I:%M %p")
      except:
        start_str = start
      formatted.append(f"- {start_str}: {summary}")
      
    return "\n".join(formatted)
  except Exception as e:
    log.error(f"Failed to fetch today's calendar: {e}")
    return f"Failed to retrieve today's schedule: {e}"

def list_upcoming_events(max_results: int = 5) -> str:
  """Retrieves the next N upcoming events from primary calendar."""
  service = get_calendar_service()
  if not service:
    return "Google Calendar integration is not configured. Please place credentials.json in the project root folder."

  try:
    now = datetime.datetime.now().astimezone().isoformat()
    events_result = service.events().list(
      calendarId='primary',
      timeMin=now,
      maxResults=max_results,
      singleEvents=True,
      orderBy='startTime'
    ).execute()
    
    events = events_result.get('items', [])
    if not events:
      return "No upcoming events found."

    formatted = ["Upcoming Calendar Events:"]
    for event in events:
      start = event['start'].get('dateTime', event['start'].get('date'))
      summary = event.get('summary', 'Untitled Event')
      try:
        dt = dateutil.parser.isoparse(start)
        dt_local = dt.astimezone()
        start_str = dt_local.strftime("%Y-%m-%d %I:%M %p")
      except:
        start_str = start
      formatted.append(f"- {start_str}: {summary}")
      
    return "\n".join(formatted)
  except Exception as e:
    log.error(f"Failed to fetch upcoming calendar events: {e}")
    return f"Failed to retrieve upcoming events: {e}"

def create_calendar_event(summary: str, start_time_str: str, duration_minutes: int = 30, description: str = "") -> str:
  """Creates a new calendar event.
  start_time_str should be parseable (e.g. ISO format or natural date parsed to ISO)
  """
  service = get_calendar_service()
  if not service:
    return "Google Calendar integration is not configured. Please place credentials.json in the project root folder."

  try:
    try:
      # Parse the start time string dynamically
      start_dt = dateutil.parser.parse(start_time_str)
      if start_dt.tzinfo is None:
        start_dt = start_dt.astimezone()
    except Exception as parse_err:
      log.error(f"Failed to parse datetime string '{start_time_str}': {parse_err}")
      return f"Invalid start time format: '{start_time_str}'. Please provide a valid timestamp."

    end_dt = start_dt + datetime.timedelta(minutes=duration_minutes)

    event = {
      'summary': summary,
      'description': description,
      'start': {
        'dateTime': start_dt.isoformat(),
      },
      'end': {
        'dateTime': end_dt.isoformat(),
      }
    }

    created_event = service.events().insert(calendarId='primary', body=event).execute()
    event_id = created_event.get('id')
    event_link = created_event.get('htmlLink')
    
    log.info(f"Event created successfully: {summary} (ID: {event_id})")
    return f"Successfully created event '{summary}' on your Google Calendar starting at {start_dt.strftime('%Y-%m-%d %I:%M %p')}."
  except Exception as e:
    log.error(f"Failed to create calendar event: {e}")
    return f"Failed to create event: {e}"
