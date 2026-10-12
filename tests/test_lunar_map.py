import unittest
from unittest.mock import patch
from pathlib import Path

import stalzone_lunar as lunar


class LunarMapTests(unittest.TestCase):
    def test_categories_drop_empty_layers(self):
        rows = lunar._categories([
            {"id": 5, "title": "Аномалии", "color": "#66A9FF", "markers": 10},
            {"id": 14, "title": "Пусто", "color": "#fff", "markers": 0},
        ])
        self.assertEqual(rows, [{"id": 5, "title": "Аномалии", "color": "#66A9FF", "count": 10}])

    def test_tiles_keep_every_zoom(self):
        tiles = lunar._tiles({
            "tileBase": "https://cdn/map/",
            "tileQuery": "?md5=1",
            "tileSize": 512,
            "zoomMax": 3,
            "grid": {"z0": [[3, 4]], "z3": [[0, 0]]},
        })
        self.assertEqual(tiles["base"], "https://cdn/map/")
        self.assertEqual(tiles["grid"]["0"], [[3, 4]])
        self.assertEqual(tiles["grid"]["3"], [[0, 0]])
        self.assertEqual(tiles["zoomMax"], 3)

    def test_catalog_keeps_only_maps_with_marks(self):
        payload = {"maps": [
            {"slug": "empty", "title": "Пусто", "markers": 0},
            {"slug": "yug", "title": "Южная зона", "markers": 3},
            {"slug": "north", "title": "Север", "markers": 9},
        ]}
        with patch.object(lunar,'_json',return_value=payload):
            rows = lunar.catalog()
        self.assertEqual([row["slug"] for row in rows], ["north", "yug"])

    def test_slug_cannot_escape_cache_folder(self):
        with patch.object(lunar,'_json') as fetch:
            with self.assertRaises(ValueError): lunar.load(Path('.'),'../outside')
            fetch.assert_not_called()

    def test_decoder_filename_cannot_escape_cache_folder(self):
        with self.assertRaises(ValueError): lunar._markers(Path('.'),'../../outside','decode','yug',[])

    def test_cache_detects_title_and_chunk_revision_changes(self):
        base={'format':{'salt':'abc','entry':'run'},'version':{'id':1},'titles':['A'],
              'categories':[], 'chunks':[{'id':1,'count':2,'revision':1}]}
        first=lunar._cache_stamp(base)
        base['titles']=['B']
        self.assertNotEqual(first,lunar._cache_stamp(base))
        second=lunar._cache_stamp(base)
        base['chunks'][0]['revision']=2
        self.assertNotEqual(second,lunar._cache_stamp(base))

    def test_temporary_tile_signatures_do_not_invalidate_markers(self):
        manifest={'version':{'id':1,'width':5120,'overview':'https://cdn/map.webp?expires=1',
                             'tileQuery':'?expires=1&md5=a'}}
        first=lunar._cache_stamp(manifest)
        manifest['version']['overview']='https://cdn/map.webp?expires=2'
        manifest['version']['tileQuery']='?expires=2&md5=b'
        self.assertEqual(first,lunar._cache_stamp(manifest))


if __name__ == "__main__":
    unittest.main()
