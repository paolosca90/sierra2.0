"""Copy original SCID byte ranges to a local snapshot; never edit Sierra data."""
import hashlib
import json
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
from robust_optimizer import RECORD,micros,save_json
from resource_guard import ensure_memory


def compose(spec,base,overrides,cache):
    # overrides = {trade_date: verified source path}; whole missing sessions only.
    paths=sorted({str(Path(base).resolve())}|{str(Path(p).resolve()) for p in overrides.values()})
    states={p:dict(size=Path(p).stat().st_size,mtime=Path(p).stat().st_mtime_ns) for p in paths}
    identity=dict(base=str(Path(base).resolve()),overrides=overrides,start=spec.get('start'),end=spec.get('end'),sources=states)
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:24]
    folder=Path(cache)/'source_snapshots';folder.mkdir(parents=True,exist_ok=True)
    target=folder/(Path(base).stem+'-research-'+key+'.scid');meta_path=target.with_suffix('.json')
    if target.exists() and meta_path.exists():return str(target),json.loads(meta_path.read_text())
    arrays={p:np.memmap(p,dtype=RECORD,offset=56,mode='r',shape=((s['size']-56)//40,)) for p,s in states.items()}
    original=arrays[str(Path(base).resolve())]
    begin=micros(datetime.fromisoformat(spec['start'])) if spec.get('start') else int(original['datetime'][0])
    finish=micros(datetime.fromisoformat(spec['end'])) if spec.get('end') else int(original['datetime'][-1])+1
    segments=[];cursor=begin;tz=ZoneInfo('America/New_York')
    for day,path in sorted(overrides.items()):
        end_day=datetime.fromisoformat(day).replace(hour=18,tzinfo=tz)
        a=max(begin,micros(end_day-timedelta(days=1)));z=min(finish,micros(end_day))
        if a>=z:continue
        if cursor<a:segments.append((str(Path(base).resolve()),cursor,a))
        segments.append((str(Path(path).resolve()),a,z));cursor=z
    if cursor<finish:segments.append((str(Path(base).resolve()),cursor,finish))
    provenance=[];temporary=target.with_suffix('.tmp')
    with Path(base).open('rb') as source:header=source.read(56)
    with temporary.open('wb') as output:
        output.write(header)
        for path,start,end in segments:
            raw=arrays[path];a=int(np.searchsorted(raw['datetime'],start));z=int(np.searchsorted(raw['datetime'],end))
            digest=hashlib.sha256()
            for i in range(a,z,1_000_000):
                ensure_memory(reclaim=True)
                data=np.array(raw[i:min(z,i+1_000_000)],copy=True).tobytes();output.write(data);digest.update(data)
            provenance.append(dict(path=path,record_start=a,record_end=z,sha256=digest.hexdigest()))
    for path,state in states.items():
        if Path(path).stat().st_size!=state['size'] or Path(path).stat().st_mtime_ns!=state['mtime']:
            raise ValueError(f'Sorgente cambiata durante copia snapshot: {path}; riprovare')
    metadata=dict(source_components=provenance,filled_trade_dates=sorted(overrides),identity=identity,
                  note='Original byte ranges only; no interpolation, sorting, synthetic ticks or changes to Sierra files.')
    temporary.replace(target);save_json(meta_path,metadata)
    return str(target),metadata
