"""Read-only SCID -> memory-mapped tick tape and compact bar footprint cache."""
import csv
import hashlib
import json
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from footprint_kernel import aggregate_vap, block_extrema, scores, vector
from robust_optimizer import RECORD, EPOCH, CSV_DT, micros, save_json
from resource_guard import ensure_memory

SCHEMA = 2
EPOCH_PY = datetime(1899,12,30,tzinfo=timezone.utc)


def load_cache(folder):
    folder=Path(folder).resolve()
    meta=json.loads((folder/'metadata.json').read_text())
    # Older caches can contain a relative creation path. The directory being
    # opened is authoritative, including when a dashboard worker has another cwd.
    meta['cache_directory']=str(folder)
    return {name:np.load(folder/(name+'.npy'),mmap_mode='r',allow_pickle=False)
            for name in meta['arrays']},meta


def prepare(path, cache_root, seconds=60, chart_timezone='America/New_York', start=None, end=None):
    """Window endpoints UTC, exclusive end. Processes one contract at a time.

    Memory maps the tape, bounds temporary allocations to 1m records. Cache
    identity uses path,size,mtime,window; SHA256 of actual input bytes is saved.
    Changing/appending the source invalidates the cache (immutable snapshots).
    """
    path=Path(path).resolve();cache_root=Path(cache_root)
    if path.stem.endswith('.CME'):
        raise ValueError('Alias .CME escluso: scala prezzi non verificata; usare solo -CME senza normalizzazione')
    if seconds < 1 or 86400 % seconds:
        raise ValueError('Time bar size must divide a UTC day')
    stat=path.stat()
    signature=dict(schema=SCHEMA,path=str(path),bytes=stat.st_size,mtime_ns=stat.st_mtime_ns,
                   seconds=seconds,timezone=chart_timezone,start=start,end=end)
    key=hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()
    folder=cache_root/key
    if (folder/'metadata.json').exists():
        data,meta=load_cache(folder);meta['cache_hit']=True
        return data,meta
    folder.mkdir(parents=True,exist_ok=True)
    with path.open('rb') as f:header=f.read(56)
    if len(header)!=56 or header[:4]!=b'SCID' or struct.unpack_from('<IIH',header,4)!=(56,40,1):
        raise ValueError('Unsupported SCID layout/version')
    if (stat.st_size-56)%40:raise ValueError('Incomplete SCID record; retry when writer completes')
    raw=np.memmap(path,dtype=RECORD,offset=56,mode='r',shape=((stat.st_size-56)//40,))
    a=0 if start is None else np.searchsorted(raw['datetime'],micros(datetime.fromisoformat(start)))
    z=len(raw) if end is None else np.searchsorted(raw['datetime'],micros(datetime.fromisoformat(end)))
    if z<=a:raise ValueError('No records in requested window')
    r=raw[a:z]
    count=int(np.count_nonzero(r['total_volume']))
    if count<2:raise ValueError('No executed trades')
    output={}
    for name,dtype in [('times','int64'),('price','int32'),('tick_bid','uint32'),('tick_ask','uint32'),('tick_volume','uint32')]:
        output[name]=np.lib.format.open_memmap(folder/(name+'.npy'),mode='w+',dtype=dtype,shape=(count,))
    h=hashlib.sha256(header);pos=0;prior=-1
    for chunk in range(0,len(r),1_000_000):
        ensure_memory(reclaim=True)
        snapshot=np.array(r[chunk:chunk+1_000_000],copy=True)
        h.update(snapshot.tobytes())
        if np.any(np.diff(snapshot['datetime'])<0) or snapshot['datetime'][0]<prior:
            bad=np.flatnonzero(np.diff(snapshot['datetime'])<0)
            offset=int(bad[0]+1) if len(bad) else 0
            raise ValueError(f'{path.name}: timestamp fuori ordine al record {int(a)+chunk+offset}; nessun riordino automatico')
        prior=int(snapshot['datetime'][-1])
        rows=snapshot[snapshot['total_volume']>0]
        flags=(rows['open']==0)|(rows['open']==np.float32(-1.99900095e37))|(rows['open']==np.float32(-1.99900197e37))
        if not np.all(flags & (rows['num_trades']==1)):
            raise ValueError('Aggregated/unknown records: cannot reconstruct tick footprint')
        if not np.isfinite(rows['close']).all() or np.any(rows['close']<=0):
            raise ValueError('Invalid prices')
        if not np.allclose(rows['close'].astype(float)*4,np.rint(rows['close'].astype(float)*4),atol=1e-6,rtol=0):
            raise ValueError('NQ/ES prices must be on .25 tick grid')
        if np.any(rows['bid_volume'].astype(np.uint64)+rows['ask_volume']!=rows['total_volume']):
            raise ValueError('Unclassified volume: bid+ask must equal total volume for footprint parity')
        n=len(rows)
        output['times'][pos:pos+n]=rows['datetime']
        output['price'][pos:pos+n]=np.rint(rows['close'].astype(float)*4).astype(np.int32)
        for dest,source in [('tick_bid','bid_volume'),('tick_ask','ask_volume'),('tick_volume','total_volume')]:
            output[dest][pos:pos+n]=rows[source]
        pos+=n
    if pos!=count:raise ValueError('Source changed during snapshot; retry with stable historical file')
    # Sierra may append live ticks while historical input is read. Verify the
    # selected prefix again on any modification; accept only identical bytes.
    changed=path.stat().st_mtime_ns!=stat.st_mtime_ns
    if changed:
        verify=hashlib.sha256(header)
        for chunk in range(0,len(r),1_000_000):
            verify.update(np.array(r[chunk:chunk+1_000_000],copy=True).tobytes())
        if verify.digest()!=h.digest():
            raise ValueError('Historical source bytes changed during snapshot; retry on stable data')
    for arr in output.values():arr.flush()
    # Input mapping is no longer needed. Release it before allocating footprint
    # arrays, instead of retaining both the original tape and its parsed cache.
    del r,raw,rows,snapshot
    times,price=output['times'],output['price']
    buckets=times//(seconds*1_000_000)
    starts=np.r_[0,np.flatnonzero(np.diff(buckets))+1].astype(np.int64)
    ends=np.r_[starts[1:],len(times)].astype(np.int64)
    bar_time=buckets[starts]*(seconds*1_000_000)
    del buckets
    low=np.minimum.reduceat(price,starts);high=np.maximum.reduceat(price,starts)
    close=price[ends-1]
    offsets=np.r_[0,np.cumsum(high.astype(np.int64)-low+1)]
    if offsets[-1]>200_000_000:
        raise ValueError('Footprint window too large; split by contract/date in manifest')
    vb,va,vv=aggregate_vap(price,output['tick_bid'],output['tick_ask'],output['tick_volume'],starts,ends,low,offsets)
    ensure_memory(reclaim=True)
    block_low,block_high=block_extrema(price)
    tz=ZoneInfo(chart_timezone)
    local=[(EPOCH_PY+timedelta(microseconds=int(t))).astimezone(tz) for t in bar_time]
    # Trade date rolls at 18:00 New York; calendar/DST boundaries explicit.
    trade_dates=[(d.replace(tzinfo=None)-timedelta(hours=18)+timedelta(days=1)).date() for d in local]
    day=np.array([d.isoformat() for d in trade_dates])
    period_keys=np.array([[d.toordinal(),(d-timedelta(days=d.weekday())).toordinal(),d.year*12+d.month] for d in trade_dates],np.int64)
    clock_seconds=np.array([d.hour*3600+d.minute*60+d.second for d in local],np.int64)
    day_end=np.array([micros(datetime.combine(d,datetime.min.time()).replace(hour=18,tzinfo=tz)) for d in trade_dates],np.int64)
    arrays=dict(output,bar_time=bar_time,starts=starts,ends=ends,low=low,high=high,close=close,
                offsets=offsets,bid=vb,ask=va,volume=vv,block_low=block_low,block_high=block_high,
                day=day,day_end=day_end,period_keys=period_keys,clock_seconds=clock_seconds)
    for name,arr in arrays.items():
        if name not in output:np.save(folder/(name+'.npy'),arr,allow_pickle=False)
    meta=dict(signature=signature,source_sha256=h.hexdigest(),record_range=[int(a),int(z)],
              trades=count,bars=len(starts),vap_rows=int(offsets[-1]),arrays=list(arrays),cache_hit=False,
              cache_directory=str(folder),first_utc=str(EPOCH+np.timedelta64(int(times[0]),'us')),
              last_utc=str(EPOCH+np.timedelta64(int(times[-1]),'us')))
    # A source that was appended is a valid prefix snapshot; flag it explicitly.
    meta['source_changed_during_read']=changed
    save_json(folder/'metadata.json',meta)
    return load_cache(folder)


def prepare_spec(spec,cache,seconds=60,trades_per_bar=0):
    if seconds!=60 or trades_per_bar:
        from bar_aggregation import rebar
        data,meta=prepare_spec(spec,cache,60)
        return rebar(data,meta,cache,seconds,trades_per_bar)
    rejected=[];valid=[];expected=set(spec.get('expected_trade_dates',[]))
    for path in [spec['scid']]+spec.get('alternatives',[]):
        try:
            data,meta=prepare(path,cache,seconds,start=spec.get('start'),end=spec.get('end'))
            present=set(data['day']);valid.append((path,present))
            missing=expected-present
            if not missing:return data,dict(meta,rejected_sources=rejected)
            if spec.get('allow_missing_trade_dates',False):
                return data,dict(meta,rejected_sources=rejected,excluded_trade_dates=sorted(missing),
                                 coverage_policy='Explicitly authorized available -CME dates only; gaps are not filled')
            rejected.append(dict(path=path,error='Giornate intere assenti: '+', '.join(sorted(missing))))
        except (ValueError,OSError) as error:
            rejected.append(dict(path=path,error=str(error)))
    if valid and expected:
        base,present=valid[0];missing=expected-present;overrides={}
        for path in spec.get('partial_alternatives',[]):
            try:
                # Only the replacement interval is eligible. Corrupt records
                # elsewhere in an alias must never be copied into the snapshot.
                tz=ZoneInfo('America/New_York')
                replacement_start=datetime.fromisoformat(min(missing)).replace(hour=18,tzinfo=tz)-timedelta(days=1)
                replacement_end=datetime.fromisoformat(max(missing)).replace(hour=18,tzinfo=tz)
                data,_=prepare(path,cache,seconds,start=replacement_start.astimezone(timezone.utc).isoformat(),end=replacement_end.astimezone(timezone.utc).isoformat())
                valid.append((path,set(data['day'])))
            except (ValueError,OSError) as error:rejected.append(dict(path=path,error=str(error)))
        for day in sorted(missing):
            replacement=next((path for path,days in valid[1:] if day in days),None)
            if replacement:overrides[day]=replacement
        if set(overrides)==missing:
            from scid_gap_snapshot import compose
            source,provenance=compose(spec,base,overrides,cache)
            del data
            data,meta=prepare(source,cache,seconds,start=spec.get('start'),end=spec.get('end'))
            if expected-set(data['day']):raise ValueError('Snapshot incompleto dopo unione delle fonti')
            return data,dict(meta,rejected_sources=rejected,**provenance)
    raise ValueError('Nessun SCID utilizzabile per il contratto: '+json.dumps(rejected,ensure_ascii=False))


def calculate(data,params=None):
    return scores(data['low'],data['high'],data['close'],data['offsets'],data['bid'],data['ask'],data['volume'],vector(params))


def parity(data,csv_path,params=None,chart_timezone='America/New_York'):
    signal,metrics=calculate(data,params)
    tz=ZoneInfo(chart_timezone);checked=0;different=0;max_error=0.;metric_bad=np.zeros(4,int)
    examples=[];ohlc_bad=0;mask_bad=0
    with Path(csv_path).open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['kind']!='BAR_CLOSE':continue
            t=micros(datetime.strptime(r['bar_start'],CSV_DT).replace(tzinfo=tz))
            idx=np.searchsorted(data['bar_time'],t)
            if idx>=len(signal) or data['bar_time'][idx]!=t or idx<500:continue
            if data['high'][idx]/4!=float(r['high']) or data['low'][idx]/4!=float(r['low']) or data['close'][idx]/4!=float(r['close']):
                ohlc_bad+=1
            error=abs(float(signal[idx])-float(r['reversal_score']))
            checked+=1;different+=error>1e-5;max_error=max(max_error,error)
            mask=1 if signal[idx]>=.3 else 2 if signal[idx]<=-.3 else 0
            mask_bad+=mask!=(int(r['signal_mask'])&3)
            for k,name in enumerate(['bar_delta','net_trapped','net_imbalance_count','net_absorbed_volume']):
                if name in r:metric_bad[k]+=abs(metrics[idx,k]-float(r[name]))>.1
            if error>1e-5 and len(examples)<8:
                examples.append(dict(time=r['bar_start'],sierra=float(r['reversal_score']),offline=float(signal[idx])))
    return dict(checked=checked,score_mismatches=int(different),max_score_error=max_error,
                ohlc_mismatches=ohlc_bad,marker_mismatches=int(mask_bad),metric_mismatches=metric_bad.tolist(),
                passed=bool(checked>=100 and different==0 and ohlc_bad==0 and not metric_bad.any() and mask_bad==0),examples=examples)


def observation_times(data):
    if 'bar_close_time' in data:return data['bar_close_time']
    times=data['times'];n=len(data['bar_time'])
    observed=np.zeros(n,np.int64);observed[:-1]=times[data['starts'][1:]];observed[-1]=times[-1]
    return observed


def execution_arrays(data,horizon=30,delay_ms=1,max_gap=90.,max_entry_gap=5.,flatten_seconds=None):
    times=data['times'];n=len(data['bar_time'])
    # A time bar closes on first print of the next bar, not retrospectively
    # at its last print. Last bar is never eligible.
    observed=observation_times(data)
    due=observed+delay_ms*1000
    entry=np.searchsorted(times,due,side='right')
    deadline=due+horizon*60_000_000
    if flatten_seconds is not None:
        cutoff=data['day_end']-(18*3600-flatten_seconds)*1_000_000
        # Send flatten one second before the hard deadline. No retrospective
        # last-print fill: execution remains the first subsequent real print.
        deadline=np.minimum(deadline,cutoff-1_000_000)
    end=np.searchsorted(times,deadline)
    good=(entry<len(times))&(end<len(times))&(end>entry)
    entry=np.minimum(entry,len(times)-1);end=np.minimum(end,len(times)-1)
    # O(ticks) once; trials don't scan gaps repeatedly.
    gap_prefix=np.r_[0,np.cumsum(np.diff(times)>max_gap*1e6)]
    good &= (times[entry]-due<=max_entry_gap*1e6)&(times[end]-deadline<=max_entry_gap*1e6)
    good &= (gap_prefix[end]-gap_prefix[entry]==0)
    good &= times[end]<data['day_end']
    if flatten_seconds is not None:good &= (times[end]<=cutoff)&(times[entry]<cutoff-1_000_000)
    # Drop warmup, first partial and last still-forming bar, and bar/session gaps.
    good[:min(500,n)]=False;good[-1]=False
    if 'bar_complete' in data:
        good &= data['bar_complete']
    elif n>1:
        bar_duration=int(np.min(np.diff(data['bar_time'])))
        good &= observed-data['bar_time']<=bar_duration+max_entry_gap*1e6
    else:good[:]=False
    return entry,end,good
