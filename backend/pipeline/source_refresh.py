"""소스 즉시 수집 (D-199): 텔레그램 채널·유튜브 채널·블로그 하나를 버튼으로 지금 수집한다.

30분 cron 체인(run_chain.sh → scripts/ingest.py)을 기다리지 않고, 같은 커넥터·같은 적재 경로(run_source →
store_document, 새 문서만 enrich)를 소스 하나에만 돌린다. 백그라운드 스레드로 돌리고 상태는 프로세스 메모리에
둔다(같은 소스가 이미 돌고 있으면 그 상태를 돌려준다). 실행 기록은 job_runs('refresh_source')에 남긴다.
"""
from __future__ import annotations

from datetime import datetime, timezone
import threading

KINDS = {"telegram": ("telegram_channels", "channel_name"),
         "blog": ("blog_sources", "url"),
         "youtube": ("youtube_channels", "channel_id")}
STALE_SECONDS = 15 * 60   # 이 시간 넘게 running이면 스레드가 죽은 것으로 보고 다시 시작을 허용

_LOCK = threading.Lock()
_STATE: dict[tuple[str, str], dict] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _age(iso: str) -> float:
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds()


def registered(conn, kind: str, key: str) -> bool:
    table, column = KINDS[kind]
    return conn.execute(f"SELECT 1 FROM {table} WHERE {column}=?", (key,)).fetchone() is not None


def connector_for(kind: str, key: str):
    if kind == "telegram":
        from pipeline.connectors.telegram import TelegramConnector
        return TelegramConnector([key])
    if kind == "blog":
        from pipeline.connectors.blog import BlogConnector
        return BlogConnector([key])
    from pipeline.connectors.youtube import YouTubeConnector
    return YouTubeConnector(channel_ids=[key])


def status(kind: str, key: str) -> dict:
    with _LOCK:
        state = _STATE.get((kind, key))
        return dict(state) if state else {"kind": kind, "key": key, "status": "idle", "started_at": None,
                                          "finished_at": None, "stats": None, "error": None}


def start(kind: str, key: str, *, runner=None, connector_factory=None) -> dict:
    """수집을 시작하고 상태를 돌려준다. 이미 돌고 있으면(15분 이내) 새로 시작하지 않고 그 상태를 돌려준다."""
    if kind not in KINDS:
        raise ValueError("unknown kind")
    with _LOCK:
        current = _STATE.get((kind, key))
        if current and current["status"] == "running" and _age(current["started_at"]) < STALE_SECONDS:
            return {**current, "already_running": True}
        state = {"kind": kind, "key": key, "status": "running", "started_at": _now(), "finished_at": None,
                 "stats": None, "error": None}
        _STATE[(kind, key)] = state
    thread = threading.Thread(target=_run, args=(kind, key, runner, connector_factory), daemon=True, name=f"refresh-{kind}")
    thread.start()
    return dict(state)


def _run(kind: str, key: str, runner=None, connector_factory=None) -> None:
    from pipeline.ops import run_job
    from pipeline.runner import run_source
    execute = runner or run_source
    build = connector_factory or connector_for

    def work():
        stats = execute(build(kind, key))
        return {"source": f"{kind}:{key}", **stats}

    finish = {}
    try:
        result = run_job("refresh_source", work)
        finish = {"status": "done", "stats": result} if result is not None else {"status": "skipped", "error": "관리자가 '소스 즉시 수집' 작업을 꺼 두었습니다."}
    except Exception as exc:  # noqa: BLE001 — 상태에 남기고 스레드는 조용히 끝난다
        finish = {"status": "error", "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    with _LOCK:
        _STATE[(kind, key)].update(finished_at=_now(), **finish)
