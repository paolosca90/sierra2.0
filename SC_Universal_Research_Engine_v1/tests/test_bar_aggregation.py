import sys
import gc
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from bar_aggregation import trade_starts,rebar
from footprint_kernel import block_extrema,scores,vector
from scid_dataset import EPOCH_PY,observation_times,execution_arrays,load_cache
from to_score_cache import TOScoreCache


class TestBarAggregation(unittest.TestCase):
    def test_cache_creation_path_does_not_depend_on_worker_cwd(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td);np.save(folder/'price.npy',np.array([100],np.int32))
            (folder/'metadata.json').write_text(json.dumps(dict(arrays=['price'],cache_directory='old/relative/path')))
            data,meta=load_cache(folder)
            self.assertEqual(meta['cache_directory'],str(folder.resolve()))
            self.assertEqual(data['price'][0],100)
            del data;gc.collect()

    def times(self,stamps):
        return np.array([int((datetime.fromisoformat(s).replace(tzinfo=timezone.utc)-EPOCH_PY).total_seconds()*1e6) for s in stamps],np.int64)

    def test_trade_bars_reset_at_ny_session_and_gaps(self):
        times=self.times(['2026-07-13T21:59:57','2026-07-13T21:59:58','2026-07-13T22:00:00',
                         '2026-07-13T22:00:01','2026-07-13T22:00:02','2026-07-13T22:00:03','2026-07-13T22:05:00'])
        np.testing.assert_array_equal(trade_starts(times,3),[0,2,5,6])
        winter=self.times(['2026-01-12T22:59:58','2026-01-12T23:00:00','2026-01-12T23:00:01'])
        np.testing.assert_array_equal(trade_starts(winter,2),[0,1])

    @patch('bar_aggregation.ensure_memory')
    def test_shared_ticks_volume_conservation_and_actual_trade_close(self,_guard):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);base=root/'base';base.mkdir()
            data=dict(times=np.arange(9,dtype=np.int64)*1_000_000,price=np.array([100,101,100,102,101,100,100,99,100],np.int32),
                      tick_bid=np.ones(9,np.uint32),tick_ask=np.full(9,2,np.uint32),tick_volume=np.full(9,3,np.uint32))
            data['block_low'],data['block_high']=block_extrema(data['price'])
            for name,arr in data.items():np.save(base/(name+'.npy'),arr)
            meta=dict(signature=dict(path='synthetic.scid',seconds=60),cache_directory=str(base),source_sha256='synthetic')
            bars,m=rebar(data,meta,root,60,4)
            np.testing.assert_array_equal(bars['starts'],[0,4,8]);np.testing.assert_array_equal(bars['ends'],[4,8,9])
            np.testing.assert_array_equal(bars['bar_complete'],[True,True,False])
            np.testing.assert_array_equal(observation_times(bars),[3_000_000,7_000_000,8_000_000])
            self.assertEqual(bars['volume'].sum(),27);self.assertEqual(bars['bid'].sum(),9)
            self.assertEqual(Path(m['cache_directory'],'price.npy').stat().st_ino,(base/'price.npy').stat().st_ino)
            timed,_=rebar(data,meta,root,2,0)
            np.testing.assert_array_equal(timed['starts'],[0,2,4,6,8]);self.assertEqual(timed['volume'].sum(),27)
            del bars,timed
            gc.collect()

    def test_trade_entry_occurs_after_completed_bar_not_next_bar_close(self):
        n=600;times=np.arange(n*3+100,dtype=np.int64)*1_000_000
        starts=np.arange(n)*3
        data=dict(times=times,starts=starts,bar_time=times[starts],bar_close_time=times[starts+2],
                  bar_complete=np.ones(n,bool),day_end=np.full(n,86400_000_000,np.int64))
        entry,_,valid=execution_arrays(data,horizon=1,delay_ms=1,max_gap=90,max_entry_gap=5)
        self.assertTrue(valid[510]);self.assertEqual(entry[510],starts[510]+3)
        data['bar_complete'][510]=False
        self.assertFalse(execution_arrays(data,1,1,90,5)[2][510])

    def test_cached_gate_and_volume_variants_match_original_scores(self):
        rng=np.random.default_rng(511);n=100
        d=dict(low=rng.integers(100,110,n));d['high']=d['low']+2;d['close']=d['low']+1;d['offsets']=np.arange(n+1)*3
        d['bid']=rng.integers(0,300,n*3);d['ask']=rng.integers(0,300,n*3);d['volume']=d['bid']+d['ask']
        cache=TOScoreCache(d)
        for gate in [0,1]:
            for volume in [0,1]:
                p=dict(require_extreme=gate,volume_weight=volume)
                expected=scores(d['low'],d['high'],d['close'],d['offsets'],d['bid'],d['ask'],d['volume'],vector(p))[0]
                np.testing.assert_array_equal(cache.score(p),expected)


if __name__=='__main__':unittest.main()
