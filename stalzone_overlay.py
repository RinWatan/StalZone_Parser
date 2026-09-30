"""Compact/expanded window shell. All Tk calls stay on the UI thread."""
import ctypes
from ctypes import wintypes
import json
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk
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
    """Own Windows message thread; Tk receives events through a queue."""
    ID = 0x535A
    WM_HOTKEY = 0x0312

    def __init__(self, root, callback):
        self.root = root
        self.callback = callback
        self.after_id = None
        self.registered = False
        self.events = queue.Queue()
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
        if self.registered:
            self._poll()

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
                    self.events.put(True)
        finally:
            self.user32.UnregisterHotKey(None, self.ID)

    def _poll(self):
        try:
            while True:
                self.events.get_nowait()
                self.callback()
        except queue.Empty:
            pass
        self.after_id = self.root.after(40, self._poll)

    def close(self):
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        if self.registered:
            self.user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)
            self.thread.join(timeout=1)
            self.registered = False


class Overlay:
    def __init__(self, app, settings_path):
        self.app = app
        self.root = app.root
        self.settings_path = settings_path
        self.settings = load_settings(settings_path)
        self.mode = 'compact'
        self.hidden = False
        self.closed = False
        self.interactive = False
        self.game = None
        self.game_bounds = None
        self._sync_id = None
        self._drag = None
        self._last_bounds = None
        self._visible = None
        self.root.title('STALZONE — оверлей')
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.configure(highlightthickness=1, highlightbackground='#82704e')
        self.compact = tk.Frame(self.root, bg='#14120f')
        header = tk.Frame(self.compact, bg='#14120f')
        header.pack(fill='x', padx=12, pady=(10, 6))
        title_label = tk.Label(header, text='STALZONE / MARKET', bg='#14120f', fg='#f0d7a2',
                         font=('Segoe UI', 12, 'bold'))
        title_label.pack(side='left')
        ttk.Button(header, text='×', width=3, command=self.close,
                   style='Dark.TButton').pack(side='right', padx=(4, 0))
        ttk.Button(header, text='Развернуть', command=self.expand,
                   style='Dark.TButton').pack(side='right')
        tk.Label(self.compact, textvariable=app.state, anchor='w', wraplength=420,
                 bg='#14120f', fg='#cbbfa8', font=('Segoe UI', 10)).pack(fill='x', padx=12)
        self.deals = ttk.Treeview(self.compact, columns=('name', 'price', 'gain'),
                                  show='headings', height=5, selectmode='browse')
        for col, title, width in [('name', 'Предмет', 220), ('price', 'Лот', 85), ('gain', 'Прибыль', 90)]:
            self.deals.heading(col, text=title)
            self.deals.column(col, width=width, minwidth=55, anchor='w')
        self.deals.pack(fill='both', expand=True, padx=12, pady=8)
        self.deals.bind('<Double-1>', self._copy)
        self.summary = tk.StringVar(value='Нажмите «Прогон», чтобы найти сделки')
        tk.Label(self.compact, textvariable=self.summary, bg='#14120f', fg='#9ddeaf',
                 anchor='w', font=('Segoe UI', 9)).pack(fill='x', padx=12)
        actions = tk.Frame(self.compact, bg='#14120f')
        actions.pack(fill='x', padx=12, pady=8)
        self.run_button = ttk.Button(actions, text='Прогон', command=self.scan, style='Gold.TButton')
        self.run_button.pack(side='left')
        self.stop_button = ttk.Button(actions, text='Стоп', command=app.stop,
                                      style='Stop.TButton', state='disabled')
        self.stop_button.pack(side='left', padx=6)
        self.hint = tk.StringVar(value='ПРОСМОТР · Ctrl+Shift+Space — управление')
        tk.Label(self.compact, textvariable=self.hint, bg='#14120f', fg='#9c9486',
                 font=('Segoe UI', 9)).pack(pady=(0, 8))
        ttk.Button(actions, text='В игру', command=self.leave_interaction,
                   style='Dark.TButton').pack(side='right')
        ttk.Button(app.full_header, text='×', width=3, command=self.close,
                   style='Dark.TButton').pack(side='right', padx=4)
        ttk.Button(app.full_header, text='В игру · Esc', command=self.leave_interaction,
                   style='Dark.TButton').pack(side='right', padx=4)
        for widget in (header, title_label, app.full_header):
            widget.bind('<ButtonPress-1>', self._drag_start)
            widget.bind('<B1-Motion>', self._drag_move)
            widget.bind('<ButtonRelease-1>', lambda _event: self.save())
        self.root.bind('<Escape>', lambda _event: self.leave_interaction())
        self.native = GameWindow(self.root)
        self.game = self.native.find_game()
        self.game_bounds = self.native.client_bounds(self.game)
        self.hotkey = GlobalHotkey(self.root, self.toggle_interaction)
        if not self.hotkey.registered:
            self.interactive = True
            app.log('Ctrl+Shift+Space занята другой копией. Закройте её и перезапустите HUD.')
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self._show_mode()
        self.native.set_interactive(self.interactive)
        if not self.hotkey.registered:
            self.native.show(True)
            self.native.activate()
        self.sync_game()
        self._schedule_sync()

    def _bounds(self):
        if self.game_bounds:
            return self.game_bounds
        if sys.platform == 'win32':
            user32 = ctypes.windll.user32
            # Work area leaves taskbar and title-bar recovery space on primary screen.
            rect = wintypes.RECT()
            if user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _remember(self):
        if self.hidden or self.root.winfo_width() <= 1:
            return
        left, top, _, _ = self._bounds()
        self.settings[self.mode] = dict(dx=self.root.winfo_x() - left, dy=self.root.winfo_y() - top,
                                       w=self.root.winfo_width(), h=self.root.winfo_height())

    def _show_mode(self):
        if self.root.state() == 'zoomed':
            self.root.state('normal')
        compact = self.mode == 'compact'
        self.app.full_frame.pack_forget()
        self.compact.pack_forget()
        target = self.compact if compact else self.app.full_frame
        target.pack(fill='both', expand=True)
        self._layout()
        self.root.attributes('-topmost', True)

    def _layout(self):
        compact = self.mode == 'compact'
        default = (520, 370) if compact else (1180, 760)
        minimum = (440, 340) if compact else (960, 600)
        bounds = self._bounds()
        saved = self.settings.get(self.mode)
        saved = dict(saved) if isinstance(saved, dict) else {}
        for key, offset, origin in [('x', 'dx', bounds[0]), ('y', 'dy', bounds[1])]:
            relative = saved.get(offset, 32)
            saved[key] = origin + (relative if type(relative) is int else 32)
        x, y, w, h = fit_geometry(saved, bounds, default, minimum)
        self.root.minsize(min(minimum[0], w), min(minimum[1], h))
        self.root.geometry(f'{w}x{h}')
        self.root.update_idletasks()
        self.native.place(x, y, w, h)

    def expand(self):
        self._switch('full')

    def collapse(self):
        self._switch('compact')

    def _switch(self, mode):
        if self.mode == mode:
            return
        self._remember()
        self.mode = mode
        self._show_mode()
        self._write_settings()

    def toggle_visible(self):
        if self.hidden or self.root.state() == 'iconic':
            self.root.deiconify()
            self.root.attributes('-topmost', True)
            self.root.lift()
            self.hidden = False
        else:
            self.save()
            self.root.withdraw()
            self.hidden = True

    def _schedule_sync(self):
        if not self.closed:
            self.sync_game()
            self._sync_id = self.root.after(250, self._schedule_sync)

    def sync_game(self):
        self.game = self.native.find_game()
        self.game_bounds = self.native.client_bounds(self.game)
        foreground = self.native.foreground()
        own = self.native.owns(foreground)
        if self.interactive and not own and foreground != self.game:
            self.interactive = False
            self.native.set_interactive(False)
            self.collapse()
        visible = bool((self.game_bounds and foreground == self.game) or (self.interactive and own))
        if self.game_bounds != self._last_bounds:
            self._layout()
            self._last_bounds = self.game_bounds
        if visible != self._visible:
            self.native.show(visible)
            self._visible = visible
        self.hidden = not visible

    def toggle_interaction(self):
        if self.interactive:
            self.leave_interaction()
            return
        self.game = self.native.find_game()
        self.game_bounds = self.native.client_bounds(self.game)
        self.interactive = True
        self.hidden = False
        self.native.set_interactive(True)
        self._layout()
        self.native.show(True)
        self._visible = True
        self.native.activate()
        self.hint.set('УПРАВЛЕНИЕ · Esc / Ctrl+Shift+Space — в игру')
        if not self.game:
            self.app.log('Ожидание STALZONE. Запустите игру через EXBO; настройки доступны.')

    def leave_interaction(self):
        if not self.interactive:
            return
        self.save()
        self.collapse()
        self.interactive = False
        self.native.set_interactive(False)
        self.hint.set('ПРОСМОТР · Ctrl+Shift+Space — управление')
        self.native.return_to(self.game)
        self.sync_game()

    def _drag_start(self, event):
        if self.interactive:
            self._drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag_move(self, event):
        if self.interactive and self._drag:
            bounds = self._bounds()
            values = dict(x=event.x_root - self._drag[0], y=event.y_root - self._drag[1],
                          w=self.root.winfo_width(), h=self.root.winfo_height())
            x, y, w, h = fit_geometry(values, bounds, (520, 370), (1, 1))
            self.native.place(x, y, w, h)

    def scan(self):
        previous = self.app.section.get()
        try:
            self.app.section.set('Выкуп')
            self.app.start_once()
        finally:
            self.app.section.set(previous)

    def set_busy(self, busy):
        self.run_button.configure(state='disabled' if busy else 'normal')
        self.stop_button.configure(state='normal' if busy else 'disabled')

    def update_deals(self, rows):
        kids = self.deals.get_children()
        if kids:
            self.deals.delete(*kids)
        ranked = sorted(rows, key=lambda row: row.get('gain', 0), reverse=True)
        for row in ranked[:5]:
            self.deals.insert('', 'end', values=(row['name'], self.app_money(row.get('buyout', 0)),
                                                '+' + self.app_money(row.get('gain', 0))))
        total = sum(row.get('gain', 0) for row in rows)
        self.summary.set(f'Сделок: {len(rows)}  ·  Расчётный плюс: {self.app_money(total)}'
                         if rows else 'Подходящих сделок пока нет')

    @staticmethod
    def app_money(value):
        from stalzone_agent import rub
        return rub(value)

    def _copy(self, _event):
        chosen = self.deals.selection()
        if chosen:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.deals.item(chosen[0], 'values')[0])

    def _write_settings(self):
        try:
            temporary = self.settings_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.settings), encoding='utf-8')
            temporary.replace(self.settings_path)
        except OSError:
            self.app.log('Не удалось сохранить положение оверлея')

    def save(self):
        self._remember()
        self._write_settings()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.save()
        self.hotkey.close()
        if self._sync_id is not None:
            self.root.after_cancel(self._sync_id)
        if getattr(self.app, '_pump_id', None):
            self.root.after_cancel(self.app._pump_id)
        from stalzone_agent import HALT
        HALT.set()
        self.root.destroy()
