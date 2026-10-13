"""Immutable time/trade bars over a validated shared SCID tick snapshot."""
import hashlib
import json
import os
import shutil
from datetime import timedelta, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
from footprint_kernel import aggregate_vap
from resource_guard import ensure_memory
from bar_schema import validate_bar_seconds


def trade_starts(times,count):
    from scid_dataset import EPOCH_PY
    if isinstance(count,bool) or not isinstance(count,int) or count<2:
        raise ValueError('Barre trade: almeno 2 trade registrati')
    if not len(times):raise ValueError('Snapshot vuoto')
    ny=ZoneInfo('America/New_York')
    first=(EPOCH_PY+timedelta(microseconds=int(times[0]))).astimezone(ny).date()-timedelta(days=1)
    last=(EPOCH_PY+timedelta(microseconds=int(times[-1]))).astimezone(ny).date()+timedelta(days=1)
    deadlines=[];day=first
    while day<=last:
        boundary=datetime.combine(day,datetime.min.time()).replace(hour=18,tzinfo=ny)
        deadlines.append(int((boundary-EPOCH_PY).total_seconds()*1e6));day+=timedelta(days=1)
    cuts=[np.array([0,len(times)],np.int64),np.searchsorted(times,np.array(deadlines,np.int64))]
    # Prevent a trade bar from bridging a recording gap or session boundary.
    for start in range(0,len(times)-1,1_000_000):
        stop=min(len(times),start+1_000_001)
        gaps=np.flatnonzero(np.diff(times[start:stop])>90_000_000)+start+1
        if len(gaps):cuts.append(gaps)
    boundaries=np.unique(np.concatenate(cuts))
    starts=np.concatenate([np.arange(a,z,count,dtype=np.int64) for a,z in zip(boundaries[:-1],boundaries[1:]) if z>a])
    return starts


def rebar(data,meta,cache,seconds=60,trades=0):
    from scid_dataset import load_cache,EPOCH_PY
    if not trades:validate_bar_seconds(seconds)
    if not trades and seconds==60:return data,meta
    if trades and (isinstance(trades,bool) or not isinstance(trades,int) or trades<2):raise ValueError('Numero trade per barra non valido')
    signature=dict(meta['signature'],seconds=seconds,aggregation_schema=1,trades_per_bar=trades)
    key=hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest();folder=Path(cache)/key
    if (folder/'metadata.json').exists():return load_cache(folder)
    ensure_memory(reclaim=True);folder.mkdir(parents=True,exist_ok=True)
    shared=['times','price','tick_bid','tick_ask','tick_volume','block_low','block_high']
    base=Path(meta['cache_directory'])
    for name in shared:
        dest=folder/(name+'.npy')
        if dest.exists():continue
        try:os.link(base/(name+'.npy'),dest)
        except OSError:shutil.copyfile(base/(name+'.npy'),dest)
    times=data['times'];price=data['price']
    if trades:
        starts=trade_starts(times,trades);bar_time=np.asarray(times[starts])
    else:
        buckets=times//(seconds*1_000_000)
        starts=np.r_[0,np.flatnonzero(np.diff(buckets))+1].astype(np.int64)
        bar_time=buckets[starts]*(seconds*1_000_000);del buckets
    ends=np.r_[starts[1:],len(times)].astype(np.int64)
    low=np.minimum.reduceat(price,starts);high=np.maximum.reduceat(price,starts);close=price[ends-1]
    offsets=np.r_[0,np.cumsum(high.astype(np.int64)-low+1)]
    if offsets[-1]>200_000_000:raise ValueError('Footprint troppo grande; suddividere il periodo')
    bid,ask,volume=aggregate_vap(price,data['tick_bid'],data['tick_ask'],data['tick_volume'],starts,ends,low,offsets)
    ensure_memory(reclaim=True);ny=ZoneInfo('America/New_York')
    local=[(EPOCH_PY+timedelta(microseconds=int(t))).astimezone(ny) for t in bar_time]
    dates=[(t.replace(tzinfo=None)-timedelta(hours=18)+timedelta(days=1)).date() for t in local]
    day=np.array([d.isoformat() for d in dates]);clock=np.array([t.hour*3600+t.minute*60+t.second for t in local],np.int64)
    keys=np.array([[d.toordinal(),(d-timedelta(days=d.weekday())).toordinal(),d.year*12+d.month] for d in dates],np.int64)
    day_end=np.array([int((datetime.combine(d,datetime.min.time()).replace(hour=18,tzinfo=ny)-EPOCH_PY).total_seconds()*1e6) for d in dates],np.int64)
    arrays=dict(bar_time=bar_time,starts=starts,ends=ends,low=low,high=high,close=close,offsets=offsets,
                bid=bid,ask=ask,volume=volume,day=day,day_end=day_end,period_keys=keys,clock_seconds=clock)
    if trades:
        arrays['bar_close_time']=np.asarray(times[ends-1]);arrays['bar_complete']=(ends-starts)==trades
    for name,array in arrays.items():np.save(folder/(name+'.npy'),array,allow_pickle=False)
    new=dict(meta,signature=signature,arrays=shared+list(arrays),cache_directory=str(folder),
             bars=len(starts),vap_rows=int(offsets[-1]),base_cache_directory=str(base),
             bar_aggregation=dict(kind='trades' if trades else 'time',value=trades or seconds,
                                  trade_unit='SCID executed trade record; not a book order',session_reset='18:00 America/New_York'))
    (folder/'metadata.json').write_text(json.dumps(new,indent=2),encoding='utf-8')
    return load_cache(folder)
