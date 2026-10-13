import sys
from pathlib import Path
import unittest
from datetime import datetime, timezone
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from entry_sessions import entry_mask, validate_windows


class TestEntrySessions(unittest.TestCase):
    def test_actual_fill_boundaries_and_dst(self):
        epoch=datetime(1899,12,30,tzinfo=timezone.utc)
        stamps=['2026-01-12T14:29:59.999999+00:00','2026-01-12T14:30:00+00:00',
                '2026-01-12T21:00:00+00:00','2026-07-13T13:30:00+00:00',
                '2026-07-13T20:00:00+00:00']
        times=np.array([int((datetime.fromisoformat(s)-epoch).total_seconds()*1e6) for s in stamps],np.int64)
        self.assertEqual(entry_mask(times,[[34200,57600]]).tolist(),[False,True,False,True,False])

    def test_empty_and_disjoint_windows(self):
        self.assertEqual(entry_mask(np.array([0,1]),[]).tolist(),[True,True])
        validate_windows([[0,32400],[64800,86400]])
        for bad in [None,[[57600,34200]],[[0,90000]],[[True,100]],[[0.5,100]]]:
            with self.assertRaises(ValueError):validate_windows(bad)


if __name__=='__main__':unittest.main()
