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
import re
import socket
import sys
from pathlib import Path
from urllib.parse import quote

API = 'explorer-refactor-single-path'
IMAGE = 'explorer-refactor-test:psycopg-3.2.13-auth'
NETWORK = 'explorer-refactor-preview-private'
def work_volume():
    name = os.environ.get('COLLECT_WORK_VOLUME', 'explorer-refactor-collect-trial')
    if name != 'explorer-refactor-collect-trial' and not re.fullmatch(r'explorer-refactor-collect-recovery-[a-z0-9-]+', name):
        raise ValueError('Invalid collection work volume')
    return name


VOLUME = work_volume()
ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get('HOST_HOME', Path.home()))
STATE = HOME / 'server-data/review/refactor-single/collect-trial-schema'
# Live scheduling is opt-in and derives its target from the running API, never from the trial state file.
# The job independently checks that this target equals TRIAL_LIVE_SCHEMA before opening PG.
# The credit adapter (local_sources/, git-excluded code from the MacBook; architect #3 6942709181): like a credential,
# a host directory mounted read-only into job containers only, never the API or the image. Absent, credit reports
# 'adapter missing' as on a MacBook without it.
PEER_VOLUME = 'explorer-refactor-peer'  # the peer monitor's state (logs/peer-monitor), its job only
HISTORY_VOLUME = 'explorer-refactor-history'  # market_history.sqlite; the API and analysis read it read-only
LOCAL_SOURCES = Path(os.environ.get('COLLECT_LOCAL_SOURCES', HOME / 'server-data/review/refactor-single/local-sources'))
API_ENV = ('REFACTOR_POSTGRES_DSN', 'REFACTOR_TEST_DISPOSABLE', 'FASTEMBED_CACHE_PATH', 'CODEX_BIN', 'CODEX_HOME',
           'CODEX_FALLBACK_MODEL', 'HOME', 'ENRICH_ENGINE')
FORWARDED = ('TRIAL_MAX_REQUESTS', 'TRIAL_HOST_CAPS', 'COLLECT_FEED_SOURCES', 'COLLECT_MAX_NEW_DOCS',
             'COLLECT_MAX_MODEL_CALLS', 'COLLECT_PROJECTION_WAIT', 'TRIAL_MAX_ERRORS')


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


# Collection credentials (PM #3 6940013382: checked and passed safely, values never printed or recorded). They live
# only in a host file readable by its owner alone; Telegram credentials reach only a connected sending job.
SECRETS_FILE = HOME / 'server-data/review/refactor-single/collect-secrets.env'
SECRET_KEYS = ('DART_API_KEY', 'DATA_GO_KR_KEY', 'FRED_API_KEY', 'ALPHAVANTAGE_API_KEY', 'FMP_API_KEY', 'SEC_USER_AGENT',
               'KRX_ID', 'KRX_PW')
SEND_KEYS = ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID')


def secrets(keys=SECRET_KEYS):
    """{name: value} from the secrets file (absent before the cutover: {}); refused unless owner-only (0600)."""
    if not SECRETS_FILE.exists():
        return {}
    info = SECRETS_FILE.stat()
    if info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise ValueError(f'{SECRETS_FILE} must be owned by this user and readable by it alone (chmod 600)')
    found = {}
    for line in SECRETS_FILE.read_text().splitlines():
        name, sep, value = line.strip().partition('=')
        if sep and name in keys and value:
            found[name] = value
    return found


LABEL = 'explorer.collect'  # every job container carries it; only labelled containers are stopped or removed here


def check(spec):
    """Mistake guard, not a security boundary (the socket holder can do anything; PM #3 6940036896): a job container
    is only ever the collection image with the listed mounts, unprivileged, all capabilities dropped, no socket."""
    host = spec['HostConfig']
    allowed = {f'{ROOT}/backend', f'{ROOT}/scripts', 'explorer-refactor-single-projection', VOLUME,
               'explorer-public-codex-auth', 'explorer-data-rehearsal_models',
               f'{HOME}/server-data/review/refactor-single/codex-gate',
               f'{HOME}/developer/agent-whiteboard/runtime/explorer/codex-credential-gate.py', str(LOCAL_SOURCES), HISTORY_VOLUME, PEER_VOLUME}
    sources = {bind.split(':', 1)[0] for bind in host['Binds']}
    if spec['Image'] != IMAGE or sources - allowed or any('docker.sock' in bind for bind in host['Binds']):
        raise ValueError(f'Refused job container: image {spec["Image"]}, mounts {sorted(sources - allowed)}')
    if host.get('Privileged') or host.get('CapDrop') != ['ALL'] or host.get('NetworkMode') != NETWORK \
            or host.get('PidMode') or spec.get('Labels', {}).get(LABEL) != '1':
        raise ValueError('Refused job container: privilege, network, pid or label outside the job shape')


