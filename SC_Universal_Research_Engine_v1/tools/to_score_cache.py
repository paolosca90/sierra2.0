"""Reuse identical footprint metrics when only TO weights/sensitivity change."""
import numpy as np
from numba import njit
from footprint_kernel import clamp,DEFAULTS
from scid_dataset import calculate


@njit(cache=True)
def bar_totals(offsets,volume):
    totals=np.zeros(len(offsets)-1);rows=np.zeros(len(totals),np.int64)
    for b in range(len(totals)):
        for j in range(offsets[b],offsets[b+1]):
            if volume[j]>0:totals[b]+=volume[j];rows[b]+=1
    return totals,rows


@njit(cache=True)
def components(low,high,close,metrics,totals,rows,lookback,tolerance):
    n=len(low);parts=np.zeros((n,4),np.float32);factor=np.ones(n,np.float32)
    allowed=np.ones((n,2),np.bool_)
    for b in range(n):
        total=totals[b]
        if total<=0:continue
        delta,trapped,netimb,absorbed=metrics[b]
        cf=np.float32(2.*(close[b]-low[b])/(high[b]-low[b])-1.) if high[b]>low[b] else np.float32(0.)
        parts[b,0]=np.float32(clamp(np.float32(absorbed)/np.float32(total),-1.,1.))
        parts[b,1]=np.float32(clamp(np.float32(trapped)/np.float32(total),-1.,1.))
        dr=np.float32(clamp(np.float32(delta)/np.float32(total),-1.,1.))
        ir=np.float32(clamp(np.float32(netimb)/np.float32(max(1,rows[b])),-1.,1.))
        parts[b,2]=np.float32(-dr*clamp(-np.sign(dr)*cf,0.,1.))
        parts[b,3]=np.float32(-ir*clamp(-np.sign(ir)*cf,0.,1.))
        prior_vol=0.;count=0
        for j in range(max(0,b-int(lookback)),b):
            if high[j]>high[b]+tolerance:allowed[b,0]=False
            if low[j]<low[b]-tolerance:allowed[b,1]=False
            prior_vol+=totals[j];count+=1
        if count and prior_vol>0:factor[b]=np.float32(clamp(total/(prior_vol/count),.25,2.))
    return parts,factor,allowed


@njit(cache=True)
def reweight(parts,factor,allowed,weights,sensitivity,require_extreme,volume_weight):
    result=np.zeros(len(parts),np.float32)
    a,b,c,d=weights
    for i in range(len(parts)):
        ac,tc,dc,ic=parts[i]
        raw=np.float32((np.float32(a)*ac+np.float32(b)*tc+np.float32(c)*dc+np.float32(d)*ic)/np.float32(a+b+c+d))
        score=np.float32(clamp(np.float32(raw*np.float32(sensitivity)),-1.,1.))
        if require_extreme:
            if score<0 and not allowed[i,0]:score=np.float32(0.)
            if score>0 and not allowed[i,1]:score=np.float32(0.)
        if volume_weight:score=np.float32(clamp(np.float32(score*factor[i]),-1.,1.))
        result[i]=score
    return result


class TOScoreCache:
    def __init__(self,data):
        self.data=data;self.key=None;self.features=None;self.totals=None

    def score(self,params):
        p=DEFAULTS|params
        key=tuple(sorted((k,v) for k,v in p.items() if k not in ('w_abs','w_trap','w_delta','w_imb','sensitivity')))
        if self.key!=key:
            _,metrics=calculate(self.data,p)
            if self.totals is None:self.totals=bar_totals(self.data['offsets'],self.data['volume'])
            self.features=components(self.data['low'],self.data['high'],self.data['close'],metrics,*self.totals,p['lookback'],p['tolerance'])
            self.key=key
        return reweight(*self.features,np.array([p[k] for k in ('w_abs','w_trap','w_delta','w_imb')]),
                        p['sensitivity'],p['require_extreme'],p['volume_weight'])
