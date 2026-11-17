"""The Mac mini collection scheduler as a user LaunchAgent (PM #3 6940138004; architect 6940126066).

The scheduler runs as the host user, who already has full Docker control: no socket is exposed to any container.
It waits for Docker, PG and applied migrations before starting jobs (scripts/refactor_collect_scheduler.py).
This only writes the property list to a staging directory: installing (~/Library/LaunchAgents) and loading it
happen at the cutover, not before. Automatic restart after a reboot stays unverified until a real reboot test.

  python3 scripts/refactor_collect_launchagent.py <labels>   # writes the staged plist and prints its path
"""
import plistlib
import sys
from pathlib import Path

LABEL = 'dev.explorer.refactor-collect-scheduler'
ROOT = Path(__file__).resolve().parent.parent
STAGING = Path.home() / 'server-data/review/refactor-single/launchagent'


def plist(enabled):
    logs = Path.home() / 'server-data/review/refactor-single/logs'
    return {'Label': LABEL,
            'ProgramArguments': ['/usr/bin/python3', str(ROOT / 'scripts/refactor_collect_scheduler.py'), '--run',
                                 '--enable', enabled],
            'WorkingDirectory': str(ROOT),
            'EnvironmentVariables': {'DOCKER_HOST': f'unix://{Path.home()}/.colima/default/docker.sock',
                                     'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'},
            'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 60,
            'StandardOutPath': str(logs / 'collect-scheduler.log'), 'StandardErrorPath': str(logs / 'collect-scheduler.log')}


if __name__ == '__main__':
    if len(sys.argv) != 2 or not sys.argv[1]:
        raise SystemExit('name the jobs to enable')
    STAGING.mkdir(parents=True, exist_ok=True)
    (Path.home() / 'server-data/review/refactor-single/logs').mkdir(parents=True, exist_ok=True)
    path = STAGING / f'{LABEL}.plist'
    path.write_bytes(plistlib.dumps(plist(sys.argv[1])))
    print(path)
