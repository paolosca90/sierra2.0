"""Loopback-only research dashboard. Jobs execute in isolated local processes."""
import json
import math
import os
import secrets
import subprocess
import sys
import uuid
import csv
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from indicators import registry,import_source
from data_catalog import plan
from worker import EXEC_DEFAULTS
from trade_audit import audit_trade
from resource_guard import ensure_memory,available_memory
from research_grid import WEIGHTS,grid_size
from bar_schema import validate_bar_seconds
from instruments import instrument_spec

ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parent;JOBS=PROJECT/'dashboard_jobs'
app=FastAPI(title='Sierra Research Lab',docs_url=None,redoc_url=None)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','testserver'])
TOKEN=secrets.token_urlsafe(32);PROCESSES={}


@app.middleware('http')
async def same_origin(request:Request,call_next):
    if request.method not in ('GET','HEAD','OPTIONS'):
        if request.headers.get('x-local-token')!=TOKEN:
            return JSONResponse({'detail':'Token locale mancante; ricarica la dashboard'},status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    return response


@app.get('/')
def index():return FileResponse(ROOT/'static'/'index.html')


@app.get('/api/bootstrap')
def bootstrap():
    return dict(token=TOKEN,indicators=list(registry().values()),data_folder='C:\\SierraChart\\Data',
                execution_defaults=EXEC_DEFAULTS,version='0.1-local',available_memory_bytes=available_memory(),reserved_memory_gib=4)


@app.post('/api/plan')
async def get_plan(request:Request):
    c=await request.json()
    if c.get('instrument') not in ('NQ','ES'):raise HTTPException(400,'Strumento non supportato')
    try:return plan(c['data_folder'],c['instrument'],c['start'],c['end'])
    except (ValueError,OSError,KeyError) as e:raise HTTPException(400,str(e))


@app.post('/api/import')
async def upload(request:Request):
    if int(request.headers.get('content-length','0'))>1_100_000:raise HTTPException(413,'Sorgente troppo grande')
    c=await request.json()
    try:return import_source(c['filename'],c['source'],trusted=c.get('trusted_python',False))
    except (ValueError,SyntaxError,KeyError) as e:raise HTTPException(400,str(e))


def validate_config(c):
    from entry_sessions import validate_windows
    instrument_spec(c.get('instrument'))
    validate_windows(c.get('entry_windows',[]))
    c.setdefault('trades_per_bar',0)
    if isinstance(c['trades_per_bar'],bool) or not isinstance(c['trades_per_bar'],int) or c['trades_per_bar'] not in [0] and not 2<=c['trades_per_bar']<=100000:
        raise ValueError('trades_per_bar: 0 per barre tempo oppure 2..100000 trade')
    c.setdefault('execution',{}).setdefault('session_mode',[0])
    for key,default,low,high in [('min_active_days',0,0,100000),('min_trades_per_training_block',0,0,100000),
                              ('training_blocks',3,2,6),('validation_min_trades',30,1,100000),('validation_min_active_days',10,1,100000)]:
        c.setdefault(key,default)
        if isinstance(c[key],bool) or not isinstance(c[key],int) or not low<=c[key]<=high:
            raise ValueError(f'{key}: intero {low}..{high}')
    reserve=c.get('memory_reserve_gib',4)
    if isinstance(reserve,bool) or not isinstance(reserve,(int,float)) or not math.isfinite(reserve) or not 2<=reserve<=8:
        raise ValueError('Riserva RAM: 2..8 GiB')
    c.setdefault('flatten_seconds',60900)
    if not isinstance(c['flatten_seconds'],int) or not 3600<=c['flatten_seconds']<=60900:
        raise ValueError('Chiusura obbligatoria entro le 16:55 New York')
    schema=registry().get(c.get('indicator'))
    if not schema or schema['status']!='ready' or schema.get('filter_only'):raise ValueError('Indicatore principale non eseguibile: serve adattatore o sorgente di segnali')
    for key,lo,hi in [('trials',1,10000),('bar_seconds',1,3600),('min_trades',1,100000),('horizon',1,1440),('seed',0,2**31-1),
                      ('entry_slip',0,100),('stop_slip',0,100),('exit_slip',0,100),('target_through',0,20),('delay_ms',0,60000)]:
        value=c.get(key)
        if isinstance(value,bool) or not isinstance(value,int) or not lo<=value<=hi:raise ValueError(f'{key}: valore intero {lo}..{hi}')
    if not c['trades_per_bar']:validate_bar_seconds(c['bar_seconds'])
    for key,lo,hi in [('commission',0,1000),('max_gap',1,3600),('max_entry_gap',.001,3600),('level_filter',0,1000)]:
        value=c.get(key)
        if not isinstance(value,(int,float)) or not math.isfinite(value) or not lo<=value<=hi:raise ValueError(f'{key}: valore non valido')
    if c.get('method') not in ('tpe','grid'):raise ValueError('Metodo non valido')
    for flag in ('available_data_only','exploratory_retest','calibrate_sensitivity'):
        if flag in c and not isinstance(c[flag],bool):raise ValueError(f'{flag}: valore booleano richiesto')
    if set(c.get('parameters',{}))!=set(schema['params']):raise ValueError('Parametri indicatore mancanti/sconosciuti')
    if set(c.get('execution',{}))!=set(EXEC_DEFAULTS):raise ValueError('Parametri gestione mancanti/sconosciuti')
    combos=1
    for group in ['parameters','execution']:
        for k,values in c[group].items():
            if not isinstance(values,list) or not 1<=len(values)<=1000:raise ValueError(f'{k}: lista valori non valida')
            if any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):raise ValueError(f'{k}: usare numeri finiti')
            meta=schema['params'][k] if group=='parameters' else dict(integer=k!='min_score',min=1 if k=='quantity' else 0)
            if any(v<meta.get('min',0) or (meta.get('integer') and int(v)!=v) for v in values):raise ValueError(f'{k}: tipo/intervallo non valido')
            if group=='execution' and k=='min_score' and any(v<=0 or v>1 for v in values):raise ValueError('Score deve essere >0 e <=1')
            if group=='execution' and k=='quantity' and any(v>100 for v in values):raise ValueError('Massimo 100 contratti simulati')
            if group=='execution' and k=='session_mode' and any(v>3 for v in values):raise ValueError('session_mode: 0 ALL, 1 RTH, 2 AM, 3 PM')
            combos*=len(values)
    if c.get('combine_mode','and') not in ('and','or'):raise ValueError('Combinazione non valida')
    if not isinstance(c.get('confirmation_bars',3),int) or not 0<=c.get('confirmation_bars',3)<=500:raise ValueError('Conferme: 0..500 barre')
    if len(c.get('confirmations',[]))>5:raise ValueError('Massimo 5 indicatori di conferma/filtro')
    for node in c.get('confirmations',[]):
        meta=registry().get(node.get('indicator'))
        if not meta or meta['status']!='ready':raise ValueError('Conferma non eseguibile')
        if set(node.get('parameters',{}))!=set(meta['params']):raise ValueError('Parametri conferma incompleti')
        for k,vs in node['parameters'].items():
            definition=meta['params'][k]
            if not isinstance(vs,list) or not 1<=len(vs)<=1000 or any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<definition.get('min',0) or (definition.get('integer') and int(v)!=v) for v in vs):
                raise ValueError(f'Parametro conferma {k} non valido')
            combos*=len(vs)
    profiles=c.get('weight_profiles')
    if profiles:
        if c['method']!='grid' or c['indicator']!='to_reversal' or not isinstance(profiles,list) or len(profiles)>1000:
            raise ValueError('Profili pesi disponibili solo per griglia TO')
        for profile in profiles:
            if not isinstance(profile,dict) or set(profile)!=set(WEIGHTS) or any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in profile.values()) or sum(profile.values())<=0:
                raise ValueError('Profilo pesi non valido')
        combos=combos//math.prod(len(c['parameters'][k]) for k in WEIGHTS)*len(profiles)
    if c.get('calibrate_sensitivity') and c['indicator']=='to_reversal':
        combos//=len(c['parameters']['sensitivity'])
    if c['method']=='grid' and combos>10000:raise ValueError('Griglia >10.000 combinazioni: seleziona ricerca TPE o riduci i valori')
    if c['method']=='grid' and c['trials']<combos:raise ValueError(f'Per griglia completa imposta almeno {combos} prove')
    planned=plan(c['data_folder'],c['instrument'],c['start'],c['end'])
    if not planned['ready']:raise ValueError('Copertura SCID incompleta: controlla i file richiesti nel pannello dati')
    c['manifest']=planned['manifest'];c['rollover_evidence']=planned['rolls'];c['rollover_method']=planned['rollover'];c['cache']=str(PROJECT/'.scid_cache')
    return c


