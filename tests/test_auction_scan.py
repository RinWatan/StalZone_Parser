import tempfile
import threading
import time
import math
import os
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
import stalzone_agent as a

class ScanTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.dir_patch=patch.object(a,'DIR',Path(self.temp.name)); self.dir_patch.start()
        a.HALT.clear(); a._LIVE.clear(); a._BOOK.clear(); a._QUIET=None; a._OFF=None; a._SELL=None
        self.item=('abc','Test item',False,1,1)
    def tearDown(self):
        a.HALT.clear(); a._LIVE.clear(); a._BOOK.clear()
        self.dir_patch.stop(); self.temp.cleanup()
    def test_listing_keeps_the_same_items_as_the_archive(self):
        rows = [
            {"data": "/items/supply/medicine/9mmq.json", "name": {"lines": {"ru": "Аптечка"}}, "color": "RANK_VETERAN"},
            {"data": "/items/other/quest.json", "name": {"lines": {"ru": "Квест"}}, "color": "QUEST_ITEM"},
            {"data": "/items/armor/scientist/_variants/p69k2/10.json", "name": {"lines": {"ru": "Вариант"}}, "color": "RANK_MASTER"},
            {"data": "/items/misc/nope.json"},
        ]
        items = a._items_in_listing(rows)
        self.assertEqual(
            items,
            [
                {"id": "nope", "name": "nope", "cat": "misc", "color": "DEFAULT"},
                {"id": "9mmq", "name": "Аптечка", "cat": "supply", "color": "RANK_VETERAN"},
            ],
        )

    def test_unchanged_database_is_not_downloaded_again(self):
        path = a.DIR / "catalog.json"
        saved = [{"id": "abc", "name": "Тест", "cat": "misc", "color": "DEFAULT"}]
        path.write_text(json.dumps(saved), encoding="utf-8")
        old = time.time() - 4 * 86400
        path.touch()
        os.utime(path, (old, old))
        with patch.object(a, "_catalog_from_exbo", return_value=None):
            self.assertEqual(a._load_catalog(), saved)
        self.assertGreater(path.stat().st_mtime, old + 1000)

    def test_broken_listing_falls_back_to_the_archive(self):
        fallback = [{"id": "a", "name": "A", "cat": "misc", "color": "DEFAULT"}]
        with patch.object(a, "_catalog_from_listing", side_effect=httpx.HTTPError("нет списка")), \
             patch.object(a, "_catalog_from_zip", return_value=fallback) as archive:
            self.assertEqual(a._catalog_from_exbo(), fallback)
            archive.assert_called_once()

    def test_empty_lots_require_no_history(self):
        with patch.object(a,'live_lots',return_value=[]), patch.object(a,'get_json') as get:
            self.assertEqual(a._buy_one(self.item),[])
            get.assert_not_called()
    def test_empty_lots_are_skipped_on_the_next_scan(self):
        with patch.object(a,'live_lots',return_value=[]), patch.object(a,'get_json') as get:
            self.assertEqual(a._buy_one(self.item),[])
            get.assert_not_called()
        with patch.object(a,'auction_listing',return_value=[{'id':'abc','name':'Test item','cat':'medicine','color':'DEFAULT'}]):
            self.assertEqual(a.buy_targets(),[])
    def test_stop_does_not_issue_more_requests(self):
        a.HALT.set()
        with patch.object(a,'live_lots') as lots, patch.object(a,'get_json') as get:
            self.assertEqual(a._buy_one(self.item),[])
            lots.assert_not_called(); get.assert_not_called()
    def test_bid_only_lots_require_no_history(self):
        with patch.object(a,'live_lots',return_value=[{'amount':10,'buyoutPrice':0}]), patch.object(a,'get_json') as get:
            self.assertEqual(a._buy_one(self.item),[]); get.assert_not_called()
    def test_profitable_buy_preserves_liquidity_and_commission(self):
        now=time.time()
        sales=[(10,5000,now-i*600) for i in range(8)]
        lots=[{'amount':10,'buyoutPrice':15000,'additional':{}}]*3
        with patch.object(a,'live_lots',return_value=lots), patch.object(a,'market_book',return_value={'sales':{None:sales},'live':{None:1500}}):
            result=a._buy_one(self.item)
        self.assertEqual(len(result),1)
        profit=math.floor(5000*10*a.COMM)-15000
        self.assertEqual(result[0]['profit'], profit)
        self.assertGreaterEqual(profit, a.TRACKER_MIN)
        self.assertEqual(result[0]['count'],3)
        buys=a._as_buys(result)
        self.assertEqual(buys[0]['gain'], profit*3)
        self.assertEqual(a.fit_budget(buys,30000),[])
        self.assertEqual(a.fit_budget(buys,45000)[0]['copies'],3)
    def test_stop_cancels_queued_items(self):
        seen=[]; lock=threading.Lock()
        def process(item):
            with lock:
                seen.append(item[0])
                a.HALT.set()
            time.sleep(.01)
            return []
        items=[(str(i),'item',False,1,1) for i in range(80)]
        with patch.object(a,'buy_targets',return_value=items),patch.object(a,'_buy_one',side_effect=process):
            a.buy_scan()
        self.assertLessEqual(len(seen),8)

    def test_leech_does_not_skip_cheaper_competing_offers(self):
        now=time.time()
        prices=[75000,77777,77777,80000,89000,90000,100000,810520]
        a._LIVE['leech']=[{'amount':1,'buyoutPrice':p,'additional':{'qlt':4}} for p in prices]
        sales=[(1,p,now-i*600) for i,p in enumerate([4000000,75000,4000000,50000,4966000,70000])]
        self.assertEqual(a.find_flips({'sales':{(4,0):sales}},'leech','Leech',True),[])

    def test_cannot_raise_price_when_equal_price_lots_remain(self):
        now=time.time()
        a._LIVE['abc']=[{'amount':10,'buyoutPrice':700,'additional':{}}]*20
        sales=[(10,100,now-i*3600) for i in range(8)]
        self.assertEqual(a.find_flips({'sales':{None:sales}},'abc','Test'),[])

    def test_recommends_only_cheapest_profitable_tier(self):
        now=time.time()
        a._LIVE['abc']=[{'amount':10,'buyoutPrice':p,'additional':{}} for p in [500,12000]]
        sales=[(10,5000,now-i*600) for i in range(8)]
        result=a.find_flips({'sales':{None:sales}},'abc','Test')
        self.assertEqual([r['buyout'] for r in result],[500])
        self.assertEqual(result[0]['med'],1200)

    def test_budget_must_cover_all_lots_required_to_clear_price(self):
        row={'buyout':700,'copies':3,'required_copies':3,'profit':250,'gain':750,'per_h':1,'med':200,'amount':10}
        self.assertEqual(a.fit_budget([row],1400),[])
        self.assertEqual(a.fit_budget([row],2100)[0]['copies'],3)

    def test_spike_sales_do_not_invent_a_resale_price(self):
        now=time.time()
        a._LIVE['abc']=[{'amount':1,'buyoutPrice':200000,'additional':{}}]
        sales=[(1,p,now-i*600) for i,p in enumerate([4000000,75000,4000000,50000,4966000,70000,60000,80000])]
        self.assertEqual(a.find_flips({'sales':{None:sales}},'abc','Test',True),[])

    def test_normal_sales_show_buy_then_resell_profit(self):
        now=time.time()
        a._LIVE['abc']=[{'amount':1,'buyoutPrice':50000,'additional':{}}]
        sales=[(1,80000,now-i*600) for i in range(8)]
        result=a.find_flips({'sales':{None:sales}},'abc','Test',True)
        self.assertEqual(len(result),1)
        bought=a._as_buys(result)[0]
        self.assertIn('Купи 1 по 50000', bought['plan'])
        self.assertIn('Плюс', bought['plan'])
        self.assertGreater(bought['gain'], 0)
        self.assertGreater(bought['med'] * a.COMM, bought['unit'])

    def test_price_under_commission_is_not_a_buy(self):
        now=time.time()
        a._LIVE['abc']=[{'amount':1,'buyoutPrice':96000,'additional':{}}]
        sales=[(1,100000,now-i*600) for i in range(8)]
        self.assertEqual(a.find_flips({'sales':{None:sales}},'abc','Test',True),[])

    def test_lot_a_bit_under_the_sale_is_a_buy(self):
        now=time.time()
        a._LIVE['abc']=[{'amount':1,'buyoutPrice':80000,'additional':{}}]
        sales=[(1,100000,now-i*600) for i in range(8)]
        result=a.find_flips({'sales':{None:sales}},'abc','Test',True)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['profit'],100000*a.COMM-80000)
        self.assertGreaterEqual(result[0]['profit'], a.TRACKER_MIN)

    def test_three_thousand_does_not_clear_the_tracker_floor(self):
        now=time.time()
        a._LIVE['abc']=[{'amount':1,'buyoutPrice':92000,'additional':{}}]
        sales=[(1,100000,now-i*600) for i in range(8)]
        self.assertEqual(a.find_flips({'sales':{None:sales}},'abc','Test',True),[])

    def test_spike_sales_do_not_raise_the_buy_count(self):
        now=time.time()
        a._LIVE['abc']=[{'amount':10,'buyoutPrice':500,'additional':{}}]*3
        sales=[(10,5000,now-i*60) for i in range(6)]
        sales += [(10,150,now-1800-i*2400) for i in range(6)]
        self.assertEqual(a.find_flips({'sales':{None:sales}},'abc','Test'),[])

    def test_bigger_plus_outranks_a_high_percent(self):
        slow={'buyout':1000,'copies':1,'required_copies':1,'profit':50000,'gain':50000,'per_h':0.5,'med':2000,'amount':1}
        fast={'buyout':100,'copies':1,'required_copies':1,'profit':20000,'gain':20000,'per_h':4,'med':200,'amount':1}
        self.assertEqual(a.fit_budget([slow, fast], 100000)[0]['gain'], 50000)

    def test_high_percent_with_a_thousand_stays_below_real_money(self):
        crumb={'buyout':2000,'copies':1,'required_copies':1,'profit':1000,'gain':1000,'roi':0.5,'per_h':10,'med':3000,'amount':1}
        real={'buyout':200000,'copies':1,'required_copies':1,'profit':20000,'gain':20000,'roi':0.1,'per_h':1,'med':250000,'amount':1}
        picked=a.fit_budget([crumb, real], 500000)
        self.assertEqual([row['gain'] for row in picked], [20000, 1000])

    def test_old_sales_listed_first_still_count_the_newest(self):
        now=time.time()
        a._LIVE['abc']=[{'amount':10,'buyoutPrice':500,'additional':{}}]
        sales=[(10,2000,now-3600*(8-i)) for i in range(8)]
        result=a.find_flips({'sales':{None:sales}},'abc','Test')
        self.assertEqual(len(result),1)

    def test_arts_are_queued_before_the_rest(self):
        catalog=[
            {'id':'med','name':'Бинт','cat':'medicine','color':'DEFAULT'},
            {'id':'art','name':'Гребешок','cat':'artefact','color':'DEFAULT'},
            {'id':'gun','name':'АК','cat':'weapon','color':'RANK_MASTER'},
        ]
        with patch.object(a,'auction_listing',return_value=catalog), patch.object(a,'quiet_lots',return_value=set()), patch.object(a,'_off_auction',return_value=set()):
            ids=[row[0] for row in a.buy_targets()]
        self.assertEqual(ids[0],'art')
        self.assertLess(ids.index('art'), ids.index('med'))
        self.assertLess(ids.index('art'), ids.index('gun'))

    def test_dear_lots_skip_history(self):
        a._SELL={'abc|10|None': {'sell': 100, 'ts': time.time()}}
        lots=[{'amount':10,'buyoutPrice':980,'additional':{}}]
        with patch.object(a,'live_lots',return_value=lots), patch.object(a,'market_book') as book:
            self.assertEqual(a._buy_one(self.item),[])
            book.assert_not_called()

    def test_art_tab_uses_the_buy_floor(self):
        now=time.time()
        sales=[(1,100000,now-i*600) for i in range(8)]
        book={'sales':{(3,0):sales},'live':{}}
        a._LIVE['gyq5']=[{'amount':1,'buyoutPrice':92000,'additional':{'qlt':3,'ptn':0}}]
        with patch.object(a,'market_book',return_value=book):
            self.assertEqual(a._art_one(('gyq5','Спираль')),[])
        a._LIVE['gyq5']=[{'amount':1,'buyoutPrice':80000,'additional':{'qlt':3,'ptn':0}}]
        with patch.object(a,'market_book',return_value=book):
            rows=a._art_one(('gyq5','Спираль'))
        self.assertEqual(rows[0]['liq'],'ВЫКУПИТЬ')
        self.assertGreaterEqual(rows[0]['net'], a.TRACKER_MIN)

    def test_open_item_names_the_median_and_the_floor(self):
        now=time.time()
        lots=[{'amount':1,'buyoutPrice':92000,'additional':{'qlt':3,'ptn':0}}]
        sales={(3,0):[(1,100000,now-i*600) for i in range(8)]}
        text=a.flip_reason('gyq5','Спираль',lots,sales,True)
        self.assertIn('92000', text)
        self.assertIn('100000', text)
        self.assertIn(str(a.TRACKER_MIN), text)
        self.assertIn('после 5%', text)

    def test_favourite_skips_the_category_block(self):
        catalog=[
            {'id':'mod','name':'Подвижный','cat':'weapon_modules','color':'DEFAULT'},
            {'id':'dust','name':'Пыль','cat':'bullet','color':'DEFAULT'},
            {'id':'art','name':'Гребешок','cat':'artefact','color':'DEFAULT'},
            {'id':'med','name':'Бинт','cat':'medicine','color':'DEFAULT'},
        ]
        with patch.object(a,'auction_listing',return_value=catalog), patch.object(a,'quiet_lots',return_value=set()), patch.object(a,'_off_auction',return_value=set()):
            plain=[row[0] for row in a.buy_targets()]
            starred=[row[0] for row in a.buy_targets(['mod','dust'])]
        self.assertNotIn('mod', plain)
        self.assertNotIn('dust', plain)
        self.assertLess(starred.index('art'), starred.index('mod'))
        self.assertLess(starred.index('art'), starred.index('dust'))
        self.assertIn('med', starred)

    def test_favourite_is_not_muted_after_an_empty_lot(self):
        catalog=[{'id':'mod','name':'Подвижный','cat':'weapon_modules','color':'DEFAULT'}]
        with patch.object(a,'auction_listing',return_value=catalog), patch.object(a,'quiet_lots',return_value={'mod'}), patch.object(a,'_off_auction',return_value=set()):
            self.assertEqual(a.buy_targets(),[])
            self.assertEqual(a.buy_targets(['mod'])[0][0],'mod')

    def test_missing_item_stays_out_even_if_favourite(self):
        catalog=[{'id':'mod','name':'Подвижный','cat':'weapon_modules','color':'DEFAULT'}]
        with patch.object(a,'auction_listing',return_value=catalog), patch.object(a,'quiet_lots',return_value=set()), patch.object(a,'_off_auction',return_value={'mod'}):
            self.assertEqual(a.buy_targets(['mod']),[])

