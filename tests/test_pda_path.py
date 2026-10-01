import tempfile
import unittest
from pathlib import Path

import stalzone_pda as pda


class PdaPathTests(unittest.TestCase):
    def test_steam_exe_and_launcher_root_both_reach_the_tiles(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            steam = root / "SteamLibrary" / "steamapps" / "common" / "STALCRAFT"
            tiles = steam / "modassets" / "assets" / "pda" / "global_map"
            tiles.mkdir(parents=True)
            (tiles / "r.0.0.ol").write_bytes(b"x")
            exe = steam / "runtime" / "stalcraft" / "win64" / "java" / "bin" / "stalzonew.exe"
            exe.parent.mkdir(parents=True)
            self.assertEqual(pda.pda_folder(exe), tiles)

            launch = root / "EXBO" / "modassets" / "assets" / "pda" / "global_map"
            launch.mkdir(parents=True)
            (launch / "r.1.0.ol").write_bytes(b"x")
            self.assertEqual(pda.pda_folder(root / "EXBO"), launch)

    def test_map_dir_overrides_a_missing_steam_path(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            tiles = root / "custom" / "global_map"
            tiles.mkdir(parents=True)
            (tiles / "r.0.0.ol").write_bytes(b"x")
            app = root / "app"
            app.mkdir()
            (app / "map_dir.txt").write_text(str(tiles), encoding="utf-8")
            self.assertEqual(pda.locate(app), tiles)
