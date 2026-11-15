"""Capture immutable explicit document attachments for disposable PG snapshots.

The source DB and files are not an atomic snapshot; callers need an appropriate
source write freeze for that guarantee. Unsafe paths and changed files fail the
whole surrounding transaction instead of substituting current bytes.
"""
import hashlib
import json
import os
import stat
from pathlib import Path, PurePosixPath

_MAX_BYTES = 8 * 1024 * 1024
_ALLOWED = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}


def _read_file(root, reference):
    if not isinstance(reference, str) or not reference or '\\' in reference or '\x00' in reference:
        raise ValueError('Unsupported attachment path')
    path = PurePosixPath(reference)
    if path.is_absolute() or any(p in ('', '.', '..') for p in reference.split('/')) or path.suffix.lower() not in _ALLOWED:
        raise ValueError('Unsupported attachment path')
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        child = os.open(path.parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            before = os.fstat(child)
            if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_BYTES:
                raise ValueError('Unsupported attachment file')
            with os.fdopen(child, 'rb', closefd=False) as stream:
                data = stream.read(_MAX_BYTES + 1)
            after = os.fstat(child)
            if (len(data) != before.st_size or len(data) > _MAX_BYTES or
                    (before.st_ino, before.st_size, before.st_mtime_ns) !=
                    (after.st_ino, after.st_size, after.st_mtime_ns)):
                raise ValueError('Attachment changed during capture')
            return data
        finally:
            os.close(child)
    finally:
        os.close(fd)


def capture_media(source, destination, generation, media_root):
    root = Path(media_root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Invalid media root')
    destination.execute('INSERT INTO media_generations (generation_id) VALUES (%s)', (generation,))
    seen = set()
    for row in source.execute("SELECT media_json FROM raw_documents WHERE media_json IS NOT NULL AND media_json != ''"):
        refs = json.loads(row[0])
        if refs is None:
            continue
        if not isinstance(refs, list):
            raise ValueError('Invalid document attachment list')
        for ref in refs:
            if not isinstance(ref, str):
                raise ValueError('Invalid document attachment path')
            if ref in seen:
                continue
            body = _read_file(root, ref)
            digest = hashlib.sha256(body).hexdigest()
            destination.execute('INSERT INTO media_blobs (digest, content) VALUES (%s, %s) ON CONFLICT DO NOTHING',
                                (digest, body))
            destination.execute('INSERT INTO media_generation_refs VALUES (%s, %s, %s)', (generation, ref, digest))
            seen.add(ref)
    destination.execute('''DELETE FROM media_generations WHERE generation_id != %s AND generation_id NOT IN
        (SELECT generation_id FROM archived_timeline_generations WHERE expires_at > clock_timestamp())''', (generation,))
    destination.execute('DELETE FROM media_blobs WHERE NOT EXISTS '
                        '(SELECT 1 FROM media_generation_refs r WHERE r.digest=media_blobs.digest)')
    return len(seen)
