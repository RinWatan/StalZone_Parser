import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from stalzone_overlay import HudController, fit_geometry, load_settings

class Native:
    def __init__(self):
        self.game = 123
        self.fg = 123
        self.bounds = (0, 0, 1920, 1080)
        self.rect = (40, 40, 520, 380)
        self.visible = False
        self.interactive = False
    def find_game(self): return self.game
    def client_bounds(self, hwnd): return self.bounds if hwnd else None
    def work_area(self): return (0, 0, 1920, 1080)
    def window_bounds(self): return self.rect
    def foreground(self): return self.fg
    def owns(self, hwnd): return hwnd == 456
    def set_interactive(self, value): self.interactive = value
    def show(self, value): self.visible = value
    def place(self, *rect): self.rect = rect
    def activate(self): self.fg = 456
    def set_top(self, value): self.top = value
    def return_to(self, hwnd): self.fg = hwnd
    def notify(self, text): self.message = text

class Window:
    def __init__(self): self.closed = False
    def destroy(self): self.closed = True

class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.native = Native()
        self.window = Window()
        self.path = Path(self.temp.name) / 'settings.json'
        self.hud = HudController(self.window, self.path, native=self.native)
        self.hud.tick()
    def tearDown(self): self.temp.cleanup()
    def action(self, action):
        self.hud.command(action)
        self.hud.tick()
    def test_starts_full_over_game(self):
        self.assertEqual(self.hud.snapshot()['mode'], 'full')
        self.assertTrue(self.native.interactive)
        self.assertTrue(self.native.visible)
    def test_hotkey_gives_clicks_back_without_shrinking(self):
        self.native.fg = 123
        self.action('toggle')
        self.assertEqual(self.hud.session, 'overlay')
        self.assertTrue(self.native.interactive)
        self.native.fg = 123
        self.action('toggle')
        self.assertEqual(self.hud.snapshot()['mode'], 'full')
        self.assertFalse(self.native.interactive)
        self.assertEqual(self.native.fg, 123)
        self.native.fg = 123
        self.action('toggle')
        self.assertTrue(self.native.interactive)
    def test_collapse_command_stays_full(self):
        self.action('compact')
        self.assertEqual(self.hud.snapshot()['mode'], 'full')
        self.assertTrue(self.native.interactive)
    def test_alt_tab_does_not_forget_full_mode(self):
        self.action('full')
        self.native.fg = 789
        self.hud.tick()
        self.native.fg = 123
        self.native.fg = 123
        self.action('toggle')
        self.assertEqual(self.hud.snapshot()['mode'], 'full')
    def test_last_queued_command_keeps_focus_in_game(self):
        self.native.fg = 123
        self.action('toggle')
        self.hud.command('full')
        self.hud.command('passive')
        self.hud.tick()
        self.assertEqual(self.native.fg, 123)
        self.assertFalse(self.native.interactive)
    def test_alt_tab_hides_without_shrinking(self):
        self.native.fg = 123
        self.action('toggle')
        self.native.fg = 789
        self.hud.tick()
        self.assertFalse(self.native.visible)
        self.assertEqual(self.hud.session, 'desk')
        self.native.fg = 123
        self.hud.tick()
        self.assertFalse(self.native.visible)
        self.native.fg = 123
        self.action('toggle')
        self.assertTrue(self.native.visible)
        self.assertEqual(self.hud.session, 'overlay')
    def test_own_dialog_keeps_interaction(self):
        self.action('full')
        self.native.fg = 456
        self.hud.tick()
        self.assertTrue(self.native.visible)
        self.assertTrue(self.native.interactive)
    def test_no_game_can_open_settings_with_hotkey(self):
        self.native.game = None
        self.native.fg = 789
        self.hud.tick()
        self.assertTrue(self.native.visible)
        self.assertEqual(self.hud.session, 'desk')
        self.action('close')
        self.assertFalse(self.native.visible)
        self.native.fg = 123
        self.action('toggle')
        self.assertTrue(self.native.visible)
        self.assertEqual(self.hud.session, 'desk')
    def test_initial_launch_without_game_is_reachable(self):
        native = Native()
        native.game = None
        native.fg = 789
        hud = HudController(self.window, self.path, native=native)
        hud.tick()
        self.assertTrue(native.visible)
        self.assertTrue(native.interactive)
        self.assertEqual(hud.snapshot()['mode'], 'full')
    def test_window_follows_game_without_resetting_drag(self):
        self.native.fg = 123
        self.action('toggle')
        self.native.rect = (100, 120, 1280, 820)
        self.hud.tick()
        self.assertEqual(self.native.rect[:2], (100, 120))
        self.native.bounds = (300, 200, 1920, 1080)
        self.hud.tick()
        self.assertEqual(self.native.rect[:2], (400, 320))
    def test_position_saved_relative_to_game(self):
        self.native.fg = 123
        self.action('toggle')
        self.native.rect = (100, 120, 1280, 820)
        self.native.bounds = (0, 0, 1900, 1000)
        self.hud.tick()
        self.assertEqual(load_settings(self.path)['full']['dx'], 100)
    def test_close_hides_to_tray_and_quit_destroys(self):
        self.action('close')
        self.assertFalse(self.window.closed)
        self.assertFalse(self.native.visible)
        self.action('quit')
        self.assertTrue(self.window.closed)
    def test_busy_hotkey_keeps_the_window(self):
        with patch('stalzone_overlay.GlobalHotkey') as hotkey, patch('stalzone_overlay.TrayIcon'):
            hotkey.return_value.registered = False
            self.hud.start()
        self.assertFalse(self.window.closed)
        self.assertTrue(self.native.message)
    def test_native_close_saves_latest_drag(self):
        self.native.rect = (150, 160, 520, 380)
        self.hud.closing()
        self.assertEqual(load_settings(self.path)['full']['dx'], 150)
        self.assertTrue(self.hud.stopped.is_set())
    def test_invalid_geometry_is_clamped(self):
        self.assertEqual(fit_geometry({'x':9000,'y':-9000,'w':3000,'h':2000},
            (0,0,1920,1080),(520,380),(440,340)), (0,0,1920,1080))

if __name__ == '__main__': unittest.main()
