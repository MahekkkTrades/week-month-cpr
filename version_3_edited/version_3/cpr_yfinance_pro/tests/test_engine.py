import unittest
from datetime import datetime,date
from zoneinfo import ZoneInfo
import pandas as pd
from engine import cpr,overlap,previous_periods,analyze
class TestCPR(unittest.TestCase):
 def test_formula(self):
  x=cpr(110,90,100);self.assertEqual(x,{'low':100,'high':100,'pivot':100})
 def test_touch(self):self.assertIsNotNone(overlap({'low':2,'high':4},{'low':4,'high':6}))
 def test_no_overlap(self):self.assertIsNone(overlap({'low':2,'high':3},{'low':4,'high':6}))
 def test_periods(self):
  w1,w2,m1,m2=previous_periods(datetime(2026,11,10,tzinfo=ZoneInfo('America/New_York')))
  self.assertEqual((w1,w2,m1,m2),(date(2026,11,2),date(2026,11,9),date(2026,10,1),date(2026,11,1)))
 def test_adv_filter(self):
  ix=pd.bdate_range('2026-09-01','2026-11-09');f=pd.DataFrame({'High':110,'Low':90,'Close':100,'Volume':1_000_000},index=ix)
  self.assertIsNone(analyze(f,'AAA','NASDAQ','Technology',datetime(2026,11,10,tzinfo=ZoneInfo('America/New_York'))))
if __name__=='__main__':unittest.main()
