"""Transcript 팔로우 API (docs/specs/transcript-follow.md, D-061 stage 3).

전용 페이지(2분할 브라우저): 좌 팔로우 기업 그룹 리스트 → 우 선택 기업 컨콜(핵심 정리+원문).
전문은 raw_documents(source_type='transcript')에서, 정리는 transcripts.digest(lazy 생성).
"""
from fastapi import APIRouter, HTTPException
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
        out.append(FollowRow(ticker=r["ticker"], company_name=r["company_name"],
                             group_label=r["group_label"], n_calls=len(calls), latest=latest))
    conn.close()
    return out


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
        "SELECT t.id, t.ticker, t.fiscal_year, t.fiscal_period, t.call_date, t.digest, "
        "rd.markdown, f.company_name FROM transcripts t "
        "JOIN raw_documents rd ON rd.id = t.raw_doc_id "
        "LEFT JOIN transcript_follow f ON f.ticker = t.ticker WHERE t.id=?", (transcript_id,)).fetchone()


@router.get("/detail/{transcript_id}", response_model=Detail)
def detail(transcript_id: int):
    """빠른 조회 — 원문+메타+저장된 정리(없으면 null). 정리 생성은 POST /digest로 분리(수 분 소요)."""
    conn = get_connection()
    row = _detail_row(conn, transcript_id)
    conn.close()
    if not row:
        raise HTTPException(404, "transcript 없음")
    return Detail(transcript_id=row["id"], ticker=row["ticker"],
                  company_name=row["company_name"] or row["ticker"],
                  fiscal_year=row["fiscal_year"], fiscal_period=row["fiscal_period"],
                  call_date=row["call_date"], digest=row["digest"], body=row["markdown"] or "")


@router.post("/detail/{transcript_id}/digest", response_model=Detail)
def compute_digest(transcript_id: int):
    """멱등 정리 생성 — 있으면 즉답, 없으면 sonnet 생성 후 반환(apiComputeQuery, ~수 분)."""
    from pipeline.transcript import digest_one
    conn = get_connection()
    row = _detail_row(conn, transcript_id)
    conn.close()
    if not row:
        raise HTTPException(404, "transcript 없음")
    digest = row["digest"] or digest_one(transcript_id)
    return Detail(transcript_id=row["id"], ticker=row["ticker"],
                  company_name=row["company_name"] or row["ticker"],
                  fiscal_year=row["fiscal_year"], fiscal_period=row["fiscal_period"],
                  call_date=row["call_date"], digest=digest, body=row["markdown"] or "")


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
