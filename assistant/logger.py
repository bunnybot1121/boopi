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
            try:
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.readlines()
                # Keep last 1000 lines
                with open(log_file, "w", encoding="utf-8", errors="ignore") as f:
                    f.writelines(content[-1000:])
            except Exception:
                pass
                
    # Write faulthandler output to a FILE on disk appending
    try:
        _fault_log = open(crash_log_path, "a", encoding="utf-8", errors="ignore")
        faulthandler.enable(file=_fault_log, all_threads=True)
    except Exception:
        pass

_debug_log = None

def crash_log(msg):
    global _debug_log
    if not _debug_log:
        try:
            _debug_log = open(debug_log_path, "a", encoding="utf-8", errors="ignore")
        except Exception:
            return
    try:
        _debug_log.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
        _debug_log.flush()
        os.fsync(_debug_log.fileno())
    except Exception:
        pass

init_logs()

import logging
def setup_logger():
    log_file = os.path.join(os.path.dirname(__file__), 'bupi.log')
    logger = logging.getLogger('Bupi')
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    if sys.stderr and sys.stderr.isatty():
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
    return logger

log = setup_logger()
log.info("Logger initialized successfully.")

import threading
import_lock = threading.Lock()
