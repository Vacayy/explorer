"""종목별 언급 다이제스트 — 캘린더 기준 1D(오늘) · 1W(월~일 주) · 1M(월).

- KST 기준 날짜 버킷팅 (published_at은 UTC 저장 — 저녁 글이 다음날로 새지 않게)
- **캘린더 기준(비롤링)**: 1D=오늘, 1W=월~일 한 주, 1M=한 달. 각 주기는 자기 구간의 raw 문서를
  직접 요약한다(과거 구간엔 하위 1D/1W가 없어 계층·롤링 불가) — D-085.
- 재생성 가드: 문서 집합 hash(doc_ids_hash)가 바뀐 경우에만 LLM 호출 (재진입 대부분 no-op)
- **catch_up(진입 시 소급)**: 오래 밀린 기업은 과거 완결 월을 1M, 이번 달 주를 1W, 오늘을 1D로
  소급 생성(멱등). 상한 CATCHUP_MONTHS개월. 3개월 밀렸으면 3×1M + 이번 달 주 1W들 + 오늘 1D.
- 새로운 시각(insights): 이전 같은 주기 요약들을 베이스라인으로, 그 내러티브에 없던
  이슈/시각 전환/상충만 별도 추출. 이전 요약이 없으면 null (초기 과잉감지 방지)
"""
import hashlib
import json
from datetime import date, datetime, timedelta, timezone

from database import get_connection
from pipeline.enrich import _call_claude_code, llm_engine

KST = timezone(timedelta(hours=9))
DAILY_CAP = 5           # 한 구간 다이제스트 생성 종목 상한 (all-stock 경로).
# 20 → 5 (D-124, 사용자 지시) — 20이면 언급만 튄 종목까지 요약해 아무도 안 읽는 값을 치렀다.
# 상위 5는 Home에 그 내용을 직접 노출하는 단위이기도 하다(읽을 사람이 있는 만큼만 생성).
PRIOR_CAP = 4           # 새로움 판단 베이스라인으로 줄 이전 요약 수
CATCHUP_MONTHS = 3      # 진입 소급 시 과거 월 상한 (cold-start 비용 가드)

STYLE_RULES = (
    "스타일 규칙:\n"
    "- 두괄식: 첫 문장이 핵심 한 줄, 그 뒤에 전개\n"
    "- 주제가 갈리면 ### 소제목 2~4개로 구분. 문서가 적으면 소제목 없이 한 단락\n"
    "- 자연스러운 한국어 평서체(~다). 번역체 금지('~에 대해 논의되었다' 류),\n"
    "  bullet point는 수치 나열이 꼭 필요할 때만 제한적으로\n"
    "- 문서에 없는 내용 금지. 관측이 상충하면 병기\n"
    "- 분량은 문서 수에 비례: 1~2건이면 2~3문장으로 짧게\n"
)

_TIME_RULE = (
    "시간 규율: 문서마다 [현재]/[전망]/[회고] 표시가 있다. '수집'됐다고 그날 '일어난' 일이 아니다 — "
    "[전망]은 미래 예상, [회고]는 과거 얘기다. '~라는 전망' vs '~가 일어났다'를 구분해 써라. "
    "미래 전망을 방금 벌어진 사건처럼 단정하지 마라. 단, 이 대괄호 태그는 입력 주석일 뿐이니 "
    "본문에 그대로 쓰지 말고 자연스러운 시제로 녹여라.\n"
)

# 주기별 설정 — 라벨·문서상한·발췌길이·종합 지시 (긴 구간일수록 문서 많아 발췌 축소)
_CADENCE = {
    "1d": {"label": "데일리", "doc_cap": 40, "excerpt": 700, "intro": "수집 문서",
           "synth": "당일 언급을 핵심 위주로 정리해라."},
    "1w": {"label": "주간", "doc_cap": 60, "excerpt": 450, "intro": "한 주(월~일) 수집 문서",
           "synth": "일별 나열이 아니라 주 전체의 흐름·전개를 종합해라. 초반과 후반의 변화가 있으면 그 전개를 짚어라."},
    "1m": {"label": "월간", "doc_cap": 90, "excerpt": 300, "intro": "한 달 수집 문서",
           "synth": "주·일 단위 나열이 아니라 한 달 전체의 큰 흐름·전환점·반복 주제를 종합해라."},
}


_ORIENT_TAG = {"past": "[회고]", "current": "[현재]", "forward": "[전망]", "mixed": "[회고+전망]"}


def _orient_tag(d) -> str:
    """문서 행의 시간 방향 태그 (D-021) — 요약이 발행일=사건일로 착각하지 않게."""
    t = _ORIENT_TAG.get((d["time_orientation"] if "time_orientation" in d.keys() else None) or "", "")
    ref = d["reference_period"] if "reference_period" in d.keys() else None
    return f"{t}(대상:{ref})" if (t and ref) else t


