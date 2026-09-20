"""Durable fixed-code experiments, isolated from the source database and CodeAct."""
from __future__ import annotations

import csv
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import threading
import time
import uuid

from models.market_backtest import BacktestRequest, BacktestSpec
from .store import (ID, TERMINAL, Conflict, RunStore, StoreError, atomic_write,
                    encode, now, read_bytes, read_json, secure_directory)
from .backtest_verification import load_validation_input, validate_result

PROJECT = Path(__file__).resolve().parents[3]
DEFAULT_ROOT = PROJECT / 'logs/market-backtests'
ANALYSIS_ROOT = PROJECT / 'logs/market-analysis'
SKILLS = ('analytics.py', 'strategies.py', 'strategy_screen.py',
          'backtest_engine.py', 'backtest_data.py')
ACTIVE = {'queued', 'preparing', 'running'}


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _csv_bytes(rows: list[dict], fields: list[str]) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        # Numeric negative returns remain numeric; untrusted text cannot become
        # spreadsheet formulas when someone opens an exported file.
        safe = {key: ("'" + val if isinstance(val, str) and
                      val.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else val)
                for key, val in row.items()}
        writer.writerow(safe)
    return output.getvalue().encode('utf-8-sig')


class BacktestService:
    def __init__(self, root: Path = DEFAULT_ROOT, *, analysis_root: Path = ANALYSIS_ROOT,
                 source_db: Path | None = None, sandbox_factory=None, preflight=None):
        self.store = RunStore(root)
        self.analysis_root = Path(analysis_root)
        self.source_db = source_db
        self.sandbox_factory = sandbox_factory
        self.preflight = preflight
        self._thread = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._start_lock = threading.Lock()
        self._checked = False

    def snapshots(self) -> list[tuple[str, Path, dict, str]]:
        found = []
        for kind, root in (('analysis', self.analysis_root), ('backtest', self.store.root)):
            parent = root / 'snapshots'
            if not parent.is_dir() or parent.is_symlink():
                continue
            for folder in parent.iterdir():
                if not ID.fullmatch(folder.name) or folder.is_symlink() or not folder.is_dir():
                    continue
                try:
                    raw = read_bytes(folder, 'manifest.json')
                    manifest = json.loads(raw)
                    if manifest.get('schema_version') == 1 and manifest.get('snapshot_id') == folder.name:
                        found.append((kind, folder, manifest, _hash(raw)))
                except (OSError, ValueError):
                    continue
        return sorted(found, key=lambda x: (x[2]['as_of'], x[2].get('exported_at', ''), x[1].name), reverse=True)

    def config(self) -> dict:
        from .backtest_engine import ENGINE_VERSION, STRATEGIES
        latest = next(iter(self.snapshots()), None)
        defaults = BacktestSpec().model_dump(mode='json')
        if latest and latest[2]['as_of'] != defaults['end_date']:
            dates = latest[2]['calendar']['dates']
            if len(dates) >= 4:
                defaults.update(start_date=dates[max(0, len(dates)-154)],
                                split_date=dates[max(2, len(dates)-57)], end_date=dates[-1])
        schema = BacktestSpec.model_json_schema()['properties']
        limits = {k: {'min': v['minimum'], 'max': v['maximum']} for k, v in schema.items()
                  if 'minimum' in v and 'maximum' in v}
        return {'version': ENGINE_VERSION, 'defaults': defaults, 'strategies': STRATEGIES, 'limits': limits,
                'data': {'snapshot_available': latest is not None,
                         'as_of': latest[2]['as_of'] if latest else None},
                'warnings': ['과거 상장·상장폐지 이력이 없어 생존 편향을 제거하지 못한 연구용 비교입니다.',
                             '과거 시총 결측이 많아 기본 시총 필터는 0입니다. 없는 시총을 현재 값으로 채우지 않습니다.']}

    def create(self, request: dict) -> dict:
        request = BacktestRequest.model_validate(request).model_dump(mode='json')
        spec = request['spec']
        key = _hash((request.get('request_key') or uuid.uuid4().hex).encode())
        with self.store.lock('submission'):
            index = self.store.root / 'control' / f'request-{key}.json'
            if index.exists():
                previous = read_json(index.parent, index.name)
                if previous['spec'] != spec:
                    raise Conflict('같은 요청 키로 다른 비교 조건을 보낼 수 없습니다.')
                return self.get(previous['id'])
            if any(s['status'] in ACTIVE for s in self.store.list(10000)):
                raise Conflict('이미 실행 중인 전략 비교가 있습니다. 완료하거나 취소한 뒤 실행해주세요.')
            latest = next((s for s in self.snapshots() if s[2]['as_of'] >= spec['end_date']), None)
            run_id = uuid.uuid4().hex
            directory = self.store.run_dir(run_id)
            secure_directory(directory / 'events')
            state = {'id': run_id, 'status': 'queued', 'stage': 'queued', 'spec': spec,
                     'created_at': now(), 'updated_at': now(), 'result': None, 'error': None,
                     'artifacts': [], '_cancel': False,
                     '_snapshot_kind': latest[0] if latest else None,
                     '_snapshot_id': latest[1].name if latest else None,
                     '_manifest_hash': latest[3] if latest else None}
            # Preserve failed attempts too; do not wait for successful output.
            atomic_write(directory / 'request.json', encode({'created_at': state['created_at'], 'spec': spec}))
            self.store._save(state)
            atomic_write(index, encode({'id': run_id, 'spec': spec}))
        self.start()
        self._wake.set()
        return self.store.public(state)

    def get(self, run_id: str) -> dict:
        return self.store.public(self.store.read(run_id))

    def list(self, limit=30) -> dict:
        return {'items': [{k: v for k, v in self.store.public(s).items() if k != 'result'}
                          for s in self.store.list(limit)]}

    def cancel(self, run_id: str) -> dict:
        def apply(s):
            if s['status'] in ACTIVE:
                s['_cancel'] = True
                s['stage'] = 'cancelling'
                if s['status'] == 'queued':
                    s.update(status='cancelled', stage='cancelled')
        state = self.store.mutate(run_id, apply)
        self._wake.set()
        return self.store.public(state)

    def start(self):
        with self._start_lock:
            if not self._thread or not self._thread.is_alive():
                self._stop.clear()
                self._thread = threading.Thread(target=self._worker, name='market-backtest', daemon=True)
                self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=12)

    def _worker(self):
        fd = os.open(self.store.root / 'control/worker.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            while not self._stop.is_set():
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    self._stop.wait(.5)
            else:
                return
            self.recover()
            while not self._stop.is_set():
                queued = [s for s in self.store.list(10000) if s['status'] == 'queued']
                if queued:
                    self.process(queued[-1]['id'])
                else:
                    self._wake.wait(.5)
                    self._wake.clear()
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def recover(self):
        for state in self.store.list(10000):
            if state['status'] in {'preparing', 'running'}:
                self._update(state['id'], status='interrupted', stage='interrupted',
                             error='서버 실행이 중단되었습니다. 기존 실험을 보존했으며 새 실행으로 다시 비교할 수 있습니다.')

    def _update(self, run_id, **changes):
        return self.store.mutate(run_id, lambda s: s.update(changes))

    def _cancelled(self, run_id):
        return self._stop.is_set() or self.store.read(run_id).get('_cancel', False)

    def _snapshot(self, run_id: str) -> tuple[Path, dict]:
        state = self.store.read(run_id)
        if state['_snapshot_id']:
            root = self.analysis_root if state['_snapshot_kind'] == 'analysis' else self.store.root
            folder = root / 'snapshots' / state['_snapshot_id']
            raw = read_bytes(folder, 'manifest.json')
            if _hash(raw) != state['_manifest_hash']:
                raise ValueError('실험 시작 전 입력 스냅샷의 명세가 변경되었습니다.')
            return folder, json.loads(raw)
        from .snapshot import export_snapshot
        if self.source_db is None:
            from database import DB_PATH
            source_db = Path(DB_PATH)
        else:
            source_db = self.source_db
        folder = self.store.root / 'snapshots' / uuid.uuid4().hex
        manifest = export_snapshot(source_db, folder, state['spec']['end_date'],
                                   cancel=lambda: self._cancelled(run_id))
        self._update(run_id, _snapshot_kind='backtest', _snapshot_id=folder.name,
                     _manifest_hash=_hash(read_bytes(folder, 'manifest.json')))
        return folder, manifest

    def _artifact(self, run_id: str, name: str, data: bytes, label: str):
        if name not in {'experiment.json', 'result.json', 'equity.csv', 'trades.csv', 'summary.csv'}:
            raise ValueError('지원하지 않는 산출물입니다.')
        if len(data) > 16 * 1024 * 1024:
            raise ValueError('산출물 크기 제한을 초과했습니다.')
        atomic_write(self.store.run_dir(run_id) / 'artifacts' / name, data)
        item = {'name': name, 'label': label, 'bytes': len(data), 'sha256': _hash(data),
                'media_type': 'application/json' if name.endswith('.json') else 'text/csv; charset=utf-8'}
        self.store.mutate(run_id, lambda s: s['artifacts'].append(item))

    def artifact(self, run_id, name):
        item = next((a for a in self.store.read(run_id)['artifacts'] if a['name'] == name), None)
        if not item:
            raise FileNotFoundError(name)
        data = read_bytes(self.store.run_dir(run_id), 'artifacts/' + item['name'])
        if _hash(data) != item['sha256']:
            raise ValueError('산출물 해시가 변경되었습니다.')
        return item, data

    def process(self, run_id: str):
        started = time.monotonic()
        try:
            state = self.store.read(run_id)
            if state['status'] != 'queued' or self._cancelled(run_id):
                return
            self._update(run_id, status='preparing', stage='snapshot')
            folder, manifest = self._snapshot(run_id)
            if manifest['as_of'] < state['spec']['end_date']:
                raise ValueError(f"입력 자료는 {manifest['as_of']}까지입니다. 종료일을 줄여주세요.")
            from .runtime import Sandbox, preflight
            if not self._checked:
                (self.preflight or preflight)()
                self._checked = True
            control = secure_directory(self.store.root / 'control' / run_id)
            skill_dir = secure_directory(control / 'skills')
            hashes = {}
            for name in SKILLS:
                source = read_bytes(Path(__file__).parent, name)
                hashes[name] = _hash(source)
                atomic_write(skill_dir / name, source)
                (skill_dir / name).chmod(0o444)
            experiment = {'frozen_at': now(), 'request_created_at': state['created_at'], 'spec': state['spec'],
                          'code_hashes': hashes, 'snapshot_id': manifest['snapshot_id'],
                          'host_code_hashes': {name: _hash(read_bytes(Path(__file__).parent, name))
                              for name in ('backtest_runner.py', 'backtest_verification.py', 'runtime.py')},
                          'snapshot_files': manifest['files'], 'snapshot_as_of': manifest['as_of'],
                          'manifest_sha256': _hash(read_bytes(folder, 'manifest.json')),
                          'scope': 'fixed-seven-strategies-no-parameter-search',
                          'protocol': 'decision-close-quantity-next-open-fill-v1'}
            self._artifact(run_id, 'experiment.json', encode(experiment), '사전 고정 실험 조건')
            if self._cancelled(run_id):
                raise InterruptedError()
            # The only executed code is this fixed launcher and pinned modules.
            code = ('import sys,json\n'
                    f'sys.path.insert(0, {str(skill_dir)!r})\n'
                    'from backtest_data import calculate_snapshot\n'
                    f'spec = json.loads({json.dumps(state["spec"])!r})\n'
                    f'result = calculate_snapshot({str(folder)!r}, spec)\n'
                    'with open("result.json", "w", encoding="utf-8") as out:\n'
                    '    json.dump(result, out, ensure_ascii=False, allow_nan=False, separators=(",", ":"))\n'
                    'print("backtest computation completed")\n')
            expected = None
            for suffix, stage in (('', 'calculating'), ('-verify', 'verifying')):
                self._update(run_id, status='running', stage=stage)
                workspace = secure_directory(self.store.root / 'workspaces' / (run_id + suffix))
                sandbox = (self.sandbox_factory or Sandbox)(control, workspace, [folder, skill_dir])
                execution = sandbox.run(code, timeout=600, cancel=lambda: self._cancelled(run_id))
                atomic_write(control / f'execution{suffix}.json', encode({
                    'exit_code': execution.exit_code, 'stdout': execution.stdout,
                    'stderr': execution.stderr, 'timed_out': execution.timed_out,
                    'cancelled': execution.cancelled}))
                if execution.cancelled or self._cancelled(run_id):
                    raise InterruptedError()
                if execution.exit_code:
                    raise ValueError('격리된 백테스트 계산이 실패했습니다: ' + execution.stderr[-2000:])
                current = read_json(workspace, 'result.json')
                validate_result(current, state['spec'])
                if expected is not None and current != expected:
                    raise ValueError('같은 입력의 별도 프로세스 재계산 결과가 일치하지 않습니다.')
                expected = current
            if self._cancelled(run_id):
                raise InterruptedError()
            result = expected
            self._update(run_id, stage='checking_ledger')
            # The manifest and its declared Parquet hashes must still be the
            # ones frozen before any execution, even if both replays agree.
            raw_manifest = read_bytes(folder, 'manifest.json')
            if _hash(raw_manifest) != experiment['manifest_sha256']:
                raise ValueError('고정된 스냅샷 명세가 실행 도중 변경되었습니다.')
            for name in ('daily.parquet', 'universe.parquet'):
                details = experiment['snapshot_files'][name]
                digest = hashlib.sha256()
                with (folder / name).open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024*1024), b''):
                        digest.update(chunk)
                if digest.hexdigest() != details['sha256']:
                    raise ValueError('고정된 스냅샷 가격이 실행 도중 변경되었습니다.')
            if result['snapshot'] != {k: manifest[k] for k in ('snapshot_id', 'as_of', 'rows', 'symbols',
                                                             'price_adjustment', 'files')}:
                raise ValueError('결과의 데이터 출처가 사전 고정 명세와 다릅니다.')
            verification_prices, calendar = load_validation_input(folder, state['spec'], result)
            validate_result(result, state['spec'], verification_prices, calendar)
            del verification_prices
            result['provenance'] = {**experiment, 'verification': 'isolated_replay_and_ledger_checks_passed'}
            self._artifact(run_id, 'result.json', encode(result), '전체 결과 JSON')
            equity, trades, summary = [], [], []
            for segment in result['segments']:
                for strategy in segment['strategies']:
                    prefix = {'segment': segment['id'], 'strategy': strategy['id']}
                    equity.extend({**prefix, **row} for row in strategy['equity'])
                    trades.extend({**prefix, **row} for row in strategy['trades'])
                    summary.append({**prefix, **strategy['metrics']})
            self._artifact(run_id, 'equity.csv', _csv_bytes(equity, ['segment', 'strategy', 'date', 'nav',
                'cash', 'exposure_pct', 'drawdown_pct', 'positions']), '일별 자산·현금 CSV')
            self._artifact(run_id, 'trades.csv', _csv_bytes(trades, ['segment', 'strategy', 'date',
                'signal_date', 'code', 'side', 'quantity', 'price', 'notional', 'cost', 'cash_after']), '전체 체결 원장 CSV')
            self._artifact(run_id, 'summary.csv', _csv_bytes(summary, ['segment', 'strategy',
                'total_return_pct', 'max_drawdown_pct', 'exposure_avg_pct', 'cost_total',
                'trades_count', 'ending_nav', 'unfilled_orders', 'stale_valuation_days']), '전략 비교 요약 CSV')
            def finish(s):
                if s.get('_cancel') or self._stop.is_set():
                    raise InterruptedError()
                s.update(status='partial', stage='completed', result=result, error=None,
                         elapsed_seconds=round(time.monotonic()-started, 3))
            self.store.mutate(run_id, finish)
        except InterruptedError:
            status = 'interrupted' if self._stop.is_set() else 'cancelled'
            self._update(run_id, status=status, stage=status, error=None)
        except Exception as exc:
            if self._cancelled(run_id):
                status = 'interrupted' if self._stop.is_set() else 'cancelled'
                self._update(run_id, status=status, stage=status, error=None)
            else:
                self._update(run_id, status='failed', stage='failed', error=str(exc),
                             elapsed_seconds=round(time.monotonic()-started, 3))
