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

MIN_HISTORY_ROWS = 200  # 52주 신고가 판정에 필요한 최소 일봉 수 (신규상장 오탐 방지)



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
                "docs": [{"id": d["doc_id"], "title": d["title"], "url": d["url"]} for d in docs[:5]],
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


def compute_high_52w() -> list[dict]:
    """52주 신고가 스캔: 최신 거래일 고가가 직전 52주(365일) 최고가를 경신한 종목.

    - MIN_HISTORY_ROWS 미만 종목 제외 (신규상장·데이터 부족 오탐 방지)
    - payload: 종가/고가/전고점/경신폭. 근거는 가격 데이터 자체.
    """
    conn = get_connection()
    latest = conn.execute("SELECT max(trade_date) FROM stock_prices").fetchone()[0]
    if not latest:
        conn.close()
        return []

    rows = conn.execute("""
        SELECT sp.stock_code, sp.close, sp.high,
               (SELECT max(p.high) FROM stock_prices p
                WHERE p.stock_code = sp.stock_code
                  AND p.trade_date < sp.trade_date
                  AND p.trade_date >= date(sp.trade_date, '-365 days')) AS prior_high,
               (SELECT count(*) FROM stock_prices p
                WHERE p.stock_code = sp.stock_code
                  AND p.trade_date >= date(sp.trade_date, '-365 days')) AS n_days
        FROM stock_prices sp
        WHERE sp.trade_date = ? AND sp.high IS NOT NULL
    """, (latest,)).fetchall()

    # 종목코드 → entity 매핑
    ent = {r["aliases"]: (r["id"], r["name"]) for r in conn.execute(
        "SELECT id, name, aliases FROM entities WHERE type='company' AND aliases IS NOT NULL")}

    signals = []
    for r in rows:
        if (r["n_days"] or 0) < MIN_HISTORY_ROWS or not r["prior_high"]:
            continue
        if r["high"] <= r["prior_high"]:
            continue
        e = ent.get(r["stock_code"])
        if not e:
            continue
        breakout_pct = round((r["high"] / r["prior_high"] - 1) * 100, 2)
        signals.append({
            "entity_id": e[0],
            "name": e[1],
            "date": latest,
            "payload": {
                "close": r["close"], "high": r["high"],
                "prior_high_52w": r["prior_high"], "breakout_pct": breakout_pct,
            },
        })

    for s in signals:
        conn.execute("""
            INSERT INTO signals (signal_type, entity_id, date, payload_json)
            VALUES ('high_52w', ?, ?, ?)
            ON CONFLICT(signal_type, entity_id, date)
            DO UPDATE SET payload_json = excluded.payload_json
        """, (s["entity_id"], s["date"], json.dumps(s["payload"], ensure_ascii=False)))
    conn.commit()
    conn.close()
    return signals


NEGLECT_MAX_PER = 12.0    # 저평가 스크린
NEGLECT_MIN_ROE = 5.0     # 수익성 (흑자·자본효율)
NEGLECT_MIN_MCAP = 1e11   # 1,000억 — 실체 없는 초소형 제외
NEGLECT_WINDOW_DAYS = 30  # 이 기간 언급 0 = 소외
NEGLECT_LIMIT = 20


