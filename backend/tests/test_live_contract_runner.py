"""Scheduled Python probe and Node checker must target the same API."""
import io
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import types
import unittest
import urllib.request
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[2]/'scripts/check_live_contracts.py'

class ContractRunnerEndpoint(unittest.TestCase):
    def check_endpoint(self, configured, expected):
        ops = types.ModuleType('pipeline.ops')
        ops.record_run = Mock()
        env = dict(os.environ)
        env.pop('API_BASE', None)
        if configured is not None:
            env['API_BASE'] = configured
        completed = types.SimpleNamespace(returncode=0, stdout='fixture passed', stderr='')
        with patch.dict(os.environ, env, clear=True), patch.dict('sys.modules', {'pipeline.ops':ops}), \
             patch.object(urllib.request, 'urlopen') as probe, patch.object(shutil, 'which', return_value='/usr/bin/node'), \
             patch.object(subprocess, 'run', return_value=completed) as node, patch('sys.stdout', new_callable=io.StringIO):
            module = runpy.run_path(str(SCRIPT))
            self.assertEqual(module['main'](), 0)
        self.assertEqual(probe.call_args.args[0], expected+'/api/spine/admin/health')
        self.assertEqual(node.call_args.kwargs['env']['API_BASE'], expected)
        self.assertEqual(ops.record_run.call_args.args[1], 'ok')

    def test_configured_private_api_shared_by_both_checks(self):
        self.check_endpoint('http://api:8000/', 'http://api:8000')

    def test_default_macbook_endpoint_preserved(self):
        self.check_endpoint(None, 'http://localhost:8000')

if __name__ == '__main__': unittest.main()