@app.post('/api/jobs')
async def create_job(request:Request):
    raw=await request.json()
    reserve=raw.get('memory_reserve_gib',4)
    if isinstance(reserve,bool) or not isinstance(reserve,(int,float)) or not math.isfinite(reserve) or not 2<=reserve<=8:
        raise HTTPException(400,'Riserva RAM: 2..8 GiB')
    try:ensure_memory(reserve=int(reserve*1024**3))
    except MemoryError as e:raise HTTPException(409,str(e))
    if any(p.poll() is None for p in PROCESSES.values()):raise HTTPException(409,'Una ricerca è già in corso; attendi o annulla')
    try:c=validate_config(raw)
    except (ValueError,KeyError,TypeError,OSError) as e:raise HTTPException(400,str(e))
    job_id=uuid.uuid4().hex;folder=JOBS/job_id;folder.mkdir(parents=True)
    c['created_at']=datetime.now().isoformat()
    (folder/'config.json').write_text(json.dumps(c,indent=2),encoding='utf-8')
    with (folder/'worker.log').open('wb') as log:
        process=subprocess.Popen([sys.executable,str(ROOT/'worker.py'),str(folder)],stdout=log,stderr=subprocess.STDOUT,
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,cwd=ROOT)
    PROCESSES[job_id]=process
    return dict(id=job_id,status='running')


