"""Example local plugin. Import into the dashboard; never reads future bars."""
import numpy as np

METADATA={
    'name':'Momentum personalizzato',
    'params':{
        'period':{'default':10,'integer':True,'min':1,'label':'Periodo'},
        'threshold':{'default':2.0,'min':0,'label':'Movimento minimo (punti)'}
    }
}


def compute(data,params):
    close=data['close'] # Prices in points; completed bars only.
    period=int(params['period']);threshold=float(params['threshold'])
    result=np.zeros(len(close))
    if len(close)>period:
        change=close[period:]-close[:-period]
        result[period:]=np.where(change>threshold,1.,np.where(change<-threshold,-1.,0.))
    return result
