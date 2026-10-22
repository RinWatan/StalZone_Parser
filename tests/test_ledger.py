# -*- coding: utf-8 -*-
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import stalzone_agent as agent
import stalzone_ledger as book


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = agent.DIR
        agent.DIR = Path(self.tmp.name)

    def tearDown(self):
        agent.DIR = self.old
        self.tmp.cleanup()

    def test_add_writes_sale_after_five_percent_and_keeps_the_file(self):
        self.assertTrue(book.add("Бинт", 100000, 200000))
        self.assertFalse(book.add("Бинт", 100000, 200000))
        rows = book.load()
        self.assertEqual(1, len(rows))
        self.assertEqual(100000, rows[0]["buy"])
        self.assertEqual(200000, rows[0]["sell"])
        self.assertEqual(190000, rows[0]["net"])
        self.assertEqual(90000, rows[0]["gain"])
        self.assertTrue((agent.DIR / "учёт.xlsx").exists())

    def test_edit_sale_does_not_touch_date_name_or_buy(self):
        book.add("Бинт", 100000, 200000)
        row = book.load()[0]
        book.set_sell(row["id"], 150000)
        again = book.load()[0]
        self.assertEqual(row["date"], again["date"])
        self.assertEqual("Бинт", again["name"])
        self.assertEqual(100000, again["buy"])
        self.assertEqual(142500, again["net"])
        self.assertEqual(42500, again["gain"])

    def test_older_row_stays_when_a_new_purchase_is_added(self):
        book.add("Бинт", 100000, 200000)
        first = book.load()[0]
        first["date"] = first["date"] - timedelta(days=1)
        book._write_locked([first])
        book.add("Аптечка", 50000, 80000)
        rows = book.load()
        self.assertEqual(["Бинт", "Аптечка"], [row["name"] for row in rows])
        self.assertEqual(100000, rows[0]["buy"])
        shot = book.snapshot()
        self.assertEqual(rows[0]["gain"] + rows[1]["gain"], shot["gain"])
        self.assertEqual(rows[1]["gain"], shot["today_gain"])

    def test_empty_sale_is_not_counted(self):
        book.add("Бинт", 100000, 200000)
        book.set_sell(book.load()[0]["id"], None)
        row = book.load()[0]
        self.assertIsNone(row["sell"])
        self.assertIsNone(row["gain"])
        self.assertEqual(0, book.snapshot()["gain"])

    def test_sheet_date_comes_back_as_the_same_day(self):
        book.add("Бинт", 1, 2)
        day = datetime.now(agent.MSK).date()
        self.assertEqual(day, book.load()[0]["date"])


if __name__ == "__main__":
    unittest.main()
