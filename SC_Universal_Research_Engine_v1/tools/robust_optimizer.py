"""Offline NQ/ES research: cached first passage, purged chronological selection.

Optimizes execution and the threshold of an OBSERVED score. It cannot recover
different footprint/absorption inputs from a CSV. No brokerage/order API.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import optuna

from universal_tick_optimizer import RECORD, EPOCH, CSV_DT, micros, detect_offset

VERSION = '2.0.0'
INF = np.iinfo(np.int64).max
INSTRUMENTS = {'NQ': (.25, 5.), 'ES': (.25, 12.5)}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def clean_json(value):
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if isinstance(value, np.generic):
        return clean_json(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value.resolve())
    return value


def save_json(path, data):
    Path(path).write_text(json.dumps(clean_json(data), indent=2, allow_nan=False), encoding='utf-8')


def save_csv(path, rows):
    if not rows:
        return
    with Path(path).open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def load_bars(path, bar_seconds):
    bars = []
    runs = set()
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            if r['kind'] != 'BAR_CLOSE':
                continue
            b = dict(bar_start=datetime.strptime(r['bar_start'], CSV_DT),
                     observed=datetime.strptime(r['observed_market_time'], CSV_DT),
                     close=float(r['close']), score=float(r['reversal_score']),
                     mask=int(r['signal_mask']), symbol=r['symbol'])
            if not np.isfinite([b['close'], b['score']]).all() or b['close'] <= 0 or abs(b['score']) > 1.00001:
                raise ValueError('Invalid close/score in CSV')
            if b['observed'] < b['bar_start'] + timedelta(seconds=bar_seconds):
                raise ValueError('Signal observed before bar closure; check bar duration')
            if bars and (b['bar_start'] <= bars[-1]['bar_start'] or b['observed'] < bars[-1]['observed']):
                raise ValueError('Duplicate, rewound or unordered CSV; use one file per replay')
            runs.add(r.get('run', '1'))
            # Optional point-in-time snapshot columns from ResearchCollectorV2.
            if r.get('levels_causal') == '1':
                b['levels'] = np.array([float(r[f'level_{i}']) for i in range(26)])
                if not np.isfinite(b['levels']).all() or (b['levels'] < 0).any():
                    raise ValueError('Invalid levels snapshot')
            bars.append(b)
    if not bars or len(runs) != 1 or len({b['symbol'] for b in bars}) != 1:
        raise ValueError('Need a nonempty, single-symbol, single-run CSV')
    return bars


def read_tape(path, first_us=None, last_us=None):
    """Copy a bounded snapshot, never mutate or hold a live writable mapping.

    Layout verified against installed Sierra IntradayRecord.h. Strictly refuse
    ANY aggregated traded record in the evaluation range (not a 95% heuristic).
    """
    import struct
    path = Path(path)
    with path.open('rb') as f:
        head = f.read(56)
    if len(head) != 56 or head[:4] != b'SCID':
        raise ValueError('Invalid SCID header')
    header, size = struct.unpack_from('<II', head, 4)
    version = struct.unpack_from('<H', head, 12)[0]
    if header != 56 or size != 40 or version != 1:
        raise ValueError(f'Unsupported SCID header/layout/version: {header}/{size}/{version}')
    file_size = path.stat().st_size
    if (file_size-header) % size or file_size <= header:
        raise ValueError('Incomplete/empty SCID snapshot; retry after writer completes')
    raw = np.memmap(path, dtype=RECORD, mode='r', offset=header, shape=((file_size-header)//size,))
    if np.any(np.diff(raw['datetime']) < 0):
        raise ValueError('Unordered SCID timestamps')
    left = 0 if first_us is None else int(np.searchsorted(raw['datetime'], first_us))
    right = len(raw) if last_us is None else int(np.searchsorted(raw['datetime'], last_us, side='right'))
    snapshot = np.array(raw[left:right], copy=True)
    del raw
    snapshot_hash = hashlib.sha256(head + snapshot.tobytes()).hexdigest()
    r = snapshot[snapshot['total_volume'] > 0]
    if len(r) < 2 or not np.isfinite(r['close']).all() or (r['close'] <= 0).any():
        raise ValueError('Missing/invalid executed trades')
    flags = (r['open'] == 0) | (r['open'] == np.float32(-1.99900095e37)) | (r['open'] == np.float32(-1.99900197e37))
    single = flags & (r['num_trades'] == 1)
    if not single.all():
        raise ValueError(f'Aggregated/unknown trades in requested interval: {int((~single).sum())}; tick order unknown')
    return r['datetime'].astype(np.int64), r['close'].astype(float), {
        'snapshot_sha256': snapshot_hash, 'source_bytes_at_open': file_size,
        'source_record_range': [left, right], 'trades': len(r),
        'single_tick_fraction': float(single.mean()),
        'first_utc': str(EPOCH + np.timedelta64(int(r['datetime'][0]), 'us')),
        'last_utc': str(EPOCH + np.timedelta64(int(r['datetime'][-1]), 'us'))}


def align(bars, ts, px, chart_timezone, offset, bar_seconds):
    if chart_timezone:
        tz = ZoneInfo(chart_timezone)
        def convert(d):
            if d.replace(tzinfo=tz, fold=0).utcoffset() != d.replace(tzinfo=tz, fold=1).utcoffset():
                raise ValueError('Ambiguous/nonexistent DST wall time: use UTC collector')
            return micros(d.replace(tzinfo=tz))
        label = chart_timezone
    else:
        if offset is None:
            if bar_seconds != 60:
                raise ValueError('AUTO alignment supports 60-second bars only; specify chart timezone')
            offset = detect_offset(bars, ts, px)[0]
        def convert(d):
            return micros(d) - round(offset * 3_600_000_000)
        label = f'UTC{offset:+g}'
        # AUTO/fixed offsets cannot safely map an interval spanning DST changes.
        if (bars[-1]['bar_start'] - bars[0]['bar_start']).days > 20:
            raise ValueError('For long datasets specify --chart-timezone (DST aware)')
    checked = matches = 0
    for b in bars[::max(1, len(bars)//200)]:
        a = convert(b['bar_start'])
        i, j = np.searchsorted(ts, [a, a + bar_seconds * 1_000_000])
        if j > i:
            checked += 1
            matches += abs(px[j-1] - b['close']) < .126
    if checked < min(20, len(bars)) or matches / max(1, checked) < .98:
        raise ValueError(f'Price alignment failed: {matches}/{checked}; check contract, bars and timezone')
    for b in bars:
        b['time'] = convert(b['observed'])
        b['day'] = b['observed'].date().isoformat()
        b['day_end'] = convert(datetime.combine(b['observed'].date()+timedelta(days=1), datetime.min.time()))
    return {'timezone': label, 'matched': int(matches), 'checked': checked}


def build_paths(bars, ts, px, *, tick=.25, max_sl=120, max_tp=180,
                horizon=30, delay_ms=1, entry_slip=1, target_through=1,
                max_entry_gap=5., max_gap=90., mode='score'):
    """Precompute each threshold once. O(trade path) preprocessing, cheap trials.

    Stops fill at adverse observed price (including gaps), targets at limit only
    after configurable trade-through; timeout at first trade AFTER its deadline.
    """
    records, tp_rows, sl_rows, stop_moves = [], [], [], []
    rejected = Counter()
    for b in bars:
        if mode == 'markers':
            mask = b['mask'] & 3
            if mask not in (1, 2):
                continue
            side = 1 if mask == 1 else -1
            if side * b['score'] <= 0:
                raise ValueError('Marker and signed score disagree')
        else:
            if b['score'] == 0:
                continue
            side = 1 if b['score'] > 0 else -1
        due = b['time'] + delay_ms * 1000
        st = int(np.searchsorted(ts, due, side='right'))
        deadline = due + horizon * 60_000_000
        en = int(np.searchsorted(ts, deadline, side='left'))
        if st >= len(ts) or en >= len(ts):
            rejected['incomplete_horizon'] += 1
            continue
        if ts[st]-due > max_entry_gap*1e6 or ts[en]-deadline > max_entry_gap*1e6:
            rejected['entry_or_timeout_gap'] += 1
            continue
        if en <= st or np.max(np.diff(ts[st:en+1])) > max_gap*1e6:
            rejected['internal_gap'] += 1
            continue
        # Path excludes the entry print; brackets are active after entry.
        movement = side * (px[st+1:en+1]-px[st])/tick - entry_slip
        favorable = np.maximum.accumulate(movement)
        adverse = np.maximum.accumulate(-movement)
        ti = np.searchsorted(favorable, np.arange(max_tp+1)+target_through)
        si = np.searchsorted(adverse, np.arange(max_sl+1))
        ttimes = np.full(max_tp+1, INF, dtype=np.int64)
        stimes = np.full(max_sl+1, INF, dtype=np.int64)
        smove = np.zeros(max_sl+1)
        tvalid, svalid = ti < len(movement), si < len(movement)
        # Store record indices: same-microsecond trades still have file order.
        ttimes[tvalid] = st+1+ti[tvalid]
        stimes[svalid] = st+1+si[svalid]
        smove[svalid] = movement[si[svalid]]
        levels = b.get('levels', np.zeros(26))
        nonzero = levels[levels > 0]
        distance = float(np.min(np.abs(nonzero-b['close']))/tick) if len(nonzero) else np.inf
        records.append((b['time'], ts[st], ts[en], st, en, side, b['score'], px[st], movement[-1], distance, b['day'], b['day_end']))
        tp_rows.append(ttimes)
        sl_rows.append(stimes)
        stop_moves.append(smove)
    if not records:
        raise ValueError(f'No usable events: {dict(rejected)}')
    names = ['signal_time', 'entry_time', 'end_time', 'start', 'end', 'side', 'score', 'entry_last', 'timeout_move', 'level_distance', 'day', 'day_end']
    ints = {'signal_time', 'entry_time', 'end_time', 'start', 'end', 'side', 'day_end'}
    data = {name: np.array([r[i] for r in records], dtype='U10' if name == 'day' else np.int64 if name in ints else float)
            for i, name in enumerate(names)}
    data.update(tp=np.array(tp_rows), sl=np.array(sl_rows), stop_move=np.array(stop_moves), tape_time=ts)
    return data, dict(rejected)


def partition(data, days):
    """Purge the WHOLE possible path at calendar boundaries, before any search."""
    days = set(days)
    m = np.isin(data['day'], list(days))
    # Fixed, parameter-independent purge at every chart-calendar midnight.
    # Never infer boundaries from the first signal on the following day.
    m &= data['end_time'] < data['day_end']
    return np.flatnonzero(m)


def evaluate(data, indices, params, *, tick_value=5., commission=5., stop_slip=1,
             exit_slip=1, extra_cost_ticks=0., detail=False):
    selected = indices[np.abs(data['score'][indices]) >= params['min_score']]
    if params.get('level_ticks', 0):
        selected = selected[data['level_distance'][selected] <= params['level_ticks']]
    t = data['tp'][selected, params['tp']]
    s = data['sl'][selected, params['sl']]
    stop = (s <= t) & (s != INF)
    target = (t < s) & (t != INF)
    end = np.where(stop, s, np.where(target, t, data['end'][selected]))
    moves = np.where(stop, data['stop_move'][selected, params['sl']]-stop_slip,
                     np.where(target, params['tp'], data['timeout_move'][selected]-exit_slip))
    pnl = (moves-extra_cost_ticks)*tick_value-commission
    previous_time = -1
    values, trades, daily = [], [], {}
    for j, idx in enumerate(selected):
        # Prevent overlapping positions, also across equal-time records.
        if data['entry_time'][idx] <= previous_time:
            continue
        previous_time = int(data['tape_time'][end[j]])
        value = float(pnl[j])
        values.append(value)
        day = str(data['day'][idx])
        daily[day] = daily.get(day, 0.) + value
        if detail:
            trades.append(dict(day=day, side=int(data['side'][idx]), score=float(data['score'][idx]),
                entry_utc=str(EPOCH + np.timedelta64(int(data['entry_time'][idx]), 'us')),
                exit_utc=str(EPOCH + np.timedelta64(previous_time, 'us')),
                entry_last=float(data['entry_last'][idx]), net_usd=value,
                exit_reason='SL' if stop[j] else 'TP' if target[j] else 'TIMEOUT'))
    x = np.array(values)
    equity = np.r_[0., np.cumsum(x)]
    losses = float(-x[x < 0].sum())
    return dict(n=len(x), net=float(x.sum()), avg=float(x.mean()) if len(x) else 0.,
                maxdd=float(np.max(np.maximum.accumulate(equity)-equity)),
                pf=float(x[x > 0].sum()/losses) if losses else None,
                win_pct=float(100*np.mean(x > 0)) if len(x) else 0., daily=daily, trades=trades)


def metric(result, min_trades):
    if result['n'] < min_trades:
        return -1e30
    return result['net'] - .75*result['maxdd']


def optimize(data, indices, args, family, seed):
    cache = {}
    costs = dict(tick_value=args.tick_value, commission=args.commission,
                 stop_slip=args.stop_slip, exit_slip=args.exit_slip)
    def objective(trial):
        p = dict(sl=trial.suggest_int('sl', args.min_sl, args.max_sl, step=args.step),
                 tp=trial.suggest_int('tp', args.min_tp, args.max_tp, step=args.step),
                 min_score=trial.suggest_categorical('min_score', args.scores))
        if family == 'with_levels':
            p['level_ticks'] = trial.suggest_categorical('level_ticks', args.level_distances)
        key = tuple(sorted(p.items()))
        if key not in cache:
            cache[key] = evaluate(data, indices, p, **costs)
        result = cache[key]
        trial.set_user_attr('trades', result['n'])
        return metric(result, args.min_trades)
    study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=seed))
    study.enqueue_trial(dict(sl=args.min_sl, tp=args.min_tp, min_score=args.scores[0],
                             **({'level_ticks': args.level_distances[-1]} if family == 'with_levels' else {})))
    study.optimize(objective, n_trials=args.trials)
    if study.best_value <= -1e30:
        return None, [], len(cache)
    rows = [dict(trial=t.number, objective=t.value, **t.params, trades=t.user_attrs['trades']) for t in study.trials]
    return study.best_params, rows, len(cache)


def daily_bootstrap(result, days, seed, iterations=2000):
    # Circular moving blocks preserve some serial dependence; zero-trade dates
    # count. Descriptive uncertainty, NOT a multiple-testing-adjusted p-value.
    x = np.array([result['daily'].get(d, 0.) for d in days])
    if len(x) < 5:
        return {'status': 'insufficient_dates', 'dates': len(x)}
    rng = np.random.default_rng(seed)
    block = min(5, max(2, int(math.sqrt(len(x)))))
    starts = rng.integers(len(x), size=(iterations, math.ceil(len(x)/block)))
    idx = (starts[:, :, None]+np.arange(block)) % len(x)
    means = x[idx.reshape(iterations, -1)[:, :len(x)]].mean(axis=1)
    return {'status': 'descriptive_only', 'block_days': block,
            'mean_daily_usd_ci95': np.quantile(means, [.025, .975]).tolist()}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scid', type=Path, required=True)
    p.add_argument('--signals', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--instrument', choices=INSTRUMENTS, required=True)
    p.add_argument('--chart-timezone', help='IANA e.g. America/New_York, Europe/Rome, UTC')
    p.add_argument('--utc-offset-hours', type=float)
    p.add_argument('--bar-seconds', type=int, default=60)
    p.add_argument('--commission', type=float, default=5., help='USD round trip / contract; assumption, set actual costs')
    p.add_argument('--entry-slip', type=int, default=1)
    p.add_argument('--stop-slip', type=int, default=1)
    p.add_argument('--exit-slip', type=int, default=1)
    p.add_argument('--target-through', type=int, default=1)
    p.add_argument('--delay-ms', type=int, default=1)
    p.add_argument('--horizon', type=int, default=30)
    p.add_argument('--max-gap', type=float, default=90.)
    p.add_argument('--max-entry-gap', type=float, default=5.)
    p.add_argument('--min-sl', type=int, default=10)
    p.add_argument('--max-sl', type=int, default=120)
    p.add_argument('--min-tp', type=int, default=10)
    p.add_argument('--max-tp', type=int, default=180)
    p.add_argument('--step', type=int, default=5)
    p.add_argument('--scores', type=float, nargs='+', default=[.15, .2, .3, .4, .5, .6])
    p.add_argument('--signal-mode', choices=['score', 'markers'], default='score')
    p.add_argument('--level-distances', type=int, nargs='+', default=[2, 4, 8, 16])
    p.add_argument('--trials', type=int, default=200)
    p.add_argument('--min-trades', type=int, default=20)
    p.add_argument('--seed', type=int, default=20261013)
    p.add_argument('--folds', type=int, default=3)
    p.add_argument('--cache', type=Path)
    args = p.parse_args(argv)
    args.tick, args.tick_value = INSTRUMENTS[args.instrument]
    if (args.min_sl <= args.entry_slip or args.min_tp < 1 or args.max_sl < args.min_sl or
            args.max_tp < args.min_tp or args.step < 1 or args.trials < 1 or args.min_trades < 1 or
            args.horizon < 1 or args.bar_seconds < 1 or args.folds < 1 or
            min(args.entry_slip, args.stop_slip, args.exit_slip, args.target_through, args.delay_ms) < 0 or
            not np.isfinite([args.commission, args.max_gap, args.max_entry_gap, *args.scores]).all() or
            args.commission < 0 or args.max_gap <= 0 or args.max_entry_gap <= 0 or
            any(s <= 0 or s > 1 for s in args.scores) or min(args.level_distances) <= 0):
        p.error('Invalid search/execution parameters')
    if args.chart_timezone and args.utc_offset_hours is not None:
        p.error('Use chart-timezone OR utc-offset-hours')
    if args.out.exists() and any(args.out.iterdir()):
        p.error('Output directory must be new/empty; preserve previous research')
    started = time.perf_counter()
    bars = load_bars(args.signals, args.bar_seconds)
    symbol = bars[0]['symbol']
    if not symbol.startswith(args.instrument) or args.scid.stem != symbol:
        p.error('SCID filename, collector symbol and instrument must match exactly')
    # Include timezone uncertainty and full execution horizons; no unused years.
    ts, px, quality = read_tape(args.scid, micros(bars[0]['bar_start'])-15*3_600_000_000,
                               micros(bars[-1]['observed'])+(15*60+args.horizon)*60_000_000)
    if not np.allclose(px/args.tick, np.rint(px/args.tick), atol=1e-5, rtol=0):
        raise ValueError('Prices off contract tick grid')
    alignment = align(bars, ts, px, args.chart_timezone, args.utc_offset_hours, args.bar_seconds)
    print(f'Alignment {alignment}; {len(ts):,} trades; {len(bars):,} closed bars', flush=True)
    path_options = dict(tick=args.tick, max_sl=args.max_sl, max_tp=args.max_tp, horizon=args.horizon,
                        delay_ms=args.delay_ms, entry_slip=args.entry_slip, target_through=args.target_through,
                        max_gap=args.max_gap, max_entry_gap=args.max_entry_gap, mode=args.signal_mode)
    cache_identity = dict(version=VERSION, tape=quality['snapshot_sha256'], signals=digest(args.signals),
                          options=path_options, alignment=alignment)
    key = hashlib.sha256(json.dumps(cache_identity, sort_keys=True).encode()).hexdigest()
    cache_dir = args.cache or Path(__file__).resolve().parents[1]/'.research_cache'
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir/f'{key}.npz'
    cache_hit = cache_path.exists()
    if cache_hit:
        with np.load(cache_path, allow_pickle=False) as z:
            data = {k: z[k] for k in z.files if k != 'rejected'}
            rejected = json.loads(str(z['rejected']))
    else:
        data, rejected = build_paths(bars, ts, px, **path_options)
        np.savez_compressed(cache_path, **data, rejected=json.dumps(rejected))
    preprocess_seconds = time.perf_counter()-started
    days = sorted({b['day'] for b in bars})
    if len(days) < 5:
        raise ValueError('Need >=5 chronological dates; even this is only exploratory')
    hold_count = max(2, math.ceil(.2*len(days)))
    development, holdout = days[:-hold_count], days[-hold_count:]
    # First half of development for initial fit; later development dates for
    # expanding walk-forward selection. FINAL holdout never enters these folds.
    initial = max(1, len(development)//2)
    chunks = [list(c) for c in np.array_split(development[initial:], min(args.folds, len(development)-initial)) if len(c)]
    families = ['standalone']
    if all('levels' in b for b in bars):
        families.append('with_levels')
    args.out.mkdir(parents=True, exist_ok=True)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    costs = dict(tick_value=args.tick_value, commission=args.commission,
                 stop_slip=args.stop_slip, exit_slip=args.exit_slip)
    results, wf_rows, all_trials = {}, [], []
    for family in families:
        prior = development[:initial]
        oos_trades = []
        for fold, test_days in enumerate(chunks, 1):
            best, trials, unique = optimize(data, partition(data, prior), args, family, args.seed+fold)
            all_trials.extend(dict(family=family, stage=f'fold_{fold}', **r) for r in trials)
            if best is not None:
                result = evaluate(data, partition(data, test_days), best, detail=True, **costs)
                oos_trades.extend(result['trades'])
                wf_rows.append(dict(family=family, fold=fold, train_last=prior[-1], test_first=test_days[0],
                                    test_last=test_days[-1], params=json.dumps(best), n=result['n'], net=result['net']))
            else:
                wf_rows.append(dict(family=family, fold=fold, train_last=prior[-1], test_first=test_days[0],
                                    test_last=test_days[-1], params='NO_ELIGIBLE_TRIAL', n=0, net=0.))
            prior += test_days
        wf_pnl = np.array([r['net_usd'] for r in oos_trades])
        eq = np.r_[0., np.cumsum(wf_pnl)]
        selection = dict(n=len(wf_pnl), net=float(wf_pnl.sum()),
                         maxdd=float(np.max(np.maximum.accumulate(eq)-eq)))
        best, trials, unique = optimize(data, partition(data, development), args, family, args.seed)
        all_trials.extend(dict(family=family, stage='development_refit', **r) for r in trials)
        results[family] = dict(params=best, development_wf=selection, unique_refit_trials=unique)
        save_csv(args.out/f'{family}_DEVELOPMENT_OOS_TRADES.csv', oos_trades)
    eligible = [f for f in families if results[f]['params'] is not None and results[f]['development_wf']['n'] >= args.min_trades]
    winner = max(eligible, key=lambda f: metric(results[f]['development_wf'], args.min_trades)) if eligible else None
    # Freeze decision before reading ANY holdout outcome.
    save_json(args.out/'SELECTION_LOCK.json', dict(selected_family=winner, results=results,
        development_days=development, final_holdout_days=holdout, identity=cache_identity))
    hold_indices = partition(data, holdout)
    for family in families:
        best = results[family]['params']
        if best is None:
            continue
        final = evaluate(data, hold_indices, best, detail=True, **costs)
        stress = evaluate(data, hold_indices, best, extra_cost_ticks=2., **costs)
        results[family]['holdout'] = {k: v for k, v in final.items() if k != 'trades'}
        results[family]['holdout_extra_2_ticks_net'] = stress['net']
        results[family]['uncertainty'] = daily_bootstrap(final, holdout, args.seed)
        save_csv(args.out/f'{family}_HOLDOUT_TRADES.csv', final['trades'])
    baseline = dict(sl=40, tp=60, min_score=.30)
    # Fixed reference uses only values covered by the declared path grid.
    baseline_result = evaluate(data, hold_indices, baseline, **costs) if args.max_sl >= 40 and args.max_tp >= 60 else None
    save_csv(args.out/'WALK_FORWARD.csv', wf_rows)
    # Families have a different parameter schema; normalize before CSV export.
    for r in all_trials:
        r.setdefault('level_ticks', 0)
    save_csv(args.out/'TRIALS.csv', all_trials)
    warnings = ['Last-trade execution proxy, not queue/bid-ask fill validation.',
                'Fixed horizon; opposite-signal exit NOT enabled. Compare identical rules in Sierra.',
                'Observed score only: absorption inputs/weights/lookback NOT recomputed.',
                'Repeated inspection of this holdout consumes it; obtain new data before another conclusion.',
                'Drawdown is closed-trade equity, not intratrade / prop trailing drawdown.']
    if len(days) < 60 or len(holdout) < 20:
        warnings.append('INSUFFICIENT HISTORY: preliminary experiment, no robust edge claim.')
    if 'with_levels' not in families:
        warnings.append('Deluxe comparison unavailable: need causal point-in-time level snapshots in CSV.')
    elapsed = time.perf_counter()-started
    summary = dict(version=VERSION, symbol=symbol, config=vars(args), quality=quality, alignment=alignment,
                   cache_hit=cache_hit, preprocessing_seconds=preprocess_seconds, total_seconds=elapsed,
                   candidate_events=len(data['day']), rejected=rejected, development_days=development,
                   holdout_days=holdout, selected_before_holdout=winner, results=results,
                   fixed_baseline=baseline_result, warnings=warnings,
                   environment=dict(python=platform.python_version(), numpy=np.__version__, optuna=optuna.__version__),
                   optimizer_sha256=digest(__file__))
    save_json(args.out/'SUMMARY.json', summary)
    lines = ['# Ricerca NQ / ES — risultati preliminari', '',
             f'Simbolo: {symbol}. {len(days)} date, {len(data["day"])} percorsi validi.',
             f'Selezione congelata prima del test: {winner}. Holdout: {holdout[0]} — {holdout[-1]}.', '',
             '| Variante | Parametri | Trade holdout | Netto USD | DD chiuso USD | Stress +2 tick USD |',
             '|---|---|---:|---:|---:|---:|']
    for family, r in results.items():
        h = r.get('holdout')
        if h:
            lines.append(f'| {family} | {r["params"]} | {h["n"]} | {h["net"]:.2f} | {h["maxdd"]:.2f} | {r["holdout_extra_2_ticks_net"]:.2f} |')
    lines += ['', f'Tempo totale {elapsed:.2f}s; preparazione {preprocess_seconds:.2f}s; cache={cache_hit}.', '']
    lines += ['- '+w for w in warnings]
    (args.out/'REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('\n'.join(lines), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