def compute_neglect() -> list[dict]:
    """소외 신호 — mention_surge의 쌍대 (knowledge-hierarchy-design §G 태도 3).

    '괜찮은데(저PER·흑자·실체 규모) 아무도 말하지 않는(30일 언급 0)' 종목.
    주목의 부재는 비효율을 낳는다 — 소외 자체가 기회의 신호. LLM 0.
    """
    conn = get_connection()
    latest_fu = conn.execute("SELECT max(trade_date) FROM fundamentals").fetchone()[0]
    if not latest_fu:
        conn.close()
        return []

    rows = conn.execute("""
        WITH latest_px AS (
            SELECT stock_code, market_cap FROM stock_prices
            WHERE (stock_code, trade_date) IN (
                SELECT stock_code, max(trade_date) FROM stock_prices GROUP BY stock_code)
        ),
        mentioned AS (
            SELECT DISTINCT e.aliases stock_code
            FROM entity_links el
            JOIN entities e ON el.entity_id = e.id
            JOIN raw_documents rd ON el.doc_id = rd.id
            WHERE el.link_type='stock' AND e.type='company' AND e.aliases IS NOT NULL
              AND rd.published_at >= datetime('now', ?)
        )
        SELECT f.stock_code, f.per, f.roe, p.market_cap, c.corp_name, co_e.id entity_id,
               c.market
        FROM fundamentals f
        JOIN latest_px p ON p.stock_code = f.stock_code
        JOIN companies c ON c.stock_code = f.stock_code
        JOIN entities co_e ON co_e.aliases = f.stock_code AND co_e.type='company'
        WHERE f.trade_date = ?
          AND f.per > 0 AND f.per <= ?
          AND f.roe >= ?
          AND p.market_cap >= ?
          AND f.stock_code NOT IN (SELECT stock_code FROM mentioned)
        ORDER BY f.per ASC LIMIT ?
    """, (f"-{NEGLECT_WINDOW_DAYS} days", latest_fu, NEGLECT_MAX_PER,
          NEGLECT_MIN_ROE, NEGLECT_MIN_MCAP, NEGLECT_LIMIT)).fetchall()

    signals = []
    today = datetime.now(timezone.utc).date().isoformat()
    for r in rows:
        signals.append({
            "entity_id": r["entity_id"], "name": r["corp_name"], "date": today,
            "payload": {
                "per": r["per"], "roe": r["roe"], "market_cap": r["market_cap"],
                "market": r["market"], "window_days": NEGLECT_WINDOW_DAYS,
            },
        })
    for s in signals:
        conn.execute("""
            INSERT INTO signals (signal_type, entity_id, date, payload_json)
            VALUES ('neglect', ?, ?, ?)
            ON CONFLICT(signal_type, entity_id, date)
            DO UPDATE SET payload_json = excluded.payload_json
        """, (s["entity_id"], s["date"], json.dumps(s["payload"], ensure_ascii=False)))
    conn.commit()
    conn.close()
    return signals


VOLSPIKE_RATIO = 3.0        # 60일 평균 거래량 대비 배수
VOLSPIKE_MIN_CHANGE = 3.0   # 종가 등락 절대값 % (장대봉 요건)
VOLSPIKE_MIN_MCAP = 1e11    # 시총 1000억+ (저유동성 잡음 배제)
VOLSPIKE_MIN_HIST = 20      # 평균 계산 최소 일수
VOLSPIKE_LIMIT = 15


