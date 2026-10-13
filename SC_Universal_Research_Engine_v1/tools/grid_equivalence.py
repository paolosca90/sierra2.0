"""Exact TO aliases only; no rounding, approximate pruning or return fitting."""


def strategy_key(params,indicator='to_reversal'):
    ignored=set()
    if indicator=='to_reversal' and params.get('i:w_abs',4)==0:
        # min_agg changes only absorbed volume, whose score coefficient is zero.
        ignored.add('i:min_agg')
        # imbalance also changes the row imbalance count. Only drop it when
        # that score coefficient is zero as well (e.g. trapped-only profile).
        if params.get('i:w_imb',1)==0:ignored.add('i:imbalance')
    return tuple(sorted((k,v) for k,v in params.items() if k not in ignored))


def training_result(result):
    # Retain precisely the fields used by training_objective and trial logs.
    # Do not keep daily dictionaries or per-trade arrays in the search memo.
    return {k:result[k] for k in ['n','net','maxdd','sample']}
