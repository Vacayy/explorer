"""Trusted supervisor: children cannot outlive an abruptly terminated API host."""
import json
import os
from pathlib import Path
import sys
import uuid

GUARD = '''import json,os,resource,signal,subprocess,sys,time
cfg=json.loads(sys.argv[1])
stopped=False
def stop(*args):
    global stopped
    stopped=True
for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):
    signal.signal(sig,stop)
if os.getppid()!=cfg['parent_pid']:
    sys.exit(125)
for name,value in cfg['limits'].items():
    resource.setrlimit(getattr(resource,name),(value,value))
child=None
exit_code=125
try:
    child=subprocess.Popen(cfg['argv'],close_fds=True,start_new_session=True)
    deadline=time.monotonic()+cfg['timeout']
    while child.poll() is None:
        if stopped or os.getppid()!=cfg['parent_pid']:
            exit_code=125
            break
        if time.monotonic()>=deadline:
            exit_code=124
            break
        time.sleep(.05)
    else:
        exit_code=child.returncode
finally:
    if child is not None:
        try: os.killpg(child.pid,signal.SIGKILL)
        except (ProcessLookupError,PermissionError):
            if child.poll() is None: child.kill()
        child.wait(timeout=3)
sys.exit(exit_code if exit_code>=0 else 128-exit_code)
'''


def guarded_command(control_dir: Path, argv: list[str], timeout: float, *,
                    python: Path | None = None, limits: dict | None = None) -> list[str]:
    """Control directory must already be trusted and outside all sandbox writes."""
    path = control_dir / f'guard-{uuid.uuid4().hex}.py'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as out:
        out.write(GUARD)
    config = {'parent_pid': os.getpid(), 'timeout': timeout, 'argv': argv, 'limits': limits or {}}
    return [str(python or sys.executable), '-I', '-B', str(path), json.dumps(config)]
