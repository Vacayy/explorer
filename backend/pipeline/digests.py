"""종목별 언급 다이제스트 — 1D(당일) + 롤링 7D.

- KST 기준 날짜 버킷팅 (published_at은 UTC 저장 — 저녁 글이 다음날로 새지 않게)
- 대상: 그날 언급된 모든 종목, 언급 수 상위 DAILY_CAP개 상한
- 재생성 가드: 문서 집합 hash가 바뀐 경우에만 LLM 호출 (30분 cron에서 대부분 no-op)
- 7D는 계층 요약: 창 안의 1D 요약들을 재요약 (싸고 일관적) → 향후 1M도 같은 방식
- 새로운 시각(insights): 이전 요약들을 베이스라인으로 제공하고, 그 내러티브에 없던
  이슈/시각 전환/상충만 별도 추출. 이전 요약이 없으면 null (초기 과잉감지 방지)
"""
import hashlib
import json
from datetime import date, datetime, timedelta, timezone

from database import get_connection
from pipeline.enrich import _call_claude_code, llm_engine

KST = timezone(timedelta(hours=9))
DAILY_CAP = 20      # 하루 다이제스트 생성 종목 상한
EXCERPT = 700

STYLE_RULES = (
    "스타일 규칙:\n"
    "- 두괄식: 첫 문장이 핵심 한 줄, 그 뒤에 전개\n"
    "- 주제가 갈리면 ### 소제목 2~4개로 구분. 문서가 적으면 소제목 없이 한 단락\n"
    "- 자연스러운 한국어 평서체(~다). 번역체 금지('~에 대해 논의되었다' 류),\n"
    "  bullet point는 수치 나열이 꼭 필요할 때만 제한적으로\n"
    "- 문서에 없는 내용 금지. 관측이 상충하면 병기\n"
    "- 분량은 문서 수에 비례: 1~2건이면 2~3문장으로 짧게\n"
)


_ORIENT_TAG = {"past": "[회고]", "current": "[현재]", "forward": "[전망]", "mixed": "[회고+전망]"}


def _orient_tag(d) -> str:
    """문서 행의 시간 방향 태그 (D-021) — 요약이 발행일=사건일로 착각하지 않게."""
    t = _ORIENT_TAG.get((d["time_orientation"] if "time_orientation" in d.keys() else None) or "", "")
    ref = d["reference_period"] if "reference_period" in d.keys() else None
    return f"{t}(대상:{ref})" if (t and ref) else t


def _kst_day_utc_bounds(day_iso: str) -> tuple[str, str]:
    d = date.fromisoformat(day_iso)
    start = datetime(d.year, d.month, d.day, tzinfo=KST).astimezone(timezone.utc)
    return start.isoformat(), (start + timedelta(days=1)).isoformat()


def _hash(parts: list[str]) -> str:
    return hashlib.sha256("|".join(sorted(parts)).encode()).hexdigest()


def _call_json(prompt: str) -> dict:
    raw = _call_claude_code(prompt)
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


def compute_daily(day_iso: str | None = None, stock_code: str | None = None,
                  force: bool = False) -> dict:
    """당일(KST) 언급 종목별 1D 다이제스트.
    stock_code 지정 시 그 종목만(온디맨드 새로고침), force=True면 문서 무변경이어도 재생성.
    period_start=당일이라 ON CONFLICT로 같은 날 기존 행을 덮어쓴다(하루 다중 생성 방지)."""
    if llm_engine() != "claude-code":
        return {"skipped": "claude-code 엔진 아님"}
    day = day_iso or datetime.now(KST).date().isoformat()
    lo, hi = _kst_day_utc_bounds(day)

    conn = get_connection()
    sql = """
        SELECT e.id, e.name, count(*) n
        FROM entity_links el
        JOIN entities e ON el.entity_id = e.id
        JOIN raw_documents rd ON el.doc_id = rd.id
        WHERE el.link_type = 'stock' AND e.type = 'company'
          AND rd.published_at >= ? AND rd.published_at < ?"""
    params: list = [lo, hi]
    if stock_code:
        sql += " AND e.aliases = ?"
        params.append(stock_code)
    sql += " GROUP BY e.id ORDER BY n DESC LIMIT ?"
    params.append(DAILY_CAP)
    stocks = conn.execute(sql, params).fetchall()

    stats = {"day": day, "generated": 0, "unchanged": 0, "failed": 0}
    for s in stocks:
        docs = conn.execute("""
            SELECT DISTINCT rd.id, rd.title, rd.source_type, en.time_orientation,
                   en.reference_period, substr(rd.markdown, 1, ?) ex
            FROM entity_links el JOIN raw_documents rd ON el.doc_id = rd.id
            LEFT JOIN enrichments en ON en.doc_id = rd.id
            WHERE el.entity_id = ? AND el.link_type = 'stock'
              AND rd.published_at >= ? AND rd.published_at < ?
            ORDER BY rd.published_at
        """, (EXCERPT, s["id"], lo, hi)).fetchall()
        h = _hash([str(d["id"]) for d in docs])
        existing = conn.execute(
            "SELECT doc_ids_hash FROM entity_digests WHERE entity_id=? AND period='1d' AND period_start=?",
            (s["id"], day)).fetchone()
        if existing and existing["doc_ids_hash"] == h and not force:
            stats["unchanged"] += 1
            continue

        prior = [r["digest"] for r in conn.execute("""
            SELECT digest FROM entity_digests
            WHERE entity_id=? AND period='1d' AND period_start < ?
            ORDER BY period_start DESC LIMIT 5""", (s["id"], day)) if r["digest"]]

        ctx = "\n\n".join(f"[{d['source_type']}]{_orient_tag(d)} {d['title']}\n{d['ex'] or ''}" for d in docs)
        prior_block = ("\n\n[이전 며칠의 요약 — 새로움 판단 기준]\n" + "\n---\n".join(prior)) if prior else ""
        prompt = (
            f"너는 애널리스트의 데일리 노트를 쓴다. 아래는 '{s['name']}' 관련 {day}(KST) 수집 문서 {len(docs)}건이다.\n"
            "시간 규율: 문서마다 [현재]/[전망]/[회고] 표시가 있다. 오늘 '수집'됐다고 오늘 '일어난' 일이 "
            "아니다 — [전망]은 미래 예상, [회고]는 과거 얘기다. '~라는 전망' vs '~가 일어났다'를 구분해 "
            "써라. 미래 전망을 방금 벌어진 사건처럼 단정하지 마라. "
            "단, 이 대괄호 태그는 입력 주석일 뿐이니 본문에 그대로 쓰지 말고 자연스러운 시제로 녹여라.\n"
            + STYLE_RULES +
            'JSON만 출력: {"digest": "마크다운 요약", "new_insights": "이전 요약들에 없던 새 이슈·시각 전환·상충 관측이 있으면 1~3문장, 없거나 이전 요약이 없으면 null"}\n'
            f"{prior_block}\n\n[오늘 수집 문서 — 표시된 시간 방향 구분]\n{ctx}"
        )
        try:
            data = _call_json(prompt)
            _upsert(conn, s["id"], "1d", day, data, len(docs), h)
            stats["generated"] += 1
        except Exception:
            stats["failed"] += 1

    conn.close()
    return stats


