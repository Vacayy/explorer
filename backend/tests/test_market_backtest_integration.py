"""Backtest boundaries, durable experiments and actual isolated replay."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import test_market_analysis_data as fixtures
from models.market_backtest import BacktestRequest, BacktestSpec
from pipeline.market_analysis.backtest_data import calculate_snapshot
from pipeline.market_analysis.backtest_runner import BacktestService, validate_result
from pipeline.market_analysis.backtest_verification import load_validation_input
from pipeline.market_analysis.store import Conflict


class BacktestBoundaryTests(unittest.TestCase):
    setUp = fixtures.MarketDataTests.setUp
    tearDown = fixtures.MarketDataTests.tearDown
    connect = fixtures.MarketDataTests.connect
    insert = fixtures.MarketDataTests.insert

    def prepare(self):
        from pipeline.market_analysis.snapshot import export_snapshot
        for code in ('000001', '000002'):
            rows = fixtures.prices(code=code, count=550)
            altered = []
            for i, source in enumerate(rows):
                row = list(source)
                close = 100 + i * (.2 if code == '000001' else .1)
                row[2:7] = [close-.2, close+.1, close-.5, close, 10000]
                altered.append(tuple(row))
            self.insert(altered, code)
        analysis_root = self.root / 'analysis'
        parent = analysis_root / 'snapshots'
        parent.mkdir(parents=True)
        folder = parent / uuid.uuid4().hex
        manifest = export_snapshot(self.source, folder)
        dates = manifest['calendar']['dates']
        spec = BacktestSpec(start_date=dates[-100], split_date=dates[-35], end_date=dates[-1],
                            max_positions=2).model_dump(mode='json')
        service = BacktestService(self.root / 'backtests', analysis_root=analysis_root,
                                  source_db=self.source)
        # Tests explicitly call process, rather than racing a background worker.
        service.start = lambda: None
        return folder, spec, service

    def test_strict_dates_numbers_and_no_source_path_input(self):
        for field, value in [('initial_cash', True), ('max_positions', False),
                             ('buy_cost_bps', float('nan')), ('sell_cost_bps', -1),
                             ('rebalance_every', 1), ('markets', ['KOSPI', 'KOSPI']),
                             ('start_date', '20260203'), ('end_date', '2025-01-01'),
                             ('end_date', '2030-01-01')]:
            with self.subTest(field=field), self.assertRaises(ValidationError):
                BacktestSpec(**{field: value})
        for key in ('source_db', 'code', 'snapshot_path', 'sql'):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                BacktestRequest(**{key: '/tmp/anything'})

    def test_snapshot_loader_and_ledger_validation_are_read_only(self):
        folder, spec, _ = self.prepare()
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        inputs = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
        result = calculate_snapshot(folder, spec)
        validate_result(result, spec)
        self.assertEqual([s['universe']['eligible'] for s in result['segments']], [2, 2])
        self.assertTrue(result['warnings'])
        self.assertEqual(before, hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(inputs, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()})
        wrong = copy.deepcopy(result)
        wrong['segments'][0]['strategies'][0]['trades'][0]['cash_after'] += 100
        with self.assertRaisesRegex(ValueError, '현금'):
            validate_result(wrong, spec)
        with self.assertRaisesRegex(ValueError, '종료일'):
            calculate_snapshot(folder, {**spec, 'end_date': '2099-12-31'})

    def test_submission_idempotency_busy_cancel_and_failure_history(self):
        _, spec, service = self.prepare()
        request = {'spec': spec, 'request_key': 'same-request-key'}
        first = service.create(request)
        self.assertEqual(service.create(request)['id'], first['id'])
        with self.assertRaises(Conflict):
            service.create({'spec': {**spec, 'max_positions': 3}, 'request_key': 'same-request-key'})
        with self.assertRaises(Conflict):
            service.create({'spec': spec})
        self.assertEqual(service.cancel(first['id'])['status'], 'cancelled')
        second = service.create({'spec': spec})
        self.assertNotEqual(second['id'], first['id'])
        self.assertTrue((service.store.run_dir(first['id']) / 'request.json').is_file())
        self.assertEqual(len(service.list()['items']), 2)

    def test_independent_price_and_holdings_replay_rejects_impossible_results(self):
        folder, spec, _ = self.prepare()
        result = calculate_snapshot(folder, spec)
        prices, calendar = load_validation_input(folder, spec, result)
        validate_result(result, spec, prices, calendar)
        for variant in ('negative_quantity', 'wrong_open', 'fake_ending_nav', 'wrong_final_quantity', 'outside_signal'):
            wrong = copy.deepcopy(result)
            strategy = wrong['segments'][0]['strategies'][0]
            if variant == 'negative_quantity':
                strategy['trades'][0]['quantity'] *= -1
                strategy['trades'][0]['notional'] *= -1
                strategy['trades'][0]['cost'] *= -1
            elif variant == 'wrong_open':
                strategy['trades'][0]['price'] *= 2
            elif variant == 'fake_ending_nav':
                strategy['metrics']['ending_nav'] = 777
            elif variant == 'wrong_final_quantity':
                strategy['holdings'][0]['quantity'] *= 2
            else:
                strategy['trades'][0]['signal_date'] = '2020-01-01'
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                validate_result(wrong, spec, prices, calendar)

    def test_post_freeze_manifest_change_rejected_even_when_replays_agree(self):
        folder, spec, service = self.prepare()
        from pipeline.market_analysis.runtime import Result
        class FixedTestSandbox:
            def __init__(self, control, workspace, read_dirs):
                self.workspace = workspace
            def run(self, code, **kwargs):
                # Known test helper only. Never evaluate/import the passed code.
                result = calculate_snapshot(folder, spec)
                (self.workspace / 'result.json').write_text(json.dumps(result))
                return Result(0, '', '')
        service.sandbox_factory = FixedTestSandbox
        service.preflight = lambda: {}
        original_artifact = service._artifact
        def change_after_freeze(run_id, name, data, label):
            original_artifact(run_id, name, data, label)
            if name == 'experiment.json':
                path = folder / 'manifest.json'
                path.chmod(0o644)
                path.write_text(path.read_text() + '\n')
        service._artifact = change_after_freeze
        state = service.create({'spec': spec})
        service.process(state['id'])
        after = service.get(state['id'])
        self.assertEqual(after['status'], 'failed')
        self.assertIn('실행 도중 변경', after['error'])
        self.assertIsNone(after['result'])
        self.assertEqual(after['artifacts'][0]['name'], 'experiment.json')

    def test_recovery_preserves_original_spec_and_does_not_restart(self):
        _, spec, service = self.prepare()
        state = service.create({'spec': spec})
        service._update(state['id'], status='running', stage='calculating')
        service.recover()
        current = service.get(state['id'])
        self.assertEqual(current['status'], 'interrupted')
        self.assertEqual(current['spec'], spec)
        self.assertIsNone(current['result'])

    def test_tampered_manifest_fails_before_computation_and_keeps_request(self):
        folder, spec, service = self.prepare()
        state = service.create({'spec': spec})
        manifest = folder / 'manifest.json'
        manifest.chmod(0o644)
        manifest.write_text(manifest.read_text() + '\n')
        service.process(state['id'])
        current = service.get(state['id'])
        self.assertEqual(current['status'], 'failed')
        self.assertIn('명세가 변경', current['error'])
        self.assertTrue((service.store.run_dir(state['id']) / 'request.json').is_file())

    @unittest.skipUnless(sys.platform == 'darwin', 'Real macOS isolation integration')
    def test_actual_sandbox_replay_artifacts_and_original_database_unchanged(self):
        folder, spec, service = self.prepare()
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        state = service.create({'spec': spec})
        service.process(state['id'])
        current = service.get(state['id'])
        self.assertEqual(current['status'], 'partial', current['error'])
        self.assertEqual(current['stage'], 'completed')
        self.assertEqual(current['result']['provenance']['verification'],
                         'isolated_replay_and_ledger_checks_passed')
        self.assertEqual(len(current['artifacts']), 5)
        experiment_meta, experiment_bytes = service.artifact(state['id'], 'experiment.json')
        experiment = json.loads(experiment_bytes)
        self.assertEqual(experiment['snapshot_id'], folder.name)
        self.assertEqual(experiment['spec'], spec)
        self.assertEqual(experiment_meta['sha256'], hashlib.sha256(experiment_bytes).hexdigest())
        self.assertNotIn(str(self.source), experiment_bytes.decode())
        self.assertEqual(before, hashlib.sha256(self.source.read_bytes()).hexdigest())
        result_meta, data = service.artifact(state['id'], 'result.json')
        self.assertEqual(json.loads(data), current['result'])
        path = service.store.run_dir(state['id']) / 'artifacts' / 'result.json'
        path.write_bytes(data + b' ')
        with self.assertRaisesRegex(ValueError, '해시'):
            service.artifact(state['id'], 'result.json')
        with self.assertRaises(FileNotFoundError):
            service.artifact(state['id'], '../state.json')

    def test_api_routes_payload_and_cancelled_run_reload(self):
        _, spec, service = self.prepare()
        from routers import backtests
        app = FastAPI()
        app.include_router(backtests.router, prefix='/api/analysis')
        with patch.object(backtests, 'service', return_value=service), TestClient(app) as client:
            config = client.get('/api/analysis/backtests/config').json()
            self.assertEqual(len(config['strategies']), 7)
            self.assertTrue(config['data']['snapshot_available'])
            self.assertEqual(config['limits']['buy_cost_bps'], {'min': 0, 'max': 1000})
            rejected = client.post('/api/analysis/backtests', json={'spec': spec, 'code': 'DROP TABLE'})
            self.assertEqual(rejected.status_code, 422)
            made = client.post('/api/analysis/backtests', json={'spec': spec})
            self.assertEqual(made.status_code, 200)
            run_id = made.json()['id']
            self.assertEqual(client.get('/api/analysis/backtests').json()['items'][0]['id'], run_id)
            self.assertEqual(client.post(f'/api/analysis/backtests/{run_id}/cancel').json()['status'], 'cancelled')
            self.assertEqual(client.get(f'/api/analysis/backtests/{run_id}').json()['spec'], spec)
            self.assertEqual(client.get('/api/analysis/backtests/not-an-id').status_code, 400)
            self.assertEqual(client.get(f'/api/analysis/backtests/{run_id}/artifacts/unknown.csv').status_code, 404)


if __name__ == '__main__':
    unittest.main()