def compute_volume_spike() -> list[dict]:
    """거래량 급증 신호 — '거래량이 터진 날 = 시장의 생각이 바뀐 날' (추세 패턴 문서).

    가격·거래량 데이터와 수집 문서를 결합: 급증일 전후 언급 문서를 payload에
    붙여 '그날 무슨 일이 있었나'를 1클릭으로. 해석(매집/분산/재료소멸)은
    interpret_pending이 문서 근거로 채운다. LLM 0 (해석 제외).
    """
    conn = get_connection()
    latest = conn.execute("SELECT max(trade_date) d FROM stock_prices").fetchone()["d"]
    if not latest:
        conn.close()
        return []
    rows = conn.execute(f"""
        WITH cur AS (
            SELECT stock_code, volume, close, market_cap FROM stock_prices WHERE trade_date = ?
        ),
        hist AS (
            SELECT stock_code, avg(volume) avg_vol, count(*) n
            FROM stock_prices
            WHERE trade_date < ? AND trade_date >= date(?, '-90 days') AND volume > 0
            GROUP BY stock_code
        )
        SELECT c.stock_code, c.volume, c.close, c.market_cap, h.avg_vol,
               co.corp_name, e.id entity_id
        FROM cur c
        JOIN hist h ON h.stock_code = c.stock_code AND h.n >= {VOLSPIKE_MIN_HIST}
        JOIN companies co ON co.stock_code = c.stock_code
        JOIN entities e ON e.type='company' AND e.aliases = c.stock_code
        WHERE c.volume >= h.avg_vol * {VOLSPIKE_RATIO}
          AND c.market_cap >= {VOLSPIKE_MIN_MCAP}
        ORDER BY c.volume / h.avg_vol DESC
    """, (latest, latest, latest)).fetchall()

    signals = []
    for r in rows:
        prev = conn.execute("""
            SELECT close FROM stock_prices WHERE stock_code=? AND trade_date < ?
            ORDER BY trade_date DESC LIMIT 1""", (r["stock_code"], latest)).fetchone()
        if not prev or not prev["close"]:
            continue
        change_pct = (r["close"] - prev["close"]) / prev["close"] * 100
        if abs(change_pct) < VOLSPIKE_MIN_CHANGE:
            continue
        docs = conn.execute("""
            SELECT rd.id, rd.title, rd.url FROM entity_links el
            JOIN raw_documents rd ON rd.id = el.doc_id
            WHERE el.entity_id=? AND el.link_type='stock'
              AND date(rd.published_at) BETWEEN date(?, '-1 day') AND date(?, '+1 day')
            ORDER BY rd.published_at DESC LIMIT 5""",
            (r["entity_id"], latest, latest)).fetchall()
        signals.append({
            "entity_id": r["entity_id"], "name": r["corp_name"], "date": latest,
            "payload": {
                "volume": r["volume"], "avg_vol_60d": round(r["avg_vol"]),
                "ratio": round(r["volume"] / r["avg_vol"], 1),
                "change_pct": round(change_pct, 1),
                "direction": "up" if change_pct > 0 else "down",
                "docs": [{"id": d["id"], "title": d["title"], "url": d["url"]} for d in docs],
            },
        })
        if len(signals) >= VOLSPIKE_LIMIT:
            break
    for s in signals:
        conn.execute("""
            INSERT INTO signals (signal_type, entity_id, date, payload_json)
            VALUES ('volume_spike', ?, ?, ?)
            ON CONFLICT(signal_type, entity_id, date)
            DO UPDATE SET payload_json = excluded.payload_json
        """, (s["entity_id"], s["date"], json.dumps(s["payload"], ensure_ascii=False)))
    conn.commit()
    conn.close()
    return signals


QUAD_RETURN_DOWN = -10.0   # 3개월 수익률 '부진' 임계 (%)
QUAD_RETURN_UP = 30.0      # 3개월 수익률 '선반영 급등' 임계 (%)
QUAD_MIN_DOCS = 5          # 감성 방향 판정 최소 문서 수 (30일)
QUAD_POS_RATIO = 0.65      # 개선 인식 임계
QUAD_NEG_RATIO = 0.40      # 악화 인식 임계
QUAD_LIMIT = 10


