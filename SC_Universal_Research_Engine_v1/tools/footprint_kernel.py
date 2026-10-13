"""Compiled, causal subset of TraderOracle TOReversalEngine calculation.

Port of the locally installed ACSIL source: ConfirmationBars=0; time bars only.
No drawing/alert loops. Validate scores against Sierra before operational use.
"""
import numpy as np
from numba import njit

DEFAULTS = dict(min_agg=150., min_pct=8., level_multiple=2., diagonal=1., imbalance=2.5,
                extreme_ticks=3., rejection_ticks=2., close_through=0., bubbles=2., separation=3.,
                trap_buffer=2., min_trapped=0., imbalance_volume=20., lookback=10.,
                require_extreme=1., tolerance=1., w_abs=4., w_trap=1., w_delta=1., w_imb=1.,
                volume_weight=1., sensitivity=4.)
KEYS = tuple(DEFAULTS)


def vector(params=None):
    d = dict(DEFAULTS)
    if params:
        unknown = set(params)-set(d)
        if unknown:
            raise ValueError(f'Unsupported indicator parameters: {unknown}')
        d.update(params)
    a = np.array([d[k] for k in KEYS], dtype=np.float64)
    if not np.isfinite(a).all() or (a < 0).any():
        raise ValueError('Indicator parameters must be finite and nonnegative')
    if not 1 <= d['bubbles'] <= 6 or not 1 <= d['lookback'] <= 500:
        raise ValueError('bubbles 1..6 and lookback 1..500 required')
    if sum(d[k] for k in ['w_abs','w_trap','w_delta','w_imb']) <= 0:
        raise ValueError('At least one positive score weight required')
    return a


@njit(cache=True)
def aggregate_vap(price, bid, ask, volume, starts, ends, low, offsets):
    vb = np.zeros(offsets[-1], np.int64)
    va = np.zeros(offsets[-1], np.int64)
    vv = np.zeros(offsets[-1], np.int64)
    for b in range(len(starts)):
        for j in range(starts[b], ends[b]):
            k = offsets[b]+price[j]-low[b]
            vb[k] += bid[j]
            va[k] += ask[j]
            vv[k] += volume[j]
    return vb, va, vv


@njit(cache=True)
def clamp(x, lo, hi):
    return min(hi, max(lo, x))


