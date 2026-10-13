import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from research_checkpoint import TrialCheckpoint


class CheckpointTests(unittest.TestCase):
    def test_completed_trial_recovered_after_interrupted_tail(self):
        with tempfile.TemporaryDirectory() as td:
            c=TrialCheckpoint(td,{'model':'a','data':'b'});row=dict(stage=1,trial=0,params='{}',objective=5)
            c.append(row);c.close()
            with c.path.open('ab') as f:f.write(b'{"stage":')
            d=TrialCheckpoint(td,{'model':'a','data':'b'})
            self.assertEqual(d.rows[(1,0)],row);d.close()
            self.assertEqual(len(c.path.read_text().splitlines()),1)

    def test_changed_model_or_data_refuses_reuse(self):
        with tempfile.TemporaryDirectory() as td:
            c=TrialCheckpoint(td,{'model':'a','data':'b'});c.close()
            with self.assertRaisesRegex(ValueError,'incompatibile'):TrialCheckpoint(td,{'model':'new','data':'b'})

    def test_duplicate_trial_cannot_be_appended(self):
        with tempfile.TemporaryDirectory() as td:
            c=TrialCheckpoint(td,{'model':'a'});row=dict(stage=1,trial=0)
            c.append(row)
            with self.assertRaises(ValueError):c.append(row)
            c.close()