def compute_quadrant_gap() -> list[dict]:
    """4분면 갭 신호 (추세 패턴 문서 §3) — 주가 × 펀더멘탈 인식의 괴리. LLM 0.

    - C(기회): 주가 부진 + 관측 개선 — '시장이 아직 모르는 구간?'
    - D_RISK(경고): 주가 급등 + 관측 악화 — 'B(선반영)가 D(함정)로 전환?'
    펀더멘탈 축은 30일 언급 문서 감성을 프록시로 쓴다 (실적 컨센서스 이력이
    쌓이기 전까지의 정직한 근사 — payload에 근거 수치 동봉).
    """
    conn = get_connection()
    latest = conn.execute("SELECT max(trade_date) d FROM stock_prices").fetchone()["d"]
    if not latest:
        conn.close()
        return []
    rows = conn.execute("""
        SELECT el.entity_id, e.name, e.aliases stock_code,
               SUM(en.sentiment='positive') pos, SUM(en.sentiment='negative') neg
        FROM entity_links el
        JOIN entities e ON e.id = el.entity_id AND e.type='company' AND e.aliases IS NOT NULL
        JOIN raw_documents rd ON rd.id = el.doc_id
        JOIN enrichments en ON en.doc_id = rd.id
        WHERE el.link_type='stock' AND rd.published_at >= datetime('now', '-30 days')
          AND en.sentiment IN ('positive','negative')
        GROUP BY el.entity_id HAVING pos + neg >= ?""", (QUAD_MIN_DOCS,)).fetchall()

    signals = []
    for r in rows:
        px = conn.execute("""
            SELECT (SELECT close FROM stock_prices WHERE stock_code=? AND trade_date=?) cur,
                   (SELECT close FROM stock_prices WHERE stock_code=? AND trade_date <= date(?, '-90 days')
                    ORDER BY trade_date DESC LIMIT 1) base""",
            (r["stock_code"], latest, r["stock_code"], latest)).fetchone()
        if not px or not px["cur"] or not px["base"]:
            continue
        ret_3m = (px["cur"] - px["base"]) / px["base"] * 100
        n = r["pos"] + r["neg"]
        pos_ratio = r["pos"] / n
        quadrant = None
        if ret_3m <= QUAD_RETURN_DOWN and pos_ratio >= QUAD_POS_RATIO:
            quadrant = "C"
        elif ret_3m >= QUAD_RETURN_UP and (r["neg"] / n) >= QUAD_NEG_RATIO:
            quadrant = "D_RISK"
        if not quadrant:
            continue
        signals.append({
            "entity_id": r["entity_id"], "name": r["name"], "date": latest,
            "payload": {"quadrant": quadrant, "return_3m": round(ret_3m, 1),
                        "pos": r["pos"], "neg": r["neg"], "window_days": 30},
        })
    signals = signals[:QUAD_LIMIT]
    for s in signals:
        conn.execute("""
            INSERT INTO signals (signal_type, entity_id, date, payload_json)
            VALUES ('quadrant_gap', ?, ?, ?)
            ON CONFLICT(signal_type, entity_id, date)
            DO UPDATE SET payload_json = excluded.payload_json
        """, (s["entity_id"], s["date"], json.dumps(s["payload"], ensure_ascii=False)))
    conn.commit()
    conn.close()
    return signals


PENDULUM_WINDOW_DAYS = 14   # 컨센서스 판정 창
PENDULUM_MIN_DOCS = 8       # 방향 있는 문서 최소 표본 (신뢰 하한)
PENDULUM_RATIO = 0.9        # 일방향 비율 임계 — "낙관의 만장일치는 경고다"


def compute_consensus_extreme() -> list[dict]:
    """진자 감시 (K2, 설계 프로세스 6 · A-6 Marks 진자) — LLM 0.

    엔티티별 최근 창의 문서 감성 분포가 극단(일방향 90%+ & 표본 충분)이면
    'consensus_extreme' 신호. 판단이 아니라 분포 관찰 — 해석은 interpretation이.
    """
    conn = get_connection()
    rows = conn.execute(f"""
        SELECT el.entity_id, e.name,
               SUM(en.sentiment='positive') pos, SUM(en.sentiment='negative') neg
        FROM entity_links el
        JOIN entities e ON e.id = el.entity_id AND e.type='company'
        JOIN raw_documents rd ON rd.id = el.doc_id
        JOIN enrichments en ON en.doc_id = rd.id
        WHERE el.link_type='stock'
          AND rd.published_at >= datetime('now', '-{PENDULUM_WINDOW_DAYS} days')
          AND en.sentiment IN ('positive','negative')
        GROUP BY el.entity_id""").fetchall()

    signals = []
    today = datetime.now(timezone.utc).date().isoformat()
    for r in rows:
        n = (r["pos"] or 0) + (r["neg"] or 0)
        if n < PENDULUM_MIN_DOCS:
            continue
        ratio = max(r["pos"], r["neg"]) / n
        if ratio < PENDULUM_RATIO:
            continue
        signals.append({
            "entity_id": r["entity_id"], "name": r["name"], "date": today,
            "payload": {
                "direction": "optimism" if r["pos"] >= r["neg"] else "pessimism",
                "pos": r["pos"], "neg": r["neg"], "ratio": round(ratio, 2),
                "window_days": PENDULUM_WINDOW_DAYS,
            },
        })
    for s in signals:
        conn.execute("""
            INSERT INTO signals (signal_type, entity_id, date, payload_json)
            VALUES ('consensus_extreme', ?, ?, ?)
            ON CONFLICT(signal_type, entity_id, date)
            DO UPDATE SET payload_json = excluded.payload_json
        """, (s["entity_id"], s["date"], json.dumps(s["payload"], ensure_ascii=False)))
    conn.commit()
    conn.close()
    return signals


