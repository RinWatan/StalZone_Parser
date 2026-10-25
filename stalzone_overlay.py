"""Single-webview HUD controller. Win32 operations run on one worker thread."""
import ctypes
from ctypes import wintypes
import json
import queue
import sys
import threading
from game_window import GameWindow


def load_settings(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def fit_geometry(saved, bounds, default, minimum):
    left, top, screen_w, screen_h = bounds
    saved = saved if isinstance(saved, dict) else {}
    def number(key, fallback):
        value = saved.get(key)
        return value if type(value) is int else fallback
    w = min(screen_w, max(minimum[0], number('w', default[0])))
    h = min(screen_h, max(minimum[1], number('h', default[1])))
    x = max(left, min(number('x', left + 40), left + screen_w - w))
    y = max(top, min(number('y', top + 40), top + screen_h - h))
    return x, y, w, h


class GlobalHotkey:
    """Own Windows message thread; callbacks must enqueue controller commands."""
    ID = 0x535A
    WM_HOTKEY = 0x0312

    def __init__(self, callback):
        self.callback = callback
        self.registered = False
        self.thread_id = None
        self.ready = threading.Event()
        if sys.platform != 'win32':
            return
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        self.user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        self.user32.RegisterHotKey.restype = wintypes.BOOL
        self.user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.UnregisterHotKey.restype = wintypes.BOOL
        self.user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                           wintypes.UINT, wintypes.UINT, wintypes.UINT]
        self.user32.PeekMessageW.restype = wintypes.BOOL
        self.user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                          wintypes.UINT, wintypes.UINT]
        self.user32.GetMessageW.restype = ctypes.c_int
        self.user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                                  wintypes.WPARAM, wintypes.LPARAM]
        self.user32.PostThreadMessageW.restype = wintypes.BOOL
        self.thread = threading.Thread(target=self._listen, daemon=True)
        self.thread.start()
        self.ready.wait()

    def _listen(self):
        self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        self.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        # F10 одна кнопка. F11 в игре включает полный экран, F1 прячет интерфейс, F12 снимок Steam.
        self.registered = bool(self.user32.RegisterHotKey(None, self.ID, 0x4000, 0x79))
        self.ready.set()
        if not self.registered:
            return
        try:
            while self.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == self.WM_HOTKEY and msg.wParam == self.ID:
                    self.callback()
        finally:
            self.user32.UnregisterHotKey(None, self.ID)

    def close(self):
        if self.registered:
            self.user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)
            self.thread.join(timeout=1)
            self.registered = False


