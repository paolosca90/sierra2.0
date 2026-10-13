import math, struct, tempfile, unittest, sys
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from universal_tick_optimizer import (RECORD, micros,scid_reader,detect_offset,make_events,Event,evaluate,
            collector_rows,chart_to_tape_us)

class TestResearch(unittest.TestCase):
    def test_first_hit_order_and_cost(self):
        inf=sys.maxsize
        e=Event(time=0,side=1,score=.5,day='2026-10-01',hour=10,start=0,end=5,entry_last=100,
            end_last=100,best=10,worst=10,
            tp_index=np.array([inf,1,1,1,2,2,3],dtype=np.int64),
            stop_index=np.array([inf,3,3,3,3,3,4],dtype=np.int64))
        r=e.result(tp=5,sl=4,entry_slip=0,stop_slip=1,exit_slip=1,tick=.25,tick_value=5,commission=5)
        self.assertEqual(r['exit_reason'],'TP')
        self.assertEqual(r['net_usd'],20.0)
        # Same MFE/MAE but earlier stop: loses.
        e.stop_index[4]=1
        r=e.result(tp=5,sl=4,entry_slip=0,stop_slip=1,exit_slip=1,tick=.25,tick_value=5,commission=5)
        self.assertEqual(r['exit_reason'],'SL')
        self.assertEqual(r['net_usd'],-30.0)
        e.stop_index[4]=2
        self.assertEqual(e.result(5,4,0,1,1,.25,5,5)['exit_reason'],'SL')
    def test_scid_timestamp_and_alignment(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'test.scid'
            rec=np.zeros(5*60,dtype=RECORD)
            base=datetime(2026,10,1,0,0)
            rec['datetime']=micros(base)+np.arange(5*60)*1_000_000
            rec['close']=100+np.floor(np.arange(300)/60)*.25
            rec['high']=rec['close']
            rec['low']=rec['close']
            rec['total_volume']=1;rec['num_trades']=1
            with p.open('wb') as f:
                h=bytearray(56);h[:4]=b'SCID';struct.pack_into('<II',h,4,56,40);f.write(h);rec.tofile(f)
            ts,px,meta=scid_reader(p)
            self.assertEqual(len(ts),300)
            self.assertEqual(meta['single_tick_convention_fraction'],1.0)
            b=[]
            for j in range(5):
                # chart clock = UTC +2
                b.append({'bar_start':base+timedelta(hours=2,minutes=j),'observed':base+timedelta(hours=2,minutes=j+1),
                          'close':100+j*.25,'mask':1 if j==0 else 2 if j==3 else 0,'score':.5,'symbol':'NQZ26-CME'})
            chosen,m,_=detect_offset(b,ts,px)
            self.assertEqual(chosen,2)
            self.assertAlmostEqual(m,1.0)
            ev,bad,total=make_events(b,ts,px,2,.25,10,10,3,0,0,2,90,True)
            self.assertEqual(total,2)
            self.assertTrue(len(ev)>=1)
            self.assertEqual(ev[0].start,60)
            self.assertEqual(ev[0].tp_index[1],60)
    def test_reject_bad_scid_layout(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'invalid.scid';p.write_bytes(b'bad')
            with self.assertRaises(ValueError):scid_reader(p)
    def test_patch_patterns(self):
        from patch_optimizer import once
        self.assertEqual(once('abc', 'b', 'B','test'),'aBc')
        with self.assertRaises(ValueError):once('abc','x','y','test')

if __name__=='__main__': unittest.main()
