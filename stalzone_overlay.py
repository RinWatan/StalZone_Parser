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
        self.registered = bool(self.user32.RegisterHotKey(None, self.ID, 0x4006, 0x20))
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


class HudController:
    """Window state is owned by the controller thread; bridge only queues commands."""
    def __init__(self, window, settings_path, native=None):
        self.window = window
        self.settings_path = settings_path
        self.settings = load_settings(settings_path)
        self.native = native
        self.mode = 'compact'
        self.interactive = False
        self.game = None
        self.bounds = None
        self.visible = None
        self.hotkey = None
        self.commands = queue.Queue()
        self.stopped = threading.Event()
        self.lock = threading.Lock()
        self._state = {}
        self._thread = None
        self._layout_key = None
        self._last_find = 0
        self._initial = True
        self._applied_interactive = None

    def command(self, action):
        if action not in ('toggle', 'full', 'compact', 'passive', 'close'):
            return {'ok': False, 'error': 'Неизвестная команда'}
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
        # Do not leave a hidden window that cannot be reopened without its hotkey.
        if not self.hotkey.registered:
            self.native.notify('Ctrl+Shift+Space занята другой программой или копией оверлея. '
                               'Закройте предыдущую копию или освободите клавишу и запустите снова.')
            self.stopped.set()
            self.hotkey.close()
            self.window.destroy()
            return
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

    def remember(self):
        if self._layout_key is None:
            return
        rect = self.native.window_bounds()
        if not rect:
            return
        x, y, width, height = rect
        left, top, _, _ = self.bounds or self.native.work_area()
        self.settings[self.mode] = {'dx': x-left, 'dy': y-top, 'w': width, 'h': height}
        try:
            self.settings_path.write_text(json.dumps(self.settings, ensure_ascii=False), encoding='utf-8')
        except OSError:
            pass

    def _change(self, mode, interactive):
        if self.mode != mode:
            self.remember()
        self.mode, self.interactive = mode, interactive

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
            if not self.bounds:
                self.interactive = True
                activate = True
            self._initial = False
        while True:
            try:
                action = self.commands.get_nowait()
            except queue.Empty:
                break
            if action == 'close':
                self.remember()
                self.stopped.set()
                self.window.destroy()
                return
            if action == 'toggle':
                action = 'passive' if self.interactive else self.mode
            if action == 'passive':
                activate = False
                self._change('compact', False)
                if self.native.owns(self.native.foreground()):
                    self.native.return_to(self.game)
            else:
                self._change(action, True)
                activate = True
        fg = self.native.foreground()
        own = self.native.owns(fg)
        in_game = bool(self.bounds and fg == self.game)
        if self.interactive and not (own or in_game or activate):
            self._change('compact', False)
        visible = bool(in_game or (self.interactive and (own or activate)))
        bounds = self.bounds or self.native.work_area()
        key = (self.mode, bounds)
        if key != self._layout_key:
            saved = dict(self.settings.get(self.mode) or {})
            for source, target, start in [('dx','x',bounds[0]), ('dy','y',bounds[1])]:
                if type(saved.get(source)) is int:
                    saved[target] = start + saved[source]
            default = (520, 380) if self.mode == 'compact' else (1280, 820)
            minimum = (440, 340) if self.mode == 'compact' else (960, 640)
            self.native.place(*fit_geometry(saved, bounds, default, minimum))
            self._layout_key = key
        if self._applied_interactive != self.interactive:
            self.native.set_interactive(self.interactive)
            self._applied_interactive = self.interactive
        if visible != self.visible:
            self.native.show(visible)
            self.visible = visible
        if activate:
            self.native.activate()
        with self.lock:
            self._state = {'mode': self.mode, 'interactive': self.interactive,
                           'game': bool(self.bounds), 'visible': visible,
                           'hotkey': self.hotkey.registered if self.hotkey else True}
