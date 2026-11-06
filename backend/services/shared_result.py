"""같은 계산을 동시에·연달아 부르면 한 번만 한다 — 짧은 인프로세스 메모 (API 성능 A단계 ⑦, D-324).

홈 › 매크로는 첫 화면에서 era.get_state()를 두 API(/regimes/state·/regimes/commentary)가 동시에 부른다.
같은 키는 잠금으로 하나만 계산하고, 기다린 요청은 그 결과를 받는다.

묵은 값 방지: 결과에 '요청이 들어온 순간의 DB 상태'(PRAGMA data_version)를 붙여 둔다. data_version은 다른 연결·
프로세스가 무엇이든 커밋하면 바뀌므로, 그 뒤에 들어온 요청은 다시 계산한다. TTL(5분)은 그 위의 안전판이다.
"""
import sqlite3
import threading
import time
from typing import Any, Callable

import database

TTL_SECONDS = 300

_lock = threading.Lock()
_key_locks: dict[tuple, threading.Lock] = {}
_entries: dict[tuple, tuple[float, tuple, Any]] = {}   # key → (계산 시각, DB 상태, 결과)
_probe: tuple[str, sqlite3.Connection, int] | None = None   # data_version을 읽는 전용 연결(쓰지 않는다)·세대


def _db_state() -> tuple:
    global _probe
    path = str(database.DB_PATH)
    with _lock:
        if _probe is None or _probe[0] != path:
            generation = _probe[2] + 1 if _probe else 0   # data_version은 연결마다 따로 센다 — 새 연결이면 이전 결과를 쓰지 않게
            if _probe is not None:
                _probe[1].close()
            _probe = (path, sqlite3.connect(path, check_same_thread=False), generation)
        return path, _probe[2], _probe[1].execute("PRAGMA data_version").fetchone()[0]


def shared(key: tuple, compute: Callable[[], Any], ttl: float = TTL_SECONDS) -> Any:
    """key가 같고 그 사이 DB 커밋이 없었으면 직전 결과를 돌려준다. 결과는 여러 요청이 함께 쓰므로 고치지 않는다."""
    state = _db_state()   # 들어온 순간의 DB 상태 — 이보다 늦게 끝난 계산이라도 이 상태와 같을 때만 쓴다
    with _lock:
        key_lock = _key_locks.setdefault(key, threading.Lock())
    with key_lock:
        hit = _entries.get(key)
        if hit and hit[1] == state and time.monotonic() - hit[0] < ttl:
            return hit[2]
        value = compute()
        _entries[key] = (time.monotonic(), state, value)
        return value
