"""Transcript 팔로우 API (docs/specs/transcript-follow.md, D-061 stage 3).

전용 페이지(2분할 브라우저): 좌 팔로우 기업 그룹 리스트 → 우 선택 기업 컨콜(핵심 정리+원문).
전문은 raw_documents(source_type='transcript')에서, 정리는 transcripts.digest(lazy 생성).
"""
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from database import get_connection

router = APIRouter(prefix="/api/spine/transcript", tags=["spine"])


class LatestCall(BaseModel):
    transcript_id: int
    fiscal_year: int | None
    fiscal_period: str | None
    call_date: str | None
    has_digest: bool


class FollowRow(BaseModel):
    ticker: str
    company_name: str
    group_label: str | None
    n_calls: int
    latest: LatestCall | None
    last_report_date: str | None = None   # yfinance 실적 발표일 캐시 (D-081)
    next_report_date: str | None = None


class QuarterRow(BaseModel):
    transcript_id: int
    fiscal_year: int | None
    fiscal_period: str | None
    call_date: str | None
    has_digest: bool


class Detail(BaseModel):
    transcript_id: int
    ticker: str
    company_name: str
    fiscal_year: int | None
    fiscal_period: str | None
    call_date: str | None
    digest: str | None
    body: str
    proxies: list = []   # stage 4에서 채움 (proxy_observations 델타)
    nodes: list = []          # 이 콜이 언급한 엔티티(노드) — 온톨로지 딥링크 (D-089)
    causal_edges: list = []   # 이 콜에서 추출된 인과 엣지 (source_doc_id, D-089)


class FollowReq(BaseModel):
    ticker: str
    company_name: str | None = None
    group_label: str | None = None
    active: bool = True


@router.get("/follow", response_model=list[FollowRow])
def list_follow():
    conn = get_connection()
    rows = conn.execute("SELECT ticker, company_name, group_label FROM transcript_follow "
                        "WHERE active=1 ORDER BY group_label, ticker").fetchall()
    cal = {r["ticker"]: r for r in conn.execute(
        "SELECT ticker, last_report_date, next_report_date FROM transcript_calendar").fetchall()}
    out = []
    for r in rows:
        calls = conn.execute(
            "SELECT id, fiscal_year, fiscal_period, call_date, digest FROM transcripts "
            "WHERE ticker=? ORDER BY fiscal_year DESC, fiscal_period DESC", (r["ticker"],)).fetchall()
        latest = None
        if calls:
            c = calls[0]
            latest = LatestCall(transcript_id=c["id"], fiscal_year=c["fiscal_year"],
                                fiscal_period=c["fiscal_period"], call_date=c["call_date"],
                                has_digest=bool(c["digest"]))
        cr = cal.get(r["ticker"])
        out.append(FollowRow(ticker=r["ticker"], company_name=r["company_name"],
                             group_label=r["group_label"], n_calls=len(calls), latest=latest,
                             last_report_date=cr["last_report_date"] if cr else None,
                             next_report_date=cr["next_report_date"] if cr else None))
    conn.close()
    return out


JOB = "collect_transcripts"
_collect_lock = threading.Lock()
_collecting: dict = {"running": False, "started_at": None, "budget": None}


def _run_collect(budget: int, only: list[str] | None) -> None:
    """백그라운드 수집 — run_job으로 감싸 플래그 게이트·job_runs 기록을 그대로 받는다."""
    from pipeline.ops import run_job
    from pipeline.transcript import collect_and_process
    try:
        run_job(JOB, lambda: collect_and_process(budget=budget, only=only))
    except Exception as e:  # noqa: BLE001 — run_job이 이미 error를 기록했다. 여기선 플래그만 해제
        print(f"[transcript] 수집 실패: {type(e).__name__}: {str(e)[:200]}", flush=True)
    finally:
        _collecting.update(running=False)


