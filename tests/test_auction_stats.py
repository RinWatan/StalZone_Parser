import time
import tempfile
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
import stalzone_agent as a


def sale(price, amount=1, age=0, qlt=4, ptn=0):
    return {'price':price,'amount':amount,
            'time':datetime.fromtimestamp(2000000000-age,timezone.utc).isoformat(),
            'additional':{'qlt':qlt,'ptn':ptn}}


class PriceStatsTests(unittest.TestCase):
    def stats(self, prices, **kwargs):
        data={'slug':'abc','history_pages':[prices]}
        with patch.object(a.time,'time',return_value=2000000000):
            return a.auction_price_stats(data,**kwargs)

    def test_mean_median_use_unit_price_per_sale(self):
        r=self.stats([sale(1000,10),sale(200),sale(3000)])
        self.assertEqual(r['mean'],1100)
        self.assertEqual(r['median'],200)
        self.assertEqual(r['count'],3)

    def test_week_and_invalid_entries(self):
        bad=sale(999); bad['time']='invalid'
        r=self.stats([sale(100,age=7*86400),sale(10000,age=7*86400+1),
                      sale(999,age=-1),sale(0),sale(100,amount=0),bad])
        self.assertEqual(r['count'],1)
        self.assertEqual(r['mean'],100)

    def test_latest_hundred_even_if_input_not_sorted(self):
        r=self.stats([sale(i+1,age=i) for i in reversed(range(150))])
        self.assertEqual(r['count'],100)
        self.assertEqual(r['mean'],50.5)
        self.assertEqual(r['median'],50.5)

    def test_filters_before_selecting_sample(self):
        r=self.stats([sale(100,qlt=4,ptn=5),sale(2000,qlt=3),sale(5000,ptn=10)],
                     qname=a._qname(4),lo=5,hi=5)
        self.assertEqual(r['count'],1)
        self.assertEqual(r['median'],100)

    def test_empty_stats(self):
        r=self.stats([sale(100,age=8*86400)])
        self.assertEqual(r['count'],0)
        self.assertIsNone(r['mean'])
        self.assertIsNone(r['median'])

    def test_fetches_more_history_for_rare_filter_and_reuses_it(self):
        data={'slug':'abc','history_pages':[[sale(10,qlt=3)]*200]}
        with patch.object(a.time,'time',return_value=2000000000),patch.object(a,'get_json',return_value={'prices':[sale(100)]*5}) as get:
            r=a.auction_price_stats(data,qname=a._qname(4))
            self.assertEqual(r['count'],5)
            self.assertIn('offset=200',get.call_args.args[0])
            a.auction_price_stats(data,qname=a._qname(4))
            self.assertEqual(get.call_count,1)

    def test_stops_when_hundred_matching_sales_present(self):
        with patch.object(a,'get_json') as get:
            self.assertEqual(self.stats([sale(100)]*200)['count'],100)
            get.assert_not_called()

    def test_bridge_summary_changes_with_filters(self):
        from stalzone_gui import Bridge
        data={'slug':'abc','total':0,'lots':[],'sales':[],
              'history_pages':[[sale(100),sale(300),sale(9000,qlt=3)]]}
        bridge=Bridge()
        with patch.object(a.time,'time',return_value=2000000000):
            result=bridge._lots_payload('',data,a._qname(4),0,15)
            self.assertEqual(result['stats']['median'],200)
            self.assertIn('Малая выборка',result['summary'])
            result=bridge._lots_payload('',data,a._qname(4),5,5)
            self.assertIn('Нет продаж за 7 дней',result['summary'])

    def test_new_item_clears_old_data_and_rejects_stale_completion(self):
        from stalzone_gui import Bridge
        entered,release=threading.Event(),threading.Event()
        def load(slug):
            if slug=='old':
                entered.set()
                release.wait(3)
            return {'slug':slug,'lots':[],'sales':[],'total':0,'history_pages':[[]]}
        with tempfile.TemporaryDirectory() as folder,patch.object(a,'DIR',Path(folder)),patch.object(a,'item_view',side_effect=load):
            bridge=Bridge()
            bridge.lot_data={'slug':'previous'}
            with ThreadPoolExecutor(2) as pool:
                first=pool.submit(bridge.open_item,'old','Old','Все',0,15)
                try:
                    self.assertTrue(entered.wait(2))
                    self.assertFalse(bridge.filter_open('Все',0,15)['ok'])
                    second=bridge.open_item('new','New','Все',0,15)
                    self.assertTrue(second['ok'])
                finally:
                    release.set()
                self.assertFalse(first.result()['ok'])
            self.assertEqual(bridge.lot_data['slug'],'new')
