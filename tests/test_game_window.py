import unittest
from game_window import is_game_path, overlay_style


class NativePolicyTests(unittest.TestCase):
    def test_detects_exbo_game_but_not_parser(self):
        self.assertTrue(is_game_path(r'E:\games\EXBO\runtime\stalcraft\win64\java\bin\stalzone.exe'))
        self.assertTrue(is_game_path(r'D:\Steam\steamapps\common\STALCRAFT\runtime\stalcraft\win64\stalzonew.exe'))
        self.assertFalse(is_game_path(r'C:\project\dist\STALZONE.exe'))
        self.assertFalse(is_game_path(r'E:\games\EXBO\java\bin\ExboLauncher.exe'))

    def test_passive_passes_clicks_and_cannot_activate(self):
        style = overlay_style(0, False)
        self.assertEqual(style & 0x80020, 0x80020)
        self.assertTrue(style & 0x08000000)

    def test_edit_removes_passthrough_without_losing_other_flags(self):
        old = 0x80020 | 0x08000000 | 0x100
        style = overlay_style(old, True)
        self.assertFalse(style & 0x20)
        self.assertFalse(style & 0x08000000)
        self.assertTrue(style & 0x100)