@njit(cache=True)
def scores(low, high, close, offsets, bid, ask, volume, params):
    (min_agg, min_pct, level_multiple, diagonal, imbalance, extreme_ticks, rejection_ticks,
     close_through, bubbles, separation, trap_buffer, min_trapped, imbalance_volume,
     lookback, require_extreme, tolerance, w_abs, w_trap, w_delta, w_imb,
     volume_weight, sensitivity) = params
    n = len(low)
    result = np.zeros(n, np.float32)
    metrics = np.zeros((n, 4), np.float64)  # delta, trapped, imbalance, absorbed
    bar_volume = np.zeros(n, np.float64)
    for b in range(n):
        a, z = offsets[b], offsets[b+1]
        total = 0.; rows = 0; ta = 0; tb = 0; trapped = 0; netimb = 0
        for j in range(a, z):
            if volume[j] <= 0:
                continue
            rows += 1; total += volume[j]; ta += ask[j]; tb += bid[j]
            price = low[b]+j-a
            if price >= close[b]+trap_buffer: trapped -= ask[j]
            if price <= close[b]-trap_buffer: trapped += bid[j]
            opposing_bid = bid[j]
            opposing_ask = ask[j]
            if diagonal:
                opposing_bid = bid[j-1] if j>a else 0
                opposing_ask = ask[j+1] if j+1<z else 0
            if ask[j] >= imbalance_volume and ask[j] > 0 and np.float32(ask[j])/np.float32(max(1,opposing_bid)) >= imbalance:
                netimb += 1
            if bid[j] >= imbalance_volume and bid[j] > 0 and np.float32(bid[j])/np.float32(max(1,opposing_ask)) >= imbalance:
                netimb -= 1
        bar_volume[b] = total
        if total <= 0: continue
        if abs(trapped) < min_trapped: trapped = 0
        avg = total/max(1,rows)
        candidates = np.zeros((64,4), np.float64)  # price, direction, aggressive vol, rank
        count = 0
        for j in range(a,z):
            if count >= 64: break
            if volume[j] <= 0 or volume[j] < total*min_pct/100 or volume[j] < avg*level_multiple:
                continue
            price = low[b]+j-a
            for direction in (-1,1):
                if count >= 64: break
                aggressive = ask[j] if direction < 0 else bid[j]
                passive = bid[j] if direction < 0 else ask[j]
                if diagonal:
                    passive = (bid[j-1] if j>a else 0) if direction<0 else (ask[j+1] if j+1<z else 0)
                ratio = np.float32(aggressive)/np.float32(max(1,passive))
                distance = high[b]-price if direction<0 else price-low[b]
                rejection = price-close[b] if direction<0 else close[b]-price
                if aggressive < min_agg or distance > extreme_ticks or ratio < imbalance or rejection < rejection_ticks:
                    continue
                if close_through and rejection <= 0: continue
                rel = np.float32(aggressive/max(1.,avg))
                imb = np.float32(np.sqrt(np.float32(clamp(ratio,1.,12.))))
                rej = np.float32(1.+clamp(np.float32(rejection)/np.float32(8.),0.,1.))
                rank = np.float32(np.float32(rel*imb)*rej)
                candidates[count,0]=price; candidates[count,1]=direction
                candidates[count,2]=aggressive; candidates[count,3]=rank
                count += 1
        # Same selection sort and tie ordering as ACSIL.
        for i in range(count-1):
            best = i
            for j in range(i+1,count):
                if candidates[j,3] > candidates[best,3]: best=j
            if best != i:
                for k in range(4):
                    temp=candidates[i,k];candidates[i,k]=candidates[best,k];candidates[best,k]=temp
        selected = np.zeros((6,2),np.float64)
        used=0; absorbed=0.
        for j in range(count):
            if used >= int(bubbles): break
            near=False
            for k in range(used):
                if selected[k,1]==candidates[j,1] and abs(selected[k,0]-candidates[j,0])<separation:
                    near=True;break
            if not near:
                selected[used,0]=candidates[j,0];selected[used,1]=candidates[j,1]
                absorbed += candidates[j,1]*candidates[j,2];used+=1
        delta=ta-tb
        metrics[b,0]=delta;metrics[b,1]=trapped;metrics[b,2]=netimb;metrics[b,3]=absorbed
        cf=np.float32(2.*(close[b]-low[b])/(high[b]-low[b])-1.) if high[b]>low[b] else np.float32(0.)
        ac=np.float32(clamp(np.float32(absorbed)/np.float32(total),-1.,1.))
        tc=np.float32(clamp(np.float32(trapped)/np.float32(total),-1.,1.))
        dr=np.float32(clamp(np.float32(delta)/np.float32(total),-1.,1.))
        ir=np.float32(clamp(np.float32(netimb)/np.float32(max(1,rows)),-1.,1.))
        dc=np.float32(-dr*clamp(-np.sign(dr)*cf,0.,1.))
        ic=np.float32(-ir*clamp(-np.sign(ir)*cf,0.,1.))
        raw=np.float32((np.float32(w_abs)*ac+np.float32(w_trap)*tc+np.float32(w_delta)*dc+np.float32(w_imb)*ic)/np.float32(w_abs+w_trap+w_delta+w_imb))
        score=np.float32(clamp(np.float32(raw*np.float32(sensitivity)),-1.,1.))
        at_high=True;at_low=True;prior_vol=0.;count_prior=0
        for j in range(max(0,b-int(lookback)),b):
            if high[j]>high[b]+tolerance: at_high=False
            if low[j]<low[b]-tolerance: at_low=False
            prior_vol += bar_volume[j];count_prior+=1
        if require_extreme:
            if score<0 and not at_high: score=np.float32(0.)
            if score>0 and not at_low: score=np.float32(0.)
        if volume_weight and count_prior and prior_vol>0:
            factor=np.float32(clamp(total/(prior_vol/count_prior),.25,2.))
            score=np.float32(clamp(np.float32(score*factor),-1.,1.))
        result[b]=score
    return result,metrics


@njit(cache=True)
def block_extrema(price, block=256):
    size=(len(price)+block-1)//block
    lows=np.empty(size,np.int32);highs=np.empty(size,np.int32)
    for i in range(size):
        lo=price[i*block];hi=lo
        for j in range(i*block,min((i+1)*block,len(price))):
            lo=min(lo,price[j]);hi=max(hi,price[j])
        lows[i]=lo;highs[i]=hi
    return lows,highs


@njit(cache=True)
def first_hit(price,start,end,lower,upper,block_low,block_high,block=256):
    i=start
    while i<=end:
        if i%block==0 and i+block-1<=end and block_low[i//block]>lower and block_high[i//block]<upper:
            i+=block
            continue
        if price[i]<=lower: return i,-1
        if price[i]>=upper: return i,1
        i+=1
    return end,0


@njit(cache=True)
def simulate(price,times,block_low,block_high,entry,ends,valid,signal,threshold,sl,tp,
             entry_slip,stop_slip,exit_slip,target_through,tick_value,commission,level_dist,level_limit):
    n=len(signal);pnls=np.zeros(n);exit_index=np.full(n,-1,np.int64);sides=np.zeros(n,np.int8)
    previous_time=-1
    for b in range(n):
        if not valid[b] or abs(signal[b])<threshold or signal[b]==0: continue
        if level_limit>0 and level_dist[b]>level_limit: continue
        st,en=entry[b],ends[b]
        if times[st]<=previous_time: continue
        side=1 if signal[b]>0 else -1
        fill=price[st]+side*entry_slip
        lower=fill-sl if side>0 else fill-tp-target_through
        upper=fill+tp+target_through if side>0 else fill+sl
        ex,hit=first_hit(price,st+1,en,lower,upper,block_low,block_high)
        if hit==0:
            ticks=side*(price[ex]-fill)-exit_slip
        elif hit==side:
            ticks=tp
        else:
            ticks=side*(price[ex]-fill)-stop_slip
        pnls[b]=ticks*tick_value-commission;exit_index[b]=ex;sides[b]=side
        previous_time=times[ex]
    return pnls,exit_index,sides
