import tempfile
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import stalzone_agent as agent
import stalzone_license as lic
from stalzone_gui import Bridge

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patcher = patch.object(agent, 'DIR', Path(self.temp.name))
        self.patcher.start()
        self.license_root = patch('stalzone_license._root', lambda root=None: Path(self.temp.name))
        self.license_root.start()
        lic.activate(lic.issue_owner(), self.temp.name, ip="127.0.0.1")
        self.bridge = Bridge()
    def tearDown(self):
        self.license_root.stop()
        self.patcher.stop()
        self.temp.cleanup()
    def test_compact_deals_share_results_and_clear(self):
        self.bridge._show({'buys':[{'name':'Соленоид','slug':'abc','copies':1,'amount':1,
                                 'buyout':2250,'unit':2250,'med':4000,'gain':1200}]})
        self.assertEqual(self.bridge.poll()['compact'][0]['name'], 'Соленоид')
        self.bridge._show({'buys':[]})
        self.assertEqual(self.bridge.poll()['compact'], [])

    def test_compact_keeps_the_hour_figure(self):
        self.bridge._show({'buys':[
            {'name':'Медленный','slug':'a','copies':1,'amount':1,'buyout':1,'med':2,'gain':50000,'hour_gain':100},
            {'name':'Быстрый','slug':'b','copies':1,'amount':1,'buyout':1,'med':2,'gain':20000,'hour_gain':9000},
        ]})
        rows = self.bridge.poll()['compact']
        self.assertEqual(rows[1]['name'], 'Быстрый')
        self.assertEqual(rows[1]['hour_n'], 9000)
    def test_hud_actions_queue_on_controller(self):
        class Controller:
            def command(self, action): return {'ok':action == 'full'}
            def snapshot(self): return {'mode':'compact'}
        self.bridge._hud = Controller()
        self.assertTrue(self.bridge.hud_action('full')['ok'])
        self.assertEqual(self.bridge.poll()['hud']['mode'], 'compact')
    def test_personal_mark_survives_bridge_recreation(self):
        self.bridge.add_mark('south-zone', 50, 60, 'Мой тайник')
        self.assertEqual(Bridge()._marks_of('south-zone')[0]['title'], 'Мой тайник')
    def test_two_windows_buttons_cannot_launch_two_workers(self):
        entered, release, job_done = threading.Event(), threading.Event(), threading.Event()
        def budget(_):
            entered.set()
            release.wait(2)
            return 10000
        def job(*_): job_done.wait(2)
        self.bridge._budget = budget
        self.bridge._job = job
        try:
            with ThreadPoolExecutor(2) as pool:
                first = pool.submit(self.bridge.start_run, False, 30, '10000', 'Выкуп')
                self.assertTrue(entered.wait(1))
                second = pool.submit(self.bridge.start_run, False, 30, '10000', 'Выкуп')
                release.set()
                results = [first.result(2), second.result(2)]
                self.assertEqual(sum(r['ok'] for r in results), 1)
        finally:
            job_done.set()
            release.set()
            if self.bridge.worker: self.bridge.worker.join(2)

if __name__ == '__main__': unittest.main()
