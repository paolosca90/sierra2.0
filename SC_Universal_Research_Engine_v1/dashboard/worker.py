"""Isolated research job used by the local dashboard; no order routing."""
import json
import math
import sys
import time
import traceback
import hashlib
import platform
import importlib.metadata
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import numpy as np
import optuna
from scid_dataset import prepare_spec,execution_arrays,observation_times
from causal_levels import from_dataset
from managed_execution import managed_simulate
from robust_optimizer import save_json,save_csv,EPOCH,daily_bootstrap
from indicators import registry,signal,causality_probe,combine
from trade_audit import trace
from resource_guard import initialize_research,ensure_memory
from research_grid import grid_candidates,grid_size
from to_score_cache import TOScoreCache
from sample_quality import statistics,training_objective,evaluation_status
from research_checkpoint import TrialCheckpoint
from entry_sessions import entry_mask
from instruments import instrument_spec,instrument_metadata

EXEC_DEFAULTS=dict(sl=40,tp=60,min_score=.3,trailing=0,trail_trigger=20,be_trigger=0,be_offset=0,quantity=1,session_mode=0)


def publish_progress(job,payload):
    temp=job/'progress.tmp';save_json(temp,payload)
    # Windows readers/antivirus can briefly deny rename even for a completed
    # file. Retry this metadata publication, never discard a valid simulation.
    for attempt in range(50):
        try:temp.replace(job/'progress.json');return
        except PermissionError:
            if attempt==49:raise
            time.sleep(.02)


