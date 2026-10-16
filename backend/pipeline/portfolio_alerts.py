"""포트폴리오 텔레그램 알림 (D-214, docs/specs/portfolio-ledger.md §알림).

화면을 열지 않아도 먼저 보낸다. 네 종류:
  - 장중 급등락: 전일 대비 ±5%p 단위, 평단 대비 ±10%p 단위 구간에 처음 들어설 때 (장중 30분 점검)
  - 신규 공시: 보유 종목의 오늘 DART 공시 (09:00–18:00 30분 점검)
  - 주요 기술적 신호: 장 마감 뒤 오늘 새로 충족한 특이점 (기업 화면 '주요 신호'와 같은 기준)
  - 일일 계좌 요약: 장 마감 뒤 계좌·종목 수익률
모든 메시지는 비율·가격만 싣는다 — 원화 금액·수량 금지(D-212). 같은 알림은 sent 키로 한 번만 보낸다.
LLM 0.
"""
from __future__ import annotations

import html
import math
import sqlite3
from datetime import datetime

from pipeline import portfolio as pf

SCHEMA = """
CREATE TABLE IF NOT EXISTS portfolio_alerts_sent (
    key      TEXT PRIMARY KEY,
    sent_at  TEXT DEFAULT (datetime('now'))
);
"""
DAY_STEP = 5.0       # 전일 대비 알림 구간(%p)
AVG_STEP = 10.0      # 평단 대비 알림 구간(%p)
# 기업 화면 TechnicalScan.tsx의 NOTABLE과 같은 목록 + '가격 구조' 범주 전체
NOTABLE = {"high_52w", "low_52w", "high_ytd", "low_ytd", "golden_cross_20_60", "dead_cross_20_60", "trend_reversal_confirmed",
           "macd_zero_cross", "breakout_pullback_10d", "volume_profile_up_60d", "volume_profile_down_60d", "rsi_exit_oversold",
           "rsi_exit_overbought", "bollinger_reenter_lower", "bollinger_reenter_upper", "adx_rise_above"}


def _pct(v: float | None) -> str:
    return "-" if v is None else f"{'+' if v > 0 else ''}{v:.1f}%"


def _bucket(value: float | None, step: float) -> int:
    """0에서 멀어지는 방향으로 step 단위 구간. +5.3 → 1, −10.1 → −2, ±4.9 → 0."""
    if value is None:
        return 0
    return int(math.copysign(math.floor(abs(value) / step), value))


def _claim(conn: sqlite3.Connection, key: str) -> bool:
    """처음 보는 키면 기록하고 True — 발송 전에 잡아 중복을 막는다(발송 실패 시 release)."""
    return conn.execute("INSERT OR IGNORE INTO portfolio_alerts_sent (key) VALUES (?)", (key,)).rowcount == 1


def _release(conn: sqlite3.Connection, keys: list[str]) -> None:
    conn.executemany("DELETE FROM portfolio_alerts_sent WHERE key=?", [(k,) for k in keys])


def price_moves(summary: dict, today: str) -> list[tuple[str, str]]:
    """(키, 문장). 같은 날 같은 구간은 한 번, 평단 대비 구간은 편입 단위로 한 번."""
    out = []
    for h in summary["holdings"]:
        if h.get("price_source") != "live":
            continue
        b = _bucket(h["day_change_pct"], DAY_STEP)
        if b:
            out.append((f"day:{today}:{h['code']}:{b}",
                        f"{'📈' if b > 0 else '📉'} <b>{html.escape(h['name'])}</b> 전일 대비 {_pct(h['day_change_pct'])} · 현재가 {h['last_close']:,.0f}"))
        b = _bucket(h["return_pct"], AVG_STEP)
        if b:
            out.append((f"avg:{h['code']}:{h['entry_date']}:{b}",
                        f"🎯 <b>{html.escape(h['name'])}</b> 평단 대비 {_pct(h['return_pct'])} (평단 {h['avg_price']:,.0f} → {h['last_close']:,.0f})"))
    return out


def _dart_today(code: str, ymd: str) -> list[dict]:
    """DART 오늘 공시 직접 조회 — 공용 fetch_disclosures는 실패를 삼키고 빈 결과를 캐시해 알림이 조용히 빠진다."""
    from services.dart_service import _corp_code_for_stock, _get_dart
    corp = _corp_code_for_stock(code)
    if not corp:
        return []
    df = _get_dart().list(corp, start=ymd, end=ymd)
    return [] if df is None or df.empty else df.to_dict("records")


