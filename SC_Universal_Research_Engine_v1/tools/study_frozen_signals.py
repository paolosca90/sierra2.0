"""Descriptive matched event study: frozen TO direction versus control bars.

All eligible signals, including overlapping events; no position/stop simulation.
Controls match contract, trading date, NY hour and causal trailing range bucket.
"""
import gc
import json
import sys
from collections import defaultdict
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dashboard'))
from worker import Engine
from entry_sessions import entry_mask
from scid_dataset import load_cache
from robust_optimizer import save_json
from resource_guard import initialize_research,ensure_memory


def event_end(times,start,minutes,cutoff):
    target=int(times[start])+minutes*60_000_000
    if target>cutoff or target>int(times[-1]):return None
    end=int(np.searchsorted(times,target,side='right'))-1
    if end<=start or target-int(times[end])>5_000_000:return None
    return end


def paired_ci(days,values,seed=20261013):
    unique,inverse=np.unique(days,return_inverse=True)
    sums=np.bincount(inverse,weights=values);counts=np.bincount(inverse)
    if len(unique)<5:return None
    rng=np.random.default_rng(seed);block=min(5,len(unique));length=len(unique)
    starts=rng.integers(length,size=(2000,(length+block-1)//block))
    ids=((starts[:,:,None]+np.arange(block))%length).reshape(2000,-1)[:,:length]
    estimates=sums[ids].sum(axis=1)/counts[ids].sum(axis=1)
    return np.quantile(estimates,[.025,.975]).tolist()


def main():
    folder=ROOT/'output/FROZEN_HISTORY_20261013'
    protocol=json.loads((folder/'FROZEN_PROTOCOL.json').read_text())['protocol']
    summary=json.loads((folder/'SUMMARY.json').read_text())
    metadata={(m['signature']['path'],m['signature']['start'],m['signature']['end']):m for m in summary['sources']}
    initialize_research(3);rng=np.random.default_rng(20261013);results=[]
    for period in protocol:
        observations=defaultdict(list)
        for spec in period['manifest']:
            meta=metadata.get((spec['scid'],spec['start'],spec['end']))
            if meta is None:continue
            print('Event study',Path(spec['scid']).stem,flush=True)
            data,_=load_cache(Path(meta['cache_directory']))
            # Closed-bar trailing range is available when the following fill occurs.
            tr=np.maximum(data['high']-data['low'],np.maximum(np.abs(data['high']-np.r_[data['close'][0],data['close'][:-1]]),
                                                           np.abs(data['low']-np.r_[data['close'][0],data['close'][:-1]])))
            cs=np.r_[0.,np.cumsum(tr,dtype=float)];right=np.arange(1,len(tr)+1);left=np.maximum(0,right-20)
            buckets=np.searchsorted([4,8,16,32,64,128],(cs[right]-cs[left])/(right-left))
            for experiment in period['experiments']:
                engine=Engine(data,experiment['config'],spec);p=experiment['params']
                valid=np.flatnonzero(engine.good);signals=engine.signals(p)
                # The hour bucket follows actual entries, including DST.
                hours=np.full(len(engine.good),-1,np.int8)
                for hour in range(24):hours[entry_mask(data['times'][engine.entry],[[hour*3600,(hour+1)*3600]])]=hour
                groups=defaultdict(list)
                for b in valid:groups[(str(data['day'][b]),int(hours[b]),int(buckets[b]))].append(int(b))
                selected=valid[(signals[valid]!=0)&(np.abs(signals[valid])>=p['e:min_score'])]
                pairs=[]
                for b in selected:
                    controls=groups[(str(data['day'][b]),int(hours[b]),int(buckets[b]))]
                    choices=[k for k in controls if k!=b]
                    if choices:pairs.append((int(b),int(rng.choice(choices)),1 if signals[b]>0 else -1))
                for minutes in (1,3,5,10,30):
                    for b,control,side in pairs:
                        start=int(engine.entry[b]);other=int(engine.entry[control])
                        # Study horizons start at actual fill, whereas managed
                        # execution timeout starts at signal observation + delay.
                        # Do not accidentally drop 30m events due to subsecond
                        # differences between the requested and actual entry.
                        flatten=experiment['config'].get('flatten_seconds',60900)
                        cutoff=int(data['day_end'][b])-(64800-flatten)*1_000_000-1_000_000
                        control_cutoff=int(data['day_end'][control])-(64800-flatten)*1_000_000-1_000_000
                        end=event_end(data['times'],start,minutes,cutoff)
                        other_end=event_end(data['times'],other,minutes,control_cutoff)
                        if end is None or other_end is None:continue
                        signal_return=side*float(data['price'][end]-data['price'][start])
                        control_return=side*float(data['price'][other_end]-data['price'][other])
                        path=data['price'][start:end+1]
                        low=float(np.min(path));high=float(np.max(path));entry=float(data['price'][start])
                        mfe=high-entry if side>0 else entry-low
                        mae=entry-low if side>0 else high-entry
                        observations[(experiment['label'],minutes)].append((str(data['day'][b]),signal_return,control_return,mfe,mae))
                del engine;ensure_memory(reclaim=True)
            del data;gc.collect()
        for (label,minutes),obs in observations.items():
            days=np.array([r[0] for r in obs]);a=np.array([r[1:] for r in obs]);difference=a[:,0]-a[:,1]
            tick_value=5 if period['instrument']=='NQ' else 12.5
            results.append(dict(label=label,instrument=period['instrument'],start=period['start'],end=period['end'],minutes=minutes,
                                paired_events=len(obs),active_days=len(set(days)),signal_mean_ticks=float(a[:,0].mean()),
                                control_mean_ticks=float(a[:,1].mean()),excess_mean_ticks=float(difference.mean()),
                                excess_ci95_ticks=paired_ci(days,difference),mfe_mean_ticks=float(a[:,2].mean()),mae_mean_ticks=float(a[:,3].mean()),
                                mean_after_flat_cost_usd=float(a[:,0].mean()*tick_value-2*tick_value-5)))
        save_json(folder/'SIGNAL_EVENT_STUDY.json',dict(results=results,seed=20261013,
                    caveats=['Overlapping signal events are not executed trades; entry-only windows, no stops or targets.',
                             'Matched controls use same contract/date/NY hour/trailing range bucket and same signal direction; one seeded control per eligible signal.',
                             'Paired circular 5-day block bootstrap is descriptive and not adjusted for multiple comparisons.',
                             'Rules developed on later data; retrospective regime stress test, not independent forward validation.',
                             'Fixed-cost estimate uses 1 entry tick, 1 exit tick and 5 USD round trip; actual fills are not represented.']))
    print('Completed event-study cells',len(results),flush=True)


if __name__=='__main__':main()