class Engine:
    def __init__(self,data,config,spec):
        self.d=data;self.c=config;self.instrument=instrument_spec(config['instrument'])
        flatten=config.get('flatten_seconds',60900)
        self.execution_quality={}
        self.entry,self.end,self.good=execution_arrays(data,config['horizon'],config['delay_ms'],config['max_gap'],config['max_entry_gap'],flatten,self.execution_quality)
        observed=observation_times(data)
        cutoff=data['day_end']-(18*3600-flatten)*1_000_000
        self.eod=observed+config['delay_ms']*1000+config['horizon']*60_000_000>=cutoff-1_000_000
        self.good &= (data['day']>=spec['trade_from'])&(data['day']<=spec['trade_to'])
        self.good &= entry_mask(data['times'][self.entry],config.get('entry_windows',[]))
        self.session_masks={0:np.ones(len(self.good),bool)}
        for mode,window in [(1,[[34200,57600]]),(2,[[34200,43200]]),(3,[[43200,57600]])]:
            self.session_masks[mode]=entry_mask(data['times'][self.entry],window)
        self.days=sorted(set(data['day'][(data['day']>=spec['trade_from'])&(data['day']<=spec['trade_to'])]))
        need_levels=config.get('level_filter',0)>0 or any(x['indicator']=='deluxe_levels' for x in config.get('confirmations',[]))
        self.levels=from_dataset(data)[1] if need_levels else np.full(len(self.good),np.inf)
        self.cache=OrderedDict()
        self.mask_key=None;self.mask=None
        self.to_scores=TOScoreCache(data) if config['indicator']=='to_reversal' else None

    def signals(self,p):
        ip={k[2:]:v for k,v in p.items() if k.startswith('i:')};key=tuple(sorted((k,v) for k,v in p.items() if not k.startswith('e:')))
        if key not in self.cache:
            causality_probe(self.c['indicator'],self.d,ip)
            primary=self.to_scores.score(ip) if self.to_scores else signal(self.c['indicator'],self.d,ip)
            confirmations=[];level_distance=None
            for index,node in enumerate(self.c.get('confirmations',[])):
                prefix=f'c{index}:';cp={k[len(prefix):]:v for k,v in p.items() if k.startswith(prefix)}
                if node['indicator']=='deluxe_levels':
                    level_distance=cp['distance'] if level_distance is None else min(level_distance,cp['distance'])
                else:
                    causality_probe(node['indicator'],self.d,cp)
                    confirmations.append(signal(node['indicator'],self.d,cp))
            signals=combine(primary,np.array(confirmations).reshape((len(confirmations),len(primary))),self.c.get('confirmation_bars',3),self.c.get('combine_mode','and')=='or')
            if level_distance is not None:signals=np.where(self.levels<=level_distance,signals,0.)
            self.cache[key]=signals
            if len(self.cache)>8:self.cache.popitem(last=False)
        else:self.cache.move_to_end(key)
        return self.cache[key]

    def run(self,p,days,detail=False):
        d=self.d;c=self.c;ep={k[2:]:v for k,v in p.items() if k.startswith('e:')}
        if ep['sl']>0 and ep['sl']<=c['entry_slip']:raise ValueError('SL deve superare lo slippage ingresso')
        if ep['be_trigger']>0 and ep['be_offset']>=ep['be_trigger']:raise ValueError('Offset BE deve essere minore della sua attivazione')
        day_key=tuple(days)
        if self.mask_key!=day_key:
            self.mask=self.good&np.isin(d['day'],days);self.mask_key=day_key
        mode=int(ep.get('session_mode',0))
        if mode not in self.session_masks:raise ValueError('session_mode deve essere 0..3')
        good=self.mask&self.session_masks[mode]
        if not good.any():return np.array([],dtype=float),np.array([],dtype=d['day'].dtype),[]
        values,exits,sides,reasons=managed_simulate(d['price'],d['times'],d['block_low'],d['block_high'],self.entry,self.end,
            good,self.signals(p),ep['min_score'],ep['sl'],ep['tp'],c['entry_slip'],c['stop_slip'],c['exit_slip'],
            c['target_through'],self.instrument.tick_value,c['commission'],ep['trailing'],ep['trail_trigger'],
            ep['be_trigger'],ep['be_offset'],ep['quantity'],self.levels,c.get('level_filter',0))
        indices=np.flatnonzero(exits>=0);trades=[]
        reasons[(reasons==3)&self.eod]=4
        if detail:
            for i in indices:
                reason={1:'STOP',2:'TARGET',3:'TIMEOUT',4:'END_OF_DAY'}[int(reasons[i])]
                audited=trace(d['price'],d['times'],int(self.entry[i]),int(self.end[i]),int(sides[i]),ep,
                              dict(c,timeout_reason='END_OF_DAY' if self.eod[i] else 'TIMEOUT'),None)
                if audited['exit_index']!=exits[i] or abs(audited['net_usd']-values[i])>1e-7 or audited['reason']!=reason:
                    raise ValueError(f'Audit tick fallito alla barra {i}: {audited}; motore {exits[i]}, {values[i]}, {reason}')
                trades.append(dict(day=str(d['day'][i]),side=int(sides[i]),net_usd=float(values[i]),
                    entry_utc=str(EPOCH+np.timedelta64(int(d['times'][self.entry[i]]),'us')),
                    exit_utc=str(EPOCH+np.timedelta64(int(d['times'][exits[i]]),'us')),
                    exit_reason=reason,tick_audit_verified=True,ticks_audited=audited['ticks_visited'],
                    entry_last=float(d['price'][self.entry[i]])*self.instrument.tick_size,
                    entry_fill=(float(d['price'][self.entry[i]])+int(sides[i])*c['entry_slip'])*self.instrument.tick_size,
                    exit_fill=(float(d['price'][self.entry[i]])+int(sides[i])*(c['entry_slip']+(values[i]/ep['quantity']+c['commission'])/self.instrument.tick_value))*self.instrument.tick_size,
                    quantity=ep['quantity'],signal=float(self.signals(p)[i])))
        return values[indices],d['day'][indices],trades