def job_folder(identity):
    if len(identity)!=32 or any(c not in '0123456789abcdef' for c in identity):raise HTTPException(404,'Ricerca non trovata')
    folder=JOBS/identity
    if not folder.is_dir():raise HTTPException(404,'Ricerca non trovata')
    return folder


@app.post('/api/jobs/{identity}/resume')
async def resume_job(identity:str,request:Request):
    raw=await request.json();folder=job_folder(identity)
    if (folder/'SUMMARY.json').exists():raise HTTPException(409,'Ricerca gia completata')
    if any(p.poll() is None for p in PROCESSES.values()):raise HTTPException(409,'Una ricerca e gia in corso')
    c=read_json(folder/'config.json',{})
    if 'memory_reserve_gib' in raw:c['memory_reserve_gib']=raw['memory_reserve_gib']
    try:
        c=validate_config(c);ensure_memory(reserve=int(c.get('memory_reserve_gib',4)*1024**3))
    except MemoryError as e:raise HTTPException(409,str(e))
    except (ValueError,TypeError,KeyError) as e:raise HTTPException(400,str(e))
    c['resumed_at']=datetime.now().isoformat();save_tag=datetime.now().strftime('%Y%m%d%H%M%S%f')
    for name in ['ERROR.json','CANCELLED']:
        old=folder/name
        if old.exists():old.rename(folder/(old.stem+'_'+save_tag+old.suffix))
    (folder/'config.json').write_text(json.dumps(c,indent=2),encoding='utf-8')
    with (folder/'worker.log').open('ab') as log:
        process=subprocess.Popen([sys.executable,str(ROOT/'worker.py'),str(folder)],stdout=log,stderr=subprocess.STDOUT,
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,cwd=ROOT)
    PROCESSES[identity]=process
    return dict(id=identity,status='running')


def read_json(path,default=None):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,json.JSONDecodeError):return default


@app.get('/api/jobs')
def list_jobs():
    rows=[]
    if JOBS.exists():
        for folder in sorted(JOBS.iterdir(),key=lambda f:f.stat().st_mtime,reverse=True)[:30]:
            c=read_json(folder/'config.json',{})
            if c:rows.append(dict(id=folder.name,indicator=c['indicator'],instrument=c['instrument'],start=c['start'],end=c['end'],
                                  label=c.get('research_label'),
                                  complete=(folder/'SUMMARY.json').exists(),created=c.get('created_at')))
    return rows


@app.get('/api/jobs/{identity}')
def get_job(identity:str):
    folder=job_folder(identity);process=PROCESSES.get(identity)
    summary=read_json(folder/'SUMMARY.json');error=read_json(folder/'ERROR.json')
    status='complete' if summary else 'failed' if error else 'cancelled' if (folder/'CANCELLED').exists() else 'running' if process and process.poll() is None else 'interrupted'
    return dict(id=identity,status=status,progress=read_json(folder/'progress.json',{}),summary=summary,error=error,
                files=[p.name for p in folder.iterdir() if p.suffix in ('.json','.csv','.log')])


@app.post('/api/jobs/{identity}/cancel')
def cancel(identity:str):
    folder=job_folder(identity);process=PROCESSES.get(identity)
    if process and process.poll() is None:
        if os.name=='nt':
            # Windows venv launchers create a child interpreter; stopping only
            # the launcher leaves computation running. Terminate our job tree.
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=15,check=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:process.terminate()
        process.wait(timeout=10);(folder/'CANCELLED').write_text('cancelled')
    return dict(status='cancelled')


@app.get('/api/jobs/{identity}/files/{filename}')
def download(identity:str,filename:str):
    folder=job_folder(identity)
    if Path(filename).name!=filename or Path(filename).suffix not in ('.json','.csv','.log'):raise HTTPException(404)
    path=folder/filename
    if not path.is_file():raise HTTPException(404)
    return FileResponse(path,filename=filename)


@app.get('/api/jobs/{identity}/trades')
def get_trades(identity:str,offset:int=0,limit:int=50):
    folder=job_folder(identity);path=folder/'HOLDOUT_TRADES.csv'
    if not path.exists():raise HTTPException(404,'Trade non disponibili')
    with path.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    offset=max(0,offset);limit=max(1,min(100,limit))
    return dict(total=len(rows),offset=offset,trades=[dict(r,index=i) for i,r in enumerate(rows) if offset<=i<offset+limit])


@app.post('/api/jobs/{identity}/audit/{trade_index}')
def audit(identity:str,trade_index:int):
    try:return audit_trade(job_folder(identity),trade_index)
    except (ValueError,OSError,KeyError) as e:raise HTTPException(400,str(e))


app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
