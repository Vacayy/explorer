"""Runtime-path contract using ONLY fixture-authored code and disposable data.

This fake executor is not a sandbox and must never be selected by production.
"""
from pathlib import Path
import subprocess
import shutil
import sys
import unittest
from test_market_analysis_harness import HarnessTests, FixtureModel
from models.market_analysis import AnalysisSpec, RunRequest
from pipeline.market_analysis.runtime import Result


class FixtureMappedRuntime:
    calls = []

    @staticmethod
    def input_paths(paths):
        return [p.parent / ('mapped-' + p.name) for p in paths]

    def __init__(self, *, control_dir, workdir, read_dirs):
        self.workdir = workdir
        workdir.mkdir(parents=True, exist_ok=True)
        self.paths = self.input_paths(read_dirs)
        for alias, source in zip(self.paths, read_dirs):
            if not alias.exists():
                shutil.copytree(source, alias)

    def run(self, code, timeout=60, cancel=None):
        if not all(str(path) in code for path in self.paths):
            raise AssertionError('Caller bypassed runtime-visible input paths')
        self.calls.append(self.workdir)
        p = subprocess.run([sys.executable, '-c', code], cwd=self.workdir,
                           capture_output=True, text=True, timeout=timeout)
        return Result(p.returncode, p.stdout, p.stderr)


class MappedPathsTests(unittest.TestCase):
    create = HarnessTests.create
    tearDown = HarnessTests.tearDown

    def setUp(self):
        HarnessTests.setUp(self)
        FixtureMappedRuntime.calls = []
        self.service.sandbox_factory = FixtureMappedRuntime

    def test_model_and_independent_verifier_use_mapped_paths(self):
        HarnessTests.test_complete_real_sandbox_and_independent_verification(self)
        self.assertEqual(len(FixtureMappedRuntime.calls), 2)
        self.assertNotEqual(*FixtureMappedRuntime.calls)

    def test_explicit_selection_and_verifier_use_same_mapping(self):
        spec = AnalysisSpec(pattern='none', require_52w=False, require_ma=False,
                            min_market_cap=0).model_dump(mode='json')
        run = self.service.create(RunRequest(question='선택 실행', request_key='mapped-explicit-0001', spec=spec).model_dump(mode='json'))
        self.service.process(run['id'])
        state = self.service.store.read(run['id'])
        self.assertIsNotNone(state['result'], state.get('error'))
        self.assertEqual(state['result']['verification']['status'], 'matched')
        self.assertEqual(FixtureModel.calls, 0)
        self.assertEqual(len(FixtureMappedRuntime.calls), 2)

    def test_corrupted_candidate_is_still_rejected(self):
        HarnessTests.test_mismatching_result_never_becomes_verified(self)


def load_tests(loader, tests, pattern):
    return loader.loadTestsFromTestCase(MappedPathsTests)
