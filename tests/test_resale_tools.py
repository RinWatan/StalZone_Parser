import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import stalzone_agent as agent
import stalzone_tracker as tracker
from stalzone_gui import Bridge, resale_candidates


def artifact(**extra):
    row={'uniqueId':1,'itemId':'zyrm','name':'Зеркало','category':'artefact',
         'qlt':3,'ptn':10,'amount':1,'cost':1600000,'targetPrice':2600000,
         'explored':True,'charge':87,'qltInfo':{'labelPercentQlt':'132,1%'},
         'bonusInfo':['Регенерация здоровья'],
         'defaultBonusInfo':{'defaultBonuses':[{'bonusName':'Переносимый вес','textMinAndMax':'+10,5'}]},
         'metrics':{'median':2600000,'sampleSize':6}}
    row.update(extra)
    return row


class ToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.patch=patch.object(agent,'DIR',Path(self.temp.name));self.patch.start()
        self.bridge=Bridge()
        self.now=time.time()
        states=[]
        self.engine=tracker.TrackerFeed(agent,6400000,lambda _:None,states.append)
        self.engine.connected=True
        self.engine.ingest({'type':'snapshot','data':[artifact()]});self.engine.report()
        self.bridge._tracker_state=states[-1]
    def tearDown(self):
        self.patch.stop();self.temp.cleanup();agent.HALT.clear()

    def test_public_characteristics_reach_details_without_claiming_exact_exbo_match(self):
        row=self.bridge.poll()['tables']['resale'][0]
        detail=self.bridge.resale_detail(row['detail_id'])
        self.assertTrue(detail['ok'])
        self.assertIn('Переносимый вес',str(detail['attributes']))
        self.assertIn('Регенерация здоровья',str(detail['attributes']))
        self.assertEqual(detail['calculation']['profit'],870000)
        self.assertEqual(detail['calculation']['net'],2470000)
        self.assertIn('случайные',str(detail['warnings']))
        self.assertIn('проходит текущие',str(detail['basis']))

    def test_advanced_filters_apply_to_main_and_compact_and_validate_ranges(self):
        self.assertTrue(self.bridge.set_tracker_filters('100000','10',{'category':'weapon'})['ok'])
        self.assertFalse(self.bridge.poll()['resale_compact'])
        self.bridge.set_tracker_filters('100000','10',{'category':'artefact','quality':3,
            'refine_min':10,'refine_max':15,'explored':'explored','include':'зеркало','exclude':'ёж'})
        self.assertEqual(len(self.bridge.poll()['resale_compact']),1)
        self.bridge.set_tracker_filters('100000','10',{'exclude':'ЗЕРКАЛО'})
        self.assertFalse(self.bridge.poll()['resale_compact'])
        self.assertFalse(self.bridge.set_tracker_filters('100000','10',{'refine_min':15,'refine_max':5})['ok'])

    def test_presets_roundtrip_delete_and_legacy_filter_settings(self):
        self.bridge.set_tracker_filters('250000','15',{'category':'artefact','quality':3})
        self.assertTrue(self.bridge.save_tracker_preset('Мои артефакты')['ok'])
        other=Bridge()
        self.assertEqual(other.boot()['tracker_filters']['quality'],3)
        self.assertIn('Мои артефакты',other.boot()['tracker_presets'])
        other.set_tracker_filters('100000','10',{'quality':None})
        loaded=other.load_tracker_preset('Мои артефакты')
        self.assertTrue(loaded['ok']);self.assertEqual(loaded['filters']['min_profit'],250000)
        self.assertEqual(loaded['filters']['quality'],3)
        self.assertTrue(other.delete_tracker_preset('Мои артефакты')['ok'])
        self.assertNotIn('Мои артефакты',Bridge().boot()['tracker_presets'])
        (agent.DIR/'tracker_filters.json').write_text(json.dumps({'min_profit':10,'min_roi':2}),encoding='utf-8')
        self.assertEqual(Bridge().boot()['tracker_filters']['category'],'all')

    def test_unknown_artifact_properties_do_not_turn_into_studied_or_zero_charge(self):
        states=[]
        e=tracker.TrackerFeed(agent,6400000,lambda _:None,states.append)
        e.connected=True;e.ingest({'type':'snapshot','data':[artifact(explored=None,charge=None,
            bonusInfo=None,defaultBonusInfo=None)]});e.report()
        self.bridge._tracker_state=states[-1]
        row=self.bridge.poll()['tables']['resale'][0]
        detail=self.bridge.resale_detail(row['detail_id'])
        self.assertIn('неизвест',str(detail['attributes']).lower())
        self.bridge.set_tracker_filters('0','0',{'explored':'explored'})
        self.assertFalse(self.bridge.poll()['resale_compact'])

    def test_exbo_competitor_context_is_separate_from_sz_estimate_and_expires(self):
        agent.HALT.clear()
        c=tracker.candidate(artifact(),6400000,self.now)
        v=tracker.Verifier(agent)
        lots=[{'buyoutPrice':p,'amount':1,'additional':{'qlt':3,'ptn':10}}
              for p in (1400000,1600000,2000000)]
        with patch.object(agent,'live_lots',return_value=lots),patch.object(agent,'get_json',return_value={'prices':[]}):v.check([c])
        self.assertEqual(v.contexts[c.identity]['cheaper_lots'],1)
        self.assertEqual(v.contexts[c.identity]['cheapest_unit'],1400000)
        self.engine.contexts[c.identity]=dict(v.contexts[c.identity],checked_at=self.now)
        self.engine.availability[c.identity]=(True,self.now)
        states=[];self.engine.on_state=states.append;self.engine.report();self.bridge._tracker_state=states[-1]
        key=self.bridge.poll()['tables']['resale'][0]['detail_id']
        self.assertIn('1',str(self.bridge.resale_detail(key)['competition']))
        with patch('stalzone_gui.time.time',return_value=self.now+50):
            self.assertIn('устар',str(self.bridge.resale_detail(key)['competition']).lower())
            self.assertIn('устар',self.bridge.resale_detail(key)['availability'].lower())


if __name__=='__main__':unittest.main()
