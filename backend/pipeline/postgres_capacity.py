"""Conservative free-space gate for isolated fixture snapshot replacement."""
from pathlib import Path
import shutil


class SnapshotCapacityError(RuntimeError):
    """A replacement was refused before touching the current snapshot."""


def require_snapshot_capacity(source, target, *, host_probe: Path, vm_probe: Path, reserve_bytes: int = 20 * 1024**3):
    """Check both shared-host and VM free space; do not add the two values.

    The caller must mount a host filesystem probe and a Docker-volume probe in
    the worker. This estimate cannot guarantee success as data/WAL can grow.
    """
    if type(reserve_bytes) is not int or reserve_bytes < 0:
        raise ValueError('reserve_bytes must be a non-negative integer')
    if not host_probe.is_dir() or not vm_probe.is_dir():
        raise SnapshotCapacityError('Both host and VM filesystem probes are required')
    try:
        host_free = shutil.disk_usage(host_probe).free
        vm_free = shutil.disk_usage(vm_probe).free
        source_bytes = source.execute('PRAGMA page_count').fetchone()[0] * source.execute('PRAGMA page_size').fetchone()[0]
        pg_bytes = target.execute('SELECT pg_database_size(current_database())').fetchone()[0]
    except (OSError, ValueError, TypeError) as exc:
        raise SnapshotCapacityError('Could not measure replacement capacity') from exc
    required = 2 * max(source_bytes, pg_bytes) + reserve_bytes
    if host_free < required or vm_free < required:
        raise SnapshotCapacityError('Insufficient free space for snapshot replacement')
    return {'required_bytes': required, 'host_free_bytes': host_free, 'vm_free_bytes': vm_free}
