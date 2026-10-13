"""Freeze instrument-specific grids from prior INITIAL TRAIN profiling only."""
import json
import math
import sys
from pathlib import Path
from footprint_kernel import DEFAULTS
from research_grid import weight_profiles,WEIGHTS,grid_size
from robust_optimizer import save_json


def rounded(value,step):return max(step,int(round(value/step))*step)


def build(folder):
    folder=Path(folder);d=json.loads((folder/'DIAGNOSTICS.json').read_text());jobs=[]
    weights=weight_profiles()
    for omitted in WEIGHTS:
        p=dict(w_abs=4,w_trap=1,w_delta=1,w_imb=1);p[omitted]=0;weights.append(p)
    for instrument in ('NQ','ES'):
        stats=d['instrument_profiles'][instrument]['statistics'];step=4 if instrument=='NQ' else 1
        q=stats['range_ticks']['quantiles'];volume=stats['aggressive_row_volume']['quantiles']
        thresholds=stats['abs_score_no_location']['quantiles'];dist=stats['level_distance_ticks']['quantiles']
        vol_step=5 if instrument=='NQ' else 25
        agg=sorted({rounded(volume['0.7'],vol_step),rounded(volume['0.9'],vol_step),rounded(2*volume['0.9'],vol_step)})
        score=sorted({max(.02,round(thresholds[k],2)) for k in ['0.25','0.5','0.9']})
        sl=sorted({rounded(q['0.5'],step),rounded(.75*q['0.9'],step)})
        tp=sorted({rounded(1.5*q['0.75'],step),rounded(3*q['0.75'],step)})
        distances=sorted({rounded(dist[k],step) for k in ['0.25','0.5','0.75']})
        # These structural hypotheses are declared BEFORE reading new returns.
        parameters={k:[v] for k,v in DEFAULTS.items()}
        parameters.update(min_agg=agg,min_pct=[3 if instrument=='NQ' else 8],level_multiple=[1.5],
            imbalance=[2 if instrument=='NQ' else 3],lookback=[5,15] if instrument=='NQ' else [10,30],
            require_extreme=[0,1],extreme_ticks=[math.ceil(.2*q['0.5'])],
            rejection_ticks=[math.ceil(.1*q['0.5'])],tolerance=[math.ceil(.1*q['0.5'])])
        old=next(r for r in d['findings'] if r['label']==instrument+' TO solo')
        parameters['sensitivity']=[old['params']['i:sensitivity']]
        for levels in (False,True):
            execution=dict(sl=sl,tp=tp,min_score=score,trailing=[0],trail_trigger=[20],be_trigger=[0],be_offset=[0],quantity=[1])
            c=dict(data_folder='C:\\SierraChart\\Data',instrument=instrument,start='2025-04-01',end='2026-09-30',
                   indicator='to_reversal',parameters=parameters,execution=execution,weight_profiles=weights,
                   confirmations=[dict(indicator='deluxe_levels',parameters=dict(distance=distances))] if levels else [],
                   combine_mode='and',confirmation_bars=0,bar_seconds=60,method='grid',
                   min_trades=200,min_active_days=30,min_trades_per_training_block=40,training_blocks=3,
                   validation_min_trades=50,validation_min_active_days=15,
                   seed=20261013,horizon=30,commission=5,entry_slip=1,stop_slip=1,exit_slip=1,target_through=1,
                   delay_ms=1,max_gap=90,max_entry_gap=5,level_filter=0,flatten_seconds=60900,
                   available_data_only=True,exploratory_retest=True,calibrate_sensitivity=False,memory_reserve_gib=2,
                   research_label=f'{instrument} V2 TO'+(' + livelli' if levels else ' solo'))
            space={**{'i:'+k:v for k,v in parameters.items()},**{'e:'+k:v for k,v in execution.items()}}
            if levels:space['c0:distance']=distances
            c['trials']=grid_size(space,weights)
            if c['trials']>10000:raise ValueError('Split the declared grid before running it')
            jobs.append(c)
    plan=dict(phase='Instrument-specific exhaustive grids with ample and distributed samples; 19 weight profiles include 4 ablations.',
              calibration_scope='Only initial training days recorded in DIAGNOSTICS.json; never final P&L.',jobs=jobs)
    save_json(folder/'GRID_PLAN.json',plan)
    for c in jobs:print(c['research_label'],c['trials'],json.dumps(dict(parameters=c['parameters'],execution=c['execution'],confirmations=c['confirmations'])))


if __name__=='__main__':build(sys.argv[1])