def new_disclosures(holdings: list[dict], today: str, fetch=None) -> list[tuple[str, str]]:
    fetch = fetch or _dart_today
    ymd = today.replace("-", "")
    out = []
    for h in holdings:
        for d in fetch(h["code"], ymd):
            rcp, title = str(d.get("rcept_no") or ""), str(d.get("report_nm") or "").strip()
            if rcp and title:
                out.append((f"disc:{rcp}", f"📄 <b>{html.escape(h['name'])}</b> 공시 · "
                                           f"<a href=\"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcp}\">{html.escape(title)}</a>"))
    return out


def technical_signals(conn: sqlite3.Connection, holdings: list[dict], scan=None) -> list[tuple[str, str]]:
    """오늘(스캔 기준일) 새로 충족한 주요 신호."""
    if scan is None:
        from pipeline.technical_scan import scan_company as scan
    out = []
    for h in holdings:
        r = scan(conn, h["code"], "kr", 1)
        for s in r.get("signals", []):
            if s["status"] == "pass" and s["date"] == r.get("as_of") and (s["id"] in NOTABLE or s["category"] == "가격 구조"):
                out.append((f"tech:{h['code']}:{s['date']}:{s['id']}", f"📐 <b>{html.escape(h['name'])}</b> {html.escape(s['label'])} ({s['date'][5:]})"))
    return out


def daily_summary(summary: dict) -> tuple[str, str] | None:
    if not summary["holdings"] or not summary["as_of"]:
        return None
    lines = [f"💼 <b>포트폴리오</b> {summary['as_of'][5:]} · 계좌 {_pct(summary['total_return_pct'])} · 오늘 {_pct(summary['day_return_pct'])}"]
    for h in summary["holdings"]:
        lines.append(f"· {html.escape(h['name'])} {_pct(h['day_change_pct'])} (평단 대비 {_pct(h['return_pct'])}, 비중 {_pct(h['weight_pct']).lstrip('+')})")
    if summary.get("cash_weight_pct"):
        lines.append(f"· 현금 비중 {summary['cash_weight_pct']:.0f}%")
    return f"summary:{summary['as_of']}", "\n".join(lines)


def upcoming_soon(conn: sqlite3.Connection, holdings: list[dict], today: str, days: int = 3) -> str | None:
    from datetime import date
    from pipeline import portfolio_events as pe, portfolio_exposure as px
    hs = [{"code": h["code"], "name": h["name"], "weight_pct": h["weight_pct"]} for h in holdings]
    ev = pe.upcoming(conn, hs, px.chains_of(conn, hs), date.fromisoformat(today), days)
    if not ev:
        return None
    return "📅 3일 이내 일정\n" + "\n".join(f"· {e['date'][5:]} {html.escape(e['title'])}{' (예상)' if e['estimated'] else ''}" for e in ev)


def refresh_events(conn: sqlite3.Connection, holdings: list[dict], today: str) -> dict:
    """확정 일정 수집 → 예상치 → 해외 실적일(주 1회). DART 실패는 예외로 올려 job_runs에 남는다."""
    from datetime import date
    from pipeline import portfolio_events as pe, portfolio_exposure as px
    hs = [{"code": h["code"], "name": h["name"], "weight_pct": h["weight_pct"]} for h in holdings]
    d = date.fromisoformat(today)
    return {"confirmed": pe.collect_confirmed(conn, hs, d), "estimated": pe.estimate(conn, hs, d),
            "us": pe.refresh_us(list(pe.chain_tickers(px.chains_of(conn, hs))))}


def _send(conn: sqlite3.Connection, items: list[tuple[str, str]], header: str, send, dry_run: bool = False) -> int:
    if dry_run:      # 미리보기는 보낸 것으로 기록하지 않는다
        fresh = [(k, t) for k, t in items if not conn.execute("SELECT 1 FROM portfolio_alerts_sent WHERE key=?", (k,)).fetchone()]
        if fresh:
            send("\n".join([header, *[t for _, t in fresh]]) if header else "\n".join(t for _, t in fresh))
        return len(fresh)
    fresh = [(k, t) for k, t in items if _claim(conn, k)]
    if not fresh:
        conn.commit()
        return 0
    ok = send("\n".join([header, *[t for _, t in fresh]]) if header else "\n".join(t for _, t in fresh))
    if not ok:
        _release(conn, [k for k, _ in fresh])        # 실패하면 다음 점검에서 다시 보낸다
        conn.commit()
        raise RuntimeError("텔레그램 발송 실패")
    conn.commit()
    return len(fresh)


