"""Fail-closed macOS runtime for untrusted analysis code.

Only immutable inputs and a dedicated numerical Python environment are readable.
The policy and next-step scripts live outside the writable workspace. No shell,
network, child processes, application IPC, or host database handles are provided.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from .process_guard import guarded_command

PROJECT = Path(__file__).resolve().parents[3]
DEFAULT_PYTHON = PROJECT / ".analysis-venv/bin/python"
MAX_OUTPUT = 128 * 1024
MAX_FILE = 32 * 1024 * 1024
MAX_WORKSPACE = 128 * 1024 * 1024
MAX_FILES = 1024


class RuntimeUnavailable(RuntimeError):
    pass


@dataclass
class Result:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    cancelled: bool = False
    output_limited: bool = False


def checked_directory(path: Path, *, create: bool = False) -> Path:
    """Canonicalize existing parents, rejecting links rather than following them."""
    path = Path(os.path.abspath(path))
    for part in [*reversed(path.parents), path]:
        if part.is_symlink():
            # macOS system aliases /var and /tmp are accepted only at the root.
            if part not in (Path('/var'), Path('/tmp')):
                raise RuntimeUnavailable(f"심볼릭 링크 경로를 사용할 수 없습니다: {part.name}")
        if part.exists() and not part.is_dir():
            raise RuntimeUnavailable("실행 디렉터리 경로가 올바르지 않습니다.")
    if create:
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not path.is_dir():
        raise RuntimeUnavailable("실행 디렉터리가 없습니다.")
    return path.resolve()


def _write_new(path: Path, content: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as out:
        out.write(content)


def _literal(path: Path | str) -> str:
    # JSON string escaping is also appropriate for SBPL string literals.
    return json.dumps(str(path), ensure_ascii=True)


def _workspace_size(path: Path) -> int:
    size, count = 0, 0
    stack = [path]
    while stack:
        parent = stack.pop()
        with os.scandir(parent) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                count += 1
                if count > MAX_FILES:
                    raise RuntimeUnavailable("임시 파일 개수 제한을 초과했습니다.")
                if stat.S_ISLNK(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
                    raise RuntimeUnavailable("임시 폴더의 링크 파일은 허용하지 않습니다.")
                if stat.S_ISDIR(info.st_mode):
                    stack.append(Path(entry.path))
                elif stat.S_ISREG(info.st_mode):
                    size += info.st_size
                else:
                    raise RuntimeUnavailable("일반 계산 파일만 생성할 수 있습니다.")
    return size


def _kill(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError:
        # macOS can report EPERM for a group already transitioning to zombie.
        if proc.poll() is None:
            proc.kill()
    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        proc.kill()


class Sandbox:
    def __init__(self, control_dir: Path, workdir: Path, read_dirs: list[Path],
                 python: Path | None = None):
        if sys.platform != 'darwin' or not Path('/usr/bin/sandbox-exec').is_file():
            raise RuntimeUnavailable("macOS 격리 실행기를 사용할 수 없습니다. 일반 실행으로 대체하지 않습니다.")
        self.control_dir = checked_directory(control_dir, create=True)
        self.workdir = checked_directory(workdir, create=True)
        if (self.control_dir == self.workdir or self.control_dir.is_relative_to(self.workdir)
                or self.workdir.is_relative_to(self.control_dir)):
            raise RuntimeUnavailable("실행 관리 영역과 임시 계산 영역을 분리해야 합니다.")
        self.python = Path(os.path.abspath(python or DEFAULT_PYTHON))
        if not self.python.is_file():
            raise RuntimeUnavailable("분석 Python 환경이 없습니다. scripts/setup_market_analysis.sh를 실행해주세요.")
        self.venv = checked_directory(self.python.parent.parent)
        if self.venv == PROJECT / '.venv' or self.venv == PROJECT:
            raise RuntimeUnavailable("분석 전용 Python 환경을 사용해야 합니다.")
        self.read_dirs = []
        for directory in read_dirs:
            directory = checked_directory(Path(directory))
            if (directory == self.workdir or directory.is_relative_to(self.workdir)
                    or self.workdir.is_relative_to(directory)
                    or directory == PROJECT or PROJECT.is_relative_to(directory)
                    or directory == Path.home()):
                raise RuntimeUnavailable("분석 입력 범위가 너무 넓거나 임시 폴더와 겹칩니다.")
            self.read_dirs.append(directory)
        info = subprocess.run([str(self.python), '-I', '-c',
            'import json,sys; print(json.dumps({"base":sys.base_prefix}))'],
            capture_output=True, text=True, timeout=10, check=True,
            env={'PATH':'/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE':'1'})
        self.base = Path(json.loads(info.stdout)['base']).resolve()
        self.policy_path = self.control_dir / f'policy-{uuid.uuid4().hex}.sb'
        _write_new(self.policy_path, self._profile())

    def _profile(self) -> str:
        roots = [self.venv, self.base, self.workdir, *self.read_dirs]
        system_roots = ['/System/Library', '/usr/lib', '/private/var/db/dyld',
                        '/private/var/db/timezone']
        # CPython's sqlite extension links this library outside sys.base_prefix.
        # Permit only the resolved library directory, not all of Homebrew.
        for library in ('/opt/homebrew/opt/sqlite/lib', '/usr/local/opt/sqlite/lib'):
            if Path(library).is_dir():
                system_roots.append(str(Path(library).resolve()))
        reads = '\n'.join(f'  (subpath {_literal(p)})' for p in [*roots, *system_roots])
        # One trusted code file is allowed later through the CODE parameter.
        return f'''(version 1)
(deny default)
(allow sysctl-read)
(allow file-read-metadata)
(allow file-read-data
{reads}
  (literal (param "CODE"))
  (literal "/")
  (literal "/dev/null") (literal "/dev/zero")
  (literal "/dev/random") (literal "/dev/urandom")
  (literal "/private/etc/localtime"))
(allow file-write* (subpath {_literal(self.workdir)}))
(allow file-write-data (literal "/dev/null"))
(allow process-exec (literal {_literal(self.python.resolve())})
  (literal {_literal(self.base / 'Resources/Python.app/Contents/MacOS/Python')}))
(allow signal (target self))
'''

    def run(self, code: str, timeout: float = 60,
            cancel: Callable[[], bool] | None = None) -> Result:
        if not isinstance(code, str) or len(code.encode()) > 128 * 1024:
            raise ValueError("분석 코드 크기 제한을 초과했습니다.")
        if not math.isfinite(timeout) or timeout <= 0 or timeout > 900:
            raise ValueError("실행 시간 제한이 올바르지 않습니다.")
        if checked_directory(self.workdir) != self.workdir:
            raise RuntimeUnavailable("임시 계산 경로가 변경되었습니다.")
        checked_directory(self.control_dir)
        if _workspace_size(self.workdir) > MAX_WORKSPACE:
            raise RuntimeUnavailable("임시 계산 공간 제한을 초과했습니다.")
        script = self.control_dir / f'code-{uuid.uuid4().hex}.py'
        _write_new(script, code)
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(self.workdir),
               'TMPDIR': str(self.workdir), 'MPLCONFIGDIR': str(self.workdir / '.matplotlib'),
               'MPLBACKEND': 'Agg', 'PYTHONDONTWRITEBYTECODE': '1',
               'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1',
               'VECLIB_MAXIMUM_THREADS': '1', 'NUMEXPR_MAX_THREADS': '1'}
        argv = ['/usr/bin/sandbox-exec', '-f', str(self.policy_path),
                '-D', f'CODE={script}', str(self.python), '-I', '-B', str(script)]
        # Fresh trusted supervisor applies resource limits and kills its child
        # if the API host dies, even when the parent cannot execute its finally.
        command = guarded_command(self.control_dir, argv, timeout + 1, python=self.python,
            limits={'RLIMIT_CORE': 0, 'RLIMIT_NOFILE': 128, 'RLIMIT_FSIZE': MAX_FILE,
                    'RLIMIT_CPU': max(1, math.ceil(timeout))})
        proc = subprocess.Popen(command,
            cwd=self.workdir, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True, close_fds=True)
        streams = {'stdout':bytearray(), 'stderr':bytearray()}
        timed_out = cancelled = limited = False
        reason = ''
        start = last_disk_check = time.monotonic()
        try:
            with selectors.DefaultSelector() as selector:
                for name in streams:
                    pipe = getattr(proc, name)
                    os.set_blocking(pipe.fileno(), False)
                    selector.register(pipe, selectors.EVENT_READ, name)
                while selector.get_map():
                    now = time.monotonic()
                    if cancel and cancel():
                        cancelled, reason = True, '사용자가 실행을 취소했습니다.'
                    elif now-start > timeout:
                        timed_out, reason = True, '분석 실행 시간 제한을 초과했습니다.'
                    elif now-last_disk_check > .1:
                        last_disk_check = now
                        try:
                            if _workspace_size(self.workdir) > MAX_WORKSPACE:
                                reason = '임시 계산 공간 제한을 초과했습니다.'
                        except (OSError, RuntimeUnavailable) as exc:
                            reason = str(exc)
                    if reason:
                        _kill(proc)
                    for key, _ in selector.select(.05):
                        chunk = os.read(key.fileobj.fileno(), 8192)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        used = sum(len(v) for v in streams.values())
                        streams[key.data].extend(chunk[:max(0, MAX_OUTPUT-used)])
                        if used+len(chunk) > MAX_OUTPUT:
                            limited, reason = True, '출력 크기 제한을 초과했습니다.'
                            _kill(proc)
                proc.wait(timeout=3)
        finally:
            # Also clean up a process which exited before an exception or EOF.
            _kill(proc)
            proc.wait(timeout=3)
            proc.stdout.close()
            proc.stderr.close()
        if not reason:
            try:
                if _workspace_size(self.workdir) > MAX_WORKSPACE:
                    reason = '임시 계산 공간 제한을 초과했습니다.'
            except (RuntimeUnavailable, OSError) as exc:
                reason = str(exc)
        stderr = streams['stderr'].decode('utf-8', 'replace')
        if reason:
            stderr += '\n' + reason
        return Result(proc.returncode if not reason else (proc.returncode or 1),
                      streams['stdout'].decode('utf-8', 'replace'), stderr,
                      timed_out, cancelled, limited)


def preflight(python: Path | None = None) -> dict:
    """Real OS boundary smoke using fixtures only; must pass before a model run."""
    with tempfile.TemporaryDirectory(prefix='explorer-analysis-check-') as folder:
        root = Path(folder).resolve()
        protected = root / 'protected.txt'
        protected.write_text('ORIGINAL')
        inputs = root / 'inputs'
        inputs.mkdir()
        source = inputs / 'input.txt'
        source.write_text('INPUT')
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        sb = Sandbox(root/'control', root/'scratch', [inputs], python)
        code = f'''import json,os,socket
from pathlib import Path
checks={{}}
checks['input_read']=Path({str(source)!r}).read_text()=='INPUT'
Path('result.txt').write_text('OK')
checks['output_write']=Path('result.txt').read_text()=='OK'
def blocked(key, fn):
    try: fn(); checks[key]=False
    except (OSError,PermissionError): checks[key]=True
blocked('source_read',lambda:Path({str(protected)!r}).read_text())
blocked('source_write',lambda:Path({str(protected)!r}).write_text('BAD'))
blocked('source_delete',lambda:Path({str(protected)!r}).unlink())
blocked('input_write',lambda:Path({str(source)!r}).write_text('BAD'))
blocked('input_chmod',lambda:os.chmod({str(source)!r},0o777))
blocked('network',lambda:socket.create_connection(('127.0.0.1',{listener.getsockname()[1]}),timeout=1))
print(json.dumps(checks))
'''
        try:
            result = sb.run(code, timeout=15)
        finally:
            listener.close()
        try:
            checks = json.loads(result.stdout)
        except ValueError as exc:
            raise RuntimeUnavailable('격리 검사를 실행하지 못했습니다: '+result.stderr[-600:]) from exc
        if result.exit_code or not all(checks.values()) or protected.read_text()!='ORIGINAL' or source.read_text()!='INPUT':
            raise RuntimeUnavailable('격리 검사에 실패했습니다. 분석 실행을 차단합니다.')
        return {'runtime':'macos-seatbelt', 'checks':checks,
                'policy_hash':hashlib.sha256(sb._profile().encode()).hexdigest()}
