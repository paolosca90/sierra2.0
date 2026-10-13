#!/usr/bin/env python3
"""Event-time first-hit research on Sierra .scid last-trade tape + replay-observed signal CSV.
No trading. Do NOT mistake last-trade first-hit for validated market/limit order fills.
"""
from __future__ import annotations
import argparse, csv, json, math, struct, sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np

EPOCH=np.datetime64('1899-12-30T00:00:00','us')
RECORD=np.dtype([('datetime','<i8'),('open','<f4'),('high','<f4'),('low','<f4'),
    ('close','<f4'),('num_trades','<u4'),('total_volume','<u4'),('bid_volume','<u4'),('ask_volume','<u4')])
assert RECORD.itemsize==40
CSV_DT='%Y-%m-%d  %H:%M:%S.%f'


def micros(dt:datetime)->int:
    if dt.tzinfo is not None: dt=dt.astimezone(timezone.utc).replace(tzinfo=None)
    return int((np.datetime64(dt,'us')-EPOCH)/np.timedelta64(1,'us'))


def scid_reader(p:Path):
    with p.open('rb') as f: head=f.read(56)
    if len(head)!=56 or head[:4]!=b'SCID': raise ValueError('Invalid SCID header')
    header,record=struct.unpack_from('<II',head,4)
    if header<56 or header>4096 or record!=40: raise ValueError(f'Unsupported .scid layout header={header} record={record}')
    size=p.stat().st_size-header
    if size<0 or size%40: raise ValueError(f'SCID truncated / incomplete record bytes = {size%40}')
    raw=np.memmap(p,dtype=RECORD,mode='r',offset=header,shape=(size//40,))
    # Keep only executed-trade records; SCID may also contain quote updates or placeholders.
    valid=(raw['total_volume']>0)&np.isfinite(raw['close'])&(raw['close']>0)
    ts=np.asarray(raw['datetime'][valid],dtype=np.int64)
    px=np.asarray(raw['close'][valid],dtype=np.float64)
    if len(ts)<2:raise ValueError('No valid trade records')
    if (np.diff(ts)<0).any():raise ValueError('SCID traded records are not chronologically ordered')
    # Sierra IntradayRecord.h::IsSingleTradeWithBidAsk also accepts the
    # first/last sub-trade flags. These are trades, NOT aggregated candles.
    flags=(raw['open']==0)|(raw['open']==np.float32(-1.99900095e37))|(raw['open']==np.float32(-1.99900197e37))
    single=(raw['num_trades']==1)&flags&valid
    frac=float(np.count_nonzero(single)/np.count_nonzero(valid))
    return ts,px,{'all_records':int(len(raw)),'trade_records':int(len(ts)),
         'single_tick_convention_fraction':frac,'pct_aggregated_or_unknown':round(100*(1-frac),2),
         'first_utc':str(EPOCH+np.timedelta64(int(ts[0]),'us')),
         'last_utc':str(EPOCH+np.timedelta64(int(ts[-1]),'us'))}


def collector_rows(p:Path):
    bars=[];all_=Counter()
    with p.open('r',newline='',encoding='utf-8-sig') as f:
        r=csv.DictReader(f)
        need={'kind','bar_index','bar_start','observed_market_time','close','signal_mask','symbol','reversal_score'}
        if not need.issubset(r.fieldnames or []):raise ValueError('Not a TO Replay Collector CSV')
        for row in r:
            all_[row['kind']]+=1
            if row['kind']!='BAR_CLOSE':continue
            bars.append({'bar_start':datetime.strptime(row['bar_start'],CSV_DT),
                'observed':datetime.strptime(row['observed_market_time'],CSV_DT),
                'close':float(row['close']),'bar_index':int(row['bar_index']),
                'mask':int(row['signal_mask']),'score':float(row['reversal_score']),
                'symbol':row['symbol']})
    if not bars:raise ValueError('Collector has no BAR_CLOSE events')
    if any(x['bar_start']>=y['bar_start'] for x,y in zip(bars,bars[1:])):
        raise ValueError('Collector BAR_CLOSE timestamps are not strictly increasing')
    if len({b['symbol'] for b in bars})!=1:raise ValueError('Collector contains multiple symbols: split first')
    return bars,all_


def chart_to_tape_us(d:datetime,offset:float=0)->int:
    return micros(d)-int(round(offset*3600*1_000_000))


def detect_offset(bars,ts,px):
    """Try whole-hour chart minus UTC differences by candle-final CLOSE, not signal hindsight."""
    sample=bars[::max(1,len(bars)//140)]
    offsets={}
    for offset in range(-12,15):
        ok=0;valid=0
        for b in sample:
            a=chart_to_tape_us(b['bar_start'],offset)
            i=int(np.searchsorted(ts,a,'left'));j=int(np.searchsorted(ts,a+60_000_000,'left'))
            if j<=i:continue
            valid+=1
            if abs(float(px[j-1])-b['close'])<=0.26:ok+=1
        offsets[offset]=(ok/valid if valid else 0.0,valid)
    ordered=sorted(offsets,key=lambda k:(offsets[k][0],offsets[k][1]),reverse=True)
    chosen=ordered[0];score=offsets[chosen][0];second=offsets[ordered[1]][0]
    if score<0.75 or score-second<0.12:
        raise ValueError(f'Timestamp alignment is not reliably identifiable: first={chosen}:{score:.2%} vs second={ordered[1]}:{second:.2%}. Verify chart timezone, exact contract, 1-minute period; pass --utc-offset-hours manually only after verification.')
    return chosen,score,offsets


@dataclass
class Event:
    time:int
    side:int
    score:float
    day:str
    hour:int
    start:int
    end:int
    entry_last:float
    end_last:float
    best:float
    worst:float
    tp_index:np.ndarray
    stop_index:np.ndarray
    def result(self,tp:int,sl:int,entry_slip:int,stop_slip:int,exit_slip:int,tick:float,tick_value:float,commission:float):
        # First-hit thresholds generated relative to actual first LAST TRADE.
        tpi=int(self.tp_index[tp]) if tp else sys.maxsize
        sli=int(self.stop_index[sl]) if sl else sys.maxsize
        if tpi==sli==sys.maxsize:
            duration=self.end-self.start-1
            exit_last=self.end_last
            ticks=self.side*(exit_last-self.entry_last)/tick-entry_slip-exit_slip
            why='NEXT_OPPOSITE_OR_TIMEOUT'
        elif sli<=tpi:
            duration=sli
            ticks=-sl-stop_slip
            why='SL'
        else:
            duration=tpi
            ticks=tp
            why='TP'
        # Entry slippage is already incorporated in first-hit thresholds and timeout P/L.
        # A trigger at price fill_entry can only happen at/after observed signal timestamp.
        return {'net_ticks':float(ticks-commission/tick_value),
                'gross_ticks':float(ticks),'net_usd':float(ticks*tick_value-commission),
                'exit_reason':why,'duration_records':int(duration),
                'mfe_full_window_ticks':float(self.best-entry_slip),
                'mae_full_window_ticks':float(self.worst+entry_slip),
                'end_record':self.start+int(duration)}


def make_events(bars,ts,px,offset:int,tick:float,max_tp:int,max_sl:int,
                horizon_min:int,entry_delay_ms:int,entry_slip:int,max_entry_gap_s:float,
                max_inner_gap_s:float,limit_opposite:bool):
    sgs=[]
    for b in bars:
        m=b['mask'] & 3
        if m not in (1,2):continue
        sgs.append((b,1 if m==1 else -1))
    rows=[];bad=Counter()
    for n,(b,side) in enumerate(sgs):
        signal_t=chart_to_tape_us(b['observed'],offset)
        entry_t=signal_t+entry_delay_ms*1000
        stop_t=entry_t+int(horizon_min*60*1_000_000)
        if limit_opposite:
            for next_b,next_side in sgs[n+1:]:
                if next_side==-side:
                    stop_t=min(stop_t,chart_to_tape_us(next_b['observed'],offset))
                    break
        if stop_t>int(ts[-1]):bad['NO_FULL_HORIZON']+=1;continue
        st=int(np.searchsorted(ts,entry_t,'left'))
        en=int(np.searchsorted(ts,stop_t,'right'))
        if st>=len(ts) or en<=st:bad['NO_TRADE_WINDOW']+=1;continue
        if (int(ts[st])-entry_t)>max_entry_gap_s*1e6:bad['ENTRY_GAP']+=1;continue
        if en-st>1 and float(np.max(np.diff(ts[st:en])))>max_inner_gap_s*1e6:
            bad['INTERNAL_TAPE_GAP']+=1;continue
        sub=px[st:en]
        entry=float(sub[0]);signed=np.rint(side*(sub-entry)/tick).astype(np.int32)
        # A long enters above first last-trade with entry slippage, so it needs
        # more favorable raw movement to hit its target; analogously stop is closer.
        f=np.maximum.accumulate(signed)
        a=np.maximum.accumulate(-signed)
        tp_threshold=np.arange(max_tp+1,dtype=np.int32)+entry_slip
        sl_threshold=np.arange(max_sl+1,dtype=np.int32)-entry_slip
        tp_idx=np.searchsorted(f,tp_threshold,'left').astype(np.int64)
        sl_idx=np.searchsorted(a,sl_threshold,'left').astype(np.int64)
        tp_idx[tp_idx==len(sub)]=sys.maxsize
        sl_idx[sl_idx==len(sub)]=sys.maxsize
        rows.append(Event(time=entry_t,side=side,score=b['score'],day=b['bar_start'].date().isoformat(),hour=b['bar_start'].hour,
            start=st,end=en,entry_last=entry,end_last=float(sub[-1]),
            best=float(f[-1]),worst=float(a[-1]),tp_index=tp_idx,stop_index=sl_idx))
    return rows,bad,len(sgs)


def evaluate(events,params,cfg):
    prev_end=-1;rets=[];results=[]; wins=0;losses=0;gains=0;gross_losses=0;equity=0;high_water=0;maxdd=0
    for e in events:
        if e.start<=prev_end:continue # One virtual portfolio position at a time.
        if abs(e.score)<params['min_score']:continue
        out=e.result(params['tp'],params['sl'],cfg['entry_slip'],cfg['stop_slip'],cfg['exit_slip'],cfg['tick'],cfg['tick_value'],cfg['commission'])
        prev_end=out['end_record'];p=out['net_usd'];equity+=p;high_water=max(high_water,equity);maxdd=max(maxdd,high_water-equity)
        wins+=p>0;losses+=p<=0;gains+=max(0,p);gross_losses+=max(0,-p)
        out.update(day=e.day,direction='LONG' if e.side==1 else 'SHORT',entry_price=e.entry_last,effective_timestamp_utc=str(EPOCH+np.timedelta64(int(e.time),'us')))
        rets.append(p);results.append(out)
    x=np.asarray(rets,dtype=float)
    if not len(x):return {'n':0,'net':-float('inf'),'pf':0,'maxdd':float('inf'),'avg':0,'win_pct':0,'trades':[]}
    return {'n':len(x),'net':float(x.sum()),'pf':float(gains/gross_losses) if gross_losses else float('inf'),
            'maxdd':float(maxdd),'avg':float(x.mean()),'win_pct':float(100*wins/len(x)),'trades':results}


def write_csv(p,rows):
    if not rows:return
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def main(argv=None):
    p=argparse.ArgumentParser(description='Sierra tick first-passage research. NO ORDERS, NO CLAIMS OF LIVE FILLS.')
    p.add_argument('--scid',type=Path,required=True)
    p.add_argument('--signals',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--tick',type=float,default=.25)
    p.add_argument('--tick-value',type=float,default=5.,help='NQ $5/tick; ES $12.50/tick; verify contract')
    p.add_argument('--commission',type=float,default=5.,help='USD round-trip per contract')
    p.add_argument('--utc-offset-hours',type=float,help='Chart time minus UTC; default: AUTO via bar close price')
    p.add_argument('--entry-delay-ms',type=int,default=0)
    p.add_argument('--entry-slippage-ticks',type=int,default=1)
    p.add_argument('--stop-slippage-ticks',type=int,default=1)
    p.add_argument('--exit-slippage-ticks',type=int,default=1)
    p.add_argument('--max-horizon-min',type=int,default=30)
    p.add_argument('--max-entry-gap-sec',type=float,default=5.)
    p.add_argument('--max-inner-gap-sec',type=float,default=90.)
    p.add_argument('--limit-at-next-opposite',action='store_true')
    p.add_argument('--allow-aggregated-exploratory',action='store_true')
    p.add_argument('--min-sl',type=int,default=10);p.add_argument('--max-sl',type=int,default=120)
    p.add_argument('--min-tp',type=int,default=10);p.add_argument('--max-tp',type=int,default=180)
    p.add_argument('--trials',type=int,default=100)
    p.add_argument('--seed',type=int,default=20261010)
    p.add_argument('--walk-forward-folds',type=int,default=3,help='Rolling folds when >= 30 dates; 0 disables')
    args=p.parse_args(argv)
    args.out.mkdir(parents=True,exist_ok=True)
    if args.tick<=0 or args.tick_value<=0 or args.commission<0 or args.max_horizon_min<1:
        p.error('Invalid tick/tick-value/commission/horizon')
    if args.min_sl<1 or args.min_tp<1 or args.max_sl<args.min_sl or args.max_tp<args.min_tp:
        p.error('Invalid stops / targets')
    t,px,quality=scid_reader(args.scid)
    bars,counts=collector_rows(args.signals)
    if quality['single_tick_convention_fraction']<.95 and not args.allow_aggregated_exploratory:
        raise SystemExit('DATA QUALITY BLOCK: Less than 95% SCID records match single-tick convention. '+
             'Cannot assert tick-by-tick first-hit order. Use --allow-aggregated-exploratory ONLY for diagnostics.')
    if args.utc_offset_hours is None:
        offset,match,scores=detect_offset(bars,t,px)
    else:
        offset=args.utc_offset_hours
        # Explicit offsets MUST still pass price alignment. Never silently force a different contract.
        checked=0;matchcount=0
        for b in bars[::max(1,len(bars)//120)]:
            a=chart_to_tape_us(b['bar_start'],offset)
            i=int(np.searchsorted(t,a,'left'));j=int(np.searchsorted(t,a+60_000_000,'left'))
            if j>i:
                checked+=1
                matchcount+=abs(float(px[j-1])-b['close'])<=0.26
        match=matchcount/max(1,checked)
        if match<.75:raise SystemExit(f'Failed alignment test for --utc-offset-hours={offset}: {match:.1%}; STOP')
    print(f'Chart-UTC offset = {offset:+g}h; price-alignment verified = {match:.1%}',flush=True)
    print('Tape quality:',quality,flush=True)
    ev,bad,total=make_events(bars,t,px,offset,args.tick,args.max_tp,args.max_sl,
        args.max_horizon_min,args.entry_delay_ms,args.entry_slippage_ticks,
        args.max_entry_gap_sec,args.max_inner_gap_sec,args.limit_at_next_opposite)
    print(f'Closed signals: {total}; valid paths: {len(ev)}; rejected: {bad}',flush=True)
    if len(ev)<10:raise SystemExit('Too few valid events for optimization; check alignment, gaps, SCID data range')
    days=sorted({e.day for e in ev});nd=len(days)
    if nd<3:raise SystemExit('At least three chronological trading dates needed for train/test')
    i=max(1,min(nd-2,math.ceil(nd*.6)))
    train_days=set(days[:i]);test_days=set(days[i:])
    train=[e for e in ev if e.day in train_days]
    test=[e for e in ev if e.day in test_days]
    cfg=dict(tick=args.tick,tick_value=args.tick_value,commission=args.commission,
             entry_slip=args.entry_slippage_ticks,stop_slip=args.stop_slippage_ticks,exit_slip=args.exit_slippage_ticks)
    if not train or not test:raise SystemExit('Empty train / test')
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    def objective(trial):
        params={'tp':trial.suggest_int('tp',args.min_tp,args.max_tp,step=5),
                'sl':trial.suggest_int('sl',args.min_sl,args.max_sl,step=5),
                'min_score':trial.suggest_categorical('min_score',[0.0,0.3,0.45,0.6,0.75])}
        r=evaluate(train,params,cfg)
        trial.set_user_attr('train_trades',r['n'])
        if r['n']<max(12,len(train)//10):return -1e12
        # Max DD penalized; trades are only assessed once in training.
        return r['net']-0.45*r['maxdd']
    study=optuna.create_study(direction='maximize',sampler=optuna.samplers.TPESampler(seed=args.seed))
    study.optimize(objective,n_trials=args.trials,show_progress_bar=False)
    best=study.best_params
    train_r=evaluate(train,best,cfg)
    test_r=evaluate(test,best,cfg) # exactly once for selected params
    all_r=evaluate(ev,best,cfg)
    trialrows=[{**t.params,'objective_train':t.value,'train_trades':t.user_attrs.get('train_trades',0)} for t in study.trials]
    write_csv(args.out/'TRAIN_OPTUNA_TRIALS.csv',trialrows)
    write_csv(args.out/'HOLDOUT_TRADES.csv',test_r['trades'])
    write_csv(args.out/'ALL_TRADES_EXPLORATORY.csv',all_r['trades'])
    wfrows=[];wftrades=[]
    if nd>=30 and args.walk_forward_folds>0:
        mintrain=max(12, int(.5*nd))
        remaining=days[mintrain:]
        chunks=[list(x) for x in np.array_split(remaining,args.walk_forward_folds) if len(x)]
        prior=days[:mintrain]
        for fold,heldout in enumerate(chunks,1):
            tr=[e for e in ev if e.day in set(prior)]
            te=[e for e in ev if e.day in set(heldout)]
            def wf_objective(trial):
                p_={'tp':trial.suggest_int('tp',args.min_tp,args.max_tp,step=5),
                    'sl':trial.suggest_int('sl',args.min_sl,args.max_sl,step=5),
                    'min_score':trial.suggest_categorical('min_score',[0.,.3,.45,.6,.75])}
                r_=evaluate(tr,p_,cfg)
                return r_['net']-.45*r_['maxdd'] if r_['n']>=max(12,len(tr)//10) else -1e12
            st=optuna.create_study(direction='maximize',sampler=optuna.samplers.TPESampler(seed=args.seed+fold))
            st.optimize(wf_objective,n_trials=args.trials,show_progress_bar=False)
            rr=evaluate(te,st.best_params,cfg)
            wfrows.append({'fold':fold,'train_first':prior[0],'train_last':prior[-1],
                'test_first':heldout[0],'test_last':heldout[-1],**st.best_params,
                'oos_trades':rr['n'],'oos_net':rr['net'],'oos_dd':rr['maxdd'],'oos_pf':rr['pf']})
            wftrades.extend([{'fold':fold,**t_} for t_ in rr['trades']])
            prior+=heldout
        write_csv(args.out/'WALK_FORWARD_FOLDS.csv',wfrows)
        write_csv(args.out/'WALK_FORWARD_TRADES.csv',wftrades)
    summary={'instrument':bars[0]['symbol'],'date_count':nd,'signal_count':total,'valid_events':len(ev),
       'reject_reasons':dict(bad),'collector_record_counts':dict(counts),'data_quality':quality,
       'mode':'EXPLORATORY_AGGREGATED' if quality['single_tick_convention_fraction']<.95 else 'TICK_CONVENTION_PASS',
       'time_alignment':{'chart_minus_utc_hours':offset,'bar_close_match_fraction':match},
       'config':vars(args) | cfg,'best_params_train_only':best,
       'train_days':sorted(train_days),'holdout_days':sorted(test_days),
       'train':{k:v for k,v in train_r.items() if k!='trades'},
       'holdout':{k:v for k,v in test_r.items() if k!='trades'},
       'all_exploratory':{k:v for k,v in all_r.items() if k!='trades'},
       'walk_forward_folds':wfrows,
       'warning':'Single train/test split, no walk-forward; limited dates cannot establish edge. Last-trade trigger is not an order-fill simulator. Overlapping signals are skipped by a one-position portfolio filter. First-hit on aggregated records is NOT reliably tick-accurate.'}
    (args.out/'SUMMARY.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
    quality_flag='NOT VALIDATED for live; >= 30 calendar trading dates needed before even a walk-forward research claim' if nd<30 else 'Walk-forward output available; still needs stronger independent holdout and Sierra replay validation'
    report='\n'.join(['# Universal research / tick first-hit audit','',f'- Instrument: **{bars[0]["symbol"]}**',
        f'- Dates: **{nd}** ({days[0]} ... {days[-1]})',f'- Confirmed events: **{total}**; valid paths **{len(ev)}**',
        f'- Tape single-tick conventional fraction: **{quality["single_tick_convention_fraction"]:.1%}**',
        f'- Price-alignment chart/UTC: **{offset:+g} h**, matched **{match:.1%}**',
        f'- Selected parameters (TRAIN ONLY): **{best}**',
        f'- TRAIN: {train_r["n"]} trades, net ${train_r["net"]:.2f}, maxDD ${train_r["maxdd"]:.2f}, PF {train_r["pf"]:.2f}',
        f'- HOLDOUT: {test_r["n"]} trades, net ${test_r["net"]:.2f}, maxDD ${test_r["maxdd"]:.2f}, PF {test_r["pf"]:.2f}',
        f'- Walk-forward folds: {len(wfrows)} (only if enough dates)',
        f'- **STATUS: {quality_flag}**',
        '', '**No edge is guaranteed.** Synthetic/slippage assumptions, last-trade-only execution, one-fold selection; replay order fills required as final verification.',
        '','## Rejections',f'`{dict(bad)}`','', 'Full machine-readable outputs in `SUMMARY.json`.'])
    (args.out/'REPORT.md').write_text(report,encoding='utf-8')
    print(report,flush=True)
    return 0

if __name__=='__main__':sys.exit(main())
