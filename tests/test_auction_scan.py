import tempfile
import threading
import time
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
        sales=[(10,100,now-i*600) for i in range(8)]
        lots=[{'amount':10,'buyoutPrice':700,'additional':{}}]*3
        with patch.object(a,'live_lots',return_value=lots), patch.object(a,'market_book',return_value={'sales':{None:sales},'live':{None:70}}):
            result=a._buy_one(self.item)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['profit'],(100*a.COMM-70)*10)
        self.assertEqual(result[0]['count'],3)
        buys=a._as_buys(result)
        self.assertEqual(buys[0]['gain'], (100*a.COMM-70)*10*3)
        rich=dict(buys[0])
        rich['profit']=4000
        rich['gain']=12000
        self.assertEqual(a.fit_budget([rich],1400),[])
        self.assertEqual(a.fit_budget([rich],2100)[0]['copies'],3)
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
        a._LIVE['abc']=[{'amount':10,'buyoutPrice':p,'additional':{}} for p in [500,800,1000]]
        sales=[(10,150,now-i*600) for i in range(8)]
        result=a.find_flips({'sales':{None:sales}},'abc','Test')
        self.assertEqual([r['buyout'] for r in result],[500])
        self.assertEqual(result[0]['med'],80)

    def test_budget_must_cover_all_lots_required_to_clear_price(self):
        row={'buyout':700,'copies':3,'required_copies':3,'profit':4000,'gain':12000,'per_h':1,'med':200,'amount':10}
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

    def test_thin_spread_dies_to_commission(self):
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

    def test_budget_prefers_rubles_per_hour(self):
        slow={'buyout':1000,'copies':1,'required_copies':1,'profit':50000,'gain':50000,'per_h':0.5,'med':2000,'amount':1}
        fast={'buyout':100,'copies':1,'required_copies':1,'profit':20000,'gain':20000,'per_h':4,'med':200,'amount':1}
        self.assertEqual(a.fit_budget([slow, fast], 100000)[0]['buyout'], 100)
        self.assertGreater(a.fit_budget([slow, fast], 100000)[0]['hour_gain'], 25000)

    def test_high_percent_with_a_thousand_profit_is_not_a_buy(self):
        crumb={'buyout':2000,'copies':1,'required_copies':1,'profit':1000,'gain':1000,'roi':0.5,'per_h':10,'med':3000,'amount':1}
        real={'buyout':200000,'copies':1,'required_copies':1,'profit':20000,'gain':20000,'roi':0.1,'per_h':1,'med':250000,'amount':1}
        picked=a.fit_budget([crumb, real], 500000)
        self.assertEqual(len(picked),1)
        self.assertEqual(picked[0]['gain'],20000)

    def test_old_sales_listed_first_still_count_the_newest(self):
        now=time.time()
        a._LIVE['abc']=[{'amount':10,'buyoutPrice':500,'additional':{}}]
        sales=[(10,150,now-3600*(8-i)) for i in range(8)]
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
