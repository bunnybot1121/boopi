import ctypes
from ctypes import wintypes
import psutil

user32 = ctypes.windll.user32
hdesk = user32.OpenDesktopW('Default', 0, False, 0x01FF)
if hdesk:
    user32.SetThreadDesktop(hdesk)

pids = [p.info['pid'] for p in psutil.process_iter(['name', 'pid']) if 'electron' in (p.info['name'] or '').lower()]
print('Electron PIDs:', pids)

found_visible = []

def enum_cb(hwnd, lparam):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value in pids:
        visible = user32.IsWindowVisible(hwnd)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if visible and w > 0 and h > 0:
            info = f'HWND: {hwnd} | PID: {pid.value} | Rect: ({rect.left}, {rect.top}, {w}x{h}) | Title: "{buf.value}"'
            found_visible.append(info)
    return True

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumDesktopWindows(hdesk, WNDENUMPROC(enum_cb), 0)

print(f"Total visible electron windows found: {len(found_visible)}")
for item in found_visible:
    print("  ->", item)
