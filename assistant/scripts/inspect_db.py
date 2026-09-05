import sqlite3

conn = sqlite3.connect('bupi_telemetry.db')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print("Tables:", tables)
for t in tables:
    tname = t[0]
    cursor.execute(f"SELECT count(*) FROM {tname}")
    cnt = cursor.fetchone()[0]
    print(f"\n--- Table '{tname}' ({cnt} rows) ---")
    cursor.execute(f"SELECT * FROM {tname} ORDER BY rowid DESC LIMIT 5")
    rows = cursor.fetchall()
    for r in rows:
        print(r)
