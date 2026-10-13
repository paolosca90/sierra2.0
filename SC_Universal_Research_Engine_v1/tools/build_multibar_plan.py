"""Declared Cartesian research over time and executed-trade bars."""
import copy
import json
import math
from pathlib import Path
from research_grid import grid_size


def build(root):
    base_plan=json.loads((root/'config/research_base.json').read_text())
    profiles=[dict(w_abs=4,w_trap=1,w_delta=1,w_imb=1),dict(w_abs=1,w_trap=1,w_delta=1,w_imb=1),
              dict(w_abs=4,w_trap=0,w_delta=1,w_imb=1),dict(w_abs=1,w_trap=0,w_delta=0,w_imb=0),
              dict(w_abs=0,w_trap=1,w_delta=0,w_imb=0),dict(w_abs=0,w_trap=0,w_delta=1,w_imb=1)]
    jobs=[]
    # Coarser and trade bars first; every declared block remains exhaustive.
    frames=[('300s',300,0),('120s',120,0),('trade-large',60,1),('trade-small',60,2),('60s',60,0),('30s',30,0),('15s',15,0)]
    for name,seconds,tick_mode in frames:
        for instrument in ('NQ','ES'):
            nq=instrument=='NQ'
            c=copy.deepcopy(next(j for j in base_plan['jobs'] if j['instrument']==instrument and not j['confirmations']))
            count=(2000 if nq else 10000) if tick_mode==1 else (500 if nq else 2000) if tick_mode==2 else 0
            scale=math.sqrt(seconds/60) if not count else (2 if tick_mode==1 else 1)
            step=5 if nq else 25
            volumes=sorted({max(step,round(v*scale/step)*step) for v in ([20,80,200] if nq else [150,600,1500])})
            c['parameters'].update(min_agg=volumes,imbalance=[2,4],require_extreme=[0,1],
                lookback=[20 if count else max(2,round((900 if nq else 1800)/seconds))],
                min_pct=[3 if nq else 8],level_multiple=[1.5],sensitivity=[4],
                extreme_ticks=[max(1,round((6 if nq else 2)*scale))],
                rejection_ticks=[max(1,round((3 if nq else 1)*scale))],
                tolerance=[max(1,round((3 if nq else 1)*scale))],
                imbalance_volume=[max(5,round((20 if nq else 150)*scale))])
            c['weight_profiles']=profiles
            c['execution']=dict(sl=[24,56,112] if nq else [8,16,32],tp=[40,100,240] if nq else [8,24,64],
                min_score=[.15,.3],trailing=[0],trail_trigger=[20],be_trigger=[0],be_offset=[0],quantity=[1],session_mode=[0,1,2,3])
            c.update(start='2025-01-02',end='2026-09-30',bar_seconds=seconds,trades_per_bar=count,
                entry_windows=[],calibrate_sensitivity=False,min_trades=100,min_active_days=20,min_trades_per_training_block=20,
                memory_reserve_gib=3,research_label=f'{instrument} V4 TO '+(f'{count} trades' if count else f'{seconds}s'))
            space={**{'i:'+k:v for k,v in c['parameters'].items()},**{'e:'+k:v for k,v in c['execution'].items()}}
            c['trials']=grid_size(space,profiles)
            assert c['trials']<=10000
            jobs.append(c)
    output=root/'output/MULTIBAR_GRID_20261013';output.mkdir(parents=True,exist_ok=True)
    plan=dict(phase='Full per-block Cartesian search: seven aggregations, two instruments, six score profiles, four entry sessions, wider static brackets.',
              caveats=['Parameter combinations are unique; some zero-weight profiles can produce equivalent signals despite different unused detection inputs.',
                       'All available 2025-2026 data have been consulted: exploratory screening, not independent final validation.',
                       'Tick-by-tick execution does not mean recalculating a closed-bar TO signal on every forming-bar update.',
                       'Trade bars count executed SCID trade records, reset at NY 18:00 or recording gaps, and discard incomplete trade bars.'],jobs=jobs)
    path=output/'GRID_PLAN.json'
    if path.exists() and json.loads(path.read_text())!=plan:raise ValueError('Existing plan differs; choose a new campaign')
    path.write_text(json.dumps(plan,indent=2),encoding='utf-8')
    print('Jobs',len(jobs),'parameter combinations',sum(j['trials'] for j in jobs),'training evaluations',sum(j['trials'] for j in jobs)*4)
    for j in jobs:print(j['research_label'],j['trials'],j['parameters']['min_agg'])


if __name__=='__main__':build(Path(__file__).resolve().parents[1])
