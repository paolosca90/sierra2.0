"""TO Deluxe default 18:00 NY session, 70% VA, one tick rows; causal outputs.

First incomplete day/week/month suppressed. No OHLC volume approximation.
This port needs a separate Sierra point-in-time parity export for full validation.
"""
import numpy as np
from numba import njit


@njit(cache=True)
def profile(volumes, base, percent=70.):
    rows=np.flatnonzero(volumes>0)
    if not len(rows):return 0.,0.,0.
    maximum=0.
    for i in rows:maximum=max(maximum,volumes[i])
    poc=0;distance=1e30;middle=(len(rows)-1)/2.
    for j in range(len(rows)):
        if volumes[rows[j]]==maximum and abs(j-middle)<distance:
            poc=j;distance=abs(j-middle)
    running=volumes[rows[poc]];target=volumes.sum()*percent/100.
    up=poc+1;down=poc-1;hi=poc;lo=poc
    while running<target and (up<len(rows) or down>=0):
        uc=min(2,len(rows)-up);dc=min(2,down+1)
        us=0.;ds=0.
        for k in range(uc):us+=volumes[rows[up+k]]
        for k in range(dc):ds+=volumes[rows[down-k]]
        if dc==0 or (uc>0 and us>=ds):
            running+=us;hi=up+uc-1;up+=uc
        else:
            running+=ds;lo=down-dc+1;down-=dc
    return float(base+rows[poc]),float(base+rows[hi]),float(base+rows[lo])


@njit(cache=True)
def compute(low,high,close,offsets,volume,keys,clock):
    n=len(low);base=low.min();size=high.max()-base+1
    profiles=np.zeros((3,size),np.float64)
    period_hi=np.zeros(3);period_lo=np.full(3,1e30);period_close=np.zeros(3)
    current=keys[0].copy();complete=np.zeros(3,np.bool_)
    previous=np.zeros((3,6));ranges=np.zeros((4,2))
    result=np.zeros((n,26));distance=np.full(n,np.inf)
    starts=np.array([34200,34200,64800,10800])
    ends=np.array([35100,37800,10800,34200])
    for b in range(n):
        for g in range(3):
            if keys[b,g]!=current[g]:
                if complete[g]:
                    poc,vah,val=profile(profiles[g],base)
                    previous[g,0]=period_hi[g];previous[g,1]=period_lo[g];previous[g,2]=period_close[g]
                    previous[g,3]=vah;previous[g,4]=val;previous[g,5]=poc
                profiles[g,:]=0;period_hi[g]=0;period_lo[g]=1e30
                current[g]=keys[b,g];complete[g]=True
                if g==0:ranges[:,:]=0
            for k in range(6):result[b,g*6+k]=previous[g,k]
        for g in range(4):
            inside=(starts[g]<=clock[b]<ends[g]) if starts[g]<ends[g] else (clock[b]>=starts[g] or clock[b]<ends[g])
            if inside:
                ranges[g,0]=max(ranges[g,0],high[b])
                ranges[g,1]=min(ranges[g,1],low[b]) if ranges[g,1]>0 else low[b]
            result[b,18+g*2]=ranges[g,0];result[b,19+g*2]=ranges[g,1]
        for k in range(26):
            if result[b,k]>0:distance[b]=min(distance[b],abs(close[b]-result[b,k]))
        for g in range(3):
            period_hi[g]=max(period_hi[g],high[b]);period_lo[g]=min(period_lo[g],low[b]);period_close[g]=close[b]
            for j in range(offsets[b],offsets[b+1]):
                if volume[j]>0:profiles[g,low[b]+j-offsets[b]-base]+=volume[j]
    return result,distance


def from_dataset(data):
    return compute(data['low'],data['high'],data['close'],data['offsets'],data['volume'],data['period_keys'],data['clock_seconds'])
