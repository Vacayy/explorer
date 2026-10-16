"""포트폴리오 논지·반증 감시 (docs/specs/portfolio-intelligence.md §2).

보유 종목마다 "왜 샀나 / 무엇이면 틀린가"를 기존 핵심질문 추적기(D-067)로 넘긴다 — 분해는 sonnet 1회(사용자가 누를 때만),
매일 07:40 refresh_all의 결정적 롤업이 판정한다. 판정이 나빠지면(선행·확정 중 leaning_no, 또는 반증 조건이 붙은 하위 질문이
leaning_no) 그 상태로 한 번 텔레그램을 보낸다. 국내 종목은 숫자 관측 경로(전사록=미국 기업)가 없어 분해 때 미국 관련 기업
티커를 지표로 쓰라고 안내한다 — 국내 시세·DART·수출입 지표 어댑터는 P1.
"""
from __future__ import annotations

import html
import sqlite3

from pipeline import portfolio_alerts as pa

KR_HINT = ("\n\n[분해 안내] 이 질문은 한국 상장 보유 종목 {name}({code})의 투자 논지다. numeric 프록시의 tickers에는 "
           "컨콜 전사록이 있는 미국 상장 관련 기업(고객사·경쟁사·장비사·수요처, 예: MU, LRCX, AMAT, NVDA)을 써라. "
           "한국 종목 코드는 tickers에 넣지 마라. 사용자가 적은 '틀린 조건'은 해당 하위 질문의 falsifier로 옮겨라.")


def ensure_schema(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ALTER TABLE questions ADD COLUMN stock_code TEXT")
    except sqlite3.OperationalError:
        pass


def question_text(name: str, why: str, falsifier: str) -> str:
    text = f"{name} 보유 논지: {why.strip()}"
    return text + (f" — 이렇게 되면 틀린 것: {falsifier.strip()}" if falsifier.strip() else "")


def start(code: str, name: str, why: str, falsifier: str) -> dict:
    from pipeline.questions import decompose_question
    return decompose_question(question_text(name, why, falsifier), created_by="portfolio", stock_code=code,
                              hint=KR_HINT.format(name=name, code=code))


def theses(conn: sqlite3.Connection, codes: list[str], created_by: str = "portfolio") -> dict[str, dict]:
    """종목별 가장 최근 추적 중 논지 — 판정·하위 질문(반증 조건)만. created_by로 보유 논지와 관심 이유(watch)를 나눈다.
    judged_at은 마지막 판정 시각 — 판정 엔진이 꺼진 동안(08-19~) 옛 판정을 오늘 것처럼 보이지 않게 함께 낸다."""
    out = {}
    for code in codes:
        q = conn.execute("SELECT * FROM questions WHERE stock_code=? AND status='tracking' AND created_by=? ORDER BY id DESC LIMIT 1",
                         (code, created_by)).fetchone()
        if not q:
            continue
        subs = [{"text": r["text"], "falsifier": r["falsifier"], "verdict": r["verdict"]}
                for r in conn.execute("SELECT text, falsifier, verdict FROM sub_questions WHERE question_id=? ORDER BY id", (q["id"],))]
        out[code] = {"id": q["id"], "text": q["text"], "lead": q["lead_verdict"], "confirm": q["confirm_verdict"],
                     "divergence": q["divergence"], "summary": q["verdict_summary"], "sub_questions": subs,
                     "judged_at": q["updated_at"]}
    return out


def judging() -> bool:
    """판정 엔진(관리자 '질문 트래커 갱신')이 켜져 있나. 꺼져 있으면 논지·관심 이유 판정과 알림이 멈춘다."""
    from pipeline.ops import flag_enabled
    return flag_enabled("refresh_questions")


def warnings(t: dict) -> list[str]:
    """나빠진 신호 — 선행·확정 leaning_no, 반증 조건이 붙은 하위 질문 leaning_no."""
    out = [label for label, v in (("선행 신호", t["lead"]), ("확정 지표", t["confirm"])) if v == "leaning_no"]
    out += [f"반증 조건: {s['falsifier']}" for s in t["sub_questions"] if s["falsifier"] and s["verdict"] == "leaning_no"]
    return out


def alert(conn: sqlite3.Connection, holdings: list[dict], send=None, dry_run: bool = False) -> int:
    from pipeline.notify import send_telegram
    conn.executescript(pa.SCHEMA)
    send = send or ((lambda text: print(text) or True) if dry_run else send_telegram)
    names = {h["code"]: h["name"] for h in holdings}
    items = []
    for code, t in theses(conn, list(names)).items():
        warn = warnings(t)
        if warn:
            key = f"q:{t['id']}:{t['lead']}:{t['confirm']}:{t['divergence']}:{len(warn)}"
            line = f"⚠️ <b>{html.escape(names[code])}</b> 논지 점검 — " + " · ".join(html.escape(w) for w in warn)
            if t["summary"]:
                line += f"\n  {html.escape(t['summary'][:200])}"
            items.append((key, line))
    return pa._send(conn, items, "🧭 <b>보유 논지 판정이 나빠졌습니다</b>", send, dry_run)
