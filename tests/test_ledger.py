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

    def test_changing_the_count_rescales_the_purchase_and_the_sale(self):
        book.add("Осколок", 2200000, 2390000, 2)
        row = book.load()[0]
        book.set_qty(row["id"], 3)
        again = book.load()[0]
        self.assertEqual(3, again["qty"])
        self.assertEqual(3300000, again["buy"])
        self.assertEqual(3585000, again["sell"])
        self.assertEqual(3405750, again["net"])
        self.assertEqual(105750, again["gain"])
        self.assertEqual(row["date"], again["date"])
        self.assertEqual("Осколок", again["name"])

    def test_remove_drops_only_the_chosen_row(self):
        book.add("Бинт", 100000, 200000, 2)
        book.add("Аптечка", 50000, 80000, 1)
        first = book.load()[0]["id"]
        book.remove(first)
        rows = book.load()
        self.assertEqual(["Аптечка"], [row["name"] for row in rows])
        self.assertTrue((agent.DIR / "учёт.xlsx").exists())

    def test_old_sheet_without_count_still_opens(self):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(["Дата", "Предмет", "Куплено", "Продано", "После 5%", "Плюс", "id"])
        ws.append(["22.10.2026", "Бинт", 100000, 200000, 190000, 90000, "abc"])
        wb.save(agent.DIR / "учёт.xlsx")
        row = book.load()[0]
        self.assertEqual(200000, row["sell"])
        self.assertIsNone(row["qty"])
        self.assertFalse(row["hand"])
        self.assertEqual(90000, row["gain"])

    def test_own_position_keeps_the_date_and_edits_the_rest(self):
        self.assertTrue(book.add("Свой лот", 1100000, 1800000, 1, hand=True))
        self.assertTrue(book.add("Свой лот", 1100000, 1800000, 1, hand=True))
        row = book.load()[0]
        self.assertTrue(row["hand"])
        self.assertEqual(1710000, row["net"])
        self.assertEqual(610000, row["gain"])
        book.set_name(row["id"], "Другой лот")
        book.set_buy(row["id"], 1500000)
        book.set_qty(row["id"], 4)
        book.set_sell(row["id"], 2000000)
        again = book.load()[0]
        self.assertEqual(row["date"], again["date"])
        self.assertEqual("Другой лот", again["name"])
        self.assertEqual(1500000, again["buy"])
        self.assertEqual(4, again["qty"])
        self.assertEqual(1900000, again["net"])
        self.assertEqual(400000, again["gain"])
        scan = book.add("Осколок", 100, 200, 2)
        self.assertTrue(scan)
        with self.assertRaises(ValueError):
            book.set_buy(book.load()[2]["id"], 300)
        book.add("Бинт", 1, 2)
        day = datetime.now(agent.MSK).date()
        self.assertEqual(day, book.load()[0]["date"])

    def test_rarity_and_point_stay_in_the_sheet_and_color_the_row(self):
        self.assertTrue(book.add("Спираль", 80000, 100000, 1, qlt="Обычный", ptn="+0"))
        self.assertTrue(book.add("Спираль", 80000, 120000, 1, qlt="Исключительный", ptn="+15"))
        rows = book.load()
        self.assertEqual(["Обычный", "Исключительный"], [row["qlt"] for row in rows])
        self.assertEqual(["+0", "+15"], [row["ptn"] for row in rows])
        book.set_mark(rows[0]["id"], "Редкий", "+3")
        again = book.load()[0]
        self.assertEqual("Редкий", again["qlt"])
        self.assertEqual("+3", again["ptn"])
        self.assertEqual("Спираль", again["name"])
        shot = book.snapshot()
        self.assertEqual("Редкий", shot["rows"][0]["qlt"])


if __name__ == "__main__":
    unittest.main()
