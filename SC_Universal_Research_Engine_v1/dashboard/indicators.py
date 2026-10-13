"""Generic indicator protocol. Builtins + explicitly imported local Python plugins."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import numpy as np
from numba import njit
from footprint_kernel import DEFAULTS
from scid_dataset import calculate

ROOT=Path(__file__).resolve().parent
PLUGINS=ROOT/'plugins'


def param(default,label=None,integer=False,min_value=0):
    return dict(default=default,label=label,integer=integer,min=min_value)


BUILTINS={
 'deluxe_levels':dict(name='TO Deluxe · livelli causali',kind='Filtro prezzo',status='ready',filter_only=True,
     description='Distanza da PD/PW/PM HLC, VAH/VAL/POC e range intraday disponibili alla chiusura. Port da riconciliare con Sierra.',
     params=dict(distance=param(8,'Distanza massima (tick)',True,1))),
 'to_reversal':dict(name='TO Reversal Engine',kind='Footprint / order flow',status='ready',
     description='Replica causale: 9.299 barre NQ confrontate con Sierra, zero frecce discordanti ai parametri originali.',
     params={k:param(v,k,k in ['min_agg','diagonal','extreme_ticks','rejection_ticks','close_through','bubbles','separation','trap_buffer','min_trapped','imbalance_volume','lookback','require_extreme','tolerance','volume_weight']) for k,v in DEFAULTS.items()}),
 'rsi':dict(name='RSI · rientro dalle bande',kind='Oscillatore',status='ready',description='RSI Wilder: long quando rientra sopra la banda bassa, short quando rientra sotto la banda alta.',
     params=dict(period=param(14,'Periodo',True,2),lower=param(30,'Banda bassa'),upper=param(70,'Banda alta'))),
 'ema_cross':dict(name='EMA · incrocio medie',kind='Trend',status='ready',description='Long all’incrocio della media veloce sopra la lenta; short all’incrocio opposto.',
     params=dict(fast=param(9,'Periodo veloce',True,1),slow=param(21,'Periodo lento',True,2))),
 'macd':dict(name='MACD · incrocio signal',kind='Oscillatore',status='ready',description='Incroci della linea MACD e della signal EMA su barre chiuse.',
     params=dict(fast=param(12,'EMA veloce',True,1),slow=param(26,'EMA lenta',True,2),signal=param(9,'EMA signal',True,1))),
 'stochastic':dict(name='Stocastico · rientro %K',kind='Oscillatore',status='ready',description='%K non smussato: rientro dalle bande, con uscita gestita dal simulatore.',
     params=dict(period=param(14,'Periodo %K',True,2),lower=param(20,'Banda bassa'),upper=param(80,'Banda alta')))
}


@njit(cache=True)
def ema(x,period):
    out=np.empty(len(x));out[0]=x[0];alpha=2./(period+1)
    for i in range(1,len(x)):out[i]=alpha*x[i]+(1-alpha)*out[i-1]
    return out


@njit(cache=True)
def rsi(x,period):
    out=np.full(len(x),50.);gain=0.;loss=0.
    for i in range(1,len(x)):
        change=x[i]-x[i-1]
        if i<=period:gain+=max(0.,change)/period;loss+=max(0.,-change)/period
        else:gain=(gain*(period-1)+max(0.,change))/period;loss=(loss*(period-1)+max(0.,-change))/period
        if i>=period:out[i]=100.-100./(1.+gain/loss) if loss>0 else 100. if gain>0 else 50.
    return out


@njit(cache=True)
def stochastic(high,low,close,period):
    out=np.full(len(close),50.)
    for i in range(period-1,len(close)):
        hi=np.max(high[i-period+1:i+1]);lo=np.min(low[i-period+1:i+1])
        out[i]=100.*(close[i]-lo)/(hi-lo) if hi>lo else 50.
    return out


def registry():
    result={k:dict(v,id=k) for k,v in BUILTINS.items()}
    if PLUGINS.exists():
        for p in PLUGINS.glob('*.json'):
            meta=json.loads(p.read_text(encoding='utf-8'))
            result[meta['id']]=meta
    return result


def import_source(filename,source,trusted=False):
    if len(source.encode())>1_000_000:raise ValueError('Max 1 MB per sorgente')
    suffix=Path(filename).suffix.lower()
    identity='plugin_'+hashlib.sha256(source.encode()).hexdigest()[:16]
    if suffix=='.py':
        if trusted is not True:
            raise ValueError('Plugin Python non autorizzato: codice senza sandbox con accesso ai file e alla rete del tuo utente. Importa solo sorgenti fidati e conferma trusted_python.')
        tree=ast.parse(source);metadata=None
        for node in tree.body:
            if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='METADATA' for t in node.targets):
                metadata=ast.literal_eval(node.value)
        if not isinstance(metadata,dict) or not isinstance(metadata.get('params'),dict):
            raise ValueError('Plugin Python: servono METADATA={name, params} letterali e compute(data, params)')
        if not any(isinstance(n,ast.FunctionDef) and n.name=='compute' for n in tree.body):
            raise ValueError('Manca compute(data, params)')
        for k,v in metadata['params'].items():
            if not isinstance(v,dict) or not isinstance(v.get('default'),(float,int)) or not np.isfinite(v['default']):
                raise ValueError('Ogni parametro richiede un default numerico finito')
        meta=dict(id=identity,name=str(metadata.get('name',filename)),kind='Plugin Python locale',status='ready',
                  description='Codice fidato senza sandbox: accesso ai file e alla rete del tuo utente. Parità Sierra non verificata.',
                  params=metadata['params'],trusted_python=True,source_sha256=hashlib.sha256(source.encode()).hexdigest())
    elif suffix in ('.cpp','.h'):
        # Import is real source inspection, never an invented conversion.
        import re
        inputs={}
        for alias,index in re.findall(r'SCInputRef\s+(\w+)\s*=\s*sc\.Input\[(\d+)\]',source):
            default=re.search(re.escape(alias)+r'\.Set(?:Float|Int|YesNo)\(([-+\d.]+)\)',source)
            if default:inputs[index]=param(float(default.group(1)),alias)
        meta=dict(id=identity,name=Path(filename).name,kind='Sorgente ACSIL',status='adapter_required',
                  description='Input rilevati. Questo sorgente dipende da Sierra: serve un adattatore verificato prima del backtest offline.',params=inputs)
    else:raise ValueError('Importa un plugin .py oppure un sorgente ACSIL .cpp/.h')
    PLUGINS.mkdir(parents=True,exist_ok=True)
    (PLUGINS/(identity+suffix)).write_bytes(source.encode('utf-8'))
    (PLUGINS/(identity+'.json')).write_text(json.dumps(meta,indent=2),encoding='utf-8')
    return meta


_loaded={}
def plugin_module(identity):
    if not identity.startswith('plugin_') or len(identity)!=23 or any(c not in '0123456789abcdef' for c in identity[7:]):
        raise ValueError('Identita plugin non valida')
    path=PLUGINS/(identity+'.py')
    meta=json.loads((PLUGINS/(identity+'.json')).read_text(encoding='utf-8'))
    source=path.read_bytes();digest=hashlib.sha256(source).hexdigest()
    if meta.get('trusted_python') is not True or meta.get('source_sha256')!=digest or identity!='plugin_'+digest[:16]:
        raise ValueError('Plugin non autorizzato o modificato: reimportare e confermare il sorgente fidato')
    # Verify even cached modules; compile the checked bytes, never a stale .pyc.
    key=(str(path.resolve()),digest)
    if key not in _loaded:
        spec=importlib.util.spec_from_file_location(identity,path)
        module=importlib.util.module_from_spec(spec);exec(compile(source,str(path),'exec'),module.__dict__);_loaded[key]=module
    return _loaded[key]


def signal(identity,data,params):
    close=data['close'].astype(float)
    if identity=='to_reversal':return calculate(data,params)[0]
    if identity.startswith('plugin_'):
        # Expose bar OHLC in PRICE units, timestamps and VAP arrays; no future
        # entry/fill information in the protocol. Plugins must be causal.
        view=dict(close=close*.25,high=data['high']*.25,low=data['low']*.25,time=data['bar_time'],
                  vap_offsets=data['offsets'],vap_bid=data['bid'],vap_ask=data['ask'],vap_volume=data['volume'])
        out=np.asarray(plugin_module(identity).compute(view,dict(params)),dtype=np.float64)
        if out.shape!=close.shape or not np.isfinite(out).all() or np.any(np.abs(out)>1):
            raise ValueError('Plugin deve restituire un segnale finito [-1,1] per ogni barra')
        return out
    n=len(close);out=np.zeros(n)
    if identity in ('ema_cross','macd'):
        if params['fast']>=params['slow']:raise ValueError('Periodo veloce deve essere minore del lento')
        line=ema(close,int(params['fast']))-ema(close,int(params['slow']))
        if identity=='macd':line-=ema(line,int(params['signal']))
        out[1:]=np.where((line[1:]>0)&(line[:-1]<=0),1,np.where((line[1:]<0)&(line[:-1]>=0),-1,0))
    else:
        if not 0<=params['lower']<params['upper']<=100:raise ValueError('Bande: 0 <= bassa < alta <= 100')
        values=rsi(close,int(params['period'])) if identity=='rsi' else stochastic(data['high'],data['low'],data['close'],int(params['period']))
        out[1:]=np.where((values[1:]>params['lower'])&(values[:-1]<=params['lower']),1,
                        np.where((values[1:]<params['upper'])&(values[:-1]>=params['upper']),-1,0))
    return out


def causality_probe(identity,data,params):
    if not identity.startswith('plugin_'):return
    full=signal(identity,data,params)
    for cut in sorted({min(len(full)-1,500),len(full)//2,len(full)-1}):
        if cut<2:continue
        rows=int(data['offsets'][cut])
        partial={k:(v[:rows] if k in ['bid','ask','volume'] else v[:cut+1] if k=='offsets' else v[:cut])
                 for k,v in data.items() if k in ['close','high','low','bar_time','offsets','bid','ask','volume']}
        if not np.allclose(full[:cut],signal(identity,partial,params),atol=1e-7,rtol=0):
            raise ValueError('Plugin non causale: modifica i segnali passati quando arrivano barre future')


@njit(cache=True)
def combine(primary,confirmations,window,any_mode=False):
    out=np.zeros(len(primary));last=np.full(len(confirmations),-1000000,np.int64);direction=np.zeros(len(confirmations))
    for i in range(len(primary)):
        for k in range(len(confirmations)):
            if confirmations[k,i]!=0:last[k]=i;direction[k]=np.sign(confirmations[k,i])
        if any_mode:
            pos=primary[i]>0;neg=primary[i]<0;strength=abs(primary[i])
            for k in range(len(confirmations)):
                pos=pos or confirmations[k,i]>0;neg=neg or confirmations[k,i]<0
                strength=max(strength,abs(confirmations[k,i]))
            if pos and not neg:out[i]=strength
            elif neg and not pos:out[i]=-strength
        elif primary[i]!=0:
            valid=True
            for k in range(len(confirmations)):
                if i-last[k]>window or direction[k]!=np.sign(primary[i]):valid=False
            if valid:out[i]=primary[i]
    return out
