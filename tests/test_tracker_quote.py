import time
import unittest

import stalzone_agent as a


class TrackerQuoteTests(unittest.TestCase):
    def test_week_median_is_the_list_price(self):
        now = time.time()
        prices = [100, 100, 100, 100, 140, 150, 160, 200]
        sales = [(price, now - i * 600) for i, price in enumerate(prices)]
        quote = a.tracker_quote(sales, now)
        self.assertEqual(quote["depth_days"], 7)
        self.assertEqual(quote["method"], "median")
        self.assertAlmostEqual(quote["ask"], a._fair_of(sales, "median"))
        self.assertEqual(quote["advisor"], "d1")
        self.assertTrue(quote["share"])
        self.assertGreater(quote["per_day"], 0)
        self.assertIsNotNone(quote["hours"])

    def test_week_uses_median_when_the_day_has_no_sales(self):
        now = time.time()
        sales = [(100 + (i % 3) * 10, now - 2 * 86400 - i * 3600) for i in range(8)]
        quote = a.tracker_quote(sales, now)
        self.assertEqual(quote["depth_days"], 7)
        self.assertEqual(quote["advisor"], "d7")
        self.assertAlmostEqual(quote["ask"], a._fair_of(sales, "median"))
        self.assertEqual(quote["horizons"][0]["status"], "INSUFFICIENT_EVIDENCE")

    def test_thin_week_widens_and_a_strict_week_does_not(self):
        now = time.time()
        old = [(500000, now - 10 * 86400 - i * 3600) for i in range(8)]
        opened = a.tracker_quote(old, now)
        self.assertIsNotNone(opened)
        self.assertEqual(opened["depth_days"], 14)
        self.assertIsNone(a.tracker_quote(old, now, ignore_depth=False))

    def test_full_week_does_not_use_older_cheaper_sales(self):
        now = time.time()
        recent = [(200, now - i * 600) for i in range(8)]
        old = [(50, now - 10 * 86400 - i * 3600) for i in range(20)]
        quote = a.tracker_quote(recent + old, now)
        self.assertEqual(quote["depth_days"], 7)
        self.assertAlmostEqual(quote["ask"], 200)

    def test_longer_horizon_cannot_ask_less(self):
        now = time.time()
        cheap = [(50, now - 10 * 86400 - i * 3600) for i in range(40)]
        dear = [(200, now - i * 600) for i in range(8)]
        quote = a.tracker_quote(dear + cheap, now)
        codes = {row["code"]: row["status"] for row in quote["horizons"]}
        self.assertEqual(codes["d30"], "PRICE_INVERSION")
        self.assertEqual(quote["advisor"], "d1")
        self.assertAlmostEqual(quote["ask"], 200)

    def test_two_sales_are_not_enough(self):
        now = time.time()
        sales = [(100, now), (110, now - 600)]
        self.assertIsNone(a.tracker_quote(sales, now))

    def test_weighted_mean_follows_the_newest_sales(self):
        now = time.time()
        sales = [(100, now - 6 * 86400)] * 7 + [(400, now)]
        mean = a._fair_of(sales, "mean")
        weighted = a._fair_of(sales, "weighted")
        self.assertGreater(weighted, mean)
        self.assertLess(weighted, 400)

    def test_plan_names_the_list_price_and_the_day_rate(self):
        now = time.time()
        a._LIVE["abc"] = [{"amount": 1, "buyoutPrice": 50000, "additional": {}}]
        sales = [(1, 80000, now - i * 600) for i in range(8)]
        deal = a._as_buys(a.find_flips({"sales": {None: sales}}, "abc", "Test", True))[0]
        self.assertIn("Выстави пачку за 80000", deal["plan"])
        self.assertIn("8 из 10", deal["plan"])
        self.assertIn("продано/день", deal["plan"])
        self.assertGreaterEqual(deal["gain"], a.TRACKER_MIN)


if __name__ == "__main__":
    unittest.main()
