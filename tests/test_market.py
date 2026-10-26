# -*- coding: utf-8 -*-
import json
import tempfile
import threading
import unittest
import unittest.mock
import urllib.error
import urllib.request
from pathlib import Path

import stalzone_agent as agent
import stalzone_hub as hub
import stalzone_market as market


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = market.MarketStore(Path(self.tmp.name) / "market.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_sell_is_kept_for_two_hours(self):
        self.store.put_sells([("slug|1|(0, 0)", 100, 1_000)])
        self.assertEqual(self.store.sell("slug|1|(0, 0)", now=1_000 + 3600), 100)
        self.assertIsNone(self.store.sell("slug|1|(0, 0)", now=1_000 + 3 * 3600))

    def test_board_keeps_one_snapshot(self):
        self.store.save_board([{"name": "Вихрь", "hours": (1, 2)}], 4, 10, now=50)
        self.store.save_board([{"name": "Ершик"}], 5, 10, now=80)
        board = self.store.board()
        self.assertEqual(board["ts"], 80)
        self.assertEqual(board["rows"], [{"name": "Ершик"}])
        self.assertEqual(len(self.store.board()["rows"]), 1)

    def test_bought_lot_leaves_the_snapshot(self):
        self.store.save_board(
            [
                {"slug": "keep", "name": "Вихрь", "buyout": 100, "amount": 1},
                {"slug": "gone", "name": "Ершик", "buyout": 50, "amount": 1},
            ],
            2,
            2,
            now=1,
        )

        def lots(slug, pages=1):
            if slug == "keep":
                return [{"buyoutPrice": 100, "amount": 1}]
            return []

        with unittest.mock.patch.object(agent, "live_lots", lots):
            board = agent.refresh_board(self.store)
        self.assertEqual([row["name"] for row in board["rows"]], ["Вихрь"])

    def test_two_scans_merge_and_a_bought_lot_does_not_return(self):
        self.store.merge_scan(
            [{"slug": "art", "name": "Вихрь", "buyout": 10, "amount": 1, "gain": 5}],
            ["art"],
            "я",
            now=100,
        )
        self.store.merge_scan(
            [{"slug": "mod", "name": "Ершик", "buyout": 7, "amount": 1, "gain": 3}],
            ["mod"],
            "друг",
            now=120,
        )
        self.assertEqual({row["name"] for row in self.store.board()["rows"]}, {"Вихрь", "Ершик"})
        self.store.bury([market.offer_key({"slug": "art", "buyout": 10, "amount": 1})], now=130)
        self.store.merge_scan(
            [{"slug": "art", "name": "Вихрь", "buyout": 10, "amount": 1, "gain": 5}],
            ["art"],
            "я",
            now=140,
        )
        self.assertEqual([row["name"] for row in self.store.board()["rows"]], ["Ершик"])

    def test_slice_splits_the_catalog(self):
        items = [{"id": "a", "cat": "artefact"}, {"id": "b", "cat": "misc"}]
        first = self.store.claim_slice(items, limit=1, who="я", now=10, stale=50)
        second = self.store.claim_slice(items, limit=1, who="друг", now=20, stale=50)
        self.assertEqual(first, ["a"])
        self.assertEqual(second, ["b"])
        self.assertEqual(self.store.claim_slice(items, limit=1, who="ещё", now=30, stale=50), [])


class HubTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = market.MarketStore(self.root / "market.db")
        self.store.save_board([{"name": "Вихрь", "buyout": 10, "profit": 20, "gain": 20, "copies": 1}], 1, 1, now=10)
        (self.root / "catalog.json").write_text(
            json.dumps([{"id": "vhr", "name": "Вихрь", "tradable": 1}]),
            encoding="utf-8",
        )
        self.http = hub.ThreadingHTTPServer(("127.0.0.1", 0), hub.make_handler(self.store, "secret"))
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.http.server_address[1]
        self.old_dir = agent.DIR
        agent.DIR = self.root

    def tearDown(self):
        self.http.shutdown()
        agent.DIR = self.old_dir
        self.tmp.cleanup()

    def _get(self, path, token="secret"):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            headers={"X-Hub-Token": token},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode())

    def test_teammate_reads_catalog_and_deals_without_a_local_copy(self):
        denied = urllib.request.Request(f"http://127.0.0.1:{self.port}/v1/deals")
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(denied, timeout=5)
        catalog = self._get("/v1/catalog")
        deals = self._get("/v1/deals")
        self.assertEqual(catalog["items"][0]["name"], "Вихрь")
        self.assertEqual(deals["rows"][0]["name"], "Вихрь")

    def test_agent_uses_the_shared_board(self):
        (self.root / "hub.url").write_text(f"http://127.0.0.1:{self.port}\nsecret\n", encoding="utf-8")
        seen = {}

        def take(rows, done, total):
            seen["rows"] = rows
            seen["done"] = done

        rows = agent.buy_scan(on_update=take, budget=0)
        self.assertEqual(rows[0]["name"], "Вихрь")
        self.assertIn("Вихрь", [row["name"] for row in seen["rows"]])
