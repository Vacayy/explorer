"""Destructive probes target only disposable fixtures, never the Explorer DB."""
import hashlib
import json
import os
from pathlib import Path
import socket
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing
from unittest.mock import patch

from pipeline.market_analysis.runtime import (Sandbox, RuntimeUnavailable, DEFAULT_PYTHON,
                                              MAX_OUTPUT, preflight)


@unittest.skipUnless(sys.platform == 'darwin' and DEFAULT_PYTHON.exists(),
                     'macOS sandbox-exec and scripts/setup_market_analysis.sh required')
class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='analysis-protection-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.source = self.root/'source'
        self.source.mkdir()
        self.db = self.source/'source.sqlite'
        with closing(sqlite3.connect(self.db)) as conn:
            with conn:
                conn.execute('create table prices(code text, close integer)')
                conn.execute("insert into prices values ('005930',100)")
        self.before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        self.inputs = self.root/'inputs'
        self.inputs.mkdir()
        (self.inputs/'data.json').write_text('{"close":100}')
        self.sb = Sandbox(self.root/'control', self.root/'scratch', [self.inputs])

    def tearDown(self):
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), self.before)
        with closing(sqlite3.connect(f'{self.db.as_uri()}?mode=ro', uri=True)) as conn:
            self.assertEqual(conn.execute('pragma integrity_check').fetchone()[0], 'ok')
            self.assertEqual(conn.execute('select * from prices').fetchall(), [('005930',100)])

    def run_code(self, code, **kw):
        result = self.sb.run(code, timeout=kw.pop('timeout',10), **kw)
        self.assertEqual(result.exit_code, 0, result.stderr)
        return result.stdout

    def test_preflight(self):
        self.assertTrue(all(preflight()['checks'].values()))

    def test_normal_numeric_read_and_output(self):
        out = self.run_code(f'''import json,duckdb,pandas,numpy,pyarrow
from pathlib import Path
data=json.loads(Path({str(self.inputs/'data.json')!r}).read_text())
Path('result.json').write_text(json.dumps({{'double':data['close']*2}}))
print(duckdb.sql('select sum(i) from range(11) t(i)').fetchone()[0])
''')
        self.assertEqual(out.strip(), '55')
        self.assertEqual(json.loads((self.sb.workdir/'result.json').read_text()), {'double':200})

    def test_source_sql_mutations_and_attach_are_inaccessible(self):
        out = self.run_code(f'''import sqlite3,json
results=[]
for query in ['select * from prices', "insert into prices values ('x',0)",
              'delete from prices','update prices set close=0','drop table prices',
              'alter table prices add column changed text']:
    try:
        c=sqlite3.connect({str(self.db)!r});c.execute(query);c.commit()
        results.append(False)
    except sqlite3.Error: results.append(True)
try:
    c=sqlite3.connect(':memory:');c.execute('attach database ? as source',({str(self.db)!r},))
    results.append(False)
except sqlite3.Error: results.append(True)
print(json.dumps(results))
''')
        self.assertTrue(all(json.loads(out)))

    def test_direct_file_mutation_is_denied(self):
        out = self.run_code(f'''import json,os,shutil
from pathlib import Path
p=Path({str(self.db)!r});results=[]
for fn in [lambda:p.read_bytes(),lambda:p.write_bytes(b'BAD'),lambda:os.truncate(p,0),
           lambda:p.unlink(),lambda:p.rename(p.with_name('stolen')),
           lambda:os.chmod(p,0o777),lambda:shutil.rmtree(p.parent)]:
    try: fn(); results.append(False)
    except OSError: results.append(True)
print(json.dumps(results))
''')
        self.assertTrue(all(json.loads(out)))

    def test_input_policy_and_other_runs_not_writable(self):
        peer=self.root/'peer';peer.mkdir();(peer/'secret').write_text('private')
        self.run_code('print(1)')
        guard=next(self.sb.control_dir.glob('guard-*.py'))
        paths=[self.inputs/'data.json',self.sb.policy_path,guard,peer/'secret']
        out=self.run_code(f'''import json,os
from pathlib import Path
out=[]
for name in {list(map(str,paths))!r}:
    try: Path(name).write_text('BAD');out.append(False)
    except OSError:out.append(True)
try: Path({str(peer/'secret')!r}).read_text();out.append(False)
except OSError:out.append(True)
print(json.dumps(out))
''')
        self.assertTrue(all(json.loads(out)))

    def test_symlink_cannot_redirect_host_next_script_or_reach_source(self):
        result=self.sb.run(f'''import os
os.symlink({str(self.db)!r},'next.py')
try: open('next.py','w').write('BAD')
except OSError: print('blocked')
''')
        self.assertNotEqual(result.exit_code,0)
        self.assertIn('blocked',result.stdout)
        with self.assertRaises(RuntimeUnavailable): self.sb.run('print(1)')
        (self.sb.workdir/'next.py').unlink()
        self.run_code('print(2)')

    def test_hardlink_to_input_is_denied(self):
        result=self.sb.run(f'''import os
try: os.link({str(self.inputs/'data.json')!r},'input-link');print('ALLOWED')
except OSError: print('BLOCKED')
''')
        self.assertEqual(result.stdout.strip(),'BLOCKED')
        self.assertEqual((self.inputs/'data.json').read_text(),'{"close":100}')

    def test_network_localhost_unix_socket_and_child_processes_denied(self):
        tcp=socket.socket();self.addCleanup(tcp.close)
        tcp.bind(('127.0.0.1',0));tcp.listen(1)
        unix=socket.socket(socket.AF_UNIX);self.addCleanup(unix.close)
        address=str(self.root/'host.sock');unix.bind(address);unix.listen(1)
        out=self.run_code(f'''import socket,subprocess,sys,os,json
checks=[]
def call(fn):
    try: fn();checks.append(False)
    except OSError: checks.append(True)
call(lambda:socket.create_connection(('127.0.0.1',{tcp.getsockname()[1]}),timeout=1))
call(lambda:socket.socket(socket.AF_UNIX).connect({address!r}))
call(lambda:subprocess.run(['/bin/sh','-c','true']))
call(lambda:subprocess.run([sys.executable,'-c','print(1)']))
try:
    pid=os.fork()
    if pid==0: os._exit(0)
    os.waitpid(pid,0);checks.append(False)
except OSError: checks.append(True)
print(json.dumps(checks))
''')
        self.assertTrue(all(json.loads(out)))

    def test_environment_and_application_source_unreadable(self):
        with patch.dict(os.environ,{'ANALYSIS_TEST_SECRET':'must-not-leak'}):
            out=self.run_code(f'''import os,json
from pathlib import Path
checks=[not os.environ.get('ANALYSIS_TEST_SECRET')]
try: Path({str(Path(__file__).resolve())!r}).read_text();checks.append(False)
except OSError: checks.append(True)
print(json.dumps(checks))
''')
        self.assertTrue(all(json.loads(out)))

    def test_timeout_cancel_and_bounded_output(self):
        result=self.sb.run('import time;time.sleep(30)',timeout=.15)
        self.assertTrue(result.timed_out)
        start=time.monotonic()
        result=self.sb.run('import time;time.sleep(30)',cancel=lambda:time.monotonic()-start>.1)
        self.assertTrue(result.cancelled)
        result=self.sb.run("while True: print('x'*8192)")
        self.assertTrue(result.output_limited)
        self.assertLessEqual(len(result.stdout.encode())+len(result.stderr.encode()),MAX_OUTPUT+200)

    def test_file_limit(self):
        result=self.sb.run("with open('large','wb') as f:\n for _ in range(65): f.write(b'x'*1024*1024)")
        self.assertNotEqual(result.exit_code,0)
        self.assertLessEqual((self.sb.workdir/'large').stat().st_size,32*1024*1024)

    def test_abrupt_host_death_terminates_runtime(self):
        work=self.root/'orphan-work'
        code="import os,time;open('pid','w').write(str(os.getpid()));time.sleep(60)"
        host_code=(f"import sys;sys.path.insert(0,{str(Path(__file__).resolve().parents[1])!r})\n"
                   "from pathlib import Path\nfrom pipeline.market_analysis.runtime import Sandbox\n"
                   f"Sandbox(Path({str(self.root/'orphan-control')!r}),Path({str(work)!r}),[]).run({code!r})")
        host=subprocess.Popen([sys.executable,'-I','-c',host_code],
                              stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        child_pid=None
        try:
            deadline=time.monotonic()+5
            while not (work/'pid').exists() and time.monotonic()<deadline:
                time.sleep(.02)
            self.assertTrue((work/'pid').exists())
            child_pid=int((work/'pid').read_text())
            host.kill();host.wait(timeout=2)
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                try: os.kill(child_pid,0)
                except ProcessLookupError: break
                time.sleep(.02)
            else: self.fail('Sandbox child survived host death')
        finally:
            if host.poll() is None: host.kill();host.wait(timeout=2)
            if child_pid:
                try: os.kill(child_pid,signal.SIGKILL)
                except (ProcessLookupError,PermissionError): pass

    def test_unavailable_or_overlapping_runtime_fails_closed(self):
        with patch('pipeline.market_analysis.runtime.sys.platform','linux'):
            with self.assertRaises(RuntimeUnavailable): Sandbox(self.root/'c2',self.root/'w2',[])
        with self.assertRaises(RuntimeUnavailable): Sandbox(self.root/'c2',self.root/'c2'/'w',[])
        with self.assertRaises(RuntimeUnavailable): Sandbox(self.root/'c2',self.root/'w2',[Path.home()])


if __name__=='__main__': unittest.main()
