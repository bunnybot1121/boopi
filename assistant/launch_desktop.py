import ctypes
from ctypes import wintypes
import os
import sys
import time
import psutil

class STARTUPINFO(ctypes.Structure):
    _fields_ = [
        ('cb', wintypes.DWORD),
        ('lpReserved', wintypes.LPWSTR),
        ('lpDesktop', wintypes.LPWSTR),
        ('lpTitle', wintypes.LPWSTR),
        ('dwX', wintypes.DWORD),
        ('dwY', wintypes.DWORD),
        ('dwXSize', wintypes.DWORD),
        ('dwYSize', wintypes.DWORD),
        ('dwXCountChars', wintypes.DWORD),
        ('dwYCountChars', wintypes.DWORD),
        ('dwFillAttribute', wintypes.DWORD),
        ('dwFlags', wintypes.DWORD),
        ('wShowWindow', wintypes.WORD),
        ('cbReserved2', wintypes.WORD),
        ('lpReserved2', ctypes.c_char_p),
        ('hStdInput', wintypes.HANDLE),
        ('hStdOutput', wintypes.HANDLE),
        ('hStdError', wintypes.HANDLE),
    ]

class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('hProcess', wintypes.HANDLE),
        ('hThread', wintypes.HANDLE),
        ('dwProcessId', wintypes.DWORD),
        ('dwThreadId', wintypes.DWORD),
    ]

def launch():
    base_dir = os.path.abspath(os.path.dirname(__file__))
    electron_exe = os.path.join(base_dir, "node_modules", "electron", "dist", "electron.exe")
    
    if not os.path.exists(electron_exe):
        print(f"[ERROR] Electron binary not found: {electron_exe}")
        sys.exit(1)

    cmd = f'"{electron_exe}" .'

    si = STARTUPINFO()
    si.cb = ctypes.sizeof(STARTUPINFO)
    si.lpDesktop = 'WinSta0\\Default'
    pi = PROCESS_INFORMATION()

    kernel32 = ctypes.windll.kernel32
    print(f"[INFO] Spawning Bupi on interactive desktop (WinSta0\\Default)...")
    success = kernel32.CreateProcessW(
        None,
        cmd,
        None,
        None,
        False,
        0,
        None,
        base_dir,
        ctypes.byref(si),
        ctypes.byref(pi)
    )

    if success:
        print(f"[SUCCESS] Bupi started on user desktop with PID: {pi.dwProcessId}")
        sys.stdout.flush()
        kernel32.CloseHandle(pi.hProcess)
        kernel32.CloseHandle(pi.hThread)

        # Monitor Electron processes and stay alive as long as Bupi is running
        time.sleep(3)
        while True:
            electron_running = False
            for p in psutil.process_iter(['name', 'pid']):
                try:
                    if 'electron' in (p.info['name'] or '').lower():
                        electron_running = True
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            if not electron_running:
                print("[INFO] All Electron processes exited.")
                break
            time.sleep(2)
    else:
        err = kernel32.GetLastError()
        print(f"[ERROR] CreateProcessW failed with Win32 error code: {err}")
        sys.exit(1)

if __name__ == '__main__':
    launch()
