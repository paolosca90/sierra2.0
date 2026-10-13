"""Causal tick-by-tick brackets, trailing stop and break-even for any signals."""
import numpy as np
from numba import njit
from footprint_kernel import first_hit


@njit(cache=True)
def managed_simulate(price,times,block_low,block_high,entry,ends,valid,signal,threshold,
                     sl,tp,entry_slip,stop_slip,exit_slip,target_through,tick_value,commission,
                     trailing,trail_trigger,be_trigger,be_offset,quantity,level_dist,level_limit):
    n=len(signal);pnl=np.zeros(n);exit_index=np.full(n,-1,np.int64)
    sides=np.zeros(n,np.int8);reasons=np.zeros(n,np.int8);previous_time=-1
    for b in range(n):
        if not valid[b] or signal[b]==0 or abs(signal[b])<threshold:continue
        if level_limit>0 and level_dist[b]>level_limit:continue
        st,en=entry[b],ends[b]
        if times[st]<=previous_time:continue
        side=1 if signal[b]>0 else -1
        fill=price[st]+side*entry_slip
        stop=-float(sl) if sl>0 else -1e30
        if trailing>0 and trail_trigger<=0:stop=max(stop,-float(trailing))
        target=float(tp)+target_through if tp>0 else 1e30
        peak=0.;why=3;ex=en;ticks=side*(price[en]-fill)-exit_slip
        if trailing<=0 and be_trigger<=0:
            lower=fill+stop if side>0 else fill-target
            upper=fill+target if side>0 else fill-stop
            ex,hit=first_hit(price,st+1,en,lower,upper,block_low,block_high)
            if hit==side:why=2;ticks=float(tp)
            elif hit!=0:why=1;ticks=side*(price[ex]-fill)-stop_slip
            else:ticks=side*(price[ex]-fill)-exit_slip
        else:
            j=st+1
            while j<=en:
                # Skip only blocks with no trigger and no new favorable high:
                # then neither active stop nor future trailing state can change.
                if j%256==0 and j+255<=en:
                    lo=side*(block_low[j//256]-fill) if side>0 else side*(block_high[j//256]-fill)
                    hi=side*(block_high[j//256]-fill) if side>0 else side*(block_low[j//256]-fill)
                    if lo>stop and hi<target and hi<=peak:
                        j+=256;continue
                move=side*(price[j]-fill)
                if move<=stop:
                    ex=j;why=1;ticks=move-stop_slip;break
                if move>=target:
                    ex=j;why=2;ticks=float(tp);break
                # Activate/tighten AFTER checking this print. A new stop never
                # fills on an earlier point in the same price excursion.
                peak=max(peak,move)
                if be_trigger>0 and peak>=be_trigger:stop=max(stop,float(be_offset))
                if trailing>0 and peak>=trail_trigger:stop=max(stop,peak-trailing)
                j+=1
        pnl[b]=(ticks*tick_value-commission)*quantity
        exit_index[b]=ex;sides[b]=side;reasons[b]=why
        previous_time=times[ex]
    return pnl,exit_index,sides,reasons
