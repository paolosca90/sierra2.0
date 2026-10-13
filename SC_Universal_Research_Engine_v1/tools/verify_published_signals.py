"""Verify published time-bar signals against the original offline calculation.

This is an independent check of score-cache/report consistency, not native
Sierra execution parity. Restricted to short entry latency and time bars.
"""
import argparse
import gc
import json
import csv
import sys
from collections import Counter
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
from scid_dataset import load_cache,calculate
from robust_optimizer import EPOCH
from to_score_cache import TOScoreCache,components,bar_totals
from resource_guard import initialize_research,ensure_memory


def verify(identity):
    folder=ROOT/'dashboard_jobs'/identity
    c=json.loads((folder/'config.json').read_text());s=json.loads((folder/'SUMMARY.json').read_text())
    if c.get('trades_per_bar',0) or c['delay_ms']>=1000 or 2*c['max_entry_gap']+c['delay_ms']/1000>=c['bar_seconds']:
        raise ValueError('This verifier requires time bars and entry latency shorter than their duration')
    with (folder/'HOLDOUT_TRADES.csv').open(encoding='utf-8-sig',newline='') as stream:trades=list(csv.DictReader(stream))
    initialize_research(3);p={k[2:]:v for k,v in s['params'].items() if k.startswith('i:')}
    checked=0;dominance=Counter();net_abs_zero=0;net_abs_aligned=0;source_hashes=[]
    for meta,spec in zip(s['datasets'],[spec for spec in c['manifest'] if spec['scid'] not in {e['source'] for e in s.get('data_exclusions',[])}]):
        selected=[t for t in trades if spec['trade_from']<=t['day']<=spec['trade_to']]
        if not selected:continue
        assert meta['signature']['path']==spec['scid']
        ensure_memory(reclaim=True);data,_=load_cache(Path(meta['cache_directory']))
        original,metrics=calculate(data,p);cache=TOScoreCache(data)
        np.testing.assert_array_equal(original,cache.score(p))
        total,rows=bar_totals(data['offsets'],data['volume'])
        parts,_,_=components(data['low'],data['high'],data['close'],metrics,total,rows,p['lookback'],p['tolerance'])
        weights=np.array([p[k] for k in ['w_abs','w_trap','w_delta','w_imb']])
        for trade in selected:
            entry_us=int((np.datetime64(trade['entry_utc'],'us')-EPOCH)/np.timedelta64(1,'us'))
            current_bucket=entry_us//(c['bar_seconds']*1_000_000)*(c['bar_seconds']*1_000_000)
            previous_bucket=current_bucket-c['bar_seconds']*1_000_000
            b=int(np.searchsorted(data['bar_time'],previous_bucket))
            assert b<len(original) and int(data['bar_time'][b])==previous_bucket
            assert float(original[b])==float(trade['signal'])
            assert np.sign(original[b])==int(trade['side']) and abs(original[b])>=s['params']['e:min_score']
            term=parts[b]*weights;dominance[['absorption','trapped','delta_divergence','failed_imbalance'][int(np.argmax(np.abs(term)))]]+=1
            net_abs_zero+=int(metrics[b,3]==0);net_abs_aligned+=int(metrics[b,3]*int(trade['side'])>0);checked+=1
        source_hashes.append(meta['source_sha256']);del data,cache,original,metrics,parts,total,rows;gc.collect()
    assert checked==len(trades)
    result=dict(job_id=identity,verified_published_signals=checked,all_original_cached_scores_equal=True,
                largest_absolute_weighted_component=dict(dominance),zero_net_absorption_component=net_abs_zero,
                net_absorption_aligned_with_side=net_abs_aligned,source_hashes=source_hashes,
                scope='Original offline formula versus cached scores and published signals; not native Sierra parity. Zero net absorption can include offsetting bullish/bearish absorption.')
    (folder/'SIGNAL_REPORT_VERIFICATION.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2));return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--job',required=True);args=parser.parse_args();verify(args.job)
