"""Win32 window-only HUD integration; never touches game memory or files."""
import ctypes
from ctypes import wintypes as w
import os


def is_game_path(path):
    path = path.replace('/', '\\').lower()
    return ('\\runtime\\' in path and
            path.rsplit('\\', 1)[-1] in ('stalzone.exe', 'stalcraft.exe'))


def overlay_style(style, interactive):
    # Layered + tool window. Remove app-window to avoid a separate taskbar item.
    style = (style | 0x80000 | 0x80) & ~0x40000
    return style & ~(0x20 | 0x08000000) if interactive else style | 0x20 | 0x08000000


class GameWindow:
    def __init__(self, root):
        self.root = root
        self.u = ctypes.WinDLL('user32', use_last_error=True)
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        self.enum_type = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        signatures = {
            'EnumWindows': ([self.enum_type, w.LPARAM], w.BOOL),
            'IsWindowVisible': ([w.HWND], w.BOOL),
            'IsIconic': ([w.HWND], w.BOOL),
            'GetForegroundWindow': ([], w.HWND),
            'GetAncestor': ([w.HWND, w.UINT], w.HWND),
            'GetWindowThreadProcessId': ([w.HWND, ctypes.POINTER(w.DWORD)], w.DWORD),
            'GetClientRect': ([w.HWND, ctypes.POINTER(w.RECT)], w.BOOL),
            'ClientToScreen': ([w.HWND, ctypes.POINTER(w.POINT)], w.BOOL),
            'GetWindowLongPtrW': ([w.HWND, ctypes.c_int], ctypes.c_ssize_t),
            'SetWindowLongPtrW': ([w.HWND, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_ssize_t),
            'SetLayeredWindowAttributes': ([w.HWND, w.DWORD, w.BYTE, w.DWORD], w.BOOL),
            'ShowWindow': ([w.HWND, ctypes.c_int], w.BOOL),
            'SetForegroundWindow': ([w.HWND], w.BOOL),
            'SetWindowPos': ([w.HWND, w.HWND, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, w.UINT], w.BOOL),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.u, name)
            fn.argtypes, fn.restype = args, result
        self.k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.k.OpenProcess.restype = w.HANDLE
        self.k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
        self.k.QueryFullProcessImageNameW.restype = w.BOOL
        self.k.CloseHandle.argtypes = [w.HANDLE]
        self.k.CloseHandle.restype = w.BOOL
        self.root.update_idletasks()

    @property
    def hwnd(self):
        return self.u.GetAncestor(self.root.winfo_id(), 2)

    def find_game(self):
        found = []
        @self.enum_type
        def visit(hwnd, _):
            if not self.u.IsWindowVisible(hwnd) or self.u.IsIconic(hwnd):
                return True
            pid = w.DWORD()
            self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == os.getpid():
                return True
            handle = self.k.OpenProcess(0x1000, False, pid.value)
            if not handle:
                return True
            try:
                buffer = ctypes.create_unicode_buffer(32768)
                size = w.DWORD(len(buffer))
                if self.k.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                    if is_game_path(buffer.value) and self.client_bounds(hwnd):
                        found.append(hwnd)
            finally:
                self.k.CloseHandle(handle)
            return True
        self.u.EnumWindows(visit, 0)
        foreground = self.foreground()
        return foreground if foreground in found else (found[0] if found else None)

    def client_bounds(self, hwnd):
        if not hwnd or self.u.IsIconic(hwnd):
            return None
        rect, point = w.RECT(), w.POINT()
        if not self.u.GetClientRect(hwnd, ctypes.byref(rect)):
            return None
        if not self.u.ClientToScreen(hwnd, ctypes.byref(point)):
            return None
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width < 200 or height < 200:
            return None
        return point.x, point.y, width, height

    def foreground(self):
        return self.u.GetForegroundWindow()

    def owns(self, hwnd):
        return bool(hwnd and self.u.GetAncestor(hwnd, 3) == self.u.GetAncestor(self.hwnd, 3))

    def set_interactive(self, value):
        hwnd = self.hwnd
        old = self.u.GetWindowLongPtrW(hwnd, -20)
        self.u.SetWindowLongPtrW(hwnd, -20, overlay_style(old, value))
        self.u.SetLayeredWindowAttributes(hwnd, 0, 248 if value else 224, 2)
        self.u.SetWindowPos(hwnd, w.HWND(-1), 0, 0, 0, 0, 0x0033)

    def show(self, visible):
        # SW_SHOWNOACTIVATE avoids stealing the game's keyboard focus.
        self.u.ShowWindow(self.hwnd, 4 if visible else 0)

    def place(self, x, y, width, height):
        self.u.SetWindowPos(self.hwnd, w.HWND(-1), x, y, width, height, 0x0010)

    def activate(self):
        self.u.SetForegroundWindow(self.hwnd)
        self.root.focus_force()

    def return_to(self, hwnd):
        if hwnd:
            self.u.SetForegroundWindow(hwnd)