def _kst_midnight_utc(d: date) -> str:
    """KST 자정 → UTC ISO (published_at 비교용)."""
    return datetime(d.year, d.month, d.day, tzinfo=KST).astimezone(timezone.utc).isoformat()


def _week_monday(d: date) -> date:
    """그 날짜가 속한 주(월~일)의 월요일."""
    return d - timedelta(days=d.weekday())


def _hash(parts: list[str]) -> str:
    return hashlib.sha256("|".join(sorted(parts)).encode()).hexdigest()


def _call_json(prompt: str) -> dict:
    # 기계적 요약 — 확장 사고 불필요 (D-117)
    from pipeline.enrich import EFFORT_MECHANICAL
    raw = _call_claude_code(prompt, effort=EFFORT_MECHANICAL)
    s, e = raw.find("{"), raw.rfind("}")
    return json.loads(raw[s:e + 1])


def _upsert(conn, entity_id, period, period_start, data, doc_count, h):
    conn.execute("""
        INSERT INTO entity_digests (entity_id, period, period_start, digest, insights,
                                    doc_count, doc_ids_hash, model)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'claude-code/haiku')
        ON CONFLICT(entity_id, period, period_start) DO UPDATE SET
            digest=excluded.digest, insights=excluded.insights,
            doc_count=excluded.doc_count, doc_ids_hash=excluded.doc_ids_hash,
            model=excluded.model, created_at=datetime('now')
    """, (entity_id, period, period_start, data.get("digest"),
          data.get("new_insights") or None, doc_count, h))
    conn.commit()


def _compute_bucket(period: str, period_start: str, lo: str, hi: str,
                    stock_code: str | None, force: bool) -> dict:
    """한 캘린더 구간[lo,hi)의 종목별 다이제스트 — 그 구간의 raw 문서를 직접 요약.
    stock_code=None이면 그 구간 언급 종목 전체(상한 DAILY_CAP), 지정 시 그 종목만."""
    if llm_engine() != "claude-code":
        return {"skipped": "claude-code 엔진 아님"}
    cfg = _CADENCE[period]
    conn = get_connection()
    sql = ("SELECT e.id, e.name, count(*) n FROM entity_links el "
           "JOIN entities e ON el.entity_id=e.id JOIN raw_documents rd ON el.doc_id=rd.id "
           "WHERE el.link_type='stock' AND e.type='company' "
           "AND rd.published_at >= ? AND rd.published_at < ?")
    params: list = [lo, hi]
    if stock_code:
        # 종목코드 **또는 이름** (D-124) — 해외·비상장 기업은 aliases(종목코드)가 없다.
        # 생성은 국적 무관이었는데 단일 종목 경로만 코드로 조회해, 코드 없는 기업은
        # catch_up(진행 중 구간)을 탈 방법이 없었다. 같은 값을 두 열에 대조한다.
        sql += " AND (e.aliases = ? OR e.name = ?)"
        params += [stock_code, stock_code]
    sql += " GROUP BY e.id ORDER BY n DESC LIMIT ?"
    params.append(DAILY_CAP)
    stocks = conn.execute(sql, params).fetchall()

    stats = {"period": period, "period_start": period_start,
             "generated": 0, "unchanged": 0, "failed": 0, "empty": 0}
    for s in stocks:
        docs = conn.execute("""
            SELECT DISTINCT rd.id, rd.title, rd.source_type, en.time_orientation,
                   en.reference_period, substr(rd.markdown, 1, ?) ex
            FROM entity_links el JOIN raw_documents rd ON el.doc_id = rd.id
            LEFT JOIN enrichments en ON en.doc_id = rd.id
            WHERE el.entity_id = ? AND el.link_type = 'stock'
              AND rd.published_at >= ? AND rd.published_at < ?
            ORDER BY rd.published_at LIMIT ?
        """, (cfg["excerpt"], s["id"], lo, hi, cfg["doc_cap"])).fetchall()
        if not docs:
            stats["empty"] += 1
            continue
        h = _hash([str(d["id"]) for d in docs])
        existing = conn.execute(
            "SELECT doc_ids_hash FROM entity_digests WHERE entity_id=? AND period=? AND period_start=?",
            (s["id"], period, period_start)).fetchone()
        if existing and existing["doc_ids_hash"] == h and not force:
            stats["unchanged"] += 1
            continue

        prior = [r["digest"] for r in conn.execute("""
            SELECT digest FROM entity_digests
            WHERE entity_id=? AND period=? AND period_start < ?
            ORDER BY period_start DESC LIMIT ?""", (s["id"], period, period_start, PRIOR_CAP)) if r["digest"]]

        ctx = "\n\n".join(f"[{d['source_type']}]{_orient_tag(d)} {d['title']}\n{d['ex'] or ''}" for d in docs)
        prior_block = (f"\n\n[이전 {cfg['label']} 요약 — 새로움 판단 기준]\n" + "\n---\n".join(prior)) if prior else ""
        prompt = (
            f"너는 애널리스트의 {cfg['label']} 노트를 쓴다. 아래는 '{s['name']}' 관련 {period_start} 기준 "
            f"{cfg['intro']} {len(docs)}건이다.\n"
            + _TIME_RULE + cfg["synth"] + "\n" + STYLE_RULES +
            'JSON만 출력: {"digest": "마크다운 요약", "new_insights": "이전 요약들에 없던 새 이슈·시각 전환·'
            '상충 관측이 있으면 1~3문장, 없거나 이전 요약이 없으면 null"}\n'
            f"{prior_block}\n\n[수집 문서 — 표시된 시간 방향 구분]\n{ctx}"
        )
        try:
            data = _call_json(prompt)
            _upsert(conn, s["id"], period, period_start, data, len(docs), h)
            stats["generated"] += 1
        except Exception:
            stats["failed"] += 1

    conn.close()
    return stats


