import sqlite3

conn = sqlite3.connect('bupi_telemetry.db')
cursor = conn.cursor()
cursor.execute("SELECT DISTINCT sensor_id FROM telemetry")
print("Distinct sensor_ids in telemetry:", cursor.fetchall())

cursor.execute("SELECT id, mission_name, goal, created_at, started_at FROM missions")
print("Missions in db:", cursor.fetchall())
