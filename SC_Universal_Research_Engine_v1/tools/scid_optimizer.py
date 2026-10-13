"""Fast TO indicator + execution optimization directly from Sierra SCID files.

One preprocessing pass per contract; compiled footprint/first-hit kernels; no
Sierra replay per trial. Supports explicit non-overlapping rollover manifests.
"""
import argparse
import json
import math
import re
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np
import optuna

import footprint_kernel as fk
from causal_levels import from_dataset
from scid_dataset import prepare_spec, load_cache, calculate, parity, execution_arrays
from robust_optimizer import save_json, save_csv, digest, EPOCH, daily_bootstrap
from resource_guard import initialize_research,ensure_memory


class Engine:
    def __init__(self, data, args, first=None, last=None):
        self.data=data;self.args=args
        self.entry,self.ends,self.valid=execution_arrays(data,args.horizon,args.delay_ms,args.max_gap,args.max_entry_gap,args.flatten_seconds)
        if first:self.valid &= data['day']>=first
        if last:self.valid &= data['day']<=last
        self.days=sorted(set(data['day'][(data['day']>=first if first else np.ones(len(self.valid),bool)) &
                                       (data['day']<=last if last else np.ones(len(self.valid),bool))]))
        self.level_distance=from_dataset(data)[1] if args.compare_levels else np.full(len(self.valid),np.inf)
        self.cache=OrderedDict()

    def signals(self,params):
        indicator={k:v for k,v in params.items() if k in fk.DEFAULTS}
        key=tuple(sorted(indicator.items()))
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        result=calculate(self.data,indicator)[0]
        self.cache[key]=result
        if len(self.cache)>8:self.cache.popitem(last=False)
        return result

    def run(self,params,days,detail=False):
        a=self.args;d=self.data
        good=self.valid & np.isin(d['day'],days)
        values,exits,sides=fk.simulate(d['price'],d['times'],d['block_low'],d['block_high'],self.entry,self.ends,
            good,self.signals(params),params['min_score'],params['sl'],params['tp'],
            a.entry_slip,a.stop_slip,a.exit_slip,a.target_through,a.tick_value,a.commission,
            self.level_distance,params.get('level_ticks',0))
        indices=np.flatnonzero(exits>=0)
        trades=[]
        if detail:
            for i in indices:
                trades.append(dict(day=str(d['day'][i]),side=int(sides[i]),net_usd=float(values[i]),
                    bar_utc=str(EPOCH+np.timedelta64(int(d['bar_time'][i]),'us')),
                    entry_utc=str(EPOCH+np.timedelta64(int(d['times'][self.entry[i]]),'us')),
                    exit_utc=str(EPOCH+np.timedelta64(int(d['times'][exits[i]]),'us')),
                    signal=float(self.signals(params)[i]),entry_last=float(d['price'][self.entry[i]])/4))
        return values[indices],d['day'][indices],trades


def evaluate(engines,params,days,detail=False):
    values=[];trade_days=[];trades=[]
    for e in engines:
        x,d,t=e.run(params,days,detail)
        values.extend(x);trade_days.extend(d);trades.extend(t)
    x=np.asarray(values);eq=np.r_[0.,np.cumsum(x)];losses=-x[x<0].sum()
    daily={day:0. for day in days}
    for d,v in zip(trade_days,values):daily[d]+=float(v)
    return dict(n=len(x),net=float(x.sum()),maxdd=float(np.max(np.maximum.accumulate(eq)-eq)),
                avg=float(x.mean()) if len(x) else 0.,pf=float(x[x>0].sum()/losses) if losses else None,
                daily=daily,trades=trades)


def objective_value(r,min_trades):
    return r['net']-.75*r['maxdd'] if r['n']>=min_trades else -1e30


def search(engines,days,space,args,family,seed):
    memo={}
    def objective(trial):
        ensure_memory(reclaim=True)
        params={k:trial.suggest_categorical(k,choices) for k,choices in space.items()}
        if family=='with_levels':params['level_ticks']=trial.suggest_categorical('level_ticks',[2,4,8,16])
        key=tuple(sorted(params.items()))
        if key not in memo:memo[key]=evaluate(engines,params,days)
        r=memo[key];trial.set_user_attr('n',r['n']);trial.set_user_attr('net',r['net'])
        return objective_value(r,args.min_trades)
    study=optuna.create_study(direction='maximize',sampler=optuna.samplers.TPESampler(seed=seed))
    study.optimize(objective,n_trials=args.trials)
    rows=[dict(trial=t.number,objective=t.value,n=t.user_attrs['n'],net=t.user_attrs['net'],params=json.dumps(t.params,sort_keys=True)) for t in study.trials]
    return (study.best_params if study.best_value>-1e30 else None),rows,len(memo)


