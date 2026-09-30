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
        a.HALT.clear(); a._LIVE.clear(); a._BOOK.clear()
        self.item=('abc','Test item',False,1,1)
    def tearDown(self):
        a.HALT.clear(); a._LIVE.clear(); a._BOOK.clear()
        self.dir_patch.stop(); self.temp.cleanup()
    def test_empty_lots_require_no_history(self):
        with patch.object(a,'live_lots',return_value=[]), patch.object(a,'get_json') as get:
            self.assertEqual(a._buy_one(self.item),[])
            get.assert_not_called()
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
