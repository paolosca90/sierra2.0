import sys
import tempfile
import unittest
import struct
import hashlib
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dashboard'))
from footprint_kernel import block_extrema
from managed_execution import managed_simulate
from indicators import combine,rsi,signal,import_source,causality_probe
from types import SimpleNamespace
from data_catalog import front_contract,liquidity_rolls
from scid_dataset import execution_arrays,prepare_spec
from trade_audit import trace,audit_trade
from resource_guard import ensure_memory
from scid_gap_snapshot import compose
from robust_optimizer import RECORD,EPOCH
from datetime import date


class TestManaged(unittest.TestCase):
    def simulate(self,prices,**kwargs):
        p=np.array(prices,np.int32);t=np.arange(len(p),dtype=np.int64);lo,hi=block_extrema(p)
        args=dict(sl=20,tp=0,entry_slip=0,stop_slip=0,exit_slip=0,target_through=0,tick_value=1.,commission=0.,
                  trailing=0,trail_trigger=0,be_trigger=0,be_offset=0,quantity=1,level_dist=np.array([np.inf]),level_limit=0)
        args.update(kwargs)
        return managed_simulate(p,t,lo,hi,np.array([0]),np.array([len(p)-1]),np.array([True]),np.array([1.]),.3,**args)

    def test_trailing_activates_after_tick_then_catches_reversal(self):
        pnl,ex,_,_=self.simulate([100,104,108,106,104,101],trailing=3,trail_trigger=5)
        self.assertEqual((pnl[0],ex[0]),(4,4)) # stop105 gapped at104, not ideal fill105

    def test_break_even_does_not_apply_before_trigger(self):
        pnl,ex,_,_=self.simulate([100,99,105,100,98],be_trigger=5,be_offset=0)
        self.assertEqual((pnl[0],ex[0]),(0,3))

    def test_immediate_trailing_protects_from_first_adverse_print(self):
        pnl,ex,_,_=self.simulate([100,95,110],trailing=3,trail_trigger=0)
        self.assertEqual((pnl[0],ex[0]),(-5,1))

    def test_no_sl_tp_still_closes_at_timeout(self):
        pnl,ex,_,reason=self.simulate([100,90,110],sl=0,tp=0,quantity=2,commission=1)
        self.assertEqual((pnl[0],ex[0],reason[0]),(18,2,3))

    def test_managed_random_paths_match_scalar_both_directions(self):
        rng=np.random.default_rng(701)
        for side in [-1,1]:
            for _ in range(80):
                prices=1000+np.r_[0,np.cumsum(rng.integers(-4,5,799))]
                sl=int(rng.choice([0,20,40]));tp=int(rng.choice([0,20,50]))
                trailing=int(rng.choice([0,8,20]));trigger=int(rng.choice([0,10,30]));be=int(rng.choice([0,15]))
                fill=prices[0]+side;stop=-sl if sl else -1e30
                if trailing and trigger==0:stop=max(stop,-trailing)
                peak=0.;expected_exit=len(prices)-1;reason=3;expected=side*(prices[-1]-fill)-1
                for j in range(1,len(prices)):
                    move=side*(prices[j]-fill)
                    if move<=stop:expected=move-1;expected_exit=j;reason=1;break
                    if tp and move>=tp+1:expected=tp;expected_exit=j;reason=2;break
                    peak=max(peak,move)
                    if be and peak>=be:stop=max(stop,0)
                    if trailing and peak>=trigger:stop=max(stop,peak-trailing)
                lo,hi=block_extrema(prices)
                actual=managed_simulate(prices,np.arange(len(prices),dtype=np.int64),lo,hi,np.array([0]),np.array([len(prices)-1]),
                    np.array([True]),np.array([float(side)]),.3,sl,tp,1,1,1,1,5.,5.,trailing,trigger,be,0,2,np.array([np.inf]),0)
                self.assertEqual((actual[0][0],actual[1][0],actual[3][0]),((expected*5-5)*2,expected_exit,reason))

    def test_plugin_rejects_future_dependent_signals(self):
        n=600
        data=dict(close=np.arange(n),high=np.arange(n),low=np.arange(n),bar_time=np.arange(n),
                  offsets=np.arange(n+1),bid=np.ones(n),ask=np.ones(n),volume=np.full(n,2))
        good=SimpleNamespace(compute=lambda d,p: np.r_[0,np.sign(np.diff(d['close']))])
        bad=SimpleNamespace(compute=lambda d,p: np.sign(d['close']-d['close'].mean()))
        with patch('indicators.plugin_module',return_value=good):causality_probe('plugin_test',data,{})
        with patch('indicators.plugin_module',return_value=bad):
            with self.assertRaisesRegex(ValueError,'non causale'):causality_probe('plugin_test',data,{})

    def test_and_remembers_only_past_confirmations(self):
        p=np.array([1.,1.,1.,1.,-1.]);c=np.array([[0.,1.,0.,0.,-1.]])
        np.testing.assert_array_equal(combine(p,c,1),[0,1,1,0,-1])

    def test_or_opposing_signals_cancel(self):
        p=np.array([1.,0.,-1.]);c=np.array([[-1.,1.,-1.]])
        np.testing.assert_array_equal(combine(p,c,3,True),[0,1,-1])

    def test_rsi_wilder_known_monotone_and_flat(self):
        self.assertEqual(rsi(np.arange(30,dtype=float),14)[-1],100.)
        self.assertEqual(rsi(np.ones(30),14)[-1],50.)

    def test_rollover_rule_is_fixed_before_results(self):
        self.assertEqual(front_contract(date(2025,6,11)),'M25')
        self.assertEqual(front_contract(date(2025,6,12)),'U25')

    def test_volume_rollover_uses_only_previous_completed_session(self):
        with tempfile.TemporaryDirectory() as td:
            for code,vols in [('M25',[200,150,80]),('U25',[100,160,200])]:
                Path(td,f'NQ{code}-CME.dly').write_text('Date, Close, Volume\n'+''.join(f'2025/06/{d}, 20000, {v}\n' for d,v in zip([13,16,17],vols)))
            rolls=liquidity_rolls(td,'NQ',date(2025,6,12),date(2025,6,20))
            self.assertEqual(rolls[0]['decision_date'],'2025-06-16')
            self.assertEqual(rolls[0]['effective_trade_date'],'2025-06-17')

    def test_hard_daily_flatten_cuts_horizon_and_forbids_late_entries(self):
        times=np.arange(7*3600,17*3600,dtype=np.int64)*1_000_000
        starts=np.arange(0,len(times),60,dtype=np.int64)
        data=dict(times=times,starts=starts,bar_time=times[starts],day_end=np.full(len(starts),18*3600_000_000,np.int64))
        entry,end,good=execution_arrays(data,30,1,90,5,60900)
        self.assertTrue(good[590]) # 16:50 bar, 16:51 entry
        self.assertEqual(times[end[590]],(16*3600+54*60+59)*1_000_000)
        self.assertFalse(good[595])
        self.assertTrue(np.all(times[end[good]]<=60900_000_000))

    def test_audit_tracks_every_print_and_real_stop_gap(self):
        rows=[];c=dict(entry_slip=0,stop_slip=1,exit_slip=1,target_through=1,instrument='NQ',commission=5)
        ep=dict(sl=20,tp=0,trailing=3,trail_trigger=5,be_trigger=0,be_offset=0,quantity=1)
        result=trace(np.array([100,104,108,106,104,101]),np.arange(6,dtype=np.int64),0,5,1,ep,c,rows.append)
        self.assertEqual((result['exit_index'],result['net_usd'],len(rows)),(4,10,5))
        self.assertEqual(rows[2]['event'],'TRAILING')
        self.assertEqual(rows[4]['stop_before'],26.25)

    def test_memory_reserve_rejects_heavy_job(self):
        with patch('resource_guard.available_memory',return_value=2*1024**3):
            with self.assertRaisesRegex(MemoryError,'preservare Sierra'):ensure_memory()

    def test_gap_snapshot_copies_exact_records_without_editing_sources(self):
        with tempfile.TemporaryDirectory() as td,patch('scid_gap_snapshot.ensure_memory'):
            root=Path(td);base=root/'NQU26-CME.scid';alt=root/'NQU6.CME.scid'
            header=bytearray(56);struct.pack_into('<4sIIH',header,0,b'SCID',56,40,1)
            def write(path,days,prices):
                raw=np.zeros(len(days),dtype=RECORD)
                raw['datetime']=[int((np.datetime64(d+'T12:00:00','us')-EPOCH)/np.timedelta64(1,'us')) for d in days]
                raw['close']=prices;raw['num_trades']=1;raw['total_volume']=1;raw['ask_volume']=1
                path.write_bytes(bytes(header)+raw.tobytes());return raw
            a=write(base,['2026-07-23','2026-07-25'],[20000,20002])
            b=write(alt,['2026-07-24'],[20001])
            hashes=[hashlib.sha256(p.read_bytes()).hexdigest() for p in [base,alt]]
            out,meta=compose(dict(start='2026-07-23',end='2026-07-26'),str(base),{'2026-07-24':str(alt)},root/'cache')
            self.assertEqual(Path(out).read_bytes(),bytes(header)+a[:1].tobytes()+b.tobytes()+a[1:].tobytes())
            self.assertEqual(hashes,[hashlib.sha256(p.read_bytes()).hexdigest() for p in [base,alt]])
            self.assertEqual(meta['filled_trade_dates'],['2026-07-24'])

    def test_missing_whole_trade_date_blocks_publication(self):
        with patch('scid_dataset.prepare',return_value=({'day':np.array(['2026-07-23'])},{})):
            with self.assertRaisesRegex(ValueError,'Giornate intere assenti'):
                prepare_spec(dict(scid='NQU26-CME.scid',expected_trade_dates=['2026-07-23','2026-07-24']),'unused')

    def test_cancel_terminates_windows_job_tree(self):
        import app as webapp
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as td:
            process=Mock(pid=987654);process.poll.return_value=None
            with patch.object(webapp,'job_folder',return_value=Path(td)),patch.dict(webapp.PROCESSES,{'job':process}),patch.object(webapp.subprocess,'run') as run:
                result=webapp.cancel('job')
                if webapp.os.name=='nt':self.assertEqual(run.call_args.args[0],['taskkill','/PID','987654','/T','/F'])
                self.assertEqual(result['status'],'cancelled')
                self.assertTrue(Path(td,'CANCELLED').exists())

    def test_import_acsil_never_pretends_to_be_executable(self):
        with tempfile.TemporaryDirectory() as td,patch('indicators.PLUGINS',Path(td)):
            r=import_source('custom.cpp','SCInputRef Foo=sc.Input[8]; Foo.SetFloat(0.3);')
            self.assertEqual(r['status'],'adapter_required')
            self.assertEqual(r['params']['8']['default'],.3)

    def test_api_requires_token_on_mutations_and_serves_ui(self):
        from fastapi.testclient import TestClient
        from app import app
        with TestClient(app) as client,patch('app.ensure_memory'):
            self.assertEqual(client.get('/').status_code,200)
            self.assertEqual(client.post('/api/plan',json={}).status_code,403)
            boot=client.get('/api/bootstrap').json()
            self.assertGreater(len(boot['indicators']),4)
            bad=client.post('/api/jobs',headers={'X-Local-Token':boot['token']},json={'indicator':'nope'})
            self.assertEqual(bad.status_code,400)

if __name__=='__main__':unittest.main()