def compute_daily(day_iso: str | None = None, stock_code: str | None = None, force: bool = False) -> dict:
    """당일(KST) 1D 다이제스트. period_start=당일이라 ON CONFLICT로 같은 날 덮어씀."""
    day = day_iso or datetime.now(KST).date().isoformat()
    d = date.fromisoformat(day)
    return _compute_bucket("1d", day, _kst_midnight_utc(d), _kst_midnight_utc(d + timedelta(days=1)),
                           stock_code, force)


def compute_weekly(week_monday_iso: str | None = None, stock_code: str | None = None, force: bool = False) -> dict:
    """한 주(월~일) 1W 다이제스트. period_start=그 주 월요일(비롤링)."""
    base = date.fromisoformat(week_monday_iso) if week_monday_iso else datetime.now(KST).date()
    mon = _week_monday(base)
    return _compute_bucket("1w", mon.isoformat(), _kst_midnight_utc(mon), _kst_midnight_utc(mon + timedelta(days=7)),
                           stock_code, force)


def compute_monthly(month_first_iso: str | None = None, stock_code: str | None = None, force: bool = False) -> dict:
    """한 달 1M 다이제스트. period_start=그 달 1일."""
    mf = (date.fromisoformat(month_first_iso) if month_first_iso else datetime.now(KST).date()).replace(day=1)
    nxt = (mf + timedelta(days=32)).replace(day=1)
    return _compute_bucket("1m", mf.isoformat(), _kst_midnight_utc(mf), _kst_midnight_utc(nxt), stock_code, force)


def catch_up(stock_code: str) -> dict:
    """진입 시 소급 생성 — 과거 완결 월은 1M, 이번 달 주는 1W, 오늘은 1D. 멱등(hash 가드).

    3개월 밀렸으면 3×1M + 이번 달 주 1W들 + 오늘 1D. 이미 있으면 unchanged로 스킵(재진입 무비용).
    """
    if llm_engine() != "claude-code":
        return {"skipped": "claude-code 엔진 아님"}
    today = datetime.now(KST).date()
    cur_first = today.replace(day=1)
    out = {"monthly": 0, "weekly": 0, "daily": 0, "unchanged": 0, "empty": 0}

    def _acc(r):
        for k in ("generated",):
            pass
        out["unchanged"] += r.get("unchanged", 0)
        out["empty"] += r.get("empty", 0)

    # 과거 완결 월 — 오래된 것부터 (baseline 누적)
    mf = cur_first
    prev_months = []
    for _ in range(CATCHUP_MONTHS):
        mf = (mf - timedelta(days=1)).replace(day=1)
        prev_months.append(mf)
    for m in reversed(prev_months):
        r = compute_monthly(m.isoformat(), stock_code=stock_code)
        out["monthly"] += r.get("generated", 0)
        _acc(r)

    # 이번 달 주(월~일) — 이번 달을 건드리는 주의 월요일부터 오늘까지
    wk = _week_monday(cur_first)
    while wk <= today:
        r = compute_weekly(wk.isoformat(), stock_code=stock_code)
        out["weekly"] += r.get("generated", 0)
        _acc(r)
        wk = wk + timedelta(days=7)

    # 오늘
    r = compute_daily(today.isoformat(), stock_code=stock_code)
    out["daily"] += r.get("generated", 0)
    _acc(r)
    return out
