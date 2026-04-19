import sys
import os
import faulthandler
import datetime

# Implement log rotation/memory cleanup so logs don't get too large
crash_log_path = os.path.join(os.path.dirname(__file__), "crash_log.txt")
debug_log_path = os.path.join(os.path.dirname(__file__), "debug_log.txt")

def init_logs():
    # Truncate if larger than 1MB
    for log_file in [crash_log_path, debug_log_path]:
        if os.path.exists(log_file) and os.path.getsize(log_file) > 1024 * 1024:
            with open(log_file, "r") as f:
                content = f.readlines()
            # Keep last 1000 lines
            with open(log_file, "w") as f:
                f.writelines(content[-1000:])
                
    # Write faulthandler output to a FILE on disk appending
    _fault_log = open(crash_log_path, "a")
    faulthandler.enable(file=_fault_log, all_threads=True)

_debug_log = None

def crash_log(msg):
    global _debug_log
    if not _debug_log:
        _debug_log = open(debug_log_path, "a")
    _debug_log.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    _debug_log.flush()
    os.fsync(_debug_log.fileno())

init_logs()
