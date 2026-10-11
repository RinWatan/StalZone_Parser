import unittest
from stalzone_gui import Bridge, PAGE, TABLES, rows_from


class RemovedHuntTests(unittest.TestCase):
    def test_hunt_is_not_exposed_in_bridge_or_ui(self):
        for name in ('start_hunt','stop_hunt','add_hunt','remove_hunt','clear_hunt_alerts'):
            self.assertFalse(hasattr(Bridge,name),name)
        self.assertNotIn('huntpanel',PAGE)
        self.assertNotIn('huntnotice',PAGE)
        self.assertIn('Надёжность оценки',TABLES['buys'])

    def test_low_confidence_still_requires_manual_check(self):
        row={'name':'Test','buyout':100,'med':200,'amount':1,'copies':1,'gain':90,
             'confidence':{'level':'low','detail':'Недостаточно данных'}}
        cells=rows_from({'buys':[row]})['buys'][0]['cells']
        self.assertIn('Недостаточно данных',cells[-2])
