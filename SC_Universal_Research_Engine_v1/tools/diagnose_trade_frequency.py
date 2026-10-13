"""Trace scarce trades back to gates; profile instruments using INITIAL train only."""
import json
import sys
from pathlib import Path
import numpy as np

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT/'dashboard'))
from worker import Engine
from scid_dataset import load_cache
from robust_optimizer import save_json
from resource_guard import initialize_research,ensure_memory


def diagnose(out):
    initialize_research(3);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    campaign=json.loads((PROJECT/'output/PRIMARY_GRID_20261013/CAMPAIGN.json').read_text())
    completed=[r for r in campaign['jobs'] if r['status']=='complete']
    findings=[];profiles={}
    for instrument in ('NQ','ES'):
        rows=[r for r in completed if r['label'].startswith(instrument)]
        jobs=[PROJECT/'dashboard_jobs'/r['id'] for r in rows]
        summaries=[json.loads((p/'SUMMARY.json').read_text()) for p in jobs]
        configs=[json.loads((p/'config.json').read_text()) for p in jobs]
        initial=summaries[0]['development_days'][:len(summaries[0]['development_days'])//2]
        samples=dict(range_ticks=[],aggressive_row_volume=[],level_distance_ticks=[],abs_score_no_location=[])
        counts=[{period:dict(bars=0,nonzero_without_location=0,nonzero_with_location=0,
                score_pass=0,execution_pass=0,level_pass=0,joint_pass=0)
                 for period in ('development','final')} for _ in jobs]
        for meta in summaries[0]['datasets']:
            ensure_memory(reclaim=True)
            d,_=load_cache(Path(meta['cache_directory']))
            spec=next(s for s in configs[0]['manifest'] if s['scid']==meta['signature']['path'])
            engine=Engine(d,configs[1],spec)
            initial_mask=engine.good&np.isin(d['day'],initial)
            indices=np.flatnonzero(initial_mask)
            if len(indices):
                samples['range_ticks'].extend((d['high'][indices]-d['low'][indices])[::max(1,len(indices)//15000)])
                a=int(d['offsets'][indices[0]]);z=int(d['offsets'][indices[-1]+1]);stride=max(1,(z-a)//50000)
                agg=np.maximum(d['bid'][a:z:stride],d['ask'][a:z:stride]);agg=agg[agg>0]
                samples['aggressive_row_volume'].extend(agg)
                dist=engine.levels[indices];samples['level_distance_ticks'].extend(dist[np.isfinite(dist)])
            for i,(summary,config) in enumerate(zip(summaries,configs)):
                p={k[2:]:v for k,v in summary['params'].items() if k.startswith('i:')}
                normal=engine.to_scores.score(p)
                ungated=engine.to_scores.score(dict(p,require_extreme=0))
                if i==0 and len(indices):samples['abs_score_no_location'].extend(np.abs(ungated[indices]))
                score=(np.abs(normal)>=summary['params']['e:min_score'])&(normal!=0)
                distance=summary['params'].get('c0:distance',0)
                level=np.ones(len(normal),bool) if not distance else engine.levels<=distance
                for period,days in [('development',summary['development_days']),('final',summary['holdout_days'])]:
                    mask=np.isin(d['day'],days)&(d['day']>=spec['trade_from'])&(d['day']<=spec['trade_to'])
                    c=counts[i][period]
                    for key,condition in [('bars',mask),('nonzero_without_location',mask&(ungated!=0)),
                        ('nonzero_with_location',mask&(normal!=0)),('score_pass',mask&score),
                        ('execution_pass',mask&score&engine.good),('level_pass',mask&score&level),
                        ('joint_pass',mask&score&level&engine.good)]:c[key]+=int(np.count_nonzero(condition))
            del engine,d
        for i,(row,summary) in enumerate(zip(rows,summaries)):
            selections=json.loads((jobs[i]/'STAGE_SELECTIONS.json').read_text())
            counts[i]['development']['executed_trades']=selections[-1]['trades']
            counts[i]['final']['executed_trades']=summary['holdout']['n']
            counts[i]['development']['days']=len(summary['development_days'])
            counts[i]['final']['days']=len(summary['holdout_days'])
            findings.append(dict(label=row['label'],job=row['id'],params=summary['params'],funnel=counts[i]))
        profiles[instrument]=dict(initial_training_days=initial,statistics={})
        for key,values in samples.items():
            a=np.asarray(values,dtype=float)
            if key=='abs_score_no_location':a=a[a>0]
            profiles[instrument]['statistics'][key]=dict(n=len(a),quantiles={str(q):float(np.quantile(a,q)) for q in [.25,.5,.7,.75,.9]})
        save_json(out/'DIAGNOSTICS.json',dict(findings=findings,instrument_profiles=profiles,
                 note='Candidate bars are not executed trades. Instrument scales use initial training data only; no P&L tuning. Final-window diagnostics are descriptive and already-known.'))
        print(instrument,json.dumps(profiles[instrument]['statistics']),flush=True)
    return findings,profiles


if __name__=='__main__':diagnose(sys.argv[1])
