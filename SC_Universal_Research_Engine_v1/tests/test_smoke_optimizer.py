"""Synthetic end-to-end smoke test; synthetic trading P/L is NOT market evidence."""
import csv, json, subprocess, sys, tempfile, struct, unittest
from pathlib import Path
from datetime import datetime, timedelta
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from universal_tick_optimizer import RECORD,micros

class TestSmoke(unittest.TestCase):
    def test_end_to_end_small(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);tape=root/'synthetic.scid';signals=root/'signals.csv';out=root/'results'
            start=datetime(2026,10,1,8)
            rng=np.random.default_rng(100)
            recs=[];bars=[]
            for day in range(5):
                base=start+timedelta(days=day)
                n=60*110
                arr=np.zeros(n,dtype=RECORD)
                arr['datetime']=micros(base)+np.arange(n)*1_000_000
                data=np.cumsum(rng.choice([-1,0,1],n,p=[.3,.4,.3]))*.25+100
                arr['close']=data
                arr['high']=data;arr['low']=data;arr['num_trades']=1;arr['total_volume']=1
                recs.append(arr)
                for j in range(105):
                    s=base+timedelta(hours=2,minutes=j)
                    obs=s+timedelta(minutes=1,seconds=.4)
                    mask=1 if j%6==0 else 2 if j%6==3 else 0
                    bars.append({'kind':'BAR_CLOSE','run':1,'chart':1,'symbol':'SYNTHETIC-CME',
                       'observed_market_time':obs.strftime('%Y-%m-%d  %H:%M:%S.%f')[:-3],
                       'bar_index':day*105+j,'bar_start':s.strftime('%Y-%m-%d  %H:%M:%S.%f')[:-3],
                       'close':float(data[(j+1)*60-1]),'signal_mask':mask,'reversal_score':.5 if mask else 0.0})
            with tape.open('wb') as f:
                head=bytearray(56);head[:4]=b'SCID';struct.pack_into('<II',head,4,56,40);f.write(head)
                for a in recs:a.tofile(f)
            with signals.open('w',newline='',encoding='utf-8') as f:
                w=csv.DictWriter(f,bars[0].keys());w.writeheader();w.writerows(bars)
            cmd=[sys.executable,str(Path(__file__).resolve().parents[1]/'tools'/'universal_tick_optimizer.py'),
               '--scid',str(tape),'--signals',str(signals),'--out',str(out),'--trials','8',
               '--max-sl','30','--max-tp','30','--max-horizon-min','4']
            p=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
            self.assertEqual(p.returncode,0,p.stderr+'\n'+p.stdout)
            summary=json.loads((out/'SUMMARY.json').read_text(encoding='utf-8'))
            self.assertEqual(summary['time_alignment']['chart_minus_utc_hours'],2)
            self.assertEqual(summary['date_count'],5)
            self.assertGreater(summary['valid_events'],100)
            self.assertGreater(summary['train']['n'],10)
            self.assertGreater(summary['holdout']['n'],10)
            self.assertTrue((out/'TRAIN_OPTUNA_TRIALS.csv').is_file())
            self.assertIn('STATUS:',(out/'REPORT.md').read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()
