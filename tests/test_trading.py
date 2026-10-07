import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import stalzone_trading as t

class ConfidenceTests(unittest.TestCase):
    def test_stable_fresh_history(self):
        now=time.time()
        r=t.confidence([(100,now-i*60) for i in range(12)],now)
        self.assertEqual(r['level'],'high')
        self.assertEqual(r['count'],12)
    def test_multimillion_mix_is_insufficient(self):
        now=time.time()
        r=t.confidence([(p,now-i*60) for i,p in enumerate([75000,50000,70000,4000000,4000000,4966000])],now)
        self.assertEqual(r['level'],'low')
    def test_old_future_and_invalid_sales_do_not_inflate_sample(self):
        now=time.time()
        r=t.confidence([(100,now-86400),(100,now+10),(0,now),(100,float('nan'))],now)
        self.assertEqual(r['count'],0)
    def test_stale_last_sale(self):
        now=time.time()
        self.assertEqual(t.confidence([(100,now-3*3600-i) for i in range(12)],now)['level'],'low')

class HuntTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'price_watch.json'
        self.hunt=t.HuntStore(self.path)
        self.rule=self.hunt.add('abc','Test',4,0,0,100)
    def tearDown(self): self.temp.cleanup()
    def lot(self,price=200,amount=2,**extra):
        return {'amount':amount,'buyoutPrice':price,'startTime':'2026-10-05T00:00:00Z',
                'additional':{'qlt':4},**extra}
    def test_unit_price_filter_and_dedup(self):
        lots=[self.lot(),self.lot(price=500)]
        self.assertEqual(len(self.hunt.evaluate('abc',lots)),1)
        self.assertEqual(self.hunt.evaluate('abc',lots),[])
        self.hunt.evaluate('abc',[])
        self.assertEqual(len(self.hunt.evaluate('abc',lots)),1)
    def test_variant_personal_bid_only_and_expired_are_ignored(self):
        lots=[self.lot(additional={'qlt':3}),self.lot(additional={'qlt':4,'ptn':5}),
              self.lot(additional={'qlt':4,'personal_on_get':True}),self.lot(price=0),
              self.lot(endTime='2000-01-01T00:00:00Z')]
        self.assertEqual(self.hunt.evaluate('abc',lots),[])
    def test_rules_survive_restart_and_can_be_removed(self):
        restored=t.HuntStore(self.path)
        self.assertEqual(restored.rules()[0]['id'],self.rule['id'])
        restored.remove(self.rule['id'])
        self.assertEqual(t.HuntStore(self.path).rules(),[])
    def test_bid_changes_do_not_repeat_buyout_signal(self):
        self.assertEqual(len(self.hunt.evaluate('abc',[self.lot(currentPrice=10)])),1)
        self.assertEqual(self.hunt.evaluate('abc',[self.lot(currentPrice=20)]),[])
    def test_failed_save_does_not_activate_or_remove_rule(self):
        with patch.object(self.hunt,'_save',side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.hunt.add('new','New',None,0,15,100)
            self.assertEqual(len(self.hunt.rules()),1)
            with self.assertRaises(OSError): self.hunt.remove(self.rule['id'])
            self.assertEqual(len(self.hunt.rules()),1)
    def test_invalid_price_and_rule_limit(self):
        with self.assertRaises(ValueError): self.hunt.add('abc','Test',None,0,15,0)
        with self.assertRaises(ValueError): self.hunt.add('abc','Test',None,15,0,100)
        for i in range(9): self.hunt.add(str(i),'Test',None,0,15,100)
        with self.assertRaises(ValueError): self.hunt.add('overflow','Test',None,0,15,100)

class BridgeHuntTests(unittest.TestCase):
    def setUp(self):
        import stalzone_agent as a
        from stalzone_gui import Bridge
        self.a=a
        self.temp=tempfile.TemporaryDirectory()
        self.dir=patch.object(a,'DIR',Path(self.temp.name)); self.dir.start()
        a.HALT.clear()
        self.bridge=Bridge()
        self.bridge.auction=[{'id':'abc','name':'Test'}]
        self.assertTrue(self.bridge.add_hunt('abc','100',a.QLT[4],0,0)['ok'])
    def tearDown(self):
        self.a.HALT.set()
        self.bridge.stop_hunt()
        if self.bridge.worker: self.bridge.worker.join(2)
        if self.bridge.hunt_worker: self.bridge.hunt_worker.join(2)
        self.a.HALT.clear()
        self.dir.stop(); self.temp.cleanup()
    def test_live_check_needs_no_history_and_notifies_only_once(self):
        lots=[{'amount':2,'buyoutPrice':200,'additional':{'qlt':4}}]
        with patch.object(self.a,'live_lots',return_value=lots),patch.object(self.a,'market_book') as history:
            self.bridge._hunt_check(); self.bridge._hunt_check()
            history.assert_not_called()
        r=self.bridge.poll()['hunt']
        self.assertEqual(len(r['alerts']),1)
        self.assertEqual(r['alerts'][0]['unit'],100)
        self.assertTrue(self.bridge.clear_hunt_alerts()['ok'])
        self.assertEqual(self.bridge.poll()['hunt']['alerts'],[])
    def test_stop_interrupts_wait_and_parallel_launch_is_rejected(self):
        import threading
        entered=threading.Event()
        with patch.object(self.bridge,'_hunt_check',side_effect=entered.set):
            self.assertTrue(self.bridge.start_hunt()['ok'])
            self.assertTrue(entered.wait(2))
            self.assertFalse(self.bridge.start_hunt()['ok'])
            self.bridge.stop_hunt()
            self.bridge.hunt_worker.join(2)
        self.assertFalse(self.bridge.hunt_worker.is_alive())
        self.assertFalse(self.bridge.poll()['busy'])
    def test_invalid_catalog_item_is_rejected(self):
        self.assertFalse(self.bridge.add_hunt('unknown','100','Все',0,15)['ok'])
    def test_low_confidence_does_not_display_buy_instruction(self):
        from stalzone_gui import rows_from
        row={'name':'Test','buyout':100,'med':200,'amount':1,'copies':1,'gain':90,
             'confidence':{'level':'low','detail':'Недостаточно данных'}}
        self.bridge._show({'buys':[row]})
        self.assertIn('Недостаточно данных',rows_from({'buys':[row]})['buys'][0]['cells'][-2])
        self.assertEqual(self.bridge.poll()['compact'][0]['gain'],'—')

    def test_invalid_history_time_is_not_relabelled_as_fresh(self):
        self.assertEqual(self.a._epoch('invalid'),0)

    def test_hunt_runs_beside_scan_and_stops_independently(self):
        import threading
        scan_stop=threading.Event()
        self.bridge.worker=threading.Thread(target=scan_stop.wait,daemon=True)
        self.bridge.worker.start()
        self.bridge._set_busy(True)
        try:
            with patch.object(self.bridge,'_hunt_check'):
                self.assertTrue(self.bridge.start_hunt()['ok'])
                self.bridge.stop_run()
                self.assertFalse(self.bridge._hunt_halt.is_set())
                self.bridge.stop_hunt()
                self.bridge.hunt_worker.join(2)
                self.assertTrue(self.a.HALT.is_set())
                self.assertTrue(self.bridge.poll()['busy'])
        finally:
            scan_stop.set(); self.bridge.worker.join(2)

    def test_stopped_scan_does_not_cancel_hunt_lots(self):
        self.a.HALT.set()
        with patch.object(self.a,'get_json',return_value={'lots':[{'amount':1,'buyoutPrice':100}], 'total':1}) as get:
            lots=self.a.live_lots('abc',stop=self.bridge._hunt_halt,priority=True)
            self.assertEqual(len(lots),1)
            self.assertIs(get.call_args.kwargs['stop'],self.bridge._hunt_halt)

class RequestQueueTests(unittest.TestCase):
    def test_starting_scan_preserves_shared_rate_limit_backoff(self):
        import stalzone_agent as a
        previous=a._GAP
        try:
            a._GAP=.4
            with patch.object(a,'buy_targets',return_value=[]): a.buy_scan()
            self.assertEqual(a._GAP,.4)
        finally:
            a._GAP=previous

    def test_priority_takes_next_slot_without_bypassing_gap(self):
        import threading
        import stalzone_agent as a
        old_next,old_gap=a._NEXT_AT,a._GAP
        order=[]
        with a._PACE:
            a._NEXT_AT=time.time()+.3
            a._GAP=.08
        def take(name,priority):
            a._request_slot(threading.Event(),priority)
            order.append((name,time.time()))
        normal=threading.Thread(target=take,args=('scan',False))
        priority=threading.Thread(target=take,args=('hunt',True))
        try:
            normal.start(); priority.start()
            normal.join(2); priority.join(2)
            self.assertEqual([name for name,_ in order],['hunt','scan'])
            self.assertGreaterEqual(order[1][1]-order[0][1],.07)
        finally:
            a._NEXT_AT,a._GAP=old_next,old_gap
    def test_cancelled_priority_waiter_does_not_block_scan(self):
        import threading
        import stalzone_agent as a
        stopped=threading.Event(); stopped.set()
        with self.assertRaises(RuntimeError): a._request_slot(stopped,True)
        self.assertEqual(a._PRIORITY_WAITERS,0)
