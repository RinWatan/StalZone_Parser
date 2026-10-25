import tempfile
import unittest
from pathlib import Path

import stalzone_db as db


class ItemDbTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "items.db"

    def tearDown(self):
        self.temp.cleanup()

    def test_bound_and_quest_items_stay_off_the_auction(self):
        rows = [
            {"id": "stone", "name": "Болотный камень", "cat": "other", "color": "DEFAULT", "icon": "/icons/other/9dknl.png", "status": "PERSONAL_DROP_ON_GET"},
            {"id": "part", "name": "Часть MG3", "cat": "misc", "color": "RANK_MASTER", "icon": "/icons/misc/77do9.png", "status": "PERSONAL_ON_GET"},
            {"id": "note", "name": "Расписка", "cat": "other", "color": "QUEST_ITEM", "icon": "/icons/other/7lwvj.png", "status": "PERSONAL_ON_GET"},
            {"id": "med", "name": "Аптечка", "cat": "supply", "color": "DEFAULT", "icon": "/icons/supply/medicine/9mmq.png", "status": "NON_DROP"},
        ]
        result = db.sync_items(self.path, rows)
        self.assertEqual(result["added"], 4)
        self.assertEqual(db.untradable_ids(self.path), {"part", "note"})
        stone = db.get_item(self.path, "stone")
        self.assertEqual(stone["tradable"], 1)
        self.assertEqual(stone["icon"], "/icons/other/9dknl.png")
        self.assertTrue(db.icon_url(stone["icon"]).endswith("/icons/other/9dknl.png"))

    def test_new_item_is_added_without_dropping_a_learned_ban(self):
        db.sync_items(self.path, [{"id": "gun", "name": "АК", "cat": "weapon", "color": "RANK_MASTER", "icon": "/icons/weapon/ak.png", "status": "PERSONAL_ON_USE"}])
        db.mark_untradable(self.path, "gun", "auction")
        db.sync_items(self.path, [{"id": "gun", "name": "АК-74", "cat": "weapon", "color": "RANK_MASTER", "icon": "/icons/weapon/ak.png", "status": "PERSONAL_ON_USE"},
                                  {"id": "new", "name": "Новый", "cat": "misc", "color": "DEFAULT", "icon": "/icons/misc/new.png", "status": "NONE"}])
        self.assertEqual(db.get_item(self.path, "gun")["tradable"], 0)
        self.assertEqual(db.get_item(self.path, "gun")["name"], "АК-74")
        self.assertEqual(db.get_item(self.path, "new")["tradable"], 1)
        self.assertEqual(db.sync_items(self.path, [])["added"], 0)

    def test_status_ban_comes_back_if_the_item_becomes_personal(self):
        db.sync_items(self.path, [{"id": "box", "name": "Ящик", "cat": "misc", "color": "DEFAULT", "icon": "/icons/misc/box.png", "status": "NONE"}])
        db.sync_items(self.path, [{"id": "box", "name": "Ящик", "cat": "misc", "color": "DEFAULT", "icon": "/icons/misc/box.png", "status": "PERSONAL_ON_GET"}])
        row = db.get_item(self.path, "box")
        self.assertEqual(row["tradable"], 0)
        self.assertEqual(row["reason"], "status")


if __name__ == "__main__":
    unittest.main()
