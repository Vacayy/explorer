"""Keep one restore-tested scheduled PostgreSQL generation on the host."""

import fcntl
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory


SCRIPT = Path(__file__).with_name('refactor_pg_backup.sh')
DUMP = re.compile(r'\d{8}T\d{6}Z-candidate\.dump')
GENERATION = re.compile(r'verified-(\d{8}T\d{6}Z)')


def call(*args, directory=None):
    env = os.environ.copy()
    if directory is not None:
        env['REFACTOR_BACKUP_DIR'] = str(directory)
    command = ['bash', str(SCRIPT), *map(str, args)]
    with subprocess.Popen(command, env=env, start_new_session=True) as child:
        try:
            result = child.wait(timeout=1400)
        except (InterruptedError, KeyboardInterrupt, subprocess.TimeoutExpired):
            try:
                os.killpg(child.pid, signal.SIGTERM)
                child.wait(timeout=60)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
            raise
        if result:
            raise subprocess.CalledProcessError(result, command)


def generation_dump(directory):
    match = GENERATION.fullmatch(directory.name)
    if not match or directory.is_symlink() or not directory.is_dir():
        raise ValueError('unexpected scheduled backup directory')
    name = f'{match[1]}-candidate.dump'
    files = list(directory.iterdir())
    if {p.name for p in files} != {name, f'{name}.sha256', '.restore-verified'} or any(
        p.is_symlink() or not p.is_file() for p in files
    ):
        raise ValueError('unexpected scheduled backup contents')
    if (directory / '.restore-verified').read_text() != 'pg_restore ok\n':
        raise ValueError('scheduled backup was not verified')
    return directory / name


def current_dump(root):
    link = root / 'current'
    if link.is_symlink():
        target = os.readlink(link)
        if not GENERATION.fullmatch(target):
            raise ValueError('unexpected scheduled backup link')
        return generation_dump(root / target)
    if link.exists():
        raise ValueError('unexpected scheduled backup link')
    # Use the pre-rotation baseline until a newly verified generation exists.
    dumps = sorted(p for p in root.iterdir() if DUMP.fullmatch(p.name)
                   and p.is_file() and not p.is_symlink())
    if not dumps:
        raise FileNotFoundError('no scheduled backup')
    return dumps[-1]


def rotate(root):
    link = root / 'current'
    if link.is_symlink() or link.exists():
        current_dump(root)
    with TemporaryDirectory(prefix='.pending-', dir=root) as scratch:
        work = Path(scratch)
        stage = work / 'dump'
        call('backup', directory=stage)
        files = list(stage.iterdir())
        dumps = [p for p in files if DUMP.fullmatch(p.name)]
        if len(dumps) != 1 or len(files) != 2 or any(
            p.is_symlink() or not p.is_file() for p in files
        ):
            raise ValueError('unexpected candidate backup contents')
        dump = dumps[0]
        call('check', dump)
        (stage / '.restore-verified').write_text('pg_restore ok\n')
        generation = root / ('verified-' + dump.name.removesuffix('-candidate.dump'))
        if generation.exists() or generation.is_symlink():
            raise FileExistsError('scheduled backup already exists')
        stage.rename(generation)
        published = generation_dump(generation)
        pointer = work / 'new-current'
        pointer.symlink_to(generation.name)
        os.replace(pointer, link)
    for old in root.iterdir():
        if old == generation or not GENERATION.fullmatch(old.name):
            continue
        generation_dump(old)
        shutil.rmtree(old)
    print(published, flush=True)


def main():
    root = Path(os.environ.get('REFACTOR_BACKUP_DIR', Path.home() / 'server-data/backups/refactor-pg'))
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink():
        raise ValueError('unexpected scheduled backup root')
    with os.fdopen(os.open(root / '.rotation.lock', os.O_CREAT | os.O_NOFOLLOW | os.O_RDWR, 0o600), 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('backup deferred: rotation busy', flush=True)
            return 1
        if sys.argv[1] == 'rotate':
            rotate(root)
        else:
            call('check', current_dump(root))
    return 0


if __name__ == '__main__':
    def interrupted(_signum, _frame):
        raise InterruptedError('scheduled backup interrupted')

    signal.signal(signal.SIGTERM, interrupted)
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'scheduled backup failed: {type(error).__name__}', file=sys.stderr)
        sys.exit(1)
