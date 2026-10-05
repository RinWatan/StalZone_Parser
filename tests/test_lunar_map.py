import unittest

import stalzone_lunar as lunar


class LunarMapTests(unittest.TestCase):
    def test_categories_drop_empty_layers(self):
        rows = lunar._categories([
            {"id": 5, "title": "Аномалии", "color": "#66A9FF", "markers": 10},
            {"id": 14, "title": "Пусто", "color": "#fff", "markers": 0},
        ])
        self.assertEqual(rows, [{"id": 5, "title": "Аномалии", "color": "#66A9FF", "count": 10}])

    def test_catalog_keeps_only_maps_with_marks(self):
        payload = {"maps": [
            {"slug": "empty", "title": "Пусто", "markers": 0},
            {"slug": "yug", "title": "Южная зона", "markers": 3},
            {"slug": "north", "title": "Север", "markers": 9},
        ]}
        rows = []
        for item in payload["maps"]:
            count = int(item.get("markers") or 0)
            if count <= 0 or not item.get("slug"):
                continue
            rows.append({"slug": item["slug"], "title": item["title"], "markers": count})
        rows.sort(key=lambda row: row["markers"], reverse=True)
        self.assertEqual([row["slug"] for row in rows], ["north", "yug"])


if __name__ == "__main__":
    unittest.main()
