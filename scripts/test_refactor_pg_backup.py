"""Offline safety checks for backup retention and scratch database ownership."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name('refactor_pg_backup.sh')


class BackupSafetyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.backups = root / 'backups'
        self.backups.mkdir()
        self.log = root / 'commands'
        schema = root / 'schema.json'
        schema.write_text(json.dumps({'base_schema': 'refactor_fixture_' + 'a' * 32}))
        docker = root / 'docker'
        docker.write_text('''#!/bin/bash
set -eu
case "$*" in
  *"printenv REFACTOR_FIXTURE_SCHEMA"*) printf 'refactor_fixture_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\\n' ;;
  *"printenv REFACTOR_POSTGRES_DSN"*) printf 'synthetic-dsn\\n' ;;
  "inspect explorer-refactor-single-path") printf '[{"Config":{"Env":["REFACTOR_POSTGRES_DSN=synthetic-dsn","REFACTOR_FIXTURE_SCHEMA=refactor_fixture_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"]}}]\\n' ;;
  "inspect explorer-refactor-preview-db") printf '[{"Image":"sha256:%064d"}]\\n' 0 ;;
  *"inspect"*".Image"*) printf 'sha256:%064d\\n' 0 ;;
  *"--entrypoint python"*"BACKUP_BASE_SCHEMA"*) printf '{"locked":true,"schemas":["refactor_fixture_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","refactor_fixture_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"],"relation_bytes":1048576}\\n'; read -r _ || true ;;
  *"information_schema.views"*) : ;;
  *"sha256sum"*"pg_restore --list"*) printf 'synthetic backup\\n' | sha256sum | awk '{print $1, "fixture"}'; printf 'refactor_fixture_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\nrefactor_fixture_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\\n' ;;
  *"pg_dump"*)
    [[ "$1" = run && "$*" = *"--log-driver none"* ]] || exit 5
    printf 'synthetic backup\\n'
    if [[ "${TEST_SIMULATE_DROP:-0}" = 1 ]]; then
      printf '%s' "$$" > "$TEST_DUMP_PID"; touch "$TEST_DROP_FLAG"
      trap 'exit 9' TERM
      while :; do sleep 0.1; done
    fi ;;
  "kill "*) [[ -f "$TEST_DUMP_PID" ]] && kill "$(cat "$TEST_DUMP_PID")" || true ;;
  *"pg_database_size"*) printf '1048576\\n' ;;
  *"df -k"*|*"df -Pk"*)
    free="${TEST_VM_FREE_KB:-99999999}"
    if [[ "${TEST_SIMULATE_DROP:-0}" = 1 && -f "$TEST_DROP_FLAG" ]]; then free=2300000; fi
    printf 'fs blocks used available capacity mount\\nfs 99999999 1 %s 1%% /data\\n' "$free" ;;
  *"sum(pg_total_relation_size"*) printf '1048576\\n' ;;
  *"FROM pg_database"*) : ;;
  *"createdb -U fixture"*) printf 'created %s\\n' "${@: -1}" >> "$TEST_COMMAND_LOG" ;;
  *"dropdb -U fixture"*) printf 'dropped %s\\n' "${@: -1}" >> "$TEST_COMMAND_LOG" ;;
  *"pg_restore"*) cat >/dev/null ;;
  *"query_to_xml"*) printf 'synthetic.table|0\\n' ;;
  *) exit 4 ;;
esac
''')
        docker.chmod(0o700)
        df = root / 'df'
        df.write_text('''#!/bin/bash
printf 'fs blocks used available capacity mount\\nfs 99999999 1 %s 1%% /data\\n' "${TEST_HOST_FREE_KB:-99999999}"
''')
        df.chmod(0o700)
        self.env = os.environ.copy()
        self.env.update({'PATH': str(root) + os.pathsep + self.env['PATH'],
                         'REFACTOR_BACKUP_DIR': str(self.backups), 'REFACTOR_SCHEMA_CONFIG': str(schema),
                         'TEST_COMMAND_LOG': str(self.log), 'TEST_DROP_FLAG': str(root / 'drop'),
                         'TEST_DUMP_PID': str(root / 'dump-pid')})

    def test_backups_are_never_pruned(self):
        for n in range(5):
            (self.backups / ('2000010100000%d-candidate.dump' % n)).write_text('preserve')
        before = set(self.backups.iterdir())
        result = subprocess.run(['bash', str(SCRIPT), 'backup'], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(before.issubset(set(self.backups.iterdir())))

    def test_restore_uses_only_its_own_scratch_database(self):
        result = subprocess.run(['bash', str(SCRIPT), 'backup'], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        dump = next(self.backups.glob('*-candidate.dump'))
        result = subprocess.run(['bash', str(SCRIPT), 'check', str(dump)], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        entries = self.log.read_text().splitlines()
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].split()[1], entries[1].split()[1])
        self.assertTrue(entries[0].split()[1].startswith('explorer_restore_'))
        self.assertNotEqual(entries[0].split()[1], 'restore_check')

    def test_restore_refuses_when_vm_has_insufficient_space(self):
        result = subprocess.run(['bash', str(SCRIPT), 'backup'], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        dump = next(self.backups.glob('*-candidate.dump'))
        env = dict(self.env, TEST_VM_FREE_KB='1024')
        result = subprocess.run(['bash', str(SCRIPT), 'check', str(dump)], env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())

    def test_backup_stops_and_preserves_partial_when_vm_space_drops(self):
        env = dict(self.env, TEST_SIMULATE_DROP='1')
        result = subprocess.run(['bash', str(SCRIPT), 'backup'], env=env, capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('backup stopped: vm_space', result.stdout)
        self.assertEqual(len(list(self.backups.glob('*-candidate.dump.partial'))), 1)
        self.assertEqual(list(self.backups.glob('*-candidate.dump')), [])

    def test_backup_refuses_when_host_has_insufficient_space(self):
        env = dict(self.env, TEST_HOST_FREE_KB='1024')
        result = subprocess.run(['bash', str(SCRIPT), 'backup'], env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_backup_refuses_when_vm_has_insufficient_space(self):
        env = dict(self.env, TEST_VM_FREE_KB='1024')
        result = subprocess.run(['bash', str(SCRIPT), 'backup'], env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.backups.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
