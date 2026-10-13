import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from grid_equivalence import strategy_key,training_result
from footprint_kernel import scores,vector
from sample_quality import training_objective


class TestGridEquivalence(unittest.TestCase):
    def test_unused_detector_axes_have_identical_original_scores(self):
        rng=np.random.default_rng(7701);n=300
        low=rng.integers(100,110,n);high=low+2;close=low+rng.integers(0,3,n);offsets=np.arange(n+1)*3
        bid=rng.integers(0,1000,n*3);ask=rng.integers(0,1000,n*3);volume=bid+ask
        known={}
        for weights in [dict(w_abs=0,w_trap=1,w_delta=0,w_imb=0),dict(w_abs=0,w_trap=0,w_delta=1,w_imb=1)]:
            for aggressive in [5,200,5000]:
                for imbalance in [2,4]:
                    for gate in [0,1]:
                        params=dict(weights,min_agg=aggressive,imbalance=imbalance,require_extreme=gate)
                        key=strategy_key({'i:'+k:v for k,v in params.items()}|{'e:session_mode':2,'e:sl':56})
                        output=scores(low,high,close,offsets,bid,ask,volume,vector(params))[0]
                        if key in known:np.testing.assert_array_equal(output,known[key])
                        else:known[key]=output
        active={'i:w_abs':4,'i:w_imb':1,'i:min_agg':5}
        self.assertNotEqual(strategy_key(active),strategy_key(active|{'i:min_agg':200}))
        self.assertNotEqual(strategy_key(active, 'plugin_test'),strategy_key(active|{'i:min_agg':200},'plugin_test'))

    def test_compact_result_preserves_objective_and_sample_screen(self):
        result=dict(n=200,net=500,maxdd=100,sample=dict(active_days=30,block_trades=[60,60,80]),daily={'unused':100},trades=[{'unused':1}])
        config=dict(min_trades=100,min_active_days=20,min_trades_per_training_block=20)
        self.assertEqual(training_objective(result,config),training_objective(training_result(result),config))
        self.assertNotIn('daily',training_result(result))
        key={'i:w_abs':0,'i:w_imb':0,'i:min_agg':5,'e:session_mode':0}
        self.assertNotEqual(strategy_key(key),strategy_key(key|{'e:session_mode':1}))


if __name__=='__main__':unittest.main()