class TrayIcon:
    """Значок в трее Windows. На других системах ничего не делает."""

    def __init__(self, on_open, on_quit):
        self.on_open = on_open
        self.on_quit = on_quit
        self.hwnd = None
        self._proc = None
        self._user32 = None
        self.ready = threading.Event()
        if sys.platform != 'win32':
            self.ready.set()
            return
        self.thread = threading.Thread(target=self._run, name='STALZONE-tray', daemon=True)
        self.thread.start()
        self.ready.wait(2)

    def close(self):
        if not self.hwnd or not self._user32:
            return
        self._user32.PostMessageW(self.hwnd, 0x0010, 0, 0)

    def _run(self):
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        shell32 = ctypes.WinDLL('shell32', use_last_error=True)
        self._user32 = user32
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ('style', wintypes.UINT), ('lpfnWndProc', WNDPROC),
                ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
                ('hInstance', wintypes.HINSTANCE), ('hIcon', wintypes.HICON),
                ('hCursor', wintypes.HANDLE), ('hbrBackground', wintypes.HBRUSH),
                ('lpszMenuName', wintypes.LPCWSTR), ('lpszClassName', wintypes.LPCWSTR),
            ]

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [
                ('cbSize', wintypes.DWORD), ('hWnd', wintypes.HWND), ('uID', wintypes.UINT),
                ('uFlags', wintypes.UINT), ('uCallbackMessage', wintypes.UINT),
                ('hIcon', wintypes.HICON), ('szTip', wintypes.WCHAR * 128),
                ('dwState', wintypes.DWORD), ('dwStateMask', wintypes.DWORD),
                ('szInfo', wintypes.WCHAR * 256), ('uTimeout', wintypes.UINT),
                ('szInfoTitle', wintypes.WCHAR * 64), ('dwInfoFlags', wintypes.DWORD),
                ('guidItem', ctypes.c_byte * 16), ('hBalloonIcon', wintypes.HICON),
            ]

        tray_msg = 0x0400 + 20
        owner = self

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == tray_msg and lparam in (0x0202, 0x0203):
                owner.on_open()
                return 0
            if msg == tray_msg and lparam == 0x0205:
                menu = user32.CreatePopupMenu()
                user32.AppendMenuW(menu, 0, 1, 'Открыть')
                user32.AppendMenuW(menu, 0, 2, 'Выход')
                point = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(point))
                user32.SetForegroundWindow(hwnd)
                user32.TrackPopupMenu(menu, 0, point.x, point.y, 0, hwnd, None)
                user32.PostMessageW(hwnd, 0, 0, 0)
                user32.DestroyMenu(menu)
                return 0
            if msg == 0x0111:
                if wparam == 1:
                    owner.on_open()
                elif wparam == 2:
                    owner.on_quit()
                return 0
            if msg == 0x0010:
                nid = NOTIFYICONDATAW()
                nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
                nid.hWnd = hwnd
                nid.uID = 1
                shell32.Shell_NotifyIconW(2, ctypes.byref(nid))
                user32.DestroyWindow(hwnd)
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._proc = WNDPROC(wndproc)
        instance = ctypes.windll.kernel32.GetModuleHandleW(None)
        klass = WNDCLASSW()
        klass.lpfnWndProc = self._proc
        klass.hInstance = instance
        klass.lpszClassName = 'STALZONETray'
        user32.RegisterClassW(ctypes.byref(klass))
        self.hwnd = user32.CreateWindowExW(0, 'STALZONETray', 'STALZONE', 0, 0, 0, 0, 0, wintypes.HWND(-3), None, instance, None)
        icon = user32.LoadIconW(None, wintypes.LPCWSTR(32512))
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = 1 | 2 | 4
        nid.uCallbackMessage = tray_msg
        nid.hIcon = icon
        nid.szTip = 'STALZONE'
        shell32.Shell_NotifyIconW(0, ctypes.byref(nid))
        self.ready.set()
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))


