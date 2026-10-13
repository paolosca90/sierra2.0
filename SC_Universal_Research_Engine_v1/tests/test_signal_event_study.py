import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from study_frozen_signals import event_end,paired_ci


class TestEventStudy(unittest.TestCase):
    def test_horizon_uses_actual_entry_and_no_future_print(self):
        times=np.array([0,250000,1800001000,1800250000,1800250001],np.int64)
        self.assertEqual(event_end(times,1,30,1801000000),3)
        self.assertIsNone(event_end(times,1,30,1800001000))
        stale=np.array([0,1,60000000,90000000],np.int64)
        self.assertIsNone(event_end(stale,1,1,60000000))

    def test_cluster_bootstrap_constant_difference_and_small_sample(self):
        days=np.repeat(np.array(['2025-01-02','2025-01-03','2025-01-06','2025-01-07','2025-01-08','2025-01-09']),2)
        self.assertEqual(paired_ci(days,np.full(len(days),3.)),[3.,3.])
        self.assertIsNone(paired_ci(days[:4],np.ones(4)))


if __name__=='__main__':unittest.main()
