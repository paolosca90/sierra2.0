"""Descriptive checks of every completed block, never rerank final parameters."""
import csv
import json
from collections import defaultdict,Counter
from pathlib import Path


def inspect(root):
    folder=root/'output/MULTIBAR_GRID_20261013'
    campaign=json.loads((folder/'CAMPAIGN.json').read_text());rows=[]
    for job in campaign['jobs']:
        path=root/'dashboard_jobs'/job['id']
        if not (path/'SUMMARY.json').exists():continue
        summary=json.loads((path/'SUMMARY.json').read_text())
        with (path/'HOLDOUT_TRADES.csv').open(encoding='utf-8-sig',newline='') as stream:trades=list(csv.DictReader(stream))
        daily=defaultdict(float);monthly=defaultdict(float);directions=defaultdict(float);reasons=Counter()
        for trade in trades:
            net=float(trade['net_usd']);daily[trade['day']]+=net;monthly[trade['day'][:7]]+=net
            directions['long' if int(trade['side'])==1 else 'short']+=net;reasons[trade['exit_reason']]+=1
        total=sum(daily.values());wf=summary['walk_forward'];tick_value=5 if summary['instrument']=='NQ' else 12.5
        rows.append(dict(label=job['label'],job_id=job['id'],n=len(trades),net=total,monthly=dict(monthly),
                         directions=dict(directions),exits=dict(reasons),
                         net_without_best_day=total-max(daily.values()) if daily else 0,
                         net_without_best_five_days=total-sum(sorted(daily.values(),reverse=True)[:5]),
                         maximum_trade_loss=min((float(t['net_usd']) for t in trades),default=0),
                         wf_net=sum(f['net'] for f in wf),wf_n=sum(f['n'] for f in wf),
                         wf_stress_extra_two_ticks=sum(f['net'] for f in wf)-sum(f['n'] for f in wf)*2*tick_value,
                         every_wf_fold_positive=all(f['net']>0 for f in wf),
                         every_wf_fold_sufficient=all(f.get('sample_status')=='sufficient_for_screening' for f in wf),
                         final_sample_sufficient=summary['sample_quality']['final']['sufficient'],
                         final_stress=summary['stress_extra_2_ticks_net'],params=summary['params']))
    result=dict(scope='Descriptive results of all completed blocks; final profits do not select parameters. Walk-forward uses a new training selection per fold, not a single fixed parameter set.',rows=rows)
    (folder/'CANDIDATE_DIAGNOSTICS.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('Diagnosed blocks',len(rows))
    return result


if __name__=='__main__':inspect(Path(__file__).resolve().parents[1])