class HudController:
    """Window state is owned by the controller thread; bridge only queues commands."""
    def __init__(self, window, settings_path, native=None):
        self.window = window
        self.settings_path = settings_path
        self.settings = load_settings(settings_path)
        self.native = native
        self.mode = 'full'
        self.resume_mode = 'full'
        self.interactive = False
        self.game = None
        self.bounds = None
        self.visible = None
        self.hotkey = None
        self.tray = None
        self.commands = queue.Queue()
        self.stopped = threading.Event()
        self.lock = threading.Lock()
        self._state = {}
        self._thread = None
        self._layout_key = None
        self._last_find = 0
        self._initial = True
        self._applied_interactive = None
        self._applied_top = None
        self.session = 'desk'
        self.parked = False
        self.quit_requested = False

    def command(self, action):
        if action not in ('toggle', 'full', 'compact', 'passive', 'close', 'open', 'quit'):
            return {'ok': False, 'error': 'Неизвестная команда'}
        if action == 'compact':
            return {'ok': True}
        if action == 'quit':
            self.quit_requested = True
        self.commands.put(action)
        return {'ok': True}

    def snapshot(self):
        with self.lock:
            return dict(self._state)

    def start(self):
        if self._thread:
            return
        if self.native is None:
            handle = self.window.native.Handle.ToInt64()
            self.native = GameWindow(lambda: handle)
        self.hotkey = GlobalHotkey(lambda: self.command('toggle'))
        self.tray = TrayIcon(lambda: self.command('open'), lambda: self.command('quit'))
        if not self.hotkey.registered:
            self.native.notify('F10 занята другой программой. Окно откроется как обычно, '
                               'оверлей в игре с этой кнопки не вызовется.')
        self._thread = threading.Thread(target=self._run, name='STALZONE-HUD', daemon=True)
        self._thread.start()

    def stop(self):
        self.stopped.set()

    def closing(self):
        # The closing event still has a valid HWND; closed may be too late.
        self.stop()
        self.remember()

    def _run(self):
        try:
            while not self.stopped.is_set():
                self.tick()
                self.stopped.wait(0.15)
        finally:
            self.remember()
            if self.hotkey:
                self.hotkey.close()
            if self.tray:
                self.tray.close()

    def remember(self):
        if self._layout_key is None:
            return
        rect = self.native.window_bounds()
        if not rect:
            return
        x, y, width, height = rect
        frame = self.bounds if self.session == 'overlay' and self.bounds else self.native.work_area()
        left, top, _, _ = frame
        self.settings[self.mode] = {'dx': x-left, 'dy': y-top, 'w': width, 'h': height}
        try:
            self.settings_path.write_text(json.dumps(self.settings, ensure_ascii=False), encoding='utf-8')
        except OSError:
            pass

    def _change(self, mode, interactive):
        if self.mode != 'full':
            self.remember()
        self.mode, self.interactive = 'full', interactive

    def tick(self):
        import time
        now = time.monotonic()
        # Refresh discovery occasionally; foreground/bounds are checked every tick.
        if not self._thread or now - self._last_find > 1:
            self.game = self.native.find_game()
            self._last_find = now
        old_bounds = self.bounds
        new_bounds = self.native.client_bounds(self.game)
        # Remember a user drag relative to the previous game position.
        if old_bounds != new_bounds:
            self.remember()
        self.bounds = new_bounds
        activate = False
        if self._initial:
            self.interactive = True
            activate = True
            self._initial = False
        while True:
            try:
                action = self.commands.get_nowait()
            except queue.Empty:
                break
            if action == 'quit':
                self.remember()
                self.stopped.set()
                if self.tray:
                    self.tray.close()
                self.window.destroy()
                return
            if action == 'close':
                self.parked = True
                self.session = 'desk'
                self.visible = False
                self.native.show(False)
                continue
            if action == 'open':
                self.parked = False
                self.session = 'desk'
                activate = True
                continue
            if action == 'toggle':
                watching = bool(self.bounds and self.native.foreground() == self.game)
                if self.session != 'overlay':
                    self.parked = False
                    if watching:
                        self.session = 'overlay'
                        self._change('full', True)
                    else:
                        self.session = 'desk'
                    activate = True
                    continue
                action = 'passive' if self.interactive and self.visible else 'full'
            if action == 'passive':
                activate = False
                self._change('full', False)
                if self.native.owns(self.native.foreground()):
                    self.native.return_to(self.game)
            else:
                self.resume_mode = 'full'
                self._change('full', True)
                activate = True
        fg = self.native.foreground()
        own = self.native.owns(fg)
        in_game = bool(self.bounds and fg == self.game)
        if self.session == 'overlay' and not in_game and not own and not activate:
            self.session = 'desk'
            self.parked = True
        if self.session == 'desk':
            visible = not self.parked
        else:
            visible = bool(in_game or (self.interactive and (own or activate)))
        frame = self.bounds if self.session == 'overlay' and self.bounds else self.native.work_area()
        top = self.session == 'overlay'
        key = (self.session, self.mode, frame)
        if key != self._layout_key:
            saved = dict(self.settings.get(self.mode) or {})
            for source, target, start in [('dx','x',frame[0]), ('dy','y',frame[1])]:
                if type(saved.get(source)) is int:
                    saved[target] = start + saved[source]
            default = (1280, 820)
            minimum = (960, 640)
            self.native.place(*fit_geometry(saved, frame, default, minimum))
            self._layout_key = key
        if self._applied_interactive != self.interactive:
            self.native.set_interactive(self.interactive)
            self._applied_interactive = self.interactive
        if self._applied_top != top and hasattr(self.native, 'set_top'):
            self.native.set_top(top)
            self._applied_top = top
        if visible != self.visible:
            self.native.show(visible)
            self.visible = visible
        if activate:
            self.native.activate()
        with self.lock:
            self._state = {'mode': self.mode, 'interactive': self.interactive,
                           'game': bool(self.bounds), 'visible': visible,
                           'hotkey': self.hotkey.registered if self.hotkey else True}
