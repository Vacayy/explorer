"""기술적 분석 스캔의 AI 해설 (docs/specs/market-strategies.md §기술적 분석 스캔, D-190 후속).

모델은 차트를 보지 않는다. 호스트가 계산한 스캔 결과(성립 조건·발생일·상태)와 가격 위치 통계만 받아
문장마다 근거 항목 id를 붙여 읽어준다. 근거가 없는 문장은 호스트가 버린다. 예측·목표가·추천은 금지.
사용자 클릭 1회당 모델 1콜(도구 없음), 같은 종목·기준일·범위는 24시간 재사용.
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pipeline.market_analysis.model import structured_call
from pipeline.technical_scan import load_rows, scan_rows

MODEL = "sonnet"
BUDGET = .25
TIMEOUT = 90
REUSE_HOURS = 24
SCHEMA = """
CREATE TABLE IF NOT EXISTS technical_commentaries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code   TEXT NOT NULL,
    market       TEXT NOT NULL DEFAULT 'kr',
    as_of        TEXT NOT NULL,
    within       INTEGER NOT NULL,
    created_at   TEXT DEFAULT (datetime('now')),
    model        TEXT,
    cost_usd     REAL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_technical_commentaries_key ON technical_commentaries(stock_code, market, as_of, within);
"""


class CommentaryUnavailable(RuntimeError):
    pass


class Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class Point(Lenient):
    text: str = Field(min_length=1, max_length=400)
    basis: list[str] = Field(default_factory=list, max_length=6)


class Commentary(Lenient):
    summary: str = Field(min_length=1, max_length=600)
    reading: list[Point] = Field(default_factory=list, max_length=8)
    caveats: list[str] = Field(default_factory=list, max_length=6)
    watch: list[Point] = Field(default_factory=list, max_length=6)


SYSTEM = """당신은 기술적 분석 결과를 읽어주는 해설자다. 한국어로 쓴다. 입력은 호스트가 결정적으로 계산한 사실이다:
- signals: 최근 N거래일 안에 성립한 조건(id, label, date, value, reference)
- states: 기준일 당일의 상태 조건(성립/불성립)
- price: 가격 위치 통계(기준일 종가, 20/60/120거래일 수익률, 52주 고점·저점 대비 위치, 최근 거래량 배수)
- counts: 평가한 조건 수와 성립 수
규칙:
1. 차트를 본 척하지 마라. 입력에 없는 사실(뉴스·실적·수급·목표가·미래 전망)을 쓰지 마라.
2. reading의 각 문장은 basis에 근거가 되는 signals/states의 id 또는 price 통계 키(price.ret_20d 같은 형식)를 하나 이상 넣는다. 근거 없는 문장은 쓰지 마라.
3. 서로 어긋나는 신호(예: 정배열인데 고점 낮추기)가 있으면 그 긴장을 그대로 말하라. 억지로 한 방향으로 정리하지 마라.
4. signals의 value·reference는 조건마다 뜻이 다른 계산값(시가·종가·이평값·거래량 배수 등)이다. 어떤 값인지 label로 분명하지 않으면 수치를 인용하지 말고 성립 사실만 말하라. 종가는 price.close만 믿는다.
5. 조건이 성립했다는 것은 그 규칙의 정의를 만족했다는 뜻일 뿐이다. '매수·매도·상승·하락 전망' 같은 판단 문장은 금지. "~를 뜻한다"보다 "~인 상태다/~가 있었다"로.
6. caveats에는 이 해설이 못 보는 것(펀더멘털·뉴스·수급·거래량 질)을 1~3개 쓴다. watch에는 이 사실들이 바뀌는지 확인할 관찰 항목(예: 60일선 아래 종가 마감)을 basis와 함께 쓴다.
7. summary는 2~3문장, 중립적 서술. 마지막 메시지는 JSON 객체 하나만 출력한다.
스키마: {"summary": "", "reading": [{"text": "", "basis": ["high_20d"]}], "caveats": [""], "watch": [{"text": "", "basis": ["sma_bullish_order"]}]}"""


def price_context(rows: list[dict]) -> dict:
    """가격 위치 통계 — 모두 결정적 계산. 모델은 이 키를 근거로 인용할 수 있다."""
    closes = [r["close"] for r in rows if r.get("close")]
    if not closes:
        return {}
    last = closes[-1]

    def ret(n):
        return round((last / closes[-n - 1] - 1) * 100, 2) if len(closes) > n and closes[-n - 1] else None

    year = rows[-252:] if len(rows) >= 252 else rows
    high52 = max(r["high"] for r in year if r.get("high"))
    low52 = min(r["low"] for r in year if r.get("low"))
    volumes = [r["volume"] for r in rows[-21:-1] if r.get("volume")]
    avg_vol = sum(volumes) / len(volumes) if volumes else None
    return {"as_of": rows[-1]["date"], "close": last, "ret_20d": ret(20), "ret_60d": ret(60), "ret_120d": ret(120),
            "from_52w_high_pct": round((last / high52 - 1) * 100, 2) if high52 else None,
            "from_52w_low_pct": round((last / low52 - 1) * 100, 2) if low52 else None,
            "volume_vs_20d_avg": round(rows[-1]["volume"] / avg_vol, 2) if avg_vol and rows[-1].get("volume") else None,
            "sessions": len(rows)}


def build_context(scan: dict, price: dict) -> dict:
    strip = lambda e: {k: e[k] for k in ("id", "label", "category", "status", "date", "value", "reference") if k in e}
    return {"as_of": scan["as_of"], "within": scan["within"], "counts": scan["counts"],
            "signals": [strip(e) for e in scan["signals"]], "states": [strip(e) for e in scan["states"]],
            "unavailable": [e["label"] for e in scan["unavailable"]][:10], "price": price}


def finalize(raw: dict | None, context: dict) -> dict:
    """근거 id를 검증한다. 유효한 근거가 하나도 없는 문장은 버린다."""
    if not isinstance(raw, dict):
        raise CommentaryUnavailable("해설 결과가 JSON 형식이 아닙니다.")
    try:
        parsed = Commentary.model_validate(raw)
    except ValidationError as exc:
        raise CommentaryUnavailable("해설 결과의 형식이 올바르지 않습니다: " + str(exc.errors()[0].get("msg", ""))[:120]) from exc
    valid = {e["id"] for e in context["signals"]} | {e["id"] for e in context["states"]} | {f"price.{k}" for k, v in context["price"].items() if v is not None}
    dropped = 0

    def keep(points):
        nonlocal dropped
        out = []
        for point in points:
            basis = [b for b in point.basis if b in valid]
            if basis:
                out.append({"text": point.text, "basis": basis})
            else:
                dropped += 1
        return out

    return {"summary": parsed.summary, "reading": keep(parsed.reading), "caveats": parsed.caveats[:6], "watch": keep(parsed.watch),
            "dropped_unsupported": dropped}


def latest(conn: sqlite3.Connection, code: str, market: str, as_of: str, within: int) -> dict | None:
    row = conn.execute("SELECT * FROM technical_commentaries WHERE stock_code=? AND market=? AND as_of=? AND within=? ORDER BY id DESC LIMIT 1",
                       (code, market, as_of, within)).fetchone()
    return _row(row) if row else None


def _row(row) -> dict:
    created = str(row["created_at"]).replace(" ", "T")
    return {"id": row["id"], "created_at": created if created.endswith("Z") else created + "Z", "model": row["model"], "cost_usd": row["cost_usd"],
            "as_of": row["as_of"], "within": row["within"], **json.loads(row["payload_json"])}


def explain(conn: sqlite3.Connection, code: str, market: str = "kr", within: int = 5, *, force: bool = False,
            runner: Callable | None = None) -> tuple[dict, bool]:
    rows = load_rows(conn, code, market)
    if not rows:
        raise CommentaryUnavailable("저장된 시세가 없는 종목입니다.")
    scan = scan_rows(rows, within=within)
    current = latest(conn, code, market, scan["as_of"], within)
    if current and not force:
        created = datetime.fromisoformat(current["created_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - created < timedelta(hours=REUSE_HOURS):
            return current, True
    context = build_context(scan, price_context(rows))
    caller = runner or (lambda ctx: structured_call(SYSTEM, ctx, Commentary.model_json_schema(), budget=BUDGET, timeout=TIMEOUT, model=MODEL))
    raw, cost = caller(context)
    payload = finalize(raw, context)
    if not payload["reading"]:
        raise CommentaryUnavailable("근거가 붙은 해설 문장이 없어 표시하지 않습니다.")
    payload["basis_labels"] = {**{e["id"]: e["label"] for e in scan["signals"]}, **{e["id"]: e["label"] for e in scan["states"]}}
    conn.execute("INSERT INTO technical_commentaries (stock_code, market, as_of, within, model, cost_usd, payload_json) VALUES (?,?,?,?,?,?,?)",
                 (code, market, scan["as_of"], within, MODEL, cost if cost is not None and math.isfinite(cost) else None, json.dumps(payload, ensure_ascii=False)))
    conn.commit()
    return latest(conn, code, market, scan["as_of"], within), False