def orphans():
    """(name, label) of job containers left behind (a scheduler stopped mid-run, a reboot)."""
    found = call('GET', '/containers/json?all=1&filters=' + quote(json.dumps({'label': [f'{LABEL}=1']})))
    return [(c['Names'][0].lstrip('/'), c['Labels'].get(f'{LABEL}.job', '')) for c in found]


def remove(name):
    info = call('GET', f'/containers/{quote(name)}/json')
    if info['Config']['Labels'].get(LABEL) != '1':
        raise ValueError(f'Not a job container: {name}')
    call('DELETE', f'/containers/{quote(name)}?force=1')


def run(argv, *, name=None, memory='2g', internet=True, limit=3600, extra_env=None, job=''):
    """Create, start and wait for one job container; returns (exit code, output). Removed afterwards."""
    api = call('GET', f'/containers/{API}/json')
    env = [item for item in api['Config']['Env'] if item.split('=', 1)[0] in API_ENV]
    live = next(item.split('=', 1)[1] for item in api['Config']['Env']
                if item.startswith('REFACTOR_FIXTURE_SCHEMA='))
    production = os.environ.get('COLLECT_TARGET') == 'live'
    schema = live if production else STATE.read_text().strip()
    env += [f'REFACTOR_FIXTURE_SCHEMA={schema}', 'CLAUDE_BIN=/bin/false', 'EXPLORER_ONESHOT=1',
            'TRIAL_LIVE_SCHEMA=' + live, 'COLLECT_TARGET=' + ('live' if production else 'trial'),
            'PYTHONPATH=/app/backend:/opt/local-sources', 'PYTHONDONTWRITEBYTECODE=1']
    env += [f'{key}={os.environ[key]}' for key in FORWARDED if os.environ.get(key)]
    env += [f'{key}={value}' for key, value in (extra_env or {}).items()]  # this job's own caps
    keys = SECRET_KEYS + SEND_KEYS if job in {'briefing', 'observeweekly', 'observealerts', 'pfintraday'} else SECRET_KEYS
    found = secrets(keys)
    if job in {'briefing', 'observeweekly', 'observealerts', 'pfintraday'} and any(not found.get(key) for key in SEND_KEYS):
        raise ValueError('Telegram send credentials are missing')
    env += [f'{key}={value}' for key, value in found.items()]
    binds = [f'{ROOT}/backend:/app/backend:ro', f'{ROOT}/scripts:/app/scripts:ro',
             'explorer-refactor-single-projection:/projection:ro', f'{VOLUME}:/trial',
             'explorer-public-codex-auth:/provider-auth', 'explorer-data-rehearsal_models:/models:ro',
             f'{HOME}/server-data/review/refactor-single/codex-gate:/control/codex-gate:ro',
             f'{HOME}/developer/agent-whiteboard/runtime/explorer/codex-credential-gate.py:/control/codex-credential-gate.py:ro']
    if job == 'history':  # the market history job alone writes its own volume (refactor_collect_job.MARKET_HISTORY)
        binds.append(f'{HISTORY_VOLUME}:/history')
    if job == 'peer':  # the peer monitor's state (refactor_collect_job.PEER)
        binds.append(f'{PEER_VOLUME}:/peer')
    if (LOCAL_SOURCES / 'local_sources').is_dir():
        binds.append(f'{LOCAL_SOURCES}:/opt/local-sources:ro')
    units = {'g': 1 << 30, 'm': 1 << 20}
    spec = {'Image': IMAGE, 'Cmd': argv, 'Env': env, 'User': api['Config']['User'], 'WorkingDir': '/app/backend',
            'Labels': {LABEL: '1', f'{LABEL}.job': job},
            'HostConfig': {'Binds': binds, 'Memory': int(memory[:-1]) * units[memory[-1]], 'NetworkMode': NETWORK,
                           'Privileged': False, 'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges']}}
    check(spec)
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


if __name__ == '__main__' and sys.argv[1:] == ['--secrets-check']:  # names only, never values
    present = secrets()
    print('present:', sorted(present), '| missing:', sorted(set(SECRET_KEYS) - set(present)))
    sys.exit(0)
if __name__ == '__main__':
    code, output = run(['python', '/app/scripts/refactor_collect_job.py', *sys.argv[1:]],
                       memory=os.environ.get('JOB_MEMORY', '2g'), internet=os.environ.get('NO_INTERNET') != '1')
    print(output, end='')
    sys.exit(0 if code == 0 else 1)

