"""Collect regular-session Peer prices; publish forward research observations only."""
import argparse
import fcntl
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'backend'))
sys.path.insert(0, str(PROJECT / 'scripts'))
from research.peer_monitor import SOURCE, atomic_json, digest, parse_rows, publish, snapshot


def collect(root, catalog, now):
    import requests
    from services.cache_service import is_cached, set_cache
    payloads = {}
    # Short TTL and per-KST-date keys: yesterday's response cannot satisfy today's run.
    with requests.Session() as session:
        session.headers.update({'User-Agent': 'Mozilla/5.0', 'Referer': 'https://stock.naver.com/'})
        for company in catalog['companies']:
            code = company['code']
            key = f'peer:regular:v1:{now.date()}:{code}'
            cache = root / 'cache' / (digest(key) + '.json')
            cached = is_cached(key)
            if cached and cache.exists():
                payload = json.loads(cache.read_text())
            else:
                response = session.get(SOURCE.format(code=code), timeout=(10, 30))
                response.raise_for_status()
                payload = response.json()
                # Cache only structurally and arithmetically valid responses.
                parse_rows(payload, now.date().isoformat())
                atomic_json(root / 'raw' / (digest(payload) + '.json'), payload)
                atomic_json(cache, payload)
                set_cache(key, 900)
                time.sleep(.1)
            payloads[code] = payload
    return payloads


def refresh(root, catalog, seed, now, fetch=collect):
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'writer.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            payloads = fetch(root, catalog, now)
            # Confirmed event evidence persists; transient provider issues are recomputed.
            known = seed['qualityIssues']
            prices = snapshot(catalog, payloads, now, known)
            bundle, status = publish(root, catalog, prices, now)
            attempt = dict(at=now.isoformat(), status=status, asOf=prices['asOf'], key=bundle['key'], error=None)
        except Exception as exc:
            attempt = dict(at=now.isoformat(), status='error', error=f'{type(exc).__name__}: {exc}'[:1000])
            atomic_json(root / 'attempts' / (datetime.now().strftime('%Y%m%dT%H%M%S%f') + '.json'), attempt)
            atomic_json(root / 'last-attempt.json', attempt)
            raise
        atomic_json(root / 'attempts' / (datetime.now().strftime('%Y%m%dT%H%M%S%f') + '.json'), attempt)
        atomic_json(root / 'last-attempt.json', attempt)
        return attempt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=PROJECT / 'logs' / 'peer-monitor')
    args = parser.parse_args()
    catalog = json.loads((PROJECT / 'frontend/src/data/peer-catalog.json').read_text())
    seed = json.loads((PROJECT / 'frontend/src/data/peer-prices.json').read_text())
    now = datetime.now(ZoneInfo('Asia/Seoul'))
    from pipeline.ops import record_run
    started = time.monotonic()
    try:
        result = refresh(args.root, catalog, seed, now)
    except BlockingIOError:
        print('Peer collector already running; retry later')
        return 1
    except Exception as exc:
        record_run('peer_refresh', 'error', str(exc), int((time.monotonic() - started) * 1000))
        print(f'Peer refresh failed: {exc}', file=sys.stderr)
        return 1
    record_run('peer_refresh', result['status'], f"asOf={result['asOf']} · {result['key']} · signals held",
               int((time.monotonic() - started) * 1000))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