def interpret_pending(limit: int = 10) -> dict:
    """interpretation이 빈 신호에 haiku 1문장 해석 (epistemic: 가설 — 모델명 기록).

    - mention_surge: payload의 근거 문서 제목들로 맥락 해석
    - high_52w: 해당 종목의 최근 언급 문서가 있으면 그걸로, 없으면 skip (근거 없는 해석 금지)
    """
    from pipeline.enrich import _call_claude_code, llm_engine
    if llm_engine() != "claude-code":
        return {"skipped": "claude-code 엔진 아님"}

    conn = get_connection()
    todo = conn.execute("""
        SELECT s.id, s.signal_type, s.payload_json, e.name, e.id entity_id
        FROM signals s JOIN entities e ON s.entity_id = e.id
        WHERE s.interpretation IS NULL
        ORDER BY s.date DESC LIMIT ?
    """, (limit,)).fetchall()

    done = skipped = 0
    for r in todo:
        import json as _json
        p = _json.loads(r["payload_json"] or "{}")
        if r["signal_type"] == "mention_surge":
            titles = [d["title"] for d in (p.get("docs") or [])]
            context = "\n".join(f"- {t}" for t in titles)
            detail = f"최근 7일 {p.get('count_7d')}회 언급 (직전 {p.get('baseline_7d')}회)"
        elif r["signal_type"] == "volume_spike":
            titles = [d["title"] for d in (p.get("docs") or [])]
            if not titles:
                skipped += 1
                continue  # 근거 없는 해석 금지 — 문서 없는 급증은 해석 유보
            context = "\n".join(f"- {t}" for t in titles)
            detail = (f"거래량 급증 — 60일 평균 {p.get('ratio')}배, "
                      f"주가 {p.get('change_pct'):+}% (거래량이 터진 날 = 시장의 생각이 바뀐 날)")
        else:  # high_52w 등 — 최근 언급 문서로
            rows = conn.execute("""
                SELECT rd.title FROM entity_links el JOIN raw_documents rd ON el.doc_id = rd.id
                WHERE el.entity_id=? AND el.link_type='stock'
                ORDER BY rd.published_at DESC LIMIT 3""", (r["entity_id"],)).fetchall()
            if not rows:
                skipped += 1
                continue  # 근거 없는 해석 금지
            context = "\n".join(f"- {x['title']}" for x in rows)
            detail = f"52주 신고가 경신 (+{p.get('breakout_pct')}%)" if r["signal_type"] == "high_52w" else r["signal_type"]
        prompt = (
            f"'{r['name']}'에 {detail} 신호가 발생했다. 아래 관련 문서 제목들을 근거로 "
            "이 신호의 배경 맥락을 정확히 1문장으로 써라. 한국어 평서체, 추측 금지, "
            "문서에 없는 내용 금지. 문장만 출력.\n" + context
        )
        try:
            text = _call_claude_code(prompt).strip()[:200]
            conn.execute(
                "UPDATE signals SET interpretation=?, interpretation_model='claude-code/haiku' WHERE id=?",
                (text, r["id"]))
            conn.commit()
            done += 1
        except Exception:
            skipped += 1
    conn.close()
    return {"interpreted": done, "skipped": skipped}
