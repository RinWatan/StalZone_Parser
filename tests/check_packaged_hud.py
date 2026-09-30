import ctypes
from ctypes import wintypes as w
import json
import subprocess
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from game_window import GameWindow

root = Path(__file__).resolve().parents[1]
(root / 'build').mkdir(exist_ok=True)
exe = (root / 'dist/STALZONE-map-overlay.exe').resolve()
native = GameWindow(lambda: hwnd[0])
hwnd = [0]
report = {}
process = subprocess.Popen([str(exe)], creationflags=subprocess.CREATE_NO_WINDOW)

def locate():
    found = []
    @native.enum_type
    def visit(handle, _):
        pid = w.DWORD()
        native.u.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        process_handle = native.k.OpenProcess(0x1000, False, pid.value)
        if not process_handle: return True
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            size = w.DWORD(len(buffer))
            if native.k.QueryFullProcessImageNameW(process_handle,0,buffer,ctypes.byref(size)):
                if Path(buffer.value) == exe:
                    rect = w.RECT()
                    if native.u.GetWindowRect(handle,ctypes.byref(rect)) and rect.right-rect.left >= 400:
                        found.append(handle)
        finally: native.k.CloseHandle(process_handle)
        return True
    native.u.EnumWindows(visit,0)
    return found[0] if found else 0

u = native.u
u.RegisterHotKey.argtypes = [w.HWND,ctypes.c_int,w.UINT,w.UINT]
u.RegisterHotKey.restype = w.BOOL
u.UnregisterHotKey.argtypes = [w.HWND,ctypes.c_int]
u.UnregisterHotKey.restype = w.BOOL
u.PostMessageW.argtypes = [w.HWND,w.UINT,w.WPARAM,w.LPARAM]
u.PostMessageW.restype = w.BOOL
u.keybd_event.argtypes = [w.BYTE,w.BYTE,w.DWORD,ctypes.c_size_t]

def free_hotkey():
    value = bool(u.RegisterHotKey(None,0x535B,0x4006,0x20))
    if value: u.UnregisterHotKey(None,0x535B)
    return value

def hotkey():
    for key in [0x11,0x10,0x20]: u.keybd_event(key,0,0,0)
    for key in [0x20,0x10,0x11]: u.keybd_event(key,0,2,0)

try:
    deadline = time.monotonic()+30
    while time.monotonic() < deadline:
        hwnd[0] = locate()
        if hwnd[0] and not free_hotkey(): break
        if process.poll() is not None: raise AssertionError('EXE exited before HUD ready')
        time.sleep(.25)
    assert hwnd[0], 'No packaged native window'
    assert not free_hotkey(), 'Global hotkey not registered'
    report['size'] = exe.stat().st_size
    report['game_detected'] = bool(native.find_game())
    report['bounds'] = native.window_bounds()
    initial = u.GetWindowLongPtrW(hwnd[0],-20)
    # Ensure the toggle opens interaction from the initial passive game state.
    if not initial & 0x20:
        hotkey()
        time.sleep(.5)
    hotkey()
    time.sleep(.8)
    active = u.GetWindowLongPtrW(hwnd[0],-20)
    assert not active & 0x08000020, 'Toggle did not enable interaction'
    hotkey()
    time.sleep(.8)
    passive = u.GetWindowLongPtrW(hwnd[0],-20)
    assert passive & 0x08000020 == 0x08000020, 'Toggle did not return click-through'
    report['toggle'] = True
    u.PostMessageW(hwnd[0],0x0010,0,0)
    process.wait(15)
    assert process.returncode == 0, process.returncode
    deadline = time.monotonic()+3
    while not free_hotkey() and time.monotonic()<deadline: time.sleep(.1)
    assert free_hotkey(), 'Hotkey leaked after close'
    report['exit'] = 0
    report['ok'] = True
finally:
    if process.poll() is None:
        if hwnd[0]: u.PostMessageW(hwnd[0],0x0010,0,0)
        try: process.wait(5)
        except subprocess.TimeoutExpired: process.terminate()
    (root / 'build/packaged_hud_check.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