class RetryTests(unittest.TestCase):
    def setUp(self):
        self.old_gap,self.old_next=a._GAP,a._NEXT_AT
        a._GAP=.12; a._NEXT_AT=0
        self.url=a.EXBO+'/RU/auction/abc/lots'
        self.headers=patch.object(a,'exbo_headers',return_value={}); self.headers.start()
        self.sleep=patch.object(a.time,'sleep'); self.sleep.start()
        self.backoff=patch.object(a.HALT,'wait',return_value=False); self.wait=self.backoff.start()
    def tearDown(self):
        self.headers.stop(); self.sleep.stop()
        self.backoff.stop(); a.HALT.clear()
        a._GAP,a._NEXT_AT=self.old_gap,self.old_next
    def response(self,status):
        return httpx.Response(status,request=httpx.Request('GET',self.url),json={'lots':[]})
    def test_permanent_error_is_not_retried_or_pool_closed(self):
        with patch.object(a,'_client') as client,patch.object(a,'_reset_client') as reset:
            client.return_value.get.return_value=self.response(400)
            with self.assertRaises(httpx.HTTPStatusError): a.get_json(self.url)
            self.assertEqual(client.return_value.get.call_count,1)
            reset.assert_not_called()
            self.assertEqual(a._GAP,.12)
    def test_temporary_server_error_retries_without_closing_pool(self):
        with patch.object(a,'_client') as client,patch.object(a,'_reset_client') as reset:
            client.return_value.get.side_effect=[self.response(503),self.response(200)]
            self.assertEqual(a.get_json(self.url),{'lots':[]})
            self.assertEqual(client.return_value.get.call_count,2); reset.assert_not_called()
    def test_rate_limit_retries_without_closing_other_workers(self):
        with patch.object(a,'_client') as client,patch.object(a,'_reset_client') as reset:
            client.return_value.get.side_effect=[self.response(429),self.response(200)]
            a.get_json(self.url)
            self.assertEqual(client.return_value.get.call_count,2); reset.assert_not_called()
            self.assertGreater(a._GAP,.12)
    def test_repeated_rate_limit_is_retried(self):
        with patch.object(a,'_client') as client,patch.object(a,'_reset_client') as reset:
            client.return_value.get.side_effect=[self.response(429),self.response(429),self.response(429),self.response(200)]
            self.assertEqual(a.get_json(self.url),{'lots':[]})
            self.assertEqual(client.return_value.get.call_count,4)
            reset.assert_not_called()
    def test_stop_during_server_backoff_prevents_retry(self):
        def stop(_):
            a.HALT.set()
            return True
        self.wait.side_effect=stop
        with patch.object(a,'_client') as client:
            response=self.response(429)
            response.headers['Retry-After']='86400'
            client.return_value.get.side_effect=[response,self.response(200)]
            with self.assertRaises(httpx.HTTPStatusError): a.get_json(self.url)
            self.assertEqual(client.return_value.get.call_count,1)
    def test_retry_after_is_respected(self):
        with patch.object(a,'_client') as client:
            response=self.response(429); response.headers['Retry-After']='3'
            client.return_value.get.side_effect=[response,self.response(200)]
            a.get_json(self.url)
            self.wait.assert_called_once_with(3)

if __name__=='__main__': unittest.main()
