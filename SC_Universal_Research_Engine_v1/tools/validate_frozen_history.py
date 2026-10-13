"""Historical regime stress test of frozen V3 rules; no tuning on test returns."""
import gc
import hashlib
import json
import sys
import time
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dashboard'))
from data_catalog import plan
from worker import Engine
from scid_dataset import prepare_spec
from robust_optimizer import save_json,save_csv,daily_bootstrap
from resource_guard import initialize_research,ensure_memory


def main():
    output=ROOT/'output/FROZEN_HISTORY_20261013';output.mkdir(parents=True,exist_ok=True)
    campaign=json.loads((ROOT/'output/SESSION_STOP_GRID_20261013/CAMPAIGN.json').read_text())
    protocol=[]
    for instrument,start,end in [('NQ','2025-01-02','2025-03-31'),('ES','2025-01-02','2025-03-31'),('ES','2022-06-21','2023-03-06')]:
        data_plan=plan(r'C:\SierraChart\Data',instrument,start,end)
        if not data_plan['ready']:raise ValueError('Incomplete historical contract plan')
        experiments=[]
        for job in campaign['jobs']:
            source=ROOT/'dashboard_jobs'/job['id']
            c=json.loads((source/'config.json').read_text())
            if c['instrument']!=instrument:continue
            s=json.loads((source/'SUMMARY.json').read_text())
            experiments.append(dict(label=c['research_label'],origin_job=job['id'],
                                    source_summary_sha256=hashlib.sha256((source/'SUMMARY.json').read_bytes()).hexdigest(),
                                    params=s['params'],config=c))
        protocol.append(dict(instrument=instrument,start=start,end=end,manifest=data_plan['manifest'],
                             rollover_evidence=data_plan['rolls'],experiments=experiments))
    caveats=['Rules were developed using later 2025-2026 data; this is a retrospective historical regime stress test, not forward independent validation.',
             'No historical profit is used to select parameters or sessions.',
             'Original -CME SCID only; tick chronology, grid, volume and gaps must pass existing checks.',
             'Execution follows last prints, not actual order-book queues; complete Sierra parity remains unverified.']
    frozen=dict(protocol=protocol,caveats=caveats)
    protocol_path=output/'FROZEN_PROTOCOL.json'
    if protocol_path.exists() and json.loads(protocol_path.read_text())!=frozen:
        raise ValueError('Protocol changed: preserve prior results and use a new folder')
    save_json(protocol_path,frozen)
    initialize_research(3)
    started=time.perf_counter();results=[];sources=[];exclusions=[]
    for period in protocol:
        accumulated={e['origin_job']:[] for e in period['experiments']};days=set()
        for spec in period['manifest']:
            label=period['instrument']+' '+Path(spec['scid']).stem
            print('Preparing',label,flush=True)
            save_json(output/'progress.json',dict(stage='Preparing '+label,elapsed_seconds=time.perf_counter()-started))
            ensure_memory(reclaim=True)
            try:
                data,meta=prepare_spec(dict(spec,alternatives=[],partial_alternatives=[],allow_missing_trade_dates=True),ROOT/'.scid_cache',60)
            except ValueError as error:
                exclusions.append(dict(instrument=period['instrument'],start=spec['trade_from'],end=spec['trade_to'],error=str(error)))
                continue
            sources.append(meta)
            valid_days=sorted(set(data['day'][(data['day']>=spec['trade_from'])&(data['day']<=spec['trade_to'])]));days.update(valid_days)
            for experiment in period['experiments']:
                c=experiment['config'];engine=Engine(data,c,spec)
                _,_,trades=engine.run(experiment['params'],valid_days,detail=True)
                accumulated[experiment['origin_job']].extend(trades)
                del engine
                ensure_memory(reclaim=True)
            del data;gc.collect()
        for experiment in period['experiments']:
            trades=sorted(accumulated[experiment['origin_job']],key=lambda t:t['entry_utc'])
            assert all(a['exit_utc']<b['entry_utc'] for a,b in zip(trades,trades[1:]))
            if not days:raise ValueError('No usable historical trade dates')
            values=np.array([t['net_usd'] for t in trades]);equity=np.r_[0.,np.cumsum(values)]
            daily={day:sum(t['net_usd'] for t in trades if t['day']==day) for day in sorted(days)}
            net=float(values.sum());n=len(trades);tick_value=5 if period['instrument']=='NQ' else 12.5
            loss=-values[values<0].sum()
            row=dict(label=experiment['label'],instrument=period['instrument'],start=period['start'],end=period['end'],
                     days=len(days),active_days=sum(v!=0 for v in daily.values()),n=n,net=net,
                     avg=net/n if n else 0.,pf=float(values[values>0].sum()/loss) if loss else None,
                     maxdd=float(np.max(np.maximum.accumulate(equity)-equity)),
                     stress=net-n*2*tick_value,gross_after_slippage=net+sum(experiment['config']['commission']*t['quantity'] for t in trades),
                     daily=daily,params=experiment['params'],audited_ticks=sum(t['ticks_audited'] for t in trades))
            row['uncertainty']=daily_bootstrap(row,sorted(days),20261013)
            row['active_days']=len({t['day'] for t in trades})
            row['sample_sufficient_for_screening']=n>=50 and row['active_days']>=15
            filename=f"{period['instrument']}_{period['start']}_{experiment['label'].split()[-1]}_TRADES.csv"
            save_csv(output/filename,trades)
            row['trades_file']=filename;results.append(row)
            print(json.dumps({k:row[k] for k in ['label','start','end','days','n','net','stress']}),flush=True)
        save_json(output/'PARTIAL_RESULTS.json',dict(results=results,sources=sources,exclusions=exclusions,caveats=caveats))
    save_json(output/'SUMMARY.json',dict(results=results,sources=sources,exclusions=exclusions,caveats=caveats,elapsed_seconds=time.perf_counter()-started))
    save_json(output/'progress.json',dict(stage='Complete',elapsed_seconds=time.perf_counter()-started))


if __name__=='__main__':main()
