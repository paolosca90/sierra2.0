import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dashboard'))
from research_grid import weight_profiles,grid_candidates,grid_size
from scid_dataset import prepare,prepare_spec
from scid_dataset import calculate
from to_score_cache import TOScoreCache


class ResearchGridTests(unittest.TestCase):
    def test_campaign_memory_reserve_still_stops_below_its_floor(self):
        import resource_guard as guard
        with patch.object(guard,'RESERVE_BYTES',4*1024**3),patch.object(guard,'lower_priority'),patch.object(guard,'available_memory',return_value=int(2.5*1024**3)):
            with self.assertRaises(MemoryError):guard.initialize_research(3)
            with self.assertRaises(ValueError):guard.initialize_research(0)

    def test_windows_progress_read_lock_is_retried(self):
        from worker import publish_progress
        with tempfile.TemporaryDirectory() as td,patch('worker.time.sleep') as sleep:
            original=Path.replace;attempts=[]
            def transient(path,target):
                attempts.append(1)
                if len(attempts)<3:raise PermissionError('Transient reader lock')
                return original(path,target)
            with patch.object(Path,'replace',transient):publish_progress(Path(td),{'percent':75})
            self.assertEqual(len(attempts),3)
            self.assertEqual(sleep.call_count,2)
            self.assertIn('75',(Path(td)/'progress.json').read_text())

    def test_reweighted_scores_bit_exact_against_original_footprint(self):
        rng=np.random.default_rng(709);n=130
        low=1000+np.cumsum(rng.integers(-3,4,n));high=low+10
        close=low+rng.integers(0,11,n);bid=rng.integers(0,160,n*11);ask=rng.integers(0,160,n*11)
        bid[::7]=0;ask[::7]=0;bid[:11]=0;ask[:11]=0
        data=dict(low=low,high=high,close=close,offsets=np.arange(n+1)*11,bid=bid,ask=ask,volume=bid+ask)
        cached=TOScoreCache(data)
        for agg in [25,150]:
            for index,weights in enumerate(weight_profiles()+[dict(w_abs=0,w_trap=0,w_delta=1,w_imb=0)]):
                p=dict(weights,min_agg=agg,sensitivity=[1,2,4,8][index%4],lookback=10,
                       volume_weight=index%2,require_extreme=(index//2)%2)
                np.testing.assert_array_equal(cached.score(p),calculate(data,p)[0])

    def test_weight_ratios_unique_and_include_original(self):
        profiles=weight_profiles()
        self.assertEqual(len(profiles),15)
        self.assertIn(dict(w_abs=4,w_trap=1,w_delta=1,w_imb=1),profiles)
        ratios={tuple(v/sum(p.values()) for v in p.values()) for p in profiles}
        self.assertEqual(len(ratios),15)

    def test_every_execution_pair_for_every_profile_exactly_once(self):
        space={'i:w_abs':[4],'i:w_trap':[1],'i:w_delta':[1],'i:w_imb':[1],
               'i:min_agg':[50,150],'e:sl':[10,20],'e:tp':[30,60,90]}
        rows=list(grid_candidates(space,weight_profiles()))
        self.assertEqual(len(rows),180)
        self.assertEqual(len(rows),grid_size(space,weight_profiles()))
        self.assertEqual(len({tuple(sorted(p.items())) for p in rows}),180)
        for profile in weight_profiles():
            subset=[p for p in rows if all(p['i:'+k]==v for k,v in profile.items())]
            self.assertEqual(len(subset),12)

    def test_unverified_alias_rejected_before_read_or_cache_reuse(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError,'Alias .CME escluso'):
                prepare(Path(td)/'ESM6.CME.scid',Path(td)/'cache')

    def test_explicit_missing_days_recorded_not_filled(self):
        with patch('scid_dataset.prepare',return_value=({'day':np.array(['2026-07-23'])},{})) as reader:
            _,meta=prepare_spec(dict(scid='NQU26-CME.scid',expected_trade_dates=['2026-07-23','2026-07-24'],
                                    allow_missing_trade_dates=True,alternatives=['NQU6.CME.scid']),'unused')
            self.assertEqual(meta['excluded_trade_dates'],['2026-07-24'])
            self.assertEqual(reader.call_count,1)
