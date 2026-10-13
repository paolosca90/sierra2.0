"""Predeclared sample-size screens; never rerank models on held-out returns."""
import numpy as np


def statistics(counts,blocks=3):
    counts=np.asarray(counts,dtype=np.int64)
    groups=[x for x in np.array_split(counts,min(blocks,len(counts))) if len(x)]
    return dict(trades=int(counts.sum()),active_days=int(np.count_nonzero(counts)),days=len(counts),
                block_trades=[int(x.sum()) for x in groups])


def training_objective(result,config):
    sample=result['sample']
    if result['n']<config['min_trades']:return -1e30
    if sample['active_days']<config.get('min_active_days',0):return -1e30
    if any(n<config.get('min_trades_per_training_block',0) for n in sample['block_trades']):return -1e30
    return result['net']-.75*result['maxdd']


def evaluation_status(result,config):
    n=config.get('validation_min_trades',30);active=config.get('validation_min_active_days',10)
    sufficient=result['n']>=n and result['sample']['active_days']>=active
    return dict(status='sufficient_for_screening' if sufficient else 'insufficient_sample',
                sufficient=sufficient,minimum_trades=n,minimum_active_days=active,
                observed_trades=result['n'],observed_active_days=result['sample']['active_days'],
                note='Sample-size screen only; not proof of independence, statistical significance or edge.')