def run(mode: str, dry_run: bool = False, conn: sqlite3.Connection | None = None, send=None, now: datetime | None = None) -> dict:
    """mode='intraday'(급등락·공시) | 'close'(요약·기술적 신호·공시)."""
    from pipeline.notify import send_telegram
    own = conn is None
    conn = conn or pf.connect()
    conn.executescript(SCHEMA)
    send = send or ((lambda text: print(text) or True) if dry_run else send_telegram)
    today = (now or datetime.now(pf.KST)).strftime("%Y-%m-%d")
    try:
        summary = pf.summary(conn)
        if not summary["holdings"]:
            return {"mode": mode, "sent": 0, "reason": "보유 종목 없음"}
        if mode == "intraday" and pf.market_hours(now):
            # 30분 주기 작업이 30분 TTL에 걸려 시세를 한 주기 더 묵히지 않게, 1분보다 오래된 시세는 새로 받는다
            pf.refresh_quotes(conn, {h["code"] for h in summary["holdings"]}, ttl=60)
            summary = pf.summary(conn)
        sent, result, errors = 0, {}, []
        if mode == "intraday":
            if pf.market_hours(now):
                sent += _send(conn, price_moves(summary, today), "", send, dry_run)
                try:   # 운용 원칙(D-227) — 장중 규칙만. 실패해도 다른 알림은 보낸다
                    from pipeline import portfolio_principles as pp
                    sent += pp.alert(conn, summary, send, live_only=True, today=today, dry_run=dry_run)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"principles: {type(e).__name__}: {str(e)[:120]}")
            sent += _send(conn, new_disclosures(summary["holdings"], today), "", send, dry_run)
        elif mode == "close":
            try:
                result["events"] = refresh_events(conn, summary["holdings"], today)
            except Exception as e:  # noqa: BLE001 — 일정 수집이 실패해도 요약·신호는 보낸다. 실패는 errors로 올린다
                errors.append(f"events: {type(e).__name__}: {str(e)[:120]}")
            flow_lines = []
            try:
                from datetime import date as _date
                from pipeline import portfolio_flow as fl
                d0 = _date.fromisoformat(today)
                hs = [{"code": h["code"], "name": h["name"]} for h in summary["holdings"]]
                flows = fl.flow(conn, hs, d0)
                if not dry_run:                      # 요약 생성(LLM)은 실제 실행에서만
                    result["digests"] = fl.ensure_digests(hs, d0, flows)
                    flows = fl.flow(conn, hs, d0)
                flow_lines = fl.summary_lines(flows, d0)
            except Exception as e:  # noqa: BLE001
                errors.append(f"flow: {type(e).__name__}: {str(e)[:120]}")
            s = daily_summary(summary)
            if s and flow_lines:
                s = (s[0], s[1] + "\n🗞 자료 흐름\n" + "\n".join(html.escape(x) for x in flow_lines))
            if s:
                try:
                    soon = upcoming_soon(conn, summary["holdings"], today)
                except Exception as e:  # noqa: BLE001
                    soon = None
                    errors.append(f"upcoming: {type(e).__name__}: {str(e)[:120]}")
                s = (s[0], s[1] + ("\n" + soon if soon else ""))
                sent += _send(conn, [s], "", send, dry_run)
            sent += _send(conn, technical_signals(conn, summary["holdings"]), "📐 <b>오늘 새 기술적 신호</b>", send, dry_run)
            try:   # 운용 원칙(D-227) — 전체 규칙(공통 변수 노출·계좌 손실 포함)
                from pipeline import portfolio_exposure as px
                from pipeline import portfolio_principles as pp
                hs = [{"code": h["code"], "name": h["name"], "weight_pct": h["weight_pct"]} for h in summary["holdings"]]
                sent += pp.alert(conn, summary, send, exposure=lambda: px.cached_exposure(conn, hs), today=today, dry_run=dry_run)
            except Exception as e:  # noqa: BLE001
                errors.append(f"principles: {type(e).__name__}: {str(e)[:120]}")
            sent += _send(conn, new_disclosures(summary["holdings"], today), "", send, dry_run)
        else:
            raise ValueError(mode)
        return {"mode": mode, "sent": sent, **result, **({"errors": errors} if errors else {})}
    finally:
        if own:
            conn.close()
