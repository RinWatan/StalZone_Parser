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