def compute_rolling7(as_of_iso: str | None = None, stock_code: str | None = None,
                     force: bool = False) -> dict:
    """롤링 7일 다이제스트 — 창 안의 1D 요약들을 재요약 (기준일별 아카이브).
    stock_code 지정 시 그 종목만(온디맨드), force=True면 무변경이어도 재생성.
    period_start=기준일(as_of)이라 ON CONFLICT로 같은 날 기존 행을 덮어쓴다."""
    if llm_engine() != "claude-code":
        return {"skipped": "claude-code 엔진 아님"}
    as_of = as_of_iso or datetime.now(KST).date().isoformat()
    win_start = (date.fromisoformat(as_of) - timedelta(days=6)).isoformat()

    conn = get_connection()
    sql = """
        SELECT DISTINCT d.entity_id, e.name FROM entity_digests d
        JOIN entities e ON d.entity_id = e.id
        WHERE d.period='1d' AND d.period_start >= ? AND d.period_start <= ?"""
    params: list = [win_start, as_of]
    if stock_code:
        sql += " AND e.aliases = ?"
        params.append(stock_code)
    sql += " LIMIT ?"
    params.append(DAILY_CAP)
    entities = conn.execute(sql, params).fetchall()

    stats = {"as_of": as_of, "generated": 0, "unchanged": 0, "failed": 0}
    for ent in entities:
        dailies = conn.execute("""
            SELECT period_start, digest, doc_count, doc_ids_hash FROM entity_digests
            WHERE entity_id=? AND period='1d' AND period_start >= ? AND period_start <= ?
            ORDER BY period_start
        """, (ent["entity_id"], win_start, as_of)).fetchall()
        if not dailies:
            continue
        h = _hash([f"{r['period_start']}:{r['doc_ids_hash']}" for r in dailies])
        existing = conn.execute(
            "SELECT doc_ids_hash FROM entity_digests WHERE entity_id=? AND period='7d' AND period_start=?",
            (ent["entity_id"], as_of)).fetchone()
        if existing and existing["doc_ids_hash"] == h and not force:
            stats["unchanged"] += 1
            continue

        prior7 = [r["digest"] for r in conn.execute("""
            SELECT digest FROM entity_digests
            WHERE entity_id=? AND period='7d' AND period_start < ?
            ORDER BY period_start DESC LIMIT 3""", (ent["entity_id"], as_of)) if r["digest"]]

        ctx = "\n\n".join(f"[{r['period_start']}] ({r['doc_count']}건)\n{r['digest']}" for r in dailies)
        prior_block = ("\n\n[이전 주간 요약 — 새로움 판단 기준]\n" + "\n---\n".join(prior7)) if prior7 else ""
        total_docs = sum(r["doc_count"] or 0 for r in dailies)
        prompt = (
            f"너는 애널리스트의 주간 노트를 쓴다. 아래는 '{ent['name']}'의 최근 7일({win_start}~{as_of}) "
            f"일별 요약들이다 (원문서 총 {total_docs}건).\n"
            "일별 나열이 아니라 주 전체의 흐름·전개를 종합해라. 초반과 후반의 변화가 있으면 그 전개를 짚어라.\n"
            + STYLE_RULES +
            'JSON만 출력: {"digest": "마크다운 요약", "new_insights": "이전 주간 요약 대비 새 이슈·시각 전환이 있으면 1~3문장, 없으면 null"}\n'
            f"{prior_block}\n\n[일별 요약]\n{ctx}"
        )
        try:
            data = _call_json(prompt)
            _upsert(conn, ent["entity_id"], "7d", as_of, data, total_docs, h)
            stats["generated"] += 1
        except Exception:
            stats["failed"] += 1

    conn.close()
    return stats
