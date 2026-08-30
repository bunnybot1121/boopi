import sqlite3
import os
import time
from logger import log

class DBManager:
  def __init__(self, db_path=None):
    if db_path is None:
      db_path = os.path.join(os.path.dirname(__file__), 'bupi.db')
    self.db_path = db_path
    self._init_db()

  def _get_connection(self):
    return sqlite3.connect(self.db_path)

  def _init_db(self):
    log.info(f"Initializing SQLite database at {self.db_path}")
    try:
      with self._get_connection() as conn:
        cursor = conn.cursor()
        
        # Preferences Table
        cursor.execute('''
          CREATE TABLE IF NOT EXISTS preferences (
            key TEXT PRIMARY KEY,
            value TEXT
          )
        ''')
        
        # Reminders Table
        cursor.execute('''
          CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reminder_text TEXT NOT NULL,
            trigger_time REAL NOT NULL,
            notified INTEGER DEFAULT 0,
            calendar_event_id TEXT
          )
        ''')
        
        # Conversations Table
        cursor.execute('''
          CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp REAL NOT NULL
          )
        ''')

        # Emotion History Table
        cursor.execute('''
          CREATE TABLE IF NOT EXISTS emotion_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            message TEXT NOT NULL,
            sadness REAL NOT NULL,
            frustration REAL NOT NULL,
            stress REAL NOT NULL,
            anger REAL NOT NULL,
            happiness REAL NOT NULL,
            neutral REAL NOT NULL,
            response_mode TEXT NOT NULL
          )
        ''')
        
        # Activity Log Table
        cursor.execute('''
          CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            app_name TEXT NOT NULL,
            window_title TEXT NOT NULL,
            duration REAL NOT NULL,
            is_idle INTEGER DEFAULT 0
          )
        ''')
        
        # Memory Summaries Table
        cursor.execute('''
          CREATE TABLE IF NOT EXISTS memory_summaries (
            category TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            updated_at REAL NOT NULL
          )
        ''')
        
        conn.commit()
      log.info("SQLite database tables verified successfully.")
    except Exception as e:
      log.error(f"Failed to initialize database: {e}")

  # Preference Queries
  def get_preference(self, key, default=None):
    try:
      with self._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM preferences WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else default
    except Exception as e:
      log.error(f"Error fetching preference '{key}': {e}")
      return default

  def set_preference(self, key, value):
    try:
      if key == "preferred_language":
        value = "English"
      with self._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
          "INSERT OR REPLACE INTO preferences (key, value) VALUES (?, ?)",
          (key, str(value))
        )
        conn.commit()
    except Exception as e:
      log.error(f"Error setting preference '{key}' to '{value}': {e}")

  # Reminders Queries
  def add_reminder(self, text, trigger_time, calendar_event_id=None):
    try:
      with self._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
          "INSERT INTO reminders (reminder_text, trigger_time, notified, calendar_event_id) VALUES (?, ?, 0, ?)",
          (text, trigger_time, calendar_event_id)
        )
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
      log.error(f"Error adding reminder '{text}': {e}")
      return None

  def get_pending_reminders(self, current_time):
    try:
      with self._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
          "SELECT id, reminder_text, trigger_time, calendar_event_id FROM reminders WHERE trigger_time <= ? AND notified = 0",
          (current_time,)
        )
        return [
          {
            "id": row[0],
            "text": row[1],
            "trigger_time": row[2],
            "calendar_event_id": row[3]
          }
          for row in cursor.fetchall()
        ]
    except Exception as e:
      log.error(f"Error getting pending reminders: {e}")
      return []

  def get_all_reminders(self):
    try:
      with self._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, reminder_text, trigger_time, notified, calendar_event_id FROM reminders ORDER BY trigger_time ASC")
        return [
          {
            "id": row[0],
            "text": row[1],
            "trigger_time": row[2],
            "notified": bool(row[3]),
            "calendar_event_id": row[4]
          }
          for row in cursor.fetchall()
        ]
    except Exception as e:
      log.error(f"Error getting all reminders: {e}")
      return []

  def mark_reminder_notified(self, reminder_id):
    try:
      with self._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE reminders SET notified = 1 WHERE id = ?", (reminder_id,))
        conn.commit()
        return True
    except Exception as e:
      log.error(f"Error marking reminder {reminder_id} as notified: {e}")
      return False

  def delete_reminder(self, reminder_id):
    try:
      with self._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        conn.commit()
        return True
    except Exception as e:
      log.error(f"Error deleting reminder {reminder_id}: {e}")
      return False

  # Conversation Queries
  def add_conversation_turn(self, role, content):
    try:
      with self._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
          "INSERT INTO conversations (role, content, timestamp) VALUES (?, ?, ?)",
          (role, content, time.time())
        )
        conn.commit()
    except Exception as e:
      log.error(f"Error adding conversation turn: {e}")

  def get_recent_conversations(self, limit=15):
    try:
      with self._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
          "SELECT role, content FROM conversations ORDER BY timestamp DESC LIMIT ?",
          (limit,)
        )
        rows = cursor.fetchall()
        # Return in chronological order
        return [{"role": row[0], "content": row[1]} for row in reversed(rows)]
    except Exception as e:
      log.error(f"Error fetching conversation history: {e}")
      return []

  def add_emotion_history(self, message, sadness, frustration, stress, anger, happiness, neutral, response_mode):
    try:
      with self._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
          INSERT INTO emotion_history 
          (timestamp, message, sadness, frustration, stress, anger, happiness, neutral, response_mode) 
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (time.time(), message, sadness, frustration, stress, anger, happiness, neutral, response_mode))
        conn.commit()
    except Exception as e:
      log.error(f"Error adding emotion history: {e}")

  def get_recent_emotion_history(self, limit=10):
    try:
      with self._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
          SELECT timestamp, message, sadness, frustration, stress, anger, happiness, neutral, response_mode 
          FROM emotion_history ORDER BY timestamp DESC LIMIT ?
        ''', (limit,))
        rows = cursor.fetchall()
        return [
          {
            "timestamp": row[0],
            "message": row[1],
            "sadness": row[2],
            "frustration": row[3],
            "stress": row[4],
            "anger": row[5],
            "happiness": row[6],
            "neutral": row[7],
            "response_mode": row[8]
          }
          for row in reversed(rows)
        ]
    except Exception as e:
      log.error(f"Error fetching emotion history: {e}")
      return []

  def clear_memory(self):
    try:
      with self._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM preferences")
        cursor.execute("DELETE FROM reminders")
        cursor.execute("DELETE FROM conversations")
        cursor.execute("DELETE FROM emotion_history")
        cursor.execute("DELETE FROM activity_log")
        cursor.execute("DELETE FROM memory_summaries")
        conn.commit()
      log.info("Cleared all tables in SQLite.")
    except Exception as e:
      log.error(f"Failed to clear SQLite tables: {e}")

  # Activity Log Queries
  def log_activity(self, app_name, window_title, duration, is_idle):
    try:
      with self._get_connection() as conn:
        cursor = conn.cursor()
        
        # Check if the last log is the same app and idle status, and recent (within 15 seconds)
        cursor.execute(
          "SELECT id, timestamp, duration FROM activity_log ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        
        now = time.time()
        if row:
          last_id, last_ts, last_dur = row
          # Check if same application and idle state
          cursor.execute(
            "SELECT app_name, window_title, is_idle FROM activity_log WHERE id = ?",
            (last_id,)
          )
          last_app, last_title, last_idle = cursor.fetchone()
          
          if last_app == app_name and last_idle == is_idle and (now - last_ts) < 15:
            # Update the existing row
            cursor.execute(
              "UPDATE activity_log SET duration = duration + ?, timestamp = ? WHERE id = ?",
              (duration, now, last_id)
            )
            conn.commit()
            return
            
        # Otherwise, insert a new row
        cursor.execute(
          "INSERT INTO activity_log (timestamp, app_name, window_title, duration, is_idle) VALUES (?, ?, ?, ?, ?)",
          (now, app_name, window_title, duration, is_idle)
        )
        conn.commit()
    except Exception as e:
      log.error(f"Error logging activity: {e}")

  def get_active_duration_today(self):
    try:
      import datetime
      today_start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
      with self._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
          "SELECT SUM(duration) FROM activity_log WHERE is_idle = 0 AND timestamp >= ?",
          (today_start,)
        )
        row = cursor.fetchone()
        return row[0] if row[0] else 0.0
    except Exception as e:
      log.error(f"Error getting active duration today: {e}")
      return 0.0

  def get_idle_duration_today(self):
    try:
      import datetime
      today_start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
      with self._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
          "SELECT SUM(duration) FROM activity_log WHERE is_idle = 1 AND timestamp >= ?",
          (today_start,)
        )
        row = cursor.fetchone()
        return row[0] if row[0] else 0.0
    except Exception as e:
      log.error(f"Error getting idle duration today: {e}")
      return 0.0

  def get_app_usage_today(self, app_name):
    try:
      import datetime
      today_start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
      with self._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
          "SELECT SUM(duration) FROM activity_log WHERE is_idle = 0 AND app_name LIKE ? AND timestamp >= ?",
          (f"%{app_name}%", today_start)
        )
        row = cursor.fetchone()
        return row[0] if row[0] else 0.0
    except Exception as e:
      log.error(f"Error getting app usage today for '{app_name}': {e}")
      return 0.0

  def get_top_apps_today(self, limit=5):
    try:
      import datetime
      today_start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
      with self._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
          "SELECT app_name, SUM(duration) FROM activity_log WHERE is_idle = 0 AND timestamp >= ? GROUP BY app_name ORDER BY SUM(duration) DESC LIMIT ?",
          (today_start, limit)
        )
        return [{"app_name": row[0], "duration": row[1]} for row in cursor.fetchall()]
    except Exception as e:
      log.error(f"Error getting top apps today: {e}")
      return []

  # Memory Summaries Queries
  def get_memory_summary(self, category, default=""):
    try:
      with self._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT content FROM memory_summaries WHERE category = ?", (category,))
        row = cursor.fetchone()
        return row[0] if row else default
    except Exception as e:
      log.error(f"Error getting memory summary '{category}': {e}")
      return default

  def set_memory_summary(self, category, content):
    try:
      with self._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
          "INSERT OR REPLACE INTO memory_summaries (category, content, updated_at) VALUES (?, ?, ?)",
          (category, content, time.time())
        )
        conn.commit()
    except Exception as e:
      log.error(f"Error setting memory summary '{category}': {e}")

db_manager = DBManager()
