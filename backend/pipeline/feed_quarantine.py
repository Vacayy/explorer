"""Keep a source that returned 403/429 untouched while other feeds continue."""
import json
import os
import re
import stat
import socket
import subprocess
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit


class SourceQuarantined(BaseException):
    """A request was refused locally before contacting a quarantined host."""


def load_hosts(path):
    if not path.exists() and not path.is_symlink():
        return frozenset()
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('Invalid feed quarantine file permissions')
    value = json.loads(path.read_text())
    if not isinstance(value, list) or len(value) > 100 or any(
            not isinstance(x, str) or len(x) > 253 or not re.fullmatch(r'[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?', x)
            for x in value):
        raise ValueError('Invalid feed quarantine file')
    return frozenset(value)


def blocked_host(host, hosts):
    if isinstance(host, bytes):
        host = host.decode('ascii', 'ignore')
    host = host.lower().rstrip('.') if isinstance(host, str) else ''
    return any(host == blocked or host.endswith('.' + blocked) for blocked in hosts)


def blocked_ref(ref, hosts):
    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for v in value.values():
                yield from strings(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                yield from strings(v)
    for value in strings((ref.key, ref.meta)):
        try:
            if blocked_host(urlsplit(value).hostname, hosts):
                return True
        except ValueError:
            continue
    return False


@contextmanager
def guard_network(hosts):
    """Refuse quarantined URLs before network access, including redirects and curl fallback."""
    if not hosts:
        yield
        return
    import requests.adapters
    old_resolve, old_run = socket.getaddrinfo, subprocess.run
    old_open, old_send = urllib.request.OpenerDirector.open, requests.adapters.HTTPAdapter.send

    def check_url(url):
        try:
            if blocked_host(urlsplit(str(url)).hostname, hosts):
                raise SourceQuarantined('A feed source is quarantined')
        except ValueError:
            raise SourceQuarantined('Invalid feed request URL') from None

    def safe_open(opener, request, *args, **kwargs):
        check_url(request if isinstance(request, str) else request.full_url)
        return old_open(opener, request, *args, **kwargs)

    def safe_send(adapter, request, *args, **kwargs):
        check_url(request.url)
        return old_send(adapter, request, *args, **kwargs)

    def safe_resolve(host, *args, **kwargs):
        if blocked_host(host, hosts):
            raise SourceQuarantined('A feed source is quarantined')
        return old_resolve(host, *args, **kwargs)

    def safe_run(args, *a, **kw):
        if isinstance(args, (list, tuple)) and args and Path(args[0]).name == 'curl':
            # The legacy fallback is a subprocess, so never allow it to follow a redirect.
            if len(args) != 7 or list(args[1:4]) != ['-sL', '--max-time', '15'] or args[4] != '-A':
                raise SourceQuarantined('Unrecognized curl request while a source is quarantined')
            check_url(args[-1])
            args = list(args)
            args[1] = '-s'
        return old_run(args, *a, **kw)

    socket.getaddrinfo, subprocess.run = safe_resolve, safe_run
    urllib.request.OpenerDirector.open, requests.adapters.HTTPAdapter.send = safe_open, safe_send
    try:
        yield
    finally:
        socket.getaddrinfo, subprocess.run = old_resolve, old_run
        urllib.request.OpenerDirector.open, requests.adapters.HTTPAdapter.send = old_open, old_send
