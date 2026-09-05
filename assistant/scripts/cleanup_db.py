import sqlite3
import os

db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bupi_telemetry.db")
print("Connecting to:", db_path)

conn = sqlite3.connect(db_path)
c = conn.cursor()

# 1. Clean out mock/simulated missions
c.execute("DELETE FROM missions WHERE id = 1 OR goal LIKE '%test%' OR goal LIKE '%Find the human in the room and confirm presence%'")
print(f"Purged mock missions. Remaining missions: {c.execute('SELECT COUNT(*) FROM missions').fetchone()[0]}")

# 2. Clean out all mock/simulated sensor records from telemetry
c.execute("DELETE FROM telemetry WHERE sensor_id NOT IN ('mq2', 'distance')")
print(f"Purged dummy sensor rows. Remaining telemetry rows: {c.execute('SELECT COUNT(*) FROM telemetry').fetchone()[0]}")

conn.commit()
conn.close()
print("Database cleanup completed successfully!")
