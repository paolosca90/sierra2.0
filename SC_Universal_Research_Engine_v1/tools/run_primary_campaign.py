"""Sequential, exhaustive TO research campaign through the local dashboard API."""
import argparse
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path
import httpx
from footprint_kernel import DEFAULTS
from research_grid import weight_profiles
from robust_optimizer import save_json

PROJECT=Path(__file__).resolve().parents[1]


def configurations():
    result=[]
    for instrument in ('NQ','ES'):
        for levels in (False,True):
            parameters={k:[v] for k,v in DEFAULTS.items()}
            parameters.update(min_agg=[25,75,150] if instrument=='NQ' else [75,150,300],
                              imbalance=[2.5,4],lookback=[10,20])
            execution=dict(sl=[40,80,120] if instrument=='NQ' else [8,16,24],
                           tp=[60,120,180] if instrument=='NQ' else [12,24,36],min_score=[.2,.3,.5],
                           trailing=[0],trail_trigger=[20],be_trigger=[0],be_offset=[0],quantity=[1])
            c=dict(data_folder='C:\\SierraChart\\Data',instrument=instrument,start='2025-04-01',end='2026-09-30',
                   indicator='to_reversal',parameters=parameters,execution=execution,weight_profiles=weight_profiles(),
                   confirmations=[dict(indicator='deluxe_levels',parameters=dict(distance=[4,12]))] if levels else [],
                   combine_mode='and',confirmation_bars=0,bar_seconds=60,method='grid',
                   trials=9720 if levels else 4860,min_trades=50,seed=20261013,horizon=30,
                   commission=5,entry_slip=1,stop_slip=1,exit_slip=1,target_through=1,delay_ms=1,
                   max_gap=90,max_entry_gap=5,level_filter=0,flatten_seconds=60900,
                   available_data_only=True,exploratory_retest=True,calibrate_sensitivity=True,
                   memory_reserve_gib=3,
                   research_label=f'{instrument} TO'+(' + livelli' if levels else ' solo'))
            result.append(c)
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8877')
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--resume',action='store_true',help='Keep completed jobs and retry cancelled/failed ones')
    parser.add_argument('--plan',type=Path,help='Predeclared instrument-specific JSON plan')
    parser.add_argument('--stop-after-block',action='store_true',help='Finish one block, then return without cancelling its worker')
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    custom=json.loads(args.plan.read_text()) if args.plan else {}
    plan=custom['jobs'] if args.plan else configurations()
    save_json(args.out/'PLAN.json',dict(created=datetime.now().isoformat(),jobs=plan,
        unique_configurations=sum(c['trials'] for c in plan),evaluations_four_training_windows=sum(c['trials'] for c in plan)*4,
        source_readme='https://github.com/TraderOracle/SierraChart/blob/main/TOReversalEngine-README.md',
        phase=custom.get('phase','Initial complete Cartesian grid; broader ranges, ablations and trailing/BE are later phases')))
    if args.prepare_only:return
    state_path=args.out/'CAMPAIGN.json'
    if args.resume:
        state=json.loads(state_path.read_text())
        if any(r['status']=='running' for r in state['jobs']):raise ValueError('Prima fermare la ricerca ancora attiva')
        state['status']='running';state.pop('error',None)
    else:
        if state_path.exists():raise ValueError('Campagna esistente: usare --resume')
        state=dict(status='running',jobs=[],started=datetime.now().isoformat())
    completed={r['label'] for r in state['jobs'] if r['status']=='complete'}
    def persist():save_json(state_path,state)
    with httpx.Client(base_url=args.url,timeout=60) as client:
        boot=client.get('/api/bootstrap');boot.raise_for_status()
        client.headers['X-Local-Token']=boot.json()['token']
        for c in plan:
            if c['research_label'] in completed:continue
            if (args.out/'STOP_REQUESTED').exists():state['status']='cancelled';persist();return
            # A completed report can appear just before the old Windows child
            # exits/releases its RAM. Do not race the dashboard's single-job guard.
            previous=next((r for r in reversed(state['jobs']) if r['label']==c['research_label']),None)
            endpoint=f"/api/jobs/{previous['id']}/resume" if args.resume and previous else '/api/jobs'
            body=dict(memory_reserve_gib=c.get('memory_reserve_gib',4)) if previous and args.resume else c
            for attempt in range(30):
                response=client.post(endpoint,json=body)
                if response.status_code!=409:break
                time.sleep(2)
            if response.is_error:
                state['status']='failed_to_start';state['error']=response.text;persist()
            response.raise_for_status();identity=response.json()['id']
            if previous and args.resume:row=previous;row['status']='running'
            else:row=dict(id=identity,label=c['research_label'],status='running');state['jobs'].append(row)
            persist()
            print(json.dumps(row),flush=True)
            while True:
                if (args.out/'STOP_REQUESTED').exists():client.post(f'/api/jobs/{identity}/cancel',json={}).raise_for_status()
                response=client.get(f'/api/jobs/{identity}');response.raise_for_status();job=response.json()
                row['status']=job['status'];row['progress']=job.get('progress');persist()
                if job['status']!='running':break
                time.sleep(10)
            if job['status']!='complete':
                state['status']=job['status'];state['error']=job.get('error');persist()
                print(json.dumps(dict(status=state['status'],error=state.get('error'))),flush=True);return
            summary=job['summary']
            row.update(trials_run=summary['trials_run'],unique_configurations=summary['total_combinations'],
                       elapsed_seconds=summary['elapsed_seconds'],holdout=summary['holdout'],
                       walk_forward_net=sum(f['net'] for f in summary['walk_forward']),
                       walk_forward_trades=sum(f['n'] for f in summary['walk_forward']),
                       tick_audit=summary['tick_audit'],data_exclusions=summary['data_exclusions'],
                       warnings=summary['warnings'])
            row['sample_quality']=summary.get('sample_quality')
            print(json.dumps({k:row[k] for k in ['label','status','trials_run','elapsed_seconds','walk_forward_net']}),flush=True)
            persist()
            if args.stop_after_block:
                state['status']='between_blocks';persist();return
    state['status']='complete';state['finished']=datetime.now().isoformat();persist()


if __name__=='__main__':
    main()
