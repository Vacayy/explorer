"""운영 관리자 API — cron 작업 on/off + 최근 실행 로그 (관리자 페이지, D-055)."""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/spine/admin", tags=["spine"])


class JobStatus(BaseModel):
    name: str
    label: str
    description: str
    entrypoint: str                # 실제 실행되는 스크립트/함수 (가시화)
    enabled: bool
    last_run: dict | None = None   # {status, summary, duration_ms, ran_at}


class JobRun(BaseModel):
    job: str
    status: str
    summary: str | None = None
    duration_ms: int | None = None
    ran_at: str


class FlagBody(BaseModel):
    name: str
    enabled: bool


@router.get("/jobs", response_model=list[JobStatus])
def jobs():
    """관리 대상 작업 목록 — 라벨·on/off·마지막 실행. LLM 없음."""
    from pipeline.ops import JOBS, list_flags
    from database import get_connection
    flags = list_flags()
    conn = get_connection()
    out = []
    for name, label, desc, entrypoint in JOBS:
        lr = conn.execute(
            "SELECT status, summary, duration_ms, ran_at FROM job_runs WHERE job=? "
            "ORDER BY id DESC LIMIT 1", (name,)).fetchone()
        out.append(JobStatus(
            name=name, label=label, description=desc, entrypoint=entrypoint,
            enabled=flags.get(name, True),
            last_run=dict(lr) if lr else None))
    conn.close()
    return out


class HealthItem(BaseModel):
    key: str
    label: str
    kind: str                      # trading | age | launchd
    owner: str                     # 이 데이터를 채우는 작업
    critical: bool                 # True면 홈·텔레그램 경고에도 오른다
    latest: str | None = None
    expected: str | None = None
    status: str                    # ok | stale | error
    detail: str = ""


@router.get("/health", response_model=list[HealthItem])
def health():
    """데이터 신선도 점검 (D-222) — 결과 데이터의 최신 시점을 기대치와 비교. LLM 없음."""
    from pipeline.health import report
    from database import get_connection
    conn = get_connection()
    try:
        return [HealthItem(**i) for i in report(conn)]
    finally:
        conn.close()


@router.get("/runs", response_model=list[JobRun])
def runs(limit: int = 50):
    """최근 작업 실행 내역 — 뭐가 언제 돌았고 무엇이 바뀌었나. LLM 없음."""
    from pipeline.ops import recent_runs
    return [JobRun(**r) for r in recent_runs(limit)]


@router.post("/flag")
def set_flag(body: FlagBody):
    """작업 on/off 토글."""
    from pipeline.ops import set_flag as _set
    _set(body.name, body.enabled)
    return {"ok": True, "name": body.name, "enabled": body.enabled}
