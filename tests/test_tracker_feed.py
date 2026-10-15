import json
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import stalzone_agent as agent
import stalzone_tracker as tracker


def offer(**extra):
    row={'uniqueId':123,'itemId':'abc12','name':'Test','amount':1,'cost':70,
         'qlt':None,'ptn':None,'targetPrice':100}
    row.update(extra)
    return row


class CandidateTests(unittest.TestCase):
    def test_normalizes_price_quantity_and_known_alias(self):
        c=tracker.candidate(offer(itemId='HJC257QV5D',name='Протоартефакт',qlt=2),1000,10)
        self.assertEqual(c.slug,'dm6l2')
        self.assertEqual(c.variant,(2,0))
    def test_invalid_or_over_budget_candidates_are_ignored(self):
        for extra in ({'cost':0},{'cost':float('nan')},{'amount':0},
                      {'itemId':'../invalid'},{'cost':1001},{'module':{'id':'unknown'}},
                      {'qlt':99},{'name':'','itemId':'UPPER_UNKNOWN'}):
            self.assertIsNone(tracker.candidate(offer(**extra),1000,10),extra)
    def test_budget_is_for_whole_lot_not_unit(self):
        self.assertIsNone(tracker.candidate(offer(amount=100,cost=2000),1000,10))
    def test_duplicate_events_coalesce_and_queue_is_bounded(self):
        q=tracker.Candidates(1000,max_items=2)
        message={'type':'snapshot','data':[offer(),offer()]}
        q.ingest(message,10)
        self.assertEqual(q.queued(),1)
        self.assertEqual(q.take(10)[0].slug,'abc12')
        q.ingest(message,11)
        self.assertEqual(q.queued(),0)
        for i in range(5): q.ingest({'type':'lots_update','data':[offer(uniqueId=i+2,itemId=f'id{i}')]},12)
        self.assertLessEqual(q.queued(),2)
        self.assertLessEqual(len(q.active),2)
    def test_expired_candidates_and_unknown_messages_do_not_trigger_checks(self):
        q=tracker.Candidates(1000)
        q.ingest({'type':'snapshot','data':[offer()]},10)
        self.assertFalse(q.take(200))
        q.ingest({'type':'custom_lots_update','data':[offer()]},200)
        self.assertEqual(q.queued(),0)


class VerifyTests(unittest.TestCase):
    def setUp(self):
        agent.HALT.clear()
        self.now=time.time()
        self.c=tracker.candidate(offer(),1000,self.now)
        self.lots=[{'amount':1,'buyoutPrice':70,'additional':{}}]
        self.raw={'prices':[{'amount':1,'price':100,'time':self.now-i*60} for i in range(12)]}
        self.epoch=patch.object(agent,'_epoch',side_effect=lambda value:value); self.epoch.start()
        self.v=tracker.Verifier(agent)
    def tearDown(self):
        self.epoch.stop(); agent.HALT.clear()
    def test_missing_lot_skips_history(self):
        with patch.object(agent,'live_lots',return_value=[]),patch.object(agent,'get_json') as get:
            self.assertEqual(self.v.check([self.c]),[])
            get.assert_not_called()

    def test_current_exbo_offer_required_and_tracker_target_not_used_for_profit(self):
        c=tracker.candidate(offer(targetPrice=10000000),1000,self.now)
        with patch.object(agent,'live_lots',return_value=self.lots),patch.object(agent,'get_json',return_value=self.raw),patch.object(agent,'cached_live') as cache:
            rows=self.v.check([c])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['med'],100)
        self.assertEqual(rows[0]['profit'],25)
        self.assertEqual(rows[0]['source'],'SZ Tracker → EXBO')
        cache.assert_not_called()
    def test_wrong_amount_quality_or_price_does_not_match(self):
        for extra in ({'amount':2},{'cost':71},{'qlt':4}):
            c=tracker.candidate(offer(**extra),1000,self.now)
            with patch.object(agent,'live_lots',return_value=self.lots),patch.object(agent,'get_json') as get:
                self.assertEqual(self.v.check([c]),[])
                get.assert_not_called()
    def test_history_cached_but_lots_refetched(self):
        with patch.object(agent,'live_lots',return_value=self.lots) as live,patch.object(agent,'get_json',return_value=self.raw) as history:
            self.v.check([self.c]); self.v.check([self.c])
        self.assertEqual(live.call_count,2)
        self.assertEqual(history.call_count,1)
    def test_expired_live_offer_is_not_confirmed(self):
        lots=[dict(self.lots[0],endTime='2000-01-01T00:00:00Z')]
        with patch.object(agent,'live_lots',return_value=lots),patch.object(agent,'get_json') as get:
            self.assertEqual(self.v.check([self.c]),[])
            get.assert_not_called()

    def test_slow_history_does_not_relabel_old_lots_as_fresh(self):
        clock=[self.now]
        v=tracker.Verifier(agent,clock=lambda:clock[0])
        def history(_):
            clock[0]+=50
            return self.raw
        with patch.object(agent,'live_lots',return_value=self.lots),patch.object(agent,'get_json',side_effect=history):
            self.assertEqual(v.check([self.c]),[])

    def test_lot_expiring_during_history_request_is_not_published(self):
        clock=[self.now]
        v=tracker.Verifier(agent,clock=lambda:clock[0])
        def history(_):
            clock[0]+=20
            return self.raw
        lots=[dict(self.lots[0],endTime=self.now+10)]
        with patch.object(agent,'live_lots',return_value=lots),patch.object(agent,'get_json',side_effect=history):
            self.assertEqual(v.check([self.c]),[])

    def test_other_variants_do_not_suppress_candidate_before_matching(self):
        lots=self.lots+[{'amount':1,'buyoutPrice':100,'additional':{'qlt':q}} for q in range(3)]
        raw={'prices':self.raw['prices']+[dict(r,price=1000,additional={'qlt':q}) for q in range(3) for r in self.raw['prices']]}
        with patch.object(agent,'live_lots',return_value=lots),patch.object(agent,'get_json',return_value=raw):
            rows=self.v.check([self.c])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['buyout'],70)


