import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dashboard'))
from sample_quality import statistics,training_objective,evaluation_status
from worker import evaluate


class SampleQualityTests(unittest.TestCase):
    def result(self,counts,net=10000):
        return dict(n=sum(counts),sample=statistics(counts),net=net,maxdd=100)

    def test_high_profit_concentrated_in_one_period_is_rejected(self):
        policy=dict(min_trades=200,min_active_days=30,min_trades_per_training_block=40)
        r=self.result([10]*30+[0]*60)
        self.assertEqual(training_objective(r,policy),-1e30)
        r=self.result([3]*90)
        self.assertEqual(training_objective(r,policy),9925)

    def test_many_trades_on_one_day_do_not_count_as_broad_sample(self):
        policy=dict(min_trades=200,min_active_days=30,min_trades_per_training_block=0)
        self.assertEqual(training_objective(self.result([1000]+[0]*89),policy),-1e30)

    def test_small_profitable_final_is_labelled_not_reranked(self):
        r=self.result([1]*11+[0]*66,net=210)
        q=evaluation_status(r,dict(validation_min_trades=50,validation_min_active_days=15))
        self.assertEqual(q['status'],'insufficient_sample')
        self.assertEqual(r['net'],210)

    def test_vectorized_daily_sums_include_inactive_days(self):
        engine=Mock();engine.c={}
        engine.run.return_value=(np.array([5.,-10.,30.]),np.array(['2025-01-01','2025-01-01','2025-01-03']),[])
        r=evaluate([engine],{},['2025-01-01','2025-01-02','2025-01-03'])
        self.assertEqual(r['daily'],{'2025-01-01':-5.,'2025-01-02':0.,'2025-01-03':30.})
        self.assertEqual(r['sample']['active_days'],2)
        self.assertEqual(r['sample']['block_trades'],[2,0,1])
        self.assertEqual(r['net'],25)
        self.assertEqual(r['maxdd'],10)


if __name__=='__main__':unittest.main()
