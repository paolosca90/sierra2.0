"""Predeclare exploratory session, volume and exit tests, without final selection."""
import copy
import json
from pathlib import Path
from research_grid import grid_size


def build(root):
    previous=json.loads((root/'config/research_base.json').read_text())
    jobs=[]
    sessions={'ALL':[], 'RTH':[[34200,57600]], 'AM':[[34200,43200]], 'PM':[[43200,57600]]}
    for instrument in ('NQ','ES'):
        base=next(c for c in previous['jobs'] if c['instrument']==instrument and not c['confirmations'])
        nq=instrument=='NQ'
        for session,windows in sessions.items():
            c=copy.deepcopy(base)
            c['parameters'].update(min_agg=[10,40,80] if nq else [150,400,800],
                                   imbalance_volume=[5,20] if nq else [50,150,300],
                                   lookback=[15] if nq else [30],require_extreme=[1])
            c['weight_profiles']=[dict(w_abs=4,w_trap=0,w_delta=1,w_imb=1)]
            c['execution']=dict(sl=[24,56,112] if nq else [8,16,32],tp=[68,136] if nq else [16,32],
                                min_score=[.06,.17] if nq else [.06,.16],quantity=[1],
                                trailing=[0,48] if nq else [0,12],trail_trigger=[64] if nq else [20],
                                be_trigger=[0,40] if nq else [0,12],be_offset=[3] if nq else [2])
            c.update(entry_windows=windows,min_trades=100,min_active_days=20,min_trades_per_training_block=20,
                     research_label=f'{instrument} V3 TO stops {session}')
            space={**{'i:'+k:v for k,v in c['parameters'].items()},**{'e:'+k:v for k,v in c['execution'].items()}}
            c['trials']=grid_size(space,c['weight_profiles'])
            jobs.append(c)
    result=dict(phase='Exploratory V3: entry sessions, instrument-specific aggressive volume and imbalance floor, static stops, trailing and cost-aware break-even.',
                caveats=['Previously consulted data: no fresh independent validation.',
                         'Session windows restrict actual entries only; existing trades may continue beyond a window until normal exits or 16:55 NY.',
                         'Signal structure and weights are frozen from V2; this does not exhaust alternative indicators.',
                         '100-trade development screening is not statistical significance; held-out sample status stays explicit.'],jobs=jobs)
    folder=root/'output/SESSION_STOP_GRID_20261013';folder.mkdir(parents=True,exist_ok=True)
    (folder/'GRID_PLAN.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('Jobs',len(jobs),'unique configurations',sum(c['trials'] for c in jobs))
    return folder


if __name__=='__main__':build(Path(__file__).resolve().parents[1])
