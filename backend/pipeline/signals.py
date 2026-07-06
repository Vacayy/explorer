"""파생 신호 계산 (docs/specs/signals-spine.md).

현재 구현: mention_surge (언급량 급증 종목).
- 최근 7일 종목 언급 수 vs 직전 7일 baseline
- 기준: 최근 7일 ≥ MIN_MENTIONS 그리고 baseline 대비 SURGE_RATIO배 이상
- payload: 카운트, 함께 태깅된 키워드(산업/토픽), 근거 문서(제목/URL)
- interpretation은 비워둠 (LLM 확보 후 hypothesis로 채움)
"""
import json
from datetime import datetime, timedelta, timezone

from database import get_connection
from pipeline.dates import parse_dt as _parse_dt

MIN_MENTIONS = 3      # 최근 7일 최소 언급 수
SURGE_RATIO = 2.0     # baseline 대비 배수 (baseline 0이면 MIN_MENTIONS만으로 성립)



def compute_mention_surge(as_of: datetime | None = None) -> list[dict]:
    as_of = as_of or datetime.now(timezone.utc)
    win_start = as_of - timedelta(days=7)
    base_start = as_of - timedelta(days=14)

    conn = get_connection()
    rows = conn.execute("""
        SELECT el.entity_id, e.name, rd.id doc_id, rd.title, rd.url, rd.published_at
        FROM entity_links el
        JOIN entities e ON el.entity_id = e.id
        JOIN raw_documents rd ON el.doc_id = rd.id
        WHERE el.link_type = 'stock' AND e.type = 'company'
    """).fetchall()

    # 종목별로 최근 7일 / 직전 7일 언급 분류
    recent, baseline = {}, {}
    for r in rows:
        dt = _parse_dt(r["published_at"])
        if dt is None:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if win_start <= dt <= as_of:
            recent.setdefault(r["entity_id"], []).append(r)
        elif base_start <= dt < win_start:
            baseline.setdefault(r["entity_id"], []).append(r)

    signals = []
    for eid, docs in recent.items():
        n, b = len(docs), len(baseline.get(eid, []))
        if n < MIN_MENTIONS or (b > 0 and n < b * SURGE_RATIO):
            continue
        doc_ids = [d["doc_id"] for d in docs]
        # 함께 태깅된 산업/토픽 = "주요 키워드"
        ph = ",".join("?" for _ in doc_ids)
        keywords = [r["name"] for r in conn.execute(f"""
            SELECT e.name, count(*) c FROM entity_links el JOIN entities e ON el.entity_id=e.id
            WHERE el.doc_id IN ({ph}) AND el.link_type IN ('industry','topic')
            GROUP BY e.name ORDER BY c DESC LIMIT 5""", doc_ids)]
        signals.append({
            "entity_id": eid,
            "name": docs[0]["name"],
            "date": as_of.date().isoformat(),
            "payload": {
                "count_7d": n,
                "baseline_7d": b,
                "keywords": keywords,
                "docs": [{"title": d["title"], "url": d["url"]} for d in docs[:5]],
            },
        })

    # upsert
    for s in signals:
        conn.execute("""
            INSERT INTO signals (signal_type, entity_id, date, payload_json)
            VALUES ('mention_surge', ?, ?, ?)
            ON CONFLICT(signal_type, entity_id, date)
            DO UPDATE SET payload_json = excluded.payload_json
        """, (s["entity_id"], s["date"], json.dumps(s["payload"], ensure_ascii=False)))
    conn.commit()
    conn.close()
    return signals
