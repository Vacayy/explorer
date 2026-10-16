"""관심 종목 이유 감시 (D-227, docs/specs/portfolio-intelligence.md §6).

관심 묶음 종목마다 "왜 보고 있나 / 무엇이 오면 움직이나"를 적으면 보유 논지(§2)와 같은 핵심질문 추적기로 분해하고
(sonnet 1회, 사용자가 누를 때만) 매일 07:40 판정한다. 보유 논지는 나빠질 때만 알리지만, 관심 이유는 판정이 어느 쪽으로든
기울면 알린다 — 이유가 맞아가는 것(지지)도 매수 검토 신호다. 질문은 created_by='watch'로 보유 논지와 섞이지 않는다.
원문은 로컬 DB(questions)에만. LLM은 분해 1회뿐, 판정은 기존 롤업.
"""
from __future__ import annotations

import html
import sqlite3

from pipeline import portfolio_alerts as pa
from pipeline import portfolio_thesis as pt

CREATOR = "watch"
LEANING = {"leaning_yes": "지지", "leaning_no": "약화"}


def question_text(name: str, why: str, trigger: str) -> str:
    text = f"{name} 관심 이유: {why.strip()}"
    return text + (f" — 이렇게 되면 움직인다: {trigger.strip()}" if trigger.strip() else "")


def start(code: str, name: str, why: str, trigger: str) -> dict:
    from pipeline.questions import decompose_question
    return decompose_question(question_text(name, why, trigger), created_by=CREATOR, stock_code=code,
                              hint=pt.KR_HINT.format(name=name, code=code).replace("보유 종목", "관심 종목"))


def reasons(conn: sqlite3.Connection, codes: list[str]) -> dict[str, dict]:
    return pt.theses(conn, codes, created_by=CREATOR)


def watch_members(conn: sqlite3.Connection) -> list[dict]:
    """모든 관심 묶음의 종목(중복 제거)."""
    return [{"code": r["stock_code"], "name": r["name"] or r["stock_code"]} for r in conn.execute(
        """SELECT DISTINCT m.stock_code, c.corp_name AS name FROM stock_group_members m
           JOIN stock_groups g ON g.id = m.group_id LEFT JOIN companies c ON c.stock_code = m.stock_code
           WHERE g.kind = 'watch' ORDER BY m.stock_code""")]


def signals(t: dict) -> list[str]:
    """기운 판정 — 선행·확정이 지지/약화, 반증 조건 하위 질문이 약화."""
    out = [f"{label} {LEANING[v]}" for label, v in (("선행 신호", t["lead"]), ("확정 지표", t["confirm"])) if v in LEANING]
    out += [f"반증 조건: {s['falsifier']}" for s in t["sub_questions"] if s["falsifier"] and s["verdict"] == "leaning_no"]
    return out


def alert(conn: sqlite3.Connection, members: list[dict], send=None, dry_run: bool = False) -> int:
    from pipeline.notify import send_telegram
    conn.executescript(pa.SCHEMA)
    send = send or ((lambda text: print(text) or True) if dry_run else send_telegram)
    names = {m["code"]: m["name"] for m in members}
    items = []
    for code, t in reasons(conn, list(names)).items():
        found = signals(t)
        if found:
            key = f"w:{t['id']}:{t['lead']}:{t['confirm']}:{t['divergence']}:{len(found)}"
            up = "leaning_yes" in (t["lead"], t["confirm"]) and "leaning_no" not in (t["lead"], t["confirm"])
            line = f"{'🟢' if up else '🟠'} <b>{html.escape(names[code])}</b> " + " · ".join(html.escape(x) for x in found)
            if t["summary"]:
                line += f"\n  {html.escape(t['summary'][:200])}"
            items.append((key, line))
    return pa._send(conn, items, "👀 <b>관심 종목 이유 판정이 기울었습니다</b>", send, dry_run)
