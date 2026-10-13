"""Independent scalar audit: visits EVERY print, without optimized block skipping."""
import csv
import json
from pathlib import Path
import numpy as np
from scid_dataset import load_cache, execution_arrays,observation_times
from robust_optimizer import EPOCH
from instruments import instrument_spec


def trace(price,times,start,end,side,ep,c,emit):
    instrument=instrument_spec(c['instrument'])
    fill=float(price[start])+side*c['entry_slip']
    stop=-float(ep['sl']) if ep['sl'] else -float('inf')
    if ep['trailing']>0 and ep['trail_trigger']==0:stop=max(stop,-ep['trailing'])
    target=ep['tp']+c['target_through'] if ep['tp'] else float('inf')
    peak=0.;net=None;reason=None
    def level(v):return (fill+side*v)*instrument.tick_size if np.isfinite(v) else ''
    for i in range(start,end+1):
        move=side*(float(price[i])-fill);before=stop;event='ENTRY' if i==start else 'TICK';exit_fill=''
        if i>start:
            if move<=stop:
                event=reason='STOP';ticks=move-c['stop_slip']
            elif move>=target:
                event=reason='TARGET';ticks=ep['tp']
            elif i==end:
                event=reason=c.get('timeout_reason','TIMEOUT');ticks=move-c['exit_slip']
            else:
                peak=max(peak,move)
                if ep['be_trigger']>0 and peak>=ep['be_trigger'] and stop<ep['be_offset']:
                    stop=ep['be_offset'];event='BREAK_EVEN'
                if ep['trailing']>0 and peak>=ep['trail_trigger'] and peak-ep['trailing']>stop:
                    stop=peak-ep['trailing'];event='TRAILING' if event=='TICK' else event+'+TRAILING'
            if reason:
                net=(ticks*instrument.tick_value-c['commission'])*ep['quantity']
                exit_fill=(fill+side*ticks)*instrument.tick_size
        if emit is not None:emit(dict(tick_index_in_snapshot=i,timestamp_utc=str(EPOCH+np.timedelta64(int(times[i]),'us')),last_price=float(price[i])*instrument.tick_size,
                  event=event,side=side,entry_fill=fill*instrument.tick_size,stop_before=level(before),stop_after=level(stop),
                  target_fill=level(float(ep['tp'])) if ep['tp'] else '',target_trigger=level(target),
                  favorable_peak_ticks=peak,exit_fill=exit_fill,net_usd=net if reason else ''))
        if reason:return dict(exit_index=i,net_usd=net,reason=reason,ticks_visited=i-start+1)
    raise ValueError('No exit within recorded trade window')


def audit_trade(folder,index):
    folder=Path(folder)
    summary=json.loads((folder/'SUMMARY.json').read_text(encoding='utf-8'))
    c=json.loads((folder/'config.json').read_text(encoding='utf-8'))
    with (folder/'HOLDOUT_TRADES.csv').open(encoding='utf-8-sig',newline='') as f:trades=list(csv.DictReader(f))
    if not 0<=index<len(trades):raise ValueError('Indice trade non valido')
    trade=trades[index];side=int(trade['side'])
    ep={k[2:]:v for k,v in summary['params'].items() if k.startswith('e:')}
    entry_us=int((np.datetime64(trade['entry_utc'],'us')-EPOCH)/np.timedelta64(1,'us'))
    for meta in summary['datasets']:
        d,_=load_cache(Path(meta['cache_directory']))
        start=int(np.searchsorted(d['times'],entry_us))
        if start>=len(d['times']) or int(d['times'][start])!=entry_us:continue
        flatten=c.get('flatten_seconds') # Legacy jobs retain their original semantics.
        entries,ends,good=execution_arrays(d,c['horizon'],c['delay_ms'],c['max_gap'],c['max_entry_gap'],flatten)
        matches=np.flatnonzero((entries==start)&good)
        if not len(matches):continue
        bar=int(matches[0]);end=int(ends[bar]);filename=f'AUDIT_{index:06d}.csv';sample=[];tail=[];events=[]
        if flatten is not None:
            observed=int(observation_times(d)[bar])
            cutoff=int(d['day_end'][bar])-(18*3600-flatten)*1_000_000
            if observed+c['delay_ms']*1000+c['horizon']*60_000_000>=cutoff-1_000_000:c['timeout_reason']='END_OF_DAY'
        with (folder/filename).open('w',encoding='utf-8',newline='') as f:
            writer=None
            def emit(row):
                nonlocal writer
                tick=row['tick_index_in_snapshot']
                row.update(bid_volume=int(d['tick_bid'][tick]),ask_volume=int(d['tick_ask'][tick]),total_volume=int(d['tick_volume'][tick]))
                if writer is None:writer=csv.DictWriter(f,fieldnames=list(row));writer.writeheader()
                writer.writerow(row)
                if len(sample)<5:sample.append(row)
                tail.append(row)
                if len(tail)>5:tail.pop(0)
                if row['event']!='TICK':events.append(row)
            result=trace(d['price'],d['times'],start,end,side,ep,c,emit)
        actual_utc=str(EPOCH+np.timedelta64(int(d['times'][result['exit_index']]),'us'))
        result.update(verified=abs(result['net_usd']-float(trade['net_usd']))<1e-7 and actual_utc==trade['exit_utc'] and result['reason']==trade['exit_reason'],
            file=filename,trade_index=index,source=meta['signature']['path'],source_sha256=meta['source_sha256'],
            signal_bar_utc=str(EPOCH+np.timedelta64(int(d['bar_time'][bar]),'us')),production_trade=trade,first_ticks=sample,last_ticks=tail,
            state_changes=len(events),events=events[:100])
        (folder/f'AUDIT_{index:06d}.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        return result
    raise ValueError('Ingresso non trovato nello snapshot SCID della ricerca')