def export_inputs(params):
    mapping=dict(min_agg=2,min_pct=3,level_multiple=4,diagonal=5,imbalance=6,extreme_ticks=7,
                 rejection_ticks=8,close_through=9,bubbles=12,separation=13,trap_buffer=41,
                 min_trapped=42,imbalance_volume=43,min_score=60,lookback=61,require_extreme=62,
                 tolerance=63,w_abs=64,w_trap=65,w_delta=66,w_imb=67,volume_weight=68,sensitivity=78)
    values=dict(fk.DEFAULTS,**{k:v for k,v in params.items() if k in mapping})
    return dict(to_inputs_zero_based={str(mapping[k]):v for k,v in values.items()},
                fixed={'0':1,'1':1,'10':0,'28':0,'59':1},
                execution=dict(sl_ticks=params['sl'],tp_ticks=params['tp'],max_horizon_minutes='see SUMMARY config',
                               opposite_exit=False),warning='Research candidate, not approved for live. Verify exact chart settings and replay fills.')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    source=p.add_mutually_exclusive_group(required=True)
    source.add_argument('--scid',type=Path)
    source.add_argument('--manifest',type=Path,help='JSON list of {scid, start, end, trade_from, trade_to}; UTC input windows; non-overlapping trade dates')
    source.add_argument('--dataset',type=Path,help='Existing immutable cache directory with metadata.json')
    p.add_argument('--instrument',choices=['NQ','ES'],required=True)
    p.add_argument('--start',help='UTC data window inclusive, e.g. 2026-09-01')
    p.add_argument('--end',help='UTC data window EXCLUSIVE, e.g. 2026-10-10')
    p.add_argument('--trade-from',help='First New York trade date (after warmup)')
    p.add_argument('--trade-to',help='Last New York trade date inclusive')
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--cache',type=Path,default=Path(__file__).resolve().parents[1]/'.scid_cache')
    p.add_argument('--bar-seconds',type=int,default=60)
    p.add_argument('--parity-csv',type=Path,help='Optional Sierra export to verify DEFAULT indicator calculation')
    p.add_argument('--compare-levels',action='store_true',help='Also test causal port of default TO Deluxe; separately validate its values in Sierra')
    p.add_argument('--space',type=Path,help='JSON categorical choices; supported indicator keys plus sl,tp,min_score')
    p.add_argument('--trials',type=int,default=200)
    p.add_argument('--folds',type=int,default=3)
    p.add_argument('--min-trades',type=int,default=30)
    p.add_argument('--seed',type=int,default=20261013)
    p.add_argument('--horizon',type=int,default=30)
    p.add_argument('--flatten-seconds',type=int,default=60900,help='Hard daily close New York seconds, max 60900 = 16:55')
    p.add_argument('--commission',type=float,default=5.)
    p.add_argument('--entry-slip',type=int,default=1)
    p.add_argument('--stop-slip',type=int,default=1)
    p.add_argument('--exit-slip',type=int,default=1)
    p.add_argument('--target-through',type=int,default=1)
    p.add_argument('--delay-ms',type=int,default=1)
    p.add_argument('--max-gap',type=float,default=90.)
    p.add_argument('--max-entry-gap',type=float,default=5.)
    args=p.parse_args(argv);args.tick_value=5. if args.instrument=='NQ' else 12.5
    initialize_research()
    if not 3600<=args.flatten_seconds<=60900:p.error('Daily close must be between 01:00 and 16:55 New York')
    if args.trials<1 or args.folds<1 or args.min_trades<1 or args.horizon<1 or min(args.entry_slip,args.stop_slip,args.exit_slip,args.target_through,args.delay_ms)<0:
        p.error('Invalid trial/execution parameters')
    if not np.isfinite([args.commission,args.max_gap,args.max_entry_gap]).all() or args.commission<0 or min(args.max_gap,args.max_entry_gap)<=0:
        p.error('Invalid costs/gaps')
    if args.out.exists() and any(args.out.iterdir()):p.error('Use a new output directory')
    started=time.perf_counter();args.out.mkdir(parents=True,exist_ok=True)
    space=dict(min_agg=[20,50,100,150] if args.instrument=='NQ' else [75,150,300,600],
               imbalance=[2.,2.5,3.,4.],lookback=[5,10,20],min_score=[.2,.3,.4,.5,.6],
               sl=[20,40,60,80,100,120],tp=[30,60,90,120,150,180])
    if args.space:space=json.loads(args.space.read_text())
    if set(space)-set(fk.DEFAULTS)-{'sl','tp','min_score'} or not {'sl','tp','min_score'}.issubset(space):
        p.error('Unknown/missing search-space keys')
    for k,values in space.items():
        if not isinstance(values,list) or not values or any(not isinstance(v,(float,int)) or not math.isfinite(v) for v in values):
            p.error(f'Invalid categorical values: {k}')
        if k in fk.DEFAULTS:
            for v in values:fk.vector({k:v})
    if min(space['sl'])<=args.entry_slip or min(space['tp'])<=0 or min(space['min_score'])<=0 or max(space['min_score'])>1:
        p.error('Invalid stop/target/score search space')
    if any(int(v)!=v for k in ['sl','tp'] for v in space[k]):p.error('SL/TP must be integer ticks')
    if args.manifest:
        specs=json.loads(args.manifest.read_text())
        if not isinstance(specs,list) or not specs:p.error('Manifest must be a nonempty list')
        if any(not s.get('trade_from') or not s.get('trade_to') for s in specs):p.error('Every manifest contract needs trade_from and trade_to')
        specs.sort(key=lambda s:s['trade_from'])
        for a,b in zip(specs,specs[1:]):
            if a['trade_to']>=b['trade_from']:p.error('Overlapping contract windows; explicit rollover dates required')
    else:specs=[dict(scid=str(args.scid) if args.scid else None,start=args.start,end=args.end,trade_from=args.trade_from,trade_to=args.trade_to)]
    engines=[];metadata=[];parity_results=[]
    for spec in specs:
        if args.dataset:
            data,meta=load_cache(args.dataset)
            name=Path(meta['signature']['path']).stem
        else:
            name=Path(spec['scid']).stem
            data,meta=prepare_spec(spec,args.cache,args.bar_seconds)
            name=Path(meta['signature']['path']).stem
        if not re.match('^'+args.instrument+r'[HMUZ]\d',name):p.error(f'Unexpected instrument/contract: {name}')
        if args.dataset and (meta['signature']['seconds']!=args.bar_seconds or meta['signature']['timezone']!='America/New_York'):
            p.error('Cached bar/timezone settings do not match')
        print(f'{name}: {meta["trades"]:,} ticks; {meta["bars"]:,} bars; cache={meta["cache_hit"]}',flush=True)
        if args.parity_csv:
            check=parity(data,args.parity_csv)
            parity_results.append(dict(contract=name,**check))
            save_json(args.out/'PARITY.json',parity_results)
            if len(specs)==1 and not check['passed']:
                raise ValueError(f'Sierra parity failed: {check}; do not optimize an unverified replica')
        engines.append(Engine(data,args,spec.get('trade_from'),spec.get('trade_to')))
        metadata.append(meta)
    days=sorted({day for e in engines for day in e.days})
    if len(days)<6:raise ValueError('Need at least 6 trading dates; a short experiment is not edge evidence')
    hold_n=max(2,math.ceil(.2*len(days)));dev=days[:-hold_n];hold=days[-hold_n:]
    initial=max(1,len(dev)//2)
    chunks=[list(c) for c in np.array_split(dev[initial:],min(args.folds,len(dev)-initial)) if len(c)]
    families=['standalone','with_levels'] if args.compare_levels else ['standalone']
    baseline=dict(sl=40,tp=60,min_score=.3)
    # Warm compiled kernels before timing the actual trials.
    evaluate(engines,baseline,dev)
    prepared=time.perf_counter()-started
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    results={};trial_rows=[];fold_rows=[]
    for family in families:
        prior=dev[:initial];wf_trades=[]
        for fold,held in enumerate(chunks,1):
            best,rows,unique=search(engines,prior,space,args,family,args.seed+fold)
            trial_rows.extend(dict(family=family,stage=f'fold_{fold}',**r) for r in rows)
            if best:
                r=evaluate(engines,best,held,True);wf_trades.extend(r['trades'])
                fold_rows.append(dict(family=family,fold=fold,train_last=prior[-1],test_first=held[0],test_last=held[-1],
                                      n=r['n'],net=r['net'],params=json.dumps(best)))
            else:fold_rows.append(dict(family=family,fold=fold,train_last=prior[-1],test_first=held[0],test_last=held[-1],n=0,net=0,params='NO_ELIGIBLE_TRIAL'))
            prior+=held
            print(f'{family} fold {fold}/{len(chunks)} complete ({unique} unique trials)',flush=True)
        values=np.array([t['net_usd'] for t in wf_trades]);eq=np.r_[0.,np.cumsum(values)]
        wf=dict(n=len(values),net=float(values.sum()),maxdd=float(np.max(np.maximum.accumulate(eq)-eq)))
        best,rows,unique=search(engines,dev,space,args,family,args.seed)
        trial_rows.extend(dict(family=family,stage='refit',**r) for r in rows)
        results[family]=dict(params=best,development_walk_forward=wf,unique_refit=unique)
        save_csv(args.out/f'{family}_WF_TRADES.csv',wf_trades)
    eligible=[f for f in families if results[f]['params'] and results[f]['development_walk_forward']['n']>=args.min_trades]
    winner=max(eligible,key=lambda f:objective_value(results[f]['development_walk_forward'],args.min_trades)) if eligible else None
    # Write lock BEFORE final holdout evaluation; model-family selection uses development only.
    save_json(args.out/'SELECTION_LOCK.json',dict(selected=winner,results=results,development=dev,holdout=hold,search_space=space))
    for family in families:
        best=results[family]['params']
        if best:
            r=evaluate(engines,best,hold,True)
            results[family]['holdout']={k:v for k,v in r.items() if k!='trades'}
            results[family]['extra_2_ticks_net']=r['net']-r['n']*2*args.tick_value
            results[family]['uncertainty']=daily_bootstrap(r,hold,args.seed)
            save_csv(args.out/f'{family}_HOLDOUT_TRADES.csv',r['trades'])
            save_json(args.out/f'{family}_SIERRA_INPUTS.json',export_inputs(best))
    fixed=evaluate(engines,baseline,hold,True)
    save_csv(args.out/'FIXED_BASELINE_HOLDOUT.csv',fixed.pop('trades'))
    save_csv(args.out/'TRIALS.csv',trial_rows);save_csv(args.out/'WALK_FORWARD.csv',fold_rows)
    elapsed=time.perf_counter()-started
    warnings=['Execution is last-trade based, no order-book queue or guaranteed live fills.',
              'Only time bars; ConfirmationBars=0; bullish/bearish absorption both enabled.',
              'Initial 500 bars excluded; positions closed by configured daily cutoff (default 16:55 NY).',
              'Closed-trade drawdown is not intratrade/prop trailing drawdown.',
              'After inspection the holdout is consumed: subsequent searches require new untouched dates.']
    if len(days)<60 or len(hold)<20:warnings.append('SHORT SAMPLE: no robust edge conclusion permitted.')
    if args.compare_levels:warnings.append('Deluxe causal port not yet compared with a Sierra levels export. Combination results provisional.')
    if not args.parity_csv:warnings.append('No Sierra parity CSV supplied for this dataset/instrument.')
    summary=dict(config=vars(args),datasets=metadata,parity=parity_results,search_space=space,
        selected_before_holdout=winner,development_days=dev,holdout_days=hold,results=results,fixed_baseline=fixed,
        timing=dict(preprocessing_and_jit_seconds=prepared,search_and_reports_seconds=elapsed-prepared,total_seconds=elapsed,
                    requested_trials=len(families)*(len(chunks)+1)*args.trials),warnings=warnings,
        source_hashes={p.name:digest(p) for p in [Path(__file__),Path(__file__).with_name('footprint_kernel.py'),Path(__file__).with_name('scid_dataset.py'),Path(__file__).with_name('causal_levels.py')]},
        environment=dict(numpy=np.__version__,optuna=optuna.__version__))
    save_json(args.out/'SUMMARY.json',summary)
    lines=['# Ottimizzazione diretta SCID / TO Reversal','',
        f'{args.instrument}: {len(days)} trade dates. Holdout {hold[0]} — {hold[-1]}.',
        f'Famiglia scelta PRIMA del holdout: {winner}.','',
        '| Variante | Trade OOS sviluppo | Netto OOS sviluppo | Trade holdout | Netto holdout USD | Stress +2 tick |',
        '|---|---:|---:|---:|---:|---:|']
    for f,r in results.items():
        if 'holdout' in r:
            h=r['holdout'];w=r['development_walk_forward']
            lines.append(f'| {f} | {w["n"]} | {w["net"]:.2f} | {h["n"]} | {h["net"]:.2f} | {r["extra_2_ticks_net"]:.2f} |')
    lines+=['',f'Totale {elapsed:.2f}s; preparazione/JIT {prepared:.2f}s; {summary["timing"]["requested_trials"]} prove richieste.','']+['- '+w for w in warnings]
    (args.out/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('\n'.join(lines),flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
