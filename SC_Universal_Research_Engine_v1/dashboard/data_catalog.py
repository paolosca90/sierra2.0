"""Discover Sierra contracts and plan explicit rollovers without hindsight."""
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
import re
import struct
import csv
import hashlib
from zoneinfo import ZoneInfo
from scid_dataset import EPOCH_PY

NY=ZoneInfo('America/New_York')
MONTH_CODES={3:'H',6:'M',9:'U',12:'Z'}


def front_contract(day):
    for year in (day.year,day.year+1):
        for month,code in MONTH_CODES.items():
            first=date(year,month,1)
            third_friday=first+timedelta(days=(4-first.weekday())%7+14)
            roll=third_friday-timedelta(days=8)
            if day<roll:return f'{code}{year%100:02d}'
    raise ValueError('No contract date')


def inventory(folder,instrument):
    root=Path(folder)
    if not root.is_dir():raise ValueError('Cartella Data Sierra non trovata')
    rows=[]
    for path in root.glob(instrument+'*.scid'):
        match=re.match('^'+instrument+r'([HMUZ])(\d{1,2})(?:-CME|\.CME|_FUT_CME)?$',path.stem)
        if not match or path.stat().st_size<96:continue
        code=match[1]+(match[2] if len(match[2])==2 else '2'+match[2])
        try:
            size=path.stat().st_size
            with path.open('rb') as f:
                h=f.read(56)
                if h[:4]!=b'SCID' or struct.unpack_from('<IIH',h,4)!=(56,40,1):continue
                first=struct.unpack('<q',f.read(8))[0]
                # A partial live append is ignored for inventory only; reader is strict.
                f.seek(56+((size-56)//40-1)*40);last=struct.unpack('<q',f.read(8))[0]
            first_dt=(EPOCH_PY+timedelta(microseconds=first)).astimezone(NY)
            last_dt=(EPOCH_PY+timedelta(microseconds=last)).astimezone(NY)
            rows.append(dict(symbol=path.stem,contract=code,path=str(path.resolve()),bytes=size,
                             first=first_dt.isoformat(),last=last_dt.isoformat()))
        except (OSError,ValueError,OverflowError,struct.error):continue
    return sorted(rows,key=lambda r:(r['contract'][1:],r['first']))


def expiry(code):
    first=date(2000+int(code[1:]),next(m for m,c in MONTH_CODES.items() if c==code[0]),1)
    return first+timedelta(days=(4-first.weekday())%7+14)


def next_contract(code):
    exp=expiry(code);month=exp.month+3;year=exp.year
    if month>12:month=3;year+=1
    return MONTH_CODES[month]+f'{year%100:02d}'


def expiry_contract(day):
    for year in (day.year,day.year+1):
        for month,code in MONTH_CODES.items():
            identity=code+f'{year%100:02d}'
            if expiry(identity)>=day:return identity


def read_daily(folder,instrument,code):
    root=Path(folder);paths=[root/f'{instrument}{code}-CME.dly',root/f'{instrument}{code}.CME.dly',root/f'{instrument}{code[0]}{code[-1]}.CME.dly']
    path=next((p for p in paths if p.is_file()),None)
    if path is None:raise ValueError(f'Manca {instrument}{code}-CME.dly: apri il grafico Historical Daily in Sierra per scaricare volumi giornalieri')
    content=path.read_bytes();rows={}
    for raw in csv.DictReader(content.decode('utf-8-sig').splitlines()):
        r={k.strip().lower():v.strip() for k,v in raw.items()}
        d=datetime.strptime(r['date'],'%Y/%m/%d').date()
        if d in rows:raise ValueError(f'Date duplicate in {path.name}')
        rows[d]=dict(volume=int(float(r['volume'])),settlement=float(r.get('close',r.get('last'))))
    return rows,dict(path=str(path),sha256=hashlib.sha256(content).hexdigest())


def liquidity_rolls(folder,instrument,first,last):
    codes=[];d=first
    while d<=last:
        code=expiry_contract(d)
        if code not in codes:codes.append(code)
        d+=timedelta(days=1)
    rolls=[]
    for code in codes:
        ex=expiry(code);window=date(ex.year,ex.month-1,1)
        if last<window:continue
        following=next_contract(code);old,old_source=read_daily(folder,instrument,code);new,new_source=read_daily(folder,instrument,following)
        common=sorted(d for d in old.keys()&new.keys() if window<=d<=ex and d<datetime.now(NY).date())
        crossing=next((d for d in common if new[d]['volume']>old[d]['volume']>0),None)
        if crossing:
            effective=crossing+timedelta(days=1)
            while effective.weekday()>4:effective+=timedelta(days=1)
            rolls.append(dict(outgoing=code,incoming=following,decision_date=crossing.isoformat(),effective_trade_date=effective.isoformat(),
                              outgoing_volume=old[crossing]['volume'],incoming_volume=new[crossing]['volume'],sources=[old_source,new_source]))
        elif last>=ex:raise ValueError(f'Rollover {instrument}{code}: nessun sorpasso volume verificabile prima della scadenza; controlla i file .dly')
    return rolls


def plan(folder,instrument,start,end):
    first=date.fromisoformat(start);last=date.fromisoformat(end)
    if last<first:raise ValueError('Data finale precedente alla data iniziale')
    if (last-first).days>3650:raise ValueError('Massimo 10 anni per una ricerca')
    rows=inventory(folder,instrument);groups=[]
    rolls=liquidity_rolls(folder,instrument,first,last)
    d=first
    while d<=last:
        if d.weekday()<5:
            code=expiry_contract(d)
            for roll in rolls:
                if roll['outgoing']==code and d.isoformat()>=roll['effective_trade_date']:code=roll['incoming'];break
            if not groups or groups[-1]['contract']!=code:groups.append(dict(contract=code,trade_from=d.isoformat(),trade_to=d.isoformat()))
            else:groups[-1]['trade_to']=d.isoformat()
        d+=timedelta(days=1)
    manifest=[];missing=[]
    for group in groups:
        candidates=[r for r in rows if r['contract']==group['contract'] and r['symbol'].endswith('-CME')]
        start_dt=datetime.fromisoformat(group['trade_from']).replace(hour=18,tzinfo=NY)-timedelta(days=1)
        end_dt=datetime.fromisoformat(group['trade_to']).replace(hour=16,minute=55,tzinfo=NY)
        complete=[r for r in candidates if datetime.fromisoformat(r['first'])<=start_dt and datetime.fromisoformat(r['last'])>=end_dt]
        if not complete:
            missing.append(dict(symbol=instrument+group['contract']+'-CME',**group,
                                reason='File assente o intervallo incompleto',available=candidates))
            continue
        chosen=max(complete,key=lambda r:(r['symbol'].endswith('-CME'),r['bytes']))
        daily,daily_source=read_daily(folder,instrument,group['contract'])
        expected=sorted(d.isoformat() for d,r in daily.items() if group['trade_from']<=d.isoformat()<=group['trade_to'] and r['volume']>0)
        # Allow enough earlier context (within the available same contract).
        warmup=(start_dt-timedelta(days=35)).astimezone(timezone.utc)
        to=(end_dt.replace(hour=18,minute=0)).astimezone(timezone.utc)
        manifest.append(dict(scid=chosen['path'],start=warmup.isoformat(),end=to.isoformat(),
                             trade_from=group['trade_from'],trade_to=group['trade_to'],
                             expected_trade_dates=expected,daily_source=daily_source,
                             alternatives=[r['path'] for r in sorted(complete,key=lambda r:r['bytes'],reverse=True) if r['path']!=chosen['path']],
                             partial_alternatives=[r['path'] for r in candidates if r not in complete]))
    return dict(ready=bool(groups) and not missing,manifest=manifest,missing=missing,inventory=rows,rolls=rolls,
                rollover='Tabella fissa da volumi daily Sierra: cambio dalla sessione successiva al sorpasso del nuovo contratto. Prezzi reali, non back-adjusted. Sessione 18:00 New York.',
                note='Copertura da estremi del file; il motore verifica tick e gap durante la preparazione.')
