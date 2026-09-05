import ctypes
from ctypes import wintypes
import time
import os

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

si = STARTUPINFO()
si.cb = ctypes.sizeof(STARTUPINFO)
si.lpDesktop = 'WinSta0\\Default'
pi = PROCESS_INFORMATION()

kernel32 = ctypes.windll.kernel32
cmd = r'cmd.exe /c node_modules\electron\dist\electron.exe . > electron_out.txt 2>&1'
success = kernel32.CreateProcessW(None, cmd, None, None, False, 0, None, r'c:\Users\Sachin\boopi\assistant', ctypes.byref(si), ctypes.byref(pi))
print('Success:', bool(success), 'PID:', pi.dwProcessId)
time.sleep(3)
exit_code = wintypes.DWORD()
kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(exit_code))
print('Exit code:', exit_code.value)