@router.post("/collect")
def collect(background: BackgroundTasks, budget: int = 22, dry_run: bool = False,
            tickers: str | None = None):
    """컨콜 수집 직접 트리거 (D-121).

    실행 1회가 **~20분**(AV 무료 한도 5/min 때문에 요청마다 sleep)이라 동기 응답이 불가능하다 →
    백그라운드로 넘기고 즉시 반환, 진행은 `GET /collect/status`로 본다.
    `dry_run=1`은 외부 호출·예산 소모 없이 '무엇을 요청할지' 계획만 즉시 반환(25/day를
    한 번의 클릭으로 태우기 전에 확인용).
    """
    from pipeline.ops import flag_enabled
    from pipeline.transcript import _followed, collect_roundrobin, seed_default_follows

    only = [t.strip().upper() for t in (tickers or "").split(",") if t.strip()] or None
    if not _followed(only):
        if only:
            raise HTTPException(400, "해당 티커의 활성 팔로우가 없습니다")
        seed_default_follows()

    if dry_run:      # 예산 0 — 계획만 (DB 조회뿐, 외부 fetch 없음)
        plan = collect_roundrobin(only=only, dry_run=True)
        return {"dry_run": True, "budget": budget,
                "would_request": plan["would_request"], "skipped_cache": plan["skipped_cache"],
                "planned": plan["planned"][:budget],
                "over_budget": max(0, plan["would_request"] - budget)}

    # 관리자 플래그가 off면 조용히 skip되지 않게 여기서 막고 이유를 돌려준다(조용한 fallback 금지)
    if not flag_enabled(JOB):
        raise HTTPException(409, "관리자 페이지에서 '컨콜 수집' 작업이 off 상태입니다")
    # 중복 실행 가드 — 두 번 누르면 하루 예산(25)을 두 배로 태운다
    with _collect_lock:
        if _collecting["running"]:
            raise HTTPException(409, "이미 수집이 진행 중입니다")
        _collecting.update(running=True, started_at=datetime.now(timezone.utc).isoformat(),
                           budget=budget)
    background.add_task(_run_collect, budget, only)
    return {"started": True, "budget": budget, "tickers": only}


@router.get("/collect/status")
def collect_status():
    """진행 중 여부 + 마지막 실행 결과(job_runs) + 플래그 상태 — 버튼이 결과를 말할 수 있게."""
    from pipeline.ops import flag_enabled
    conn = get_connection()
    row = conn.execute(
        "SELECT status, summary, duration_ms, ran_at FROM job_runs WHERE job=? "
        "ORDER BY id DESC LIMIT 1", (JOB,)).fetchone()
    conn.close()
    return {"running": _collecting["running"], "started_at": _collecting["started_at"],
            "budget": _collecting["budget"], "enabled": flag_enabled(JOB),
            "last_run": dict(row) if row else None}


@router.post("/calendar/refresh")
def refresh_earnings_calendar():
    """yfinance 실적 발표일 캐시 갱신 (무료·AV 예산 무관, D-081). 활성 팔로우 전체. ~수십초."""
    from pipeline.transcript import refresh_calendar, _followed
    tickers = [c["ticker"] for c in _followed()]
    n = refresh_calendar(tickers, max_age_hours=0)   # 강제 갱신
    return {"refreshed": n}


@router.get("/company/{ticker}", response_model=list[QuarterRow])
def list_quarters(ticker: str):
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, fiscal_year, fiscal_period, call_date, digest FROM transcripts "
        "WHERE ticker=? ORDER BY fiscal_year DESC, fiscal_period DESC", (ticker.upper(),)).fetchall()
    conn.close()
    return [QuarterRow(transcript_id=r["id"], fiscal_year=r["fiscal_year"],
                       fiscal_period=r["fiscal_period"], call_date=r["call_date"],
                       has_digest=bool(r["digest"])) for r in rows]


def _detail_row(conn, transcript_id: int):
    return conn.execute(
        "SELECT t.id, t.raw_doc_id, t.ticker, t.fiscal_year, t.fiscal_period, t.call_date, t.digest, "
        "rd.markdown, f.company_name FROM transcripts t "
        "JOIN raw_documents rd ON rd.id = t.raw_doc_id "
        "LEFT JOIN transcript_follow f ON f.ticker = t.ticker WHERE t.id=?", (transcript_id,)).fetchone()


def _doc_graph(conn, raw_doc_id: int) -> dict:
    """이 콜 문서가 붙인 노드(entity_links)·추출한 인과 엣지(source_doc_id) — 온톨로지 딥링크용 (D-089)."""
    nodes = [dict(r) for r in conn.execute(
        "SELECT DISTINCT e.id, e.name, e.type, el.link_type FROM entity_links el "
        "JOIN entities e ON e.id = el.entity_id WHERE el.doc_id = ? "
        "ORDER BY el.confidence DESC, e.name LIMIT 30", (raw_doc_id,)).fetchall()]
    edges = [dict(r) for r in conn.execute(
        "SELECT er.rel_type, er.effect_direction, s.id from_id, s.name \"from\", s.type from_type, "
        "  d.id to_id, d.name \"to\", d.type to_type "
        "FROM entity_relations er JOIN entities s ON s.id=er.src_id JOIN entities d ON d.id=er.dst_id "
        "WHERE er.source_doc_id = ? AND er.rel_type IN ('CAUSES','BENEFITS_FROM') ORDER BY er.id", (raw_doc_id,)).fetchall()]
    return {"nodes": nodes, "edges": edges}


