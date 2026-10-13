"""Financial invariants; synthetic P/L is never evidence of market edge."""
import csv
import json
import struct
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import robust_optimizer as ro


def bar(time=0, side=1):
    return dict(time=time, day='2026-10-01', day_end=86_400_000_000,
                score=.5*side, mask=1 if side==1 else 2, close=100.)


class TestRobust(unittest.TestCase):
    def path(self, prices, side=1, times=None, **kw):
        times = np.array(times if times is not None else np.arange(len(prices))*1_000_000, dtype=np.int64)
        return ro.build_paths([bar(side=side)], times, np.array(prices, float), tick=1,
                              max_sl=10, max_tp=10, horizon=1, delay_ms=0,
                              max_gap=90, max_entry_gap=65, **kw)[0]

    def test_stop_gap_fills_at_observed_adverse_price(self):
        d=self.path([100,100,94,100], times=[0,1_000_000,2_000_000,60_000_000], entry_slip=1)
        r=ro.evaluate(d,np.array([0]),dict(sl=3,tp=5,min_score=.3),tick_value=1,commission=2,stop_slip=1,detail=True)
        self.assertEqual(r['net'],-10)  # entry101 -> print94 -> stop slip1 -> cost2
        self.assertEqual(r['trades'][0]['exit_reason'],'SL')

    def test_target_requires_trade_through_and_no_improved_limit_fill(self):
        d=self.path([100,100,105,104], times=[0,1_000_000,2_000_000,60_000_000],entry_slip=0,target_through=1)
        r=ro.evaluate(d,np.array([0]),dict(sl=3,tp=5,min_score=.3),tick_value=1,commission=0,exit_slip=0,detail=True)
        self.assertEqual(r['trades'][0]['exit_reason'],'TIMEOUT')
        d=self.path([100,100,109,104],times=[0,1_000_000,2_000_000,60_000_000],entry_slip=0,target_through=1)
        self.assertEqual(ro.evaluate(d,np.array([0]),dict(sl=3,tp=5,min_score=.3),tick_value=1,commission=0)['net'],5)

    def test_timeout_never_uses_pre_deadline_price(self):
        d=self.path([100,100,102,99],times=[0,1_000_000,59_000_000,60_100_000],entry_slip=0)
        r=ro.evaluate(d,np.array([0]),dict(sl=10,tp=10,min_score=.3),tick_value=1,commission=0,exit_slip=0,detail=True)
        self.assertEqual(r['net'],-1)
        self.assertIn('00:01:00.100000',r['trades'][0]['exit_utc'])

    def test_same_timestamp_records_preserve_hit_order(self):
        d=self.path([100,100,106,94,100],times=[0,1_000_000,2_000_000,2_000_000,60_000_000],entry_slip=0,target_through=0)
        r=ro.evaluate(d,np.array([0]),dict(sl=5,tp=5,min_score=.3),tick_value=1,commission=0)
        self.assertEqual(r['net'],5)

    def test_random_paths_match_independent_scalar_simulator(self):
        rng=np.random.default_rng(482)
        for side in [1,-1]:
            for _ in range(15):
                prices=100+np.r_[0,np.cumsum(rng.integers(-4,5,60))]
                d=self.path(prices,side=side,entry_slip=1,target_through=1)
                for sl in [2,5,9]:
                    for tp in [2,5,9]:
                        fill=prices[1]+side
                        movement=side*(prices[-1]-fill)-1
                        for price in prices[2:]:
                            change=side*(price-fill)
                            if change <= -sl:
                                movement=change-1
                                break
                            if change >= tp+1:
                                movement=tp
                                break
                        r=ro.evaluate(d,np.array([0]),dict(sl=sl,tp=tp,min_score=.3),tick_value=5,commission=5)
                        self.assertAlmostEqual(r['net'],movement*5-5)

    def test_partition_purges_midnight_even_without_next_day_signals(self):
        d=dict(day=np.array(['2026-10-01','2026-10-01','2026-10-03']),
               end_time=np.array([99,101,299]),day_end=np.array([100,100,300]))
        self.assertEqual(ro.partition(d,['2026-10-01','2026-10-02']).tolist(),[0])

    def test_no_trades_has_finite_equity_and_no_infinite_pf(self):
        d=self.path([100]*61,entry_slip=0)
        r=ro.evaluate(d,np.array([0]),dict(sl=5,tp=5,min_score=.9))
        self.assertEqual((r['n'],r['net'],r['maxdd'],r['pf']),(0,0,0,None))

    def test_single_trade_unbundled_flags_and_aggregated_rejection(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'test.scid'
            h=bytearray(56);h[:4]=b'SCID';struct.pack_into('<IIH',h,4,56,40,1)
            r=np.zeros(3,dtype=ro.RECORD)
            r['datetime']=np.arange(3);r['close']=100;r['total_volume']=1;r['num_trades']=1
            r['open']=[0,-1.99900095e37,-1.99900197e37]
            p.write_bytes(h+r.tobytes())
            self.assertEqual(ro.read_tape(p)[2]['single_tick_fraction'],1)
            r['num_trades'][1]=2;p.write_bytes(h+r.tobytes())
            with self.assertRaisesRegex(ValueError,'Aggregated'):
                ro.read_tape(p)

    def test_future_or_duplicate_collector_rows_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'s.csv'
            row=dict(kind='BAR_CLOSE',symbol='NQZ26-CME',bar_start='2026-10-01  12:00:00.000',
                     observed_market_time='2026-10-01  12:00:30.000',close=100,reversal_score=.5,signal_mask=1)
            with p.open('w',newline='') as f:
                w=csv.DictWriter(f,row);w.writeheader();w.writerow(row)
            with self.assertRaisesRegex(ValueError,'before bar closure'):
                ro.load_bars(p,60)

    def test_levels_filter_and_one_position(self):
        times=np.arange(121,dtype=np.int64)*1_000_000
        b=[bar(),bar(time=10_000_000)]
        b[0]['levels']=np.array([101]);b[1]['levels']=np.array([110])
        d,_=ro.build_paths(b,times,np.full(121,100.),tick=1,max_sl=10,max_tp=10,horizon=1,entry_slip=0)
        args=dict(sl=5,tp=5,min_score=.3)
        self.assertEqual(ro.evaluate(d,np.array([0,1]),args)['n'],1)
        self.assertEqual(ro.evaluate(d,np.array([1]),dict(**args,level_ticks=2))['n'],0)

    def test_all_ineligible_trials_do_not_return_fake_winner(self):
        ro.optuna.logging.set_verbosity(ro.optuna.logging.ERROR)
        d=self.path([100]*61,entry_slip=0)
        a=SimpleNamespace(tick_value=5,commission=5,stop_slip=1,exit_slip=1,min_sl=2,max_sl=5,
                          min_tp=2,max_tp=5,step=1,scores=[.3],min_trades=2,trials=3)
        self.assertIsNone(ro.optimize(d,np.array([0]),a,'standalone',1)[0])

    def test_bootstrap_counts_empty_days(self):
        r=ro.daily_bootstrap({'daily':{'1':10}},['1','2','3','4','5'],1)
        self.assertEqual(r['status'],'descriptive_only')
        self.assertLess(r['mean_daily_usd_ci95'][1],10)

if __name__=='__main__':
    unittest.main()