def verified_row(now):
    return {'name':'Test','slug':'abc12','buyout':70,'amount':1,'unit':70,'med':100,
            'profit':25,'gain':25,'copies':1,'count':1,'required_copies':1,'per_h':2,
            'qlt_i':None,'ptn':'','verified_at':now,'source':'SZ Tracker → EXBO'}


class EngineTests(unittest.TestCase):
    def setUp(self): agent.HALT.clear()
    def tearDown(self): agent.HALT.clear()
    def test_expiry_disconnect_and_source_stale_hide_rows(self):
        e=tracker.TrackerFeed(agent,1000,lambda _:None,lambda _:None)
        now=time.time()
        e.pool.ingest({'type':'snapshot','data':[offer()]},now)
        e.results={'abc12':[verified_row(now)]}
        e.connected=True
        self.assertEqual(len(e.visible(now)),1)
        self.assertEqual(e.visible(now+46),[])
        e.connected=False
        self.assertEqual(e.visible(now),[])
        e.connected=True
        e.ingest({'type':'sourceStatus','stale':True})
        self.assertEqual(e.visible(now),[])

    def test_socket_reader_stops_and_candidates_are_checked_without_catalog(self):
        import websocket
        closed=threading.Event()
        class Socket:
            first=True
            def recv(self):
                if self.first:
                    self.first=False
                    return json.dumps({'type':'snapshot','data':[offer()]})
                closed.wait(.02)
                raise websocket.WebSocketTimeoutException()
            def close(self,timeout=1): closed.set()
        updates=[]
        def update(rows):
            updates.append(rows)
            if rows: agent.HALT.set()
        e=tracker.TrackerFeed(agent,1000,update,lambda _:None,connect=Socket)
        with patch.object(e.verifier,'check',return_value=[verified_row(time.time())]) as check,patch.object(agent,'auction_listing') as catalog:
            worker=threading.Thread(target=e.run,daemon=True)
            worker.start(); worker.join(2)
            try:
                self.assertFalse(worker.is_alive())
                check.assert_called_once()
                catalog.assert_not_called()
                self.assertTrue(any(updates))
                self.assertTrue(closed.is_set())
                self.assertEqual(updates[-1],[])
            finally:
                agent.HALT.set(); worker.join(2)

    def test_bridge_poll_enforces_expiry_even_while_checker_is_blocked(self):
        from stalzone_gui import Bridge
        bridge=Bridge()
        now=time.time()
        bridge._tracker_state={'running':True,'connected':True}
        bridge._tracker_rows=[verified_row(now)]
        self.assertTrue(bridge.poll()['compact'])
        with patch('stalzone_gui.time.time',return_value=now+46):
            self.assertFalse(bridge.poll()['compact'])
        bridge._tracker_state['connected']=False
        bridge._tracker_rows=[verified_row(now)]
        self.assertFalse(bridge.poll()['compact'])
