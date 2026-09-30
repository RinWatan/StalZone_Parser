import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import stalzone_agent as agent
from stalzone_gui import App
from stalzone_overlay import fit_geometry, load_settings


class FakeGameWindow:
    def __init__(self, root):
        self.root = root
        self.game = 123
        self.foreground_hwnd = 123
        self.rect = (0, 0, 1920, 1080)
        self.interactive = False
        self.visible = False

    def find_game(self): return self.game
    def client_bounds(self, hwnd): return self.rect if hwnd else None
    def foreground(self): return self.foreground_hwnd
    def owns(self, hwnd): return hwnd == 456
    def set_interactive(self, value): self.interactive = value
    def show(self, visible):
        self.visible = visible
        self.root.deiconify() if visible else self.root.withdraw()
    def place(self, x, y, w, h): self.root.geometry(f'{w}x{h}+{x}+{y}')
    def activate(self): self.foreground_hwnd = 456
    def return_to(self, hwnd): self.foreground_hwnd = hwnd


class SettingsTests(unittest.TestCase):
    def test_bad_settings_fall_back(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            for text in ['not json', '[]', 'null']:
                path.write_text(text)
                self.assertEqual(load_settings(path), {})

    def test_offscreen_window_is_reachable(self):
        result = fit_geometry({'x': 9000, 'y': -9000, 'w': 3000, 'h': 2000},
                              (0, 0, 1920, 1080), (460, 340), (420, 280))
        self.assertEqual(result, (0, 0, 1920, 1080))

    def test_negative_monitor_coordinates_are_preserved(self):
        result = fit_geometry({'x': -1500, 'y': 40, 'w': 460, 'h': 340},
                              (-1920, 0, 3840, 1080), (460, 340), (420, 280))
        self.assertEqual(result, (-1500, 40, 460, 340))


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir_patch = patch.object(agent, 'DIR', Path(self.temp.name))
        self.dir_patch.start()
        self.catalog_patch = patch.object(App, '_load_auction', lambda self: None)
        self.catalog_patch.start()
        self.hotkey_patch = patch('stalzone_overlay.GlobalHotkey')
        self.hotkey_patch.start()
        self.native_patch = patch('stalzone_overlay.GameWindow', FakeGameWindow)
        self.native_patch.start()
        self.app = App()
        self.app.root.update()

    def tearDown(self):
        self.app.overlay.close()
        self.hotkey_patch.stop()
        self.native_patch.stop()
        self.catalog_patch.stop()
        self.dir_patch.stop()
        self.temp.cleanup()
        agent.HALT.clear()

    def test_starts_compact_and_topmost(self):
        self.assertEqual(self.app.overlay.mode, 'compact')
        self.assertTrue(self.app.overlay.compact.winfo_ismapped())
        self.assertFalse(self.app.full_frame.winfo_ismapped())
        self.assertTrue(self.app.root.attributes('-topmost'))

    def test_switch_keeps_tables_selection_and_worker(self):
        tree = self.app.trees['Арсенал']
        tree.insert('', 'end', values=('Соленоид', '2250', '2250', 'СЛИТЬ'))
        self.app.section.set('Арсенал')
        worker = object()
        self.app.worker = worker
        self.app.overlay.expand()
        self.app.root.update()
        self.app.overlay.collapse()
        self.app.root.update()
        self.app.overlay.expand()
        self.app.root.update()
        self.assertEqual(len(tree.get_children()), 1)
        self.assertEqual(self.app.section.get(), 'Арсенал')
        self.assertIs(self.app.worker, worker)
        self.assertTrue(self.app.full_frame.winfo_ismapped())

    def test_compact_clears_stale_results(self):
        self.app.overlay.update_deals([{'name': 'Test', 'buyout': 100, 'gain': 20}])
        self.assertEqual(len(self.app.overlay.deals.get_children()), 1)
        self.app.fill({'buys': []})
        self.assertEqual(len(self.app.overlay.deals.get_children()), 0)

    def test_busy_controls_and_hide_preserve_worker(self):
        self.app._busy(True)
        self.assertIn('disabled', self.app.overlay.run_button.state())
        self.assertNotIn('disabled', self.app.overlay.stop_button.state())
        self.app.overlay.toggle_visible()
        self.app.root.update()
        self.assertEqual(self.app.root.state(), 'withdrawn')
        self.app.overlay.toggle_visible()
        self.app.root.update()
        self.assertEqual(self.app.root.state(), 'normal')
        self.app._busy(False)
        self.assertNotIn('disabled', self.app.overlay.run_button.state())

    def test_compact_scan_uses_buys_without_changing_full_selection(self):
        self.app.section.set('Арсенал')
        seen = []
        with patch.object(self.app, 'start_once', lambda: seen.append(self.app.section.get())):
            self.app.overlay.scan()
        self.assertEqual(seen, ['Выкуп'])
        self.assertEqual(self.app.section.get(), 'Арсенал')

    def test_settings_save_both_modes(self):
        self.app.overlay.expand()
        self.app.root.update()
        self.app.overlay.collapse()
        self.app.root.update()
        self.app.overlay.save()
        saved = json.loads((Path(self.temp.name) / 'overlay_settings.json').read_text())
        self.assertIn('compact', saved)
        self.assertIn('full', saved)

    def test_collapse_from_maximized_restores_compact_size(self):
        self.app.overlay.expand()
        self.app.root.update()
        # Simulate legacy/decorated maximization before restoring HUD mode.
        self.app.root.overrideredirect(False)
        self.app.root.state('zoomed')
        self.app.root.update()
        self.app.overlay.collapse()
        self.app.root.update()
        self.assertEqual(self.app.root.state(), 'normal')
        self.assertLess(self.app.root.winfo_width(), 700)

    def test_hud_is_borderless_and_passive(self):
        self.assertTrue(self.app.root.overrideredirect())
        self.assertFalse(self.app.overlay.interactive)
        self.assertFalse(self.app.overlay.native.interactive)

    def test_other_application_hides_panel_and_game_restores_it(self):
        hud = self.app.overlay
        hud.native.foreground_hwnd = 999
        hud.sync_game()
        self.assertFalse(hud.native.visible)
        hud.native.foreground_hwnd = 123
        hud.sync_game()
        self.assertTrue(hud.native.visible)

    def test_hotkey_enters_edit_and_returns_game_focus(self):
        hud = self.app.overlay
        hud.toggle_interaction()
        self.assertTrue(hud.interactive)
        self.assertTrue(hud.native.interactive)
        self.assertEqual(hud.native.foreground(), 456)
        hud.expand()
        hud.toggle_interaction()
        self.assertFalse(hud.interactive)
        self.assertEqual(hud.mode, 'compact')
        self.assertEqual(hud.native.foreground(), 123)

    def test_panel_moves_with_game(self):
        hud = self.app.overlay
        self.app.root.update()
        before = self.app.root.winfo_x()
        hud.native.rect = (100, 0, 1920, 1080)
        hud.sync_game()
        self.app.root.update()
        self.assertEqual(self.app.root.winfo_x(), before + 100)

    def test_missing_game_can_open_setup_via_hotkey(self):
        hud = self.app.overlay
        hud.native.game = None
        hud.native.foreground_hwnd = 999
        hud.sync_game()
        self.assertFalse(hud.native.visible)
        hud.toggle_interaction()
        self.assertTrue(hud.native.visible)
        self.assertTrue(hud.interactive)


if __name__ == '__main__':
    unittest.main()
