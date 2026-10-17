import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import stalzone_agent as agent
import stalzone_tracker as tracker
from stalzone_gui import Bridge


def mirror(**extra):
    row={'uniqueId':1,'itemId':'zyrm','name':'Зеркало','qlt':3,'ptn':10,
         'cost':1600000,'amount':1,'targetPrice':2000000,'salesPerDay30d':0.9,
         'metrics':{'median':2600000,'sampleSize':27,'periods':{
             '7d':{'median':2600000,'sampleSize':6},
             '30d':{'median':2600000,'sampleSize':27}}}}
    row.update(extra)
    return row


class ResaleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.directory=patch.object(agent,'DIR',Path(self.temp.name))
        self.directory.start()

    def tearDown(self):
        self.directory.stop()
        self.temp.cleanup()

    def test_website_uses_selected_median_not_raw_weighted_target(self):
        c=tracker.candidate(mirror(),6400000,100)
        self.assertEqual(c.target_price,2600000)
        self.assertEqual(c.priority,870000)
        self.assertEqual(c.estimate_period,'7д')
        self.assertEqual(c.estimate_samples,6)

    def test_rare_sales_expand_period_and_stack_price_is_per_unit_times_amount_once(self):
        row=mirror(name='Инструменты',amount=83,cost=1300000,
            metrics={'median':20000,'sampleSize':20,'periods':{
                '7d':{'median':1,'sampleSize':1},
                '14d':{'median':20000,'sampleSize':4}}})
        c=tracker.candidate(row,6400000,100)
        self.assertEqual(c.target_price,1660000)
        self.assertEqual(c.estimate_period,'14д')
        self.assertEqual(c.priority,277000)

    def test_rare_valuable_lot_visible_before_exbo_and_not_removed_by_old_flip_rules(self):
        states=[]
        e=tracker.TrackerFeed(agent,6400000,lambda _:None,states.append,clock=lambda:100)
        e.connected=True
        e.ingest({'type':'snapshot','data':[mirror()]})
        e.report()
        r=states[-1]['feed_rows'][0]
        self.assertEqual(r['estimated_profit'],870000)
        self.assertEqual(r['sales_per_day'],0.9)
        self.assertEqual(r['availability'],'Не проверено')

    def test_lot_existence_is_exposed_even_if_legacy_flip_filter_rejects(self):
        agent.HALT.clear()
        now=time.time()
        c=tracker.candidate(mirror(),6400000,now)
        v=tracker.Verifier(agent)
        lots=[{'buyoutPrice':1600000,'amount':1,'additional':{'qlt':3,'ptn':10}}]
        with patch.object(agent,'live_lots',return_value=lots),patch.object(agent,'get_json',return_value={'prices':[]}):
            self.assertEqual(v.check([c]),[])
        self.assertEqual(v.availability[c.identity],True)

    def test_partial_exbo_page_cannot_establish_absence(self):
        agent.HALT.clear()
        c=tracker.candidate(mirror(),6400000,time.time())
        v=tracker.Verifier(agent)
        lots=[{'buyoutPrice':10,'amount':1,'additional':{}}]*800
        with patch.object(agent,'live_lots',return_value=lots):v.check([c])
        self.assertIsNone(v.availability[c.identity])

    def test_zero_source_estimate_does_not_gate_independent_exbo_check(self):
        pool=tracker.Candidates(6400000)
        pool.ingest({'type':'snapshot','data':[mirror(targetPrice=0,metrics=None)]},100)
        self.assertEqual(len(pool.take(100)),1)

    def test_good_observation_survives_three_minutes_and_low_value_item_eviction(self):
        pool=tracker.Candidates(6400000,max_items=2)
        pool.ingest({'type':'snapshot','data':[mirror()]},100)
        for i in range(3):
            pool.ingest({'type':'lots_update','data':[mirror(uniqueId=i+2,itemId=f'id{i}',
                cost=100,targetPrice=110,metrics=None)]},100+i)
        pool.prune(301)
        self.assertIn('zyrm',pool.active)

    def test_confirmed_absent_high_profit_cannot_evict_new_usable_offer(self):
        pool=tracker.Candidates(6400000,max_items=1)
        pool.ingest({'type':'snapshot','data':[mirror()]},100)
        pool.unavailable.add(pool.active['zyrm'][0].identity)
        pool.ingest({'type':'lots_update','data':[mirror(uniqueId=2,itemId='newid',
            cost=700000,targetPrice=980000,metrics=None)]},200)
        self.assertIn('newid',pool.active)

    def test_main_resale_ranks_profit_and_applies_user_thresholds_not_trade_velocity(self):
        bridge=Bridge()
        now=time.time()
        def source(name,cost,target,sales):
            return {'name':name,'cost':cost,'amount':1,'target_price':target,'qlt':3,'ptn':10,
                    'received_at':now,'status':'В очереди EXBO','availability':'Не проверено',
                    'estimate_period':'7д','estimate_samples':6,'sales_per_day':sales,
                    'estimated_profit':int(target*.95)-cost}
        bridge._tracker_state={'running':True,'connected':True,'feed_rows':[
            source('ОЦ-62',250000,280000,190),source('Зеркало',1600000,2600000,0.9),
            source('Чёртов еж',700000,980000,0.1)]}
        result=bridge.poll()
        self.assertEqual([r['cells'][0] for r in result['tables']['resale']],['Зеркало','Чёртов еж'])
        self.assertEqual(result['resale_compact'][0]['name'],'Зеркало')
        self.assertIn('870',result['resale_compact'][0]['gain'])
        bridge.set_tracker_filters('300000','10')
        self.assertEqual(len(bridge.poll()['tables']['resale']),1)


if __name__=='__main__':unittest.main()