def _build_detail(conn, row) -> "Detail":
    g = _doc_graph(conn, row["raw_doc_id"])
    return Detail(transcript_id=row["id"], ticker=row["ticker"],
                  company_name=row["company_name"] or row["ticker"],
                  fiscal_year=row["fiscal_year"], fiscal_period=row["fiscal_period"],
                  call_date=row["call_date"], digest=row["digest"], body=row["markdown"] or "",
                  nodes=g["nodes"], causal_edges=g["edges"])


@router.get("/detail/{transcript_id}", response_model=Detail)
def detail(transcript_id: int):
    """빠른 조회 — 원문+메타+저장된 정리(없으면 null). 정리 생성은 POST /digest로 분리(수 분 소요)."""
    conn = get_connection()
    row = _detail_row(conn, transcript_id)
    if not row:
        conn.close()
        raise HTTPException(404, "transcript 없음")
    d = _build_detail(conn, row)
    conn.close()
    return d


@router.post("/detail/{transcript_id}/digest", response_model=Detail)
def compute_digest(transcript_id: int):
    """멱등 정리 생성 — 있으면 즉답, 없으면 sonnet 생성 후 반환(apiComputeQuery, ~수 분)."""
    from pipeline.transcript import digest_one
    conn = get_connection()
    row = _detail_row(conn, transcript_id)
    if not row:
        conn.close()
        raise HTTPException(404, "transcript 없음")
    if not row["digest"]:
        digest_one(transcript_id)
        row = _detail_row(conn, transcript_id)   # digest 반영분 재조회
    d = _build_detail(conn, row)
    conn.close()
    return d


@router.post("/follow", status_code=201)
def upsert_follow(body: FollowReq):
    conn = get_connection()
    conn.execute(
        "INSERT INTO transcript_follow (ticker, company_name, group_label, active) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(ticker) DO UPDATE SET active=excluded.active, "
        "company_name=COALESCE(excluded.company_name, transcript_follow.company_name), "
        "group_label=COALESCE(excluded.group_label, transcript_follow.group_label)",
        (body.ticker.upper(), body.company_name or body.ticker.upper(), body.group_label,
         1 if body.active else 0))
    conn.commit()
    conn.close()
    return {"ticker": body.ticker.upper(), "active": body.active}


@router.post("/seed")
def seed():
    from pipeline.transcript import seed_default_follows
    return {"seeded": seed_default_follows()}


# ---------- 프록시 (관찰 선행지표, D-061 stage 4) ----------

class ProxyObs(BaseModel):
    observed_at: str | None
    value_num: float | None
    value_text: str | None
    direction: str | None
    ticker: str | None
    transcript_id: int | None


class ProxyRow(BaseModel):
    id: int
    key: str
    label: str
    unit: str | None
    tickers: str | None
    latest: ProxyObs | None
    series: list[ProxyObs]


class ProxyReq(BaseModel):
    key: str
    label: str
    tickers: str | None = None
    unit: str | None = None
    extract_hint: str | None = None


@router.get("/proxies", response_model=list[ProxyRow])
def list_proxies():
    conn = get_connection()
    proxies = conn.execute("SELECT id, key, label, unit, tickers FROM proxy_registry WHERE active=1 ORDER BY id").fetchall()
    out = []
    for p in proxies:
        obs = conn.execute(
            "SELECT o.observed_at, o.value_num, o.value_text, o.direction, t.ticker, o.transcript_id "
            "FROM proxy_observations o LEFT JOIN transcripts t ON t.id = o.transcript_id "
            "WHERE o.proxy_id=? ORDER BY o.observed_at", (p["id"],)).fetchall()
        series = [ProxyObs(**dict(r)) for r in obs]
        out.append(ProxyRow(id=p["id"], key=p["key"], label=p["label"], unit=p["unit"],
                            tickers=p["tickers"], latest=series[-1] if series else None, series=series))
    conn.close()
    return out


@router.post("/proxies", status_code=201)
def create_proxy(body: ProxyReq):
    conn = get_connection()
    conn.execute(
        "INSERT INTO proxy_registry (key, label, tickers, unit, extract_hint) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET label=excluded.label, tickers=excluded.tickers, "
        "unit=excluded.unit, extract_hint=excluded.extract_hint",
        (body.key, body.label, body.tickers, body.unit, body.extract_hint))
    conn.commit()
    conn.close()
    return {"key": body.key}


@router.post("/proxies/extract")
def run_extract():
    """관찰 프록시 추출 트리거 (멱등, haiku). 프록시 없으면 기본 시드 먼저."""
    from pipeline.transcript import extract_proxies, seed_proxies
    seed_proxies()
    return extract_proxies()
