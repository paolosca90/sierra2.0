import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import footprint_kernel as f
from causal_levels import profile,compute


class TestFootprint(unittest.TestCase):
    def test_block_skip_first_hit_matches_tick_loop(self):
        rng=np.random.default_rng(48)
        prices=np.cumsum(rng.integers(-3,4,3000)).astype(np.int32)+10000
        lows,highs=f.block_extrema(prices)
        for _ in range(200):
            start=int(rng.integers(0,2000));end=int(rng.integers(start,3000))
            lower=int(prices[start]-rng.integers(1,50));upper=int(prices[start]+rng.integers(1,50))
            expected=(end,0)
            for j in range(start,end+1):
                if prices[j]<=lower:expected=(j,-1);break
                if prices[j]>=upper:expected=(j,1);break
            self.assertEqual(f.first_hit(prices,start,end,lower,upper,lows,highs),expected)

    def test_vap_preserves_all_bid_ask_and_volume(self):
        price=np.array([100,101,100,103,102],np.int32)
        bid=np.array([1,0,2,0,3],np.uint32);ask=np.array([0,4,0,5,0],np.uint32)
        b,a,v=f.aggregate_vap(price,bid,ask,bid+ask,np.array([0,3]),np.array([3,5]),np.array([100,102]),np.array([0,2,4]))
        np.testing.assert_array_equal(b,[3,0,3,0]);np.testing.assert_array_equal(a,[0,4,0,5])
        np.testing.assert_array_equal(v,b+a)

    def one_bar(self,min_agg):
        # Heavy selling at the low rejected by a high close: +100 absorption.
        low=np.array([100]);high=np.array([102]);close=np.array([102]);offsets=np.array([0,3])
        bid=np.array([100,0,0]);ask=np.array([0,1,10]);vol=bid+ask
        return f.scores(low,high,close,offsets,bid,ask,vol,
            f.vector(dict(min_agg=min_agg,min_pct=0,level_multiple=0,diagonal=0,require_extreme=0,volume_weight=0,sensitivity=1)))

    def test_absorption_parameter_changes_actual_indicator(self):
        score,metrics=self.one_bar(50)
        self.assertEqual(metrics[0,0],-89)
        self.assertEqual(metrics[0,1],100)
        self.assertEqual(metrics[0,3],100)
        score2,metrics2=self.one_bar(150)
        self.assertEqual(metrics2[0,3],0)
        self.assertGreater(score[0],score2[0])

    def test_indicator_prefix_invariance_no_future_bars(self):
        rng=np.random.default_rng(41);n=80
        low=rng.integers(100,110,n);high=low+2;close=low+1;offsets=np.arange(n+1)*3
        bid=rng.integers(0,300,n*3);ask=rng.integers(0,300,n*3);volume=bid+ask
        full=f.scores(low,high,close,offsets,bid,ask,volume,f.vector())[0]
        prefix=f.scores(low[:40],high[:40],close[:40],offsets[:41],bid[:120],ask[:120],volume[:120],f.vector())[0]
        np.testing.assert_array_equal(full[:40],prefix)

    def test_profile_ties_and_two_row_expansion(self):
        poc,vah,val=profile(np.array([1.,5.,5.,1.]),100)
        self.assertEqual(poc,101) # nearest center tie -> lower first
        self.assertEqual((vah,val),(103,101)) # expand upper two rows (6 vs lower1)

    def test_deluxe_never_backfills_an_earlier_bar(self):
        n=8;low=np.arange(100,108);high=low+3;close=low+1;offsets=np.arange(n+1)*4
        volume=np.ones(n*4,np.int64)
        keys=np.array([[1,1,1]]*4+[[2,1,1]]*4)
        clock=np.array([34200,34260,34320,34380]*2)
        full,dist=compute(low,high,close,offsets,volume,keys,clock)
        short,_=compute(low[:3],high[:3],close[:3],offsets[:4],volume[:12],keys[:3],clock[:3])
        np.testing.assert_array_equal(full[:3],short)
        self.assertEqual(full[0,18],103)
        self.assertEqual(full[2,18],105)
        self.assertEqual(full[4,0],0) # incomplete first day never treated as a full PD

    def test_simulator_short_and_long_stop_gap_symmetry(self):
        for side in [1,-1]:
            price=np.array([100,100,100-side*7,100],np.int32)
            times=np.array([0,1,2,60],np.int64)
            lo,hi=f.block_extrema(price)
            v,e,s=f.simulate(price,times,lo,hi,np.array([1]),np.array([3]),np.array([True]),np.array([side*.5]),
                .3,3,5,1,1,1,1,5.,5.,np.array([np.inf]),0)
            self.assertEqual(v[0],-50.)
            self.assertEqual(e[0],2)
            self.assertEqual(s[0],side)

if __name__=='__main__':unittest.main()
