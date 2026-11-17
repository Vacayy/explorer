"""One-shot job containers through the Docker Engine API (standard library only), for the collection scheduler.

The same container as scripts/refactor_collect_trial.sh's `container()`, so the scheduler can run as one container
(restart: unless-stopped; architect #3 6938360203) without a Docker CLI in any local image: it is the only
container given the Docker socket. Bind sources are host paths, so in that container the repository and $HOME are
mounted at their host paths. DOCKER_HOST (unix://…) or /var/run/docker.sock.

  python scripts/refactor_collect_engine.py <label>             # one scheduled job (as `refactor_collect_trial.sh job`)
"""
import http.client
import json
import os
import socket
import sys
from pathlib import Path
from urllib.parse import quote

API = 'explorer-refactor-single-path'
IMAGE = 'explorer-refactor-test:psycopg-3.2.13-auth'
NETWORK = 'explorer-refactor-preview-private'
VOLUME = 'explorer-refactor-collect-trial'
ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get('HOST_HOME', Path.home()))
STATE = HOME / 'server-data/review/refactor-single/collect-trial-schema'
API_ENV = ('REFACTOR_POSTGRES_DSN', 'REFACTOR_TEST_DISPOSABLE', 'FASTEMBED_CACHE_PATH', 'CODEX_BIN', 'CODEX_HOME',
           'CODEX_FALLBACK_MODEL', 'HOME', 'ENRICH_ENGINE')
FORWARDED = ('TRIAL_MAX_REQUESTS', 'TRIAL_HOST_CAPS', 'COLLECT_FEED_SOURCES', 'COLLECT_MAX_NEW_DOCS',
             'COLLECT_MAX_MODEL_CALLS', 'COLLECT_PROJECTION_WAIT')


class _Unix(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__('localhost', timeout=timeout)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def _socket_path():
    host = os.environ.get('DOCKER_HOST', '')
    return host[len('unix://'):] if host.startswith('unix://') else '/var/run/docker.sock'


def call(method, path, body=None, *, timeout=60, raw=False):
    conn = _Unix(_socket_path(), timeout)
    try:
        conn.request(method, '/v1.43' + path, body=None if body is None else json.dumps(body),
                     headers={'Content-Type': 'application/json'})
        response = conn.getresponse()
        data = response.read()
        if response.status >= 400:
            raise RuntimeError(f'{method} {path}: {response.status} {data[:200]!r}')
        return data if raw else (json.loads(data) if data else None)
    finally:
        conn.close()


def _logs(ident):
    """stdout and stderr of a stopped container (multiplexed stream frames)."""
    data, out = call('GET', f'/containers/{ident}/logs?stdout=1&stderr=1', raw=True), []
    while len(data) >= 8:
        size = int.from_bytes(data[4:8], 'big')
        out.append(data[8:8 + size].decode('utf-8', 'replace'))
        data = data[8 + size:]
    return ''.join(out)


def run(argv, *, name=None, memory='2g', internet=True, limit=3600, extra_env=None):
    """Create, start and wait for one job container; returns (exit code, output). Removed afterwards."""
    api = call('GET', f'/containers/{API}/json')
    env = [item for item in api['Config']['Env'] if item.split('=', 1)[0] in API_ENV]
    env += [f'REFACTOR_FIXTURE_SCHEMA={STATE.read_text().strip()}', 'CLAUDE_BIN=/bin/false', 'EXPLORER_ONESHOT=1',
            'TRIAL_LIVE_SCHEMA=' + next(item.split('=', 1)[1] for item in api['Config']['Env']
                                        if item.startswith('REFACTOR_FIXTURE_SCHEMA=')),
            'PYTHONPATH=/app/backend', 'PYTHONDONTWRITEBYTECODE=1']
    env += [f'{key}={os.environ[key]}' for key in FORWARDED if os.environ.get(key)]
    env += [f'{key}={value}' for key, value in (extra_env or {}).items()]  # this job's own caps
    binds = [f'{ROOT}/backend:/app/backend:ro', f'{ROOT}/scripts:/app/scripts:ro',
             'explorer-refactor-single-projection:/projection:ro', f'{VOLUME}:/trial',
             'explorer-public-codex-auth:/provider-auth', 'explorer-data-rehearsal_models:/models:ro',
             f'{HOME}/server-data/review/refactor-single/codex-gate:/control/codex-gate:ro',
             f'{HOME}/developer/agent-whiteboard/runtime/explorer/codex-credential-gate.py:/control/codex-credential-gate.py:ro']
    units = {'g': 1 << 30, 'm': 1 << 20}
    spec = {'Image': IMAGE, 'Cmd': argv, 'Env': env, 'User': api['Config']['User'], 'WorkingDir': '/app/backend',
            'HostConfig': {'Binds': binds, 'Memory': int(memory[:-1]) * units[memory[-1]], 'NetworkMode': NETWORK}}
    ident = call('POST', '/containers/create' + (f'?name={quote(name)}' if name else ''), spec)['Id']
    try:
        if internet:
            call('POST', '/networks/bridge/connect', {'Container': ident})  # outbound internet for this run only
        call('POST', f'/containers/{ident}/start')
        try:
            code = call('POST', f'/containers/{ident}/wait', timeout=limit)['StatusCode']
        except (socket.timeout, TimeoutError):
            return None, ''  # the caller records the stop; the container goes below
        return code, _logs(ident)
    finally:
        call('DELETE', f'/containers/{ident}?force=1')


if __name__ == '__main__':
    code, output = run(['python', '/app/scripts/refactor_collect_job.py', *sys.argv[1:]],
                       memory=os.environ.get('JOB_MEMORY', '2g'), internet=os.environ.get('NO_INTERNET') != '1')
    print(output, end='')
    sys.exit(0 if code == 0 else 1)
