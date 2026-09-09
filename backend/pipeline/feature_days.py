"""종목 특징일 — 급등락·거래량 폭발일 추출 + AI 원인 조사 (아이디어 2).

감지(LLM 0): |등락| 3.5%+ 또는 (거래량 60일 평균 4배+ & |등락| 1.5%+),
룩백 내 |등락| 상위 24일. 설명(haiku, 게으른): 마커 클릭 시 1콜 —
해당일 ±1일의 수집 문서로 '무슨 일이 있었나' 1~2문장, 캐시 영구.
문서가 없으면 설명하지 않는다 (근거 없는 해석 금지 — no_docs 마커 캐시).
"""
import json
import subprocess
from datetime import datetime, timezone

from database import get_connection
from pipeline.enrich import _claude_bin, llm_engine

RET_TH = 3.5        # 등락 임계 (%)
VOL_RATIO_TH = 4.0  # 거래량 60일 평균 배수
VOL_RET_TH = 1.5    # 거래량 조건일 때 최소 등락
MAX_DAYS = 24
DOCS_LIMIT = 8


def detect_feature_days(stock_code: str, lookback_days: int = 365) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(f"""
        SELECT trade_date, close, volume,
               LAG(close) OVER (ORDER BY trade_date) prev_close,
               AVG(volume) OVER (ORDER BY trade_date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING) avg_vol
        FROM stock_prices
        WHERE stock_code=? AND trade_date >= date('now', '-{int(lookback_days)} days')
        ORDER BY trade_date""", (stock_code,)).fetchall()
    notes = {r["date"]: dict(r) for r in conn.execute(
        "SELECT date, note, status FROM feature_day_notes WHERE stock_code=?", (stock_code,))}
    conn.close()

    out = []
    for r in rows:
        if not r["prev_close"] or not r["close"]:
            continue
        ret = (r["close"] - r["prev_close"]) / r["prev_close"] * 100
        vol_ratio = (r["volume"] / r["avg_vol"]) if (r["volume"] and r["avg_vol"]) else 0
        if abs(ret) >= RET_TH or (vol_ratio >= VOL_RATIO_TH and abs(ret) >= VOL_RET_TH):
            n = notes.get(r["trade_date"], {})
            out.append({
                "date": r["trade_date"], "ret_pct": round(ret, 1),
                "volume_ratio": round(vol_ratio, 1) if vol_ratio else None,
                "direction": "up" if ret > 0 else "down",
                "note": n.get("note"), "note_status": n.get("status"),
            })
    out.sort(key=lambda d: -abs(d["ret_pct"]))
    out = out[:MAX_DAYS]
    out.sort(key=lambda d: d["date"])
    return out


def explain_day(stock_code: str, day: str) -> dict:
    """특징일 원인 조사 — 캐시 우선, 없으면 haiku 1콜. 반환: {note, status, docs}."""
    conn = get_connection()
    cached = conn.execute(
        "SELECT note, status FROM feature_day_notes WHERE stock_code=? AND date=?",
        (stock_code, day)).fetchone()
    docs = conn.execute("""
        SELECT DISTINCT rd.id, rd.title, substr(rd.markdown, 1, 400) ex, rd.published_at
        FROM entity_links el
        JOIN entities e ON e.id = el.entity_id AND e.type='company' AND e.aliases=?
        JOIN raw_documents rd ON rd.id = el.doc_id
        WHERE el.link_type='stock'
          AND date(rd.published_at) BETWEEN date(?, '-1 day') AND date(?, '+1 day')
        ORDER BY rd.published_at LIMIT ?""", (stock_code, day, day, DOCS_LIMIT)).fetchall()
    doc_list = [{"id": d["id"], "title": d["title"]} for d in docs]

    if cached:
        conn.close()
        return {"note": cached["note"], "status": cached["status"], "docs": doc_list}

    px = conn.execute("""
        SELECT close, LAG(close) OVER (ORDER BY trade_date) prev FROM stock_prices
        WHERE stock_code=? AND trade_date <= ? ORDER BY trade_date DESC LIMIT 2""",
        (stock_code, day)).fetchone()
    name = conn.execute("SELECT corp_name FROM companies WHERE stock_code=?",
                        (stock_code,)).fetchone()
    ret = ""
    if px and px["prev"]:
        ret = f"{(px['close'] - px['prev']) / px['prev'] * 100:+.1f}%"

    if not docs:
        note, status = None, "no_docs"
    elif llm_engine() != "claude-code":
        conn.close()
        return {"note": None, "status": "unavailable", "docs": doc_list}
    else:
        ctx = "\n\n".join(f"[{i+1}] ({(d['published_at'] or '')[:10]}) {d['title']}\n{d['ex']}"
                          for i, d in enumerate(docs))
        prompt = (
            f"'{name['corp_name'] if name else stock_code}' 주가가 {day}에 {ret} 움직였다. "
            "아래 그 전후의 수집 문서들만 근거로, 이날 무슨 일이 있었는지 1~2문장으로 설명해라. "
            "문서에 원인이 안 보이면 '수집 문서에서 직접 원인은 확인되지 않음'이라고 쓰고 "
            "당시 맥락만 요약해라. 추측 금지, 문장만 출력.\n\n" + ctx
        )
        try:
            proc = subprocess.run(
                [_claude_bin(), "-p", "--setting-sources", "", "--tools", "", "--model", "haiku", "--output-format", "json", prompt],
                capture_output=True, text=True, timeout=180)
            note = json.loads(proc.stdout).get("result", "").strip()[:400] or None
            status = "ok" if note else "failed"
        except Exception:
            note, status = None, "failed"

    conn.execute("""
        INSERT OR REPLACE INTO feature_day_notes (stock_code, date, note, status, model, created_at)
        VALUES (?, ?, ?, ?, 'claude-code/haiku', ?)""",
        (stock_code, day, note, status, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()
    return {"note": note, "status": status, "docs": doc_list}
