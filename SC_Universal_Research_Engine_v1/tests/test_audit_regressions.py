"""Regression evidence for the 2026-10-13 audit; synthetic data only."""
import copy
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'dashboard'))
import app
import indicators
import worker
from bar_schema import validate_bar_seconds
from instruments import instrument_spec
from scid_dataset import execution_arrays, prepare
from trade_audit import trace


def config():
    return dict(instrument='NQ', indicator='to_reversal', method='grid', trials=2,
                parameters={k: [v['default']] for k, v in indicators.BUILTINS['to_reversal']['params'].items()},
                execution={k: [v] for k, v in worker.EXEC_DEFAULTS.items()},
                bar_seconds=60, min_trades=1, horizon=1, seed=42, entry_slip=0,
                stop_slip=0, exit_slip=0, target_through=0, delay_ms=1, commission=0,
                max_gap=90, max_entry_gap=5, level_filter=0, data_folder='synthetic',
                start='2026-01-01', end='2026-01-12', cache='synthetic',
                manifest=[dict(scid='synthetic.scid', trade_from='2026-01-01', trade_to='2026-01-12')])


class TestAuditRegressions(unittest.TestCase):
    def test_api_rejects_bad_time_bars_before_planning_or_launch(self):
        from fastapi.testclient import TestClient
        with TestClient(app.app) as client, patch.object(app, 'plan') as plan, \
                patch.object(app, 'ensure_memory'), patch.object(app.subprocess, 'Popen') as launch:
            for value in [7, 0, True, 60.0, 3601]:
                c = config(); c['bar_seconds'] = value
                response = client.post('/api/jobs', headers={'X-Local-Token': app.TOKEN}, json=c)
                self.assertEqual(response.status_code, 400, response.text)
                self.assertIn('bar_seconds', response.json()['detail'])
            plan.assert_not_called(); launch.assert_not_called()

    def test_reader_and_api_share_duration_rule(self):
        for value in [1, 15, 30, 60, 120, 300, 3600]:
            self.assertEqual(validate_bar_seconds(value), value)
        for value in [7, True, 60.0]:
            with self.assertRaisesRegex(ValueError, '86400'):
                prepare('unused.scid', 'unused', seconds=value)

    def test_api_counts_post_calibration_grid_and_keeps_trade_bars_independent(self):
        c = config(); c['parameters']['sensitivity'] = [1, 2, 4, 6, 8]
        c['execution']['tp'] = [20, 40]; c['calibrate_sensitivity'] = True
        ready = dict(ready=True, manifest=c['manifest'], rolls=[], rollover='synthetic')
        with patch.object(app, 'plan', return_value=ready):
            self.assertEqual(app.validate_config(copy.deepcopy(c))['trials'], 2)
            c['bar_seconds'] = 7; c['trades_per_bar'] = 100
            self.assertEqual(app.validate_config(copy.deepcopy(c))['trades_per_bar'], 100)
            c['calibrate_sensitivity'] = False
            with self.assertRaisesRegex(ValueError, 'almeno 10'):
                app.validate_config(c)

    def test_calibration_summary_journal_and_resume_use_frozen_grid(self):
        days = [f'2026-01-{i:02}' for i in range(1, 13)]
        data = dict(day=np.array(days))
        calls = []

        class SyntheticEngine:
            def __init__(self, data, c, spec):
                self.d = data; self.c = c; self.days = days
                self.good = np.ones(len(days), bool); self.execution_quality = {}

            def run(self, params, selected_days, detail=False):
                calls.append((tuple(selected_days), detail))
                return np.full(len(selected_days), 5.), np.asarray(selected_days), []

        c = config(); c['parameters']['sensitivity'] = [1, 2, 4, 6, 8]
        c['execution']['tp'] = [20, 40]; c['calibrate_sensitivity'] = True
        meta = dict(signature=dict(path='synthetic.scid'), source_sha256='synthetic')
        with tempfile.TemporaryDirectory() as td, ExitStack() as stack:
            job = Path(td); (job / 'config.json').write_text(json.dumps(c), encoding='utf-8')
            stack.enter_context(patch.object(worker, 'initialize_research'))
            stack.enter_context(patch.object(worker, 'ensure_memory'))
            stack.enter_context(patch.object(worker, 'Engine', SyntheticEngine))
            stack.enter_context(patch.object(worker, 'prepare_spec', return_value=(data, meta)))
            stack.enter_context(patch('scid_dataset.calculate', side_effect=lambda d, p:
                (np.full(len(days), {1: .1, 2: .2, 4: .7, 6: .9, 8: 1.}[p['sensitivity']]),)))
            worker.main(job)
            summary = json.loads((job / 'SUMMARY.json').read_text())
            self.assertEqual((summary['total_combinations'], summary['trials_run']), (2, 8))
            self.assertEqual(summary['params']['i:sensitivity'], 4)
            self.assertEqual(summary['evidence_status']['classification'], 'exploratory')
            identity = (job / 'CHECKPOINT_IDENTITY.json').read_bytes()
            frozen = json.loads(identity)['identity']['experiment']['parameters']['sensitivity']
            self.assertEqual(frozen, [4])
            journal = (job / 'TRIAL_CHECKPOINT.jsonl').read_bytes()
            self.assertEqual(len(journal.splitlines()), 8)
            calls.clear()
            worker.main(job)
            self.assertEqual((job / 'CHECKPOINT_IDENTITY.json').read_bytes(), identity)
            self.assertEqual((job / 'TRIAL_CHECKPOINT.jsonl').read_bytes(), journal)
            self.assertTrue(all(detail for _, detail in calls))
            self.assertEqual(len(calls), 4)  # Only WF/holdout; training reused.

    def test_python_import_requires_explicit_trust_and_never_executes_on_import(self):
        source = "METADATA={'name':'Test','params':{}}\nraise RuntimeError('EXECUTED')\ndef compute(d,p): return []\n"
        with tempfile.TemporaryDirectory() as td, patch.object(indicators, 'PLUGINS', Path(td)):
            for trusted in [False, 'true', 1]:
                with self.assertRaisesRegex(ValueError, 'senza sandbox'):
                    indicators.import_source('test.py', source, trusted=trusted)
            self.assertEqual(list(Path(td).iterdir()), [])
            meta = indicators.import_source('test.py', source, trusted=True)
            self.assertTrue(meta['trusted_python'])
            with self.assertRaisesRegex(RuntimeError, 'EXECUTED'):
                indicators.plugin_module(meta['id'])

    def test_plugin_hash_checked_even_after_module_cached(self):
        source = "METADATA={'name':'Test','params':{}}\ndef compute(d,p): return [0]\n"
        with tempfile.TemporaryDirectory() as td, patch.object(indicators, 'PLUGINS', Path(td)):
            meta = indicators.import_source('test.py', source, trusted=True)
            self.assertEqual(indicators.plugin_module(meta['id']).compute({}, {}), [0])
            Path(td, meta['id'] + '.py').write_text(source.replace('[0]', '[1]'), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'modificato'):
                indicators.plugin_module(meta['id'])

    def test_legacy_untrusted_plugin_cannot_execute(self):
        source = "METADATA={'name':'Test','params':{}}\ndef compute(d,p): return [0]\n"
        with tempfile.TemporaryDirectory() as td, patch.object(indicators, 'PLUGINS', Path(td)):
            meta = indicators.import_source('test.py', source, trusted=True)
            del meta['trusted_python']
            Path(td, meta['id'] + '.json').write_text(json.dumps(meta), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'reimportare'):
                indicators.plugin_module(meta['id'])

    def test_api_requires_plugin_trust(self):
        from fastapi.testclient import TestClient
        source = "METADATA={'name':'Test','params':{}}\ndef compute(d,p): return [0]\n"
        with tempfile.TemporaryDirectory() as td, patch.object(indicators, 'PLUGINS', Path(td)), TestClient(app.app) as client:
            payload = dict(filename='test.py', source=source)
            self.assertEqual(client.post('/api/import', headers={'X-Local-Token': app.TOKEN}, json=payload).status_code, 400)
            payload['trusted_python'] = True
            self.assertEqual(client.post('/api/import', headers={'X-Local-Token': app.TOKEN}, json=payload).status_code, 200)

    def test_full_horizon_gap_excludes_trade_even_if_target_precedes_gap(self):
        times = np.arange(2000, dtype=np.int64) * 1_000_000
        times[1600:] += 120_000_000
        starts = np.arange(600) * 3
        data = dict(times=times, starts=starts, bar_time=times[starts], bar_close_time=times[starts+2],
                    bar_complete=np.ones(600, bool), day_end=np.full(600, 86400_000_000, np.int64))
        quality = {}
        entry, end, good = execution_arrays(data, horizon=5, diagnostics=quality)
        self.assertFalse(good[510])
        # The target is observable before the recording gap, yet the default excludes it.
        price = np.full(len(times), 100); price[entry[510]+1:] = 110
        c = config(); ep = {k: v[0] for k, v in c['execution'].items()}; ep['tp'] = 10
        result = trace(price, times, entry[510], end[510], 1, ep, c, None)
        self.assertEqual(result['reason'], 'TARGET')
        self.assertLess(result['exit_index'], 1600)
        self.assertGreater(quality['failures_nonexclusive']['gap_before_horizon'], 0)
        self.assertEqual(sum(quality['excluded_first_reason'].values()) + quality['eligible_bars'], 600)
        np.testing.assert_array_equal(good, execution_arrays(data, horizon=5)[2])

    def test_contract_economics_and_unknown_symbols_fail_closed(self):
        c = config(); ep = {k: v[0] for k, v in c['execution'].items()}
        ep.update(tp=0, quantity=2)
        for symbol, tick_value in [('NQ', 5.), ('ES', 12.5)]:
            self.assertEqual(instrument_spec(symbol).tick_size, .25)
            c.update(instrument=symbol, commission=3)
            result = trace(np.array([100, 102]), np.array([0, 1]), 0, 1, 1, ep, c, None)
            self.assertEqual(result['net_usd'], (2*tick_value-3)*2)
        for symbol in ['MNQ', 'MES', 'TY', None]:
            with self.assertRaisesRegex(ValueError, 'non supportato'):
                instrument_spec(symbol)
            c['instrument'] = symbol
            with self.assertRaisesRegex(ValueError, 'non supportato'):
                app.validate_config(copy.deepcopy(c))

    def test_worker_engine_prices_nq_es_and_reconciles_scalar_details(self):
        from footprint_kernel import block_extrema
        times = np.arange(2000, dtype=np.int64)*1_000_000
        starts = np.arange(600)*3
        prices = np.full(2000, 100, np.int32); prices[1534:] = 110
        low, high = block_extrema(prices)
        data = dict(times=times, starts=starts, bar_time=times[starts], bar_close_time=times[starts+2],
                    bar_complete=np.ones(600, bool), day_end=np.full(600, 86400_000_000, np.int64),
                    day=np.full(600, '2026-01-01'), price=prices, block_low=low, block_high=high)
        signals = np.zeros(600); signals[510] = 1.
        for symbol, expected in [('NQ', 94.), ('ES', 244.)]:
            c = config(); c.update(instrument=symbol, indicator='ema_cross', commission=3)
            engine = worker.Engine(data, c, c['manifest'][0])
            params = {'e:'+k: v[0] for k, v in c['execution'].items()}
            params.update({'e:tp': 10, 'e:quantity': 2})
            with patch.object(engine, 'signals', return_value=signals):
                values, _, trades = engine.run(params, ['2026-01-01'], detail=True)
            np.testing.assert_array_equal(values, [expected])
            self.assertEqual(trades[0]['exit_reason'], 'TARGET')
            self.assertTrue(trades[0]['tick_audit_verified'])
            self.assertEqual((trades[0]['entry_fill'], trades[0]['exit_fill']), (25., 27.5))


if __name__ == '__main__':
    unittest.main()
