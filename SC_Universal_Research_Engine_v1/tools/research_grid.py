"""Exact Cartesian grids with explicit, nonredundant score-weight profiles."""
import itertools
import math

WEIGHTS=('w_abs','w_trap','w_delta','w_imb')


def weight_profiles(values=(1,4)):
    seen=set();profiles=[]
    for row in itertools.product(values,repeat=4):
        divisor=math.gcd(*row)
        if not divisor:continue
        ratio=tuple(v//divisor for v in row)
        if ratio in seen:continue
        seen.add(ratio);profiles.append(dict(zip(WEIGHTS,row)))
    return profiles


def grid_size(space,profiles=None):
    ignored={'i:'+k for k in WEIGHTS} if profiles else set()
    return math.prod(len(v) for k,v in space.items() if k not in ignored)*(len(profiles) if profiles else 1)


def grid_candidates(space,profiles=None):
    ignored={'i:'+k for k in WEIGHTS} if profiles else set()
    axes={k:v for k,v in space.items() if k not in ignored}
    outer={k:v for k,v in axes.items() if k.startswith('i:')}
    inner={k:v for k,v in axes.items() if not k.startswith('i:')}
    for row in itertools.product(*outer.values()):
        for profile in profiles or [{}]:
            base=dict(zip(outer,row))|{'i:'+k:v for k,v in profile.items()}
            for execution in itertools.product(*inner.values()):
                yield base|dict(zip(inner,execution))