def evaluate(engines,p,days,detail=False):
    values=[];trade_days=[];trades=[]
    for e in engines:
        x,d,t=e.run(p,days,detail);values.extend(x);trade_days.extend(d);trades.extend(t)
    x=np.asarray(values);eq=np.r_[0.,np.cumsum(x)];loss=-x[x<0].sum()
    day_index=np.searchsorted(np.asarray(days),np.asarray(trade_days))
    counts=np.bincount(day_index,minlength=len(days))
    daily_net=np.bincount(day_index,weights=x,minlength=len(days))
    daily={day:float(v) for day,v in zip(days,daily_net)}
    return dict(n=len(x),net=float(x.sum()),avg=float(x.mean()) if len(x) else 0.,
                pf=float(x[x>0].sum()/loss) if loss else None,maxdd=float(np.max(np.maximum.accumulate(eq)-eq)),
                win_pct=float(np.mean(x>0)*100) if len(x) else 0.,daily=daily,trades=trades,
                sample=statistics(counts,c_blocks(engines)))


def c_blocks(engines):
    return engines[0].c.get('training_blocks',3) if engines else 3


def main(job):
    job=Path(job);c=json.loads((job/'config.json').read_text());started=time.perf_counter()
    instrument=instrument_spec(c['instrument'])
    initialize_research(c.get('memory_reserve_gib',4))
    def progress(stage,percent,**kw):
        publish_progress(job,dict(stage=stage,percent=percent,elapsed_seconds=time.perf_counter()-started,**kw))
    progress('Preparazione dati',1)
    code_files=list(Path(__file__).parent.glob('*.py'))+list((Path(__file__).resolve().parents[1]/'tools').glob('*.py'))+list((Path(__file__).parent/'plugins').glob('*.py'))
    save_json(job/'REPRODUCIBILITY.json',dict(python=sys.version,platform=platform.platform(),
        packages={name:importlib.metadata.version(name) for name in ['numpy','numba','optuna','fastapi']},
        source_sha256={str(p.relative_to(Path(__file__).resolve().parents[1])):hashlib.sha256(p.read_bytes()).hexdigest() for p in code_files}))
    schema=registry()[c['indicator']];space={}
    for name,meta in schema['params'].items():space['i:'+name]=c['parameters'][name]
    for index,node in enumerate(c.get('confirmations',[])):
        for name,values in node['parameters'].items():space[f'c{index}:'+name]=values
    for name,default in EXEC_DEFAULTS.items():space['e:'+name]=c['execution'][name]
    engines=[];metadata=[]
    for i,s in enumerate(c['manifest']):
        progress(f'Lettura SCID {Path(s["scid"]).stem}',2+28*i/len(c['manifest']))
        if c.get('available_data_only'):s=dict(s,allow_missing_trade_dates=True,alternatives=[],partial_alternatives=[])
        try:d,m=prepare_spec(s,c['cache'],c['bar_seconds'],c.get('trades_per_bar',0))
        except ValueError as error:
            if not c.get('available_data_only'):raise
            c.setdefault('data_exclusions',[]).append(dict(source=s['scid'],start=s['trade_from'],end=s['trade_to'],reason=str(error)))
            continue
        engines.append(Engine(d,c,s));metadata.append(m)
    days=sorted({d for e in engines for d in e.days})
    if len(days)<6:raise ValueError('Servono almeno 6 trade date per train/validazione/test; preferire mesi di storia')
    hold_n=max(2,math.ceil(len(days)*.2));dev,hold=days[:-hold_n],days[-hold_n:]
    optuna.logging.set_verbosity(optuna.logging.ERROR)
    trials=[];folds=[];wftrades=[]
    initial=max(1,len(dev)//2)
    if c.get('calibrate_sensitivity') and c['indicator']=='to_reversal':
        # Calibration uses score distribution on the INITIAL training window,
        # never P&L or later validation/holdout prices.
        from scid_dataset import calculate
        calibration=[];base={k:v[0] for k,v in c['parameters'].items()}
        for sensitivity in [1,2,4,6,8]:
            values=[]
            for engine in engines:
                mask=np.isin(engine.d['day'],dev[:initial])&engine.good
                if mask.any():values.extend(np.abs(calculate(engine.d,dict(base,sensitivity=sensitivity))[0][mask]))
            values=np.asarray(values);nonzero=values[values>0]
            calibration.append(dict(sensitivity=sensitivity,q99=float(np.quantile(nonzero,.99)) if len(nonzero) else 0.,
                                    saturation=float(np.mean(values>=.999)) if len(values) else 0.,nonzero=len(nonzero)))
        chosen=min(calibration,key=lambda r:(abs(r['q99']-.7)+5*r['saturation'],r['sensitivity']))['sensitivity']
        c['parameters']['sensitivity']=[chosen];space['i:sensitivity']=[chosen]
        save_json(job/'SCORE_CALIBRATION.json',dict(initial_training_days=dev[:initial],candidates=calibration,chosen=chosen,
                    rule='Minimize abs(nonzero-score q99 - 0.7) + 5*saturation; score distribution only, no P&L'))
    # Calibration freezes an axis: count the actual candidates, also on resume.
    total_combinations=grid_size(space,c.get('weight_profiles'))
    budget=min(c['trials'],total_combinations)
    save_json(job/'config.json',c)
    checkpoint=None
    if c['method']=='grid':
        model_files=['dashboard/worker.py','dashboard/indicators.py','tools/footprint_kernel.py','tools/managed_execution.py',
                     'tools/scid_dataset.py','tools/causal_levels.py','tools/to_score_cache.py','tools/sample_quality.py','tools/research_grid.py','tools/entry_sessions.py','tools/bar_aggregation.py','tools/bar_schema.py','tools/instruments.py']
        model_hashes={name:hashlib.sha256((Path(__file__).resolve().parents[1]/name).read_bytes()).hexdigest() for name in model_files}
        experiment={k:v for k,v in c.items() if k not in ['created_at','resumed_at','memory_reserve_gib','data_exclusions']}
        checkpoint=TrialCheckpoint(job,dict(model=model_hashes,experiment=experiment,
            datasets=[dict(signature=m['signature'],sha256=m['source_sha256']) for m in metadata]))
    chunks=[list(x) for x in np.array_split(dev[initial:],min(3,len(dev)-initial)) if len(x)]
    stages=len(chunks)+1
    def search(train,stage):
        if c['method']=='grid':
            # Keep indicator choices outside execution choices: compute each
            # footprint once for all SL/TP/threshold combinations. GridSampler
            # shuffles this order and repeatedly evicts identical signals.
            if budget!=total_combinations:raise ValueError('Griglia incompleta: budget inferiore al prodotto cartesiano')
            best=None;best_score=-1e30
            for number,params in enumerate(grid_candidates(space,c.get('weight_profiles'))):
                saved=checkpoint.rows.get((stage+1,number))
                if saved:
                    if json.loads(saved['params'])!=params:raise ValueError('Ordine o parametri griglia cambiati: checkpoint rifiutato')
                    trials.append(saved)
                    if saved['objective']>best_score:best=params;best_score=saved['objective']
                    continue
                ensure_memory(reclaim=True)
                invalid=''
                try:
                    r=evaluate(engines,params,train)
                    score=training_objective(r,c)
                except ValueError as error:
                    invalid=str(error);r=dict(n=0,net=0);score=-1e30
                trials.append(dict(stage=stage+1,trial=number,objective=score,params=json.dumps(params),
                                   trades=r['n'],net=r['net'],active_days=r.get('sample',{}).get('active_days',0),
                                   block_trades=json.dumps(r.get('sample',{}).get('block_trades',[])),invalid=invalid))
                checkpoint.append(trials[-1])
                if score>best_score:best=params;best_score=score
                if number%25==0 or number+1==budget:
                    progress(f'Griglia completa {stage+1}/{stages}',30+60*(stage+(number+1)/budget)/stages,
                             trial=number+1,budget=budget)
            save_csv(job/'TRIALS.csv',trials)
            checkpoint.stream.flush()
            return best
        memo={}
        def objective(t):
            ensure_memory(reclaim=True)
            params={k:t.suggest_categorical(k,vs) for k,vs in space.items()};key=tuple(sorted(params.items()))
            try:
                if key not in memo:memo[key]=evaluate(engines,params,train)
                r=memo[key];score=training_objective(r,c)
                t.set_user_attr('n',r['n']);t.set_user_attr('net',r['net'])
                t.set_user_attr('active_days',r['sample']['active_days']);t.set_user_attr('block_trades',r['sample']['block_trades'])
            except ValueError as error:
                t.set_user_attr('invalid',str(error));score=-1e30
            if t.number%10==0:progress(f'Ottimizzazione {stage+1}/{stages}',30+60*(stage+(t.number+1)/budget)/stages,
                                      trial=t.number+1,budget=budget)
            return score
        sampler=optuna.samplers.GridSampler(space,seed=c['seed']) if c['method']=='grid' else optuna.samplers.TPESampler(seed=c['seed']+stage)
        study=optuna.create_study(direction='maximize',sampler=sampler)
        study.optimize(objective,n_trials=budget)
        trials.extend(dict(stage=stage+1,trial=t.number,objective=t.value,params=json.dumps(t.params),
                           trades=t.user_attrs.get('n',0),net=t.user_attrs.get('net',0),active_days=t.user_attrs.get('active_days',0),
                           block_trades=json.dumps(t.user_attrs.get('block_trades',[])),invalid=t.user_attrs.get('invalid','')) for t in study.trials)
        return study.best_params if study.best_value>-1e30 else None
    prior=dev[:initial]
    for stage,held in enumerate(chunks):
        best=search(prior,stage)
        if best:
            r=evaluate(engines,best,held,True);wftrades.extend(r['trades'])
            quality=evaluation_status(r,c)
            folds.append(dict(fold=stage+1,train_last=prior[-1],test_first=held[0],test_last=held[-1],n=r['n'],net=r['net'],
                              active_days=r['sample']['active_days'],sample_status=quality['status']))
        else:folds.append(dict(fold=stage+1,train_last=prior[-1],test_first=held[0],test_last=held[-1],n=0,net=0))
        prior+=held
    best=search(dev,len(chunks))
    save_csv(job/'TRIALS.csv',trials);save_csv(job/'WALK_FORWARD.csv',folds);save_csv(job/'WF_TRADES.csv',wftrades)
    if best is None:raise ValueError('Nessuna configurazione valida raggiunge il numero minimo di trade; consulta TRIALS.csv')
    save_json(job/'SELECTION_LOCK.json',dict(params=best,development=dev,holdout=hold))
    progress('Test finale esplorativo',94)
    result=evaluate(engines,best,hold,True);save_csv(job/'HOLDOUT_TRADES.csv',result['trades'])
    uncertainty=daily_bootstrap(result,hold,c['seed'])
    eq=0.;curve=[dict(date=hold[0],equity=0.)]
    for d in hold:eq+=result['daily'].get(d,0);curve.append(dict(date=d,equity=eq))
    summary=dict(indicator=schema['name'],instrument=c['instrument'],params=best,holdout={k:v for k,v in result.items() if k!='trades'},
        walk_forward=folds,development_days=dev,holdout_days=hold,uncertainty=uncertainty,equity=curve,
        elapsed_seconds=time.perf_counter()-started,total_combinations=total_combinations,trials_run=len(trials),datasets=metadata,
        instrument_spec=instrument_metadata(c['instrument']),
        evidence_status=dict(classification='exploratory',holdout_independence='known_reused' if c.get('exploratory_retest') else 'not_verified',
                             native_execution_parity='not_verified',prop_rules='not_implemented',
                             drawdown_basis='closed_trade_equity',gap_policy='full_horizon'),
        stress_extra_2_ticks_net=result['net']-result['n']*2*instrument.tick_value*best['e:quantity'],
        warnings=['Esecuzioni da ultimo prezzo scambiato, senza simulazione della coda ordini.',
                  'Drawdown su trade chiusi; non equivale al drawdown intratrade delle prop firm.',
                  'Indipendenza del segmento finale non verificata: lo split temporale non certifica un campione mai consultato.',
                  'Le date holdout sono ora consumate: non riottimizzarle per scegliere una nuova strategia.'])
    if len(days)<60 or len(hold)<20:summary['warnings'].append('Campione breve: risultati esplorativi, nessuna conclusione robusta sull’edge.')
    for m in metadata:
        for rejected in m.get('rejected_sources',[]):summary['warnings'].append('SCID scartato: '+rejected['error']+'; usato '+m['signature']['path'])
    summary['daily_close']=dict(timezone='America/New_York',hard_cutoff_seconds=c.get('flatten_seconds',60900),order_advance_seconds=1)
    summary['sample_quality']=dict(training_policy={k:c.get(k,0) for k in ['min_trades','min_active_days','min_trades_per_training_block']},
                                   final=evaluation_status(result,c),walk_forward=[f.get('sample_status','insufficient_sample') for f in folds])
    if not summary['sample_quality']['final']['sufficient']:
        summary['warnings'].append('Campione finale insufficiente: non considerare il risultato una strategia validata.')
    if any(f.get('sample_status')!='sufficient_for_screening' for f in folds):
        summary['warnings'].append('Una o piu finestre walk-forward hanno un campione insufficiente.')
    summary['data_exclusions']=c.get('data_exclusions',[])
    summary['execution_quality']=[dict(source=m['signature']['path'],**e.execution_quality) for e,m in zip(engines,metadata)]
    summary['warnings'].append('Filtro gap conservativo fino alla scadenza: puo escludere trade gia chiusi prima del gap. Diagnostica in execution_quality; effetto sul P&L non misurato.')
    for m in metadata:
        if m.get('excluded_trade_dates'):
            summary['warnings'].append('Giornate SCID assenti ed escluse: '+', '.join(m['excluded_trade_dates']))
    for exclusion in summary['data_exclusions']:
        summary['warnings'].append('Periodo escluso: '+json.dumps(exclusion,ensure_ascii=False))
    if c.get('exploratory_retest'):
        summary['warnings'].append('Ricerca esplorativa: questi periodi sono stati consultati in ricerche precedenti; il segmento finale non e un nuovo campione indipendente.')
    summary['tick_audit']=dict(method='Independent scalar traversal of every trade in WF and holdout reports',verified=True,
                               holdout_trades=len(result['trades']),walk_forward_trades=len(wftrades),
                               ticks=sum(t['ticks_audited'] for t in result['trades']+wftrades))
    summary['rollover']=dict(method=c.get('rollover_method','Legacy: calendario fisso'),evidence=c.get('rollover_evidence',[]))
    if c['level_filter']>0:summary['warnings'].append('Filtro Deluxe causale da riconciliare con export Sierra.')
    if any(n['indicator']=='deluxe_levels' for n in c.get('confirmations',[])):
        summary['warnings'].append('La combinazione usa TO Deluxe causale: parità dei livelli Sierra ancora da verificare.')
    summary['combination']=dict(mode=c.get('combine_mode','and'),confirmation_bars=c.get('confirmation_bars',3),
                               indicators=[registry()[n['indicator']]['name'] for n in c.get('confirmations',[])])
    if c['indicator'].startswith('plugin_') or any(n['indicator'].startswith('plugin_') for n in c.get('confirmations',[])):
        summary['warnings'].append('Plugin locale: controllo causale su prefissi campionati, non prova completa di correttezza.')
    save_json(job/'SUMMARY.json',summary)
    save_json(job/'BEST_CONFIG.json',dict(indicator=c['indicator'],parameters={k[2:]:v for k,v in best.items() if k.startswith('i:')},
                                        execution={k[2:]:v for k,v in best.items() if k.startswith('e:')},configuration=c))
    progress('Completato',100)
    if checkpoint:checkpoint.close()


if __name__=='__main__':
    try:main(sys.argv[1])
    except Exception as error:
        save_json(Path(sys.argv[1])/'ERROR.json',dict(error=str(error),traceback=traceback.format_exc()))
        traceback.print_exc();sys.exit(1)
