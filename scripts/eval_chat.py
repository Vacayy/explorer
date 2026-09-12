"""대화 평가 실행 — backend/eval/chat_eval_set.json → docs/specs/chat-eval-runs/<날짜>-<label>.md (사용자 채점용).

- `chat.run_turn`(라우터→도구→종합→검증)을 영속화 없이 실행 — 대화 테이블·기억을 오염시키지 않는다.
- command 유형('시나리오:')은 라우팅 판정만 기록하고 실행하지 않는다(opus 오염 방지).
- followup은 같은 thread의 앞 문답을 최근 대화·이전 인용으로 넘긴다(같은 run 안에서 순서대로).
- 규칙 채점(자동): 거부 기대 vs 실제 · 기대 도구 호출 여부(route_hint 첫 도구명) · 인용 수 · 인용 누락 갭.
  품질 점수(0/0.5/1)는 사용자가 md에 채운다.
- 호출은 llm_calls에 job='chat.route'·'chat.answer'로 기록된다.

사용: .venv/bin/python scripts/eval_chat.py [--ids Q01,Q02] [--limit N] [--label baseline]
"""
import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

SET_PATH = ROOT / "backend" / "eval" / "chat_eval_set.json"
OUT_DIR = ROOT / "docs" / "specs" / "chat-eval-runs"


def _route_only(q: str) -> str | None:
    from pipeline.scenario import parse_scenario
    ev = parse_scenario(q)
    return f"command:scenario → {ev[:60]}" if ev else None


def _expected_tool(hint: str, tools: dict) -> str | None:
    m = re.match(r"\s*([a-z_]+)", hint or "")
    return m.group(1) if m and m.group(1) in tools else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--label", default="run")
    args = ap.parse_args()

    from pipeline import chat
    from pipeline.chat_tools import TOOLS
    items = json.loads(SET_PATH.read_text())["items"]
    if args.ids:
        want = set(args.ids.split(","))
        items = [i for i in items if i["id"] in want]
    if args.limit:
        items = items[:args.limit]
    # followup은 부모(thread) 문항 뒤에 실행 — 세트 순서와 무관하게 맥락이 먼저 생기도록
    ordered, pending = [], list(items)
    while pending:
        progressed = False
        for it in list(pending):
            parent = it.get("thread")
            if not parent or any(o["id"] == parent for o in ordered) or not any(p["id"] == parent for p in pending):
                ordered.append(it); pending.remove(it); progressed = True
        if not progressed:
            ordered += pending; break
    items = ordered

    # 스레드 맥락: id → {"recent": [...messages], "last_citations": [...]}
    threads: dict[str, dict] = {}
    rows = []
    for it in items:
        t0 = time.time()
        rec = {"id": it["id"], "type": it["type"], "question": it["question"], "expect": it["expect"],
               "route_hint": it.get("route_hint", "")}
        routed = _route_only(it["question"])
        if routed:
            rec.update(answer=None, route=routed, gaps=[], citations=[], tools=[],
                       rule="command 라우팅 OK" if it["expect"] == "command" else "command로 라우팅됐지만 기대는 answer")
            rows.append(rec)
            print(f"[{it['id']}] {routed}")
            continue

        prev = threads.get(it.get("thread") or "") or {"recent": [], "last_citations": []}
        ctx = {"note": None, "state": {"last_citations": prev["last_citations"]},
               "recent": prev["recent"][-4:], "related": []}
        try:
            turn = chat.run_turn(it["question"], ctx=ctx)
            r = {"answer": turn.answer, "gaps": turn.gaps, "citations": turn.citations, "model": turn.model,
                 "usage": turn.usage, "intent": turn.route.get("intent"),
                 "standalone": turn.route.get("standalone_question"),
                 "tools": [f"{t['name']}({json.dumps(t.get('args', {}), ensure_ascii=False)})→{t.get('n', 0)}"
                           + (f" [{t['note']}]" if t.get("note") else "") for t in turn.tool_log],
                 "tool_names": [t["name"] for t in turn.tool_log], "timings": turn.timings,
                 "steps": turn.route_log().get("steps") or [], "process": turn.process, "review": turn.review}
        except Exception as e:  # noqa: BLE001
            r = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
        rec["ms"] = int((time.time() - t0) * 1000)
        if r.get("error"):
            rec.update(answer=None, error=r["error"], gaps=[], citations=[], tools=[], rule="실패")
        else:
            rec.update(r)
            refused = not r.get("answer") or r.get("intent") == "refuse"
            checks = [("거부 기대" if it["expect"] == "refuse" else "답변 기대")
                      + (" ✓" if refused == (it["expect"] == "refuse") else " ✗")]
            exp_tool = _expected_tool(it.get("route_hint", ""), TOOLS)
            if exp_tool:
                checks.append(f"도구 {exp_tool} " + ("✓" if exp_tool in r["tool_names"] else "✗"))
            checks.append(f"인용 {len(rec['citations'])}건")
            if any("규칙 판정" in (g.get("note") or "") for g in rec["gaps"]):
                checks.append("인용 누락 갭 ⚠")
            rec["rule"] = " · ".join(checks)
        rows.append(rec)
        # 스레드 맥락 축적 (followup용)
        base = threads.get(it.get("thread") or "") or {"recent": [], "last_citations": []}
        threads[it["id"]] = {
            "recent": base["recent"] + [{"role": "user", "content": it["question"]},
                                        {"role": "assistant", "content": rec.get("answer") or ""}],
            "last_citations": [{"n": c["n"], "kind": c.get("kind"), "doc_id": c.get("doc_id"), "title": c["title"]} for c in rec.get("citations") or []],
        }
        print(f"[{it['id']}] {rec.get('rule')} · {r.get('intent', '-')} · {', '.join(r.get('tool_names', []))} ({rec.get('ms', 0)//1000}s)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{date.today().isoformat()}-{args.label}.md"
    n_tool_ok = sum(1 for r in rows if "도구" in r.get("rule", "") and "도구 " in r["rule"] and "✓" in r["rule"].split("도구")[1][:20])
    n_tool = sum(1 for r in rows if "도구 " in r.get("rule", ""))
    lines = [f"# 대화 평가 run — {date.today().isoformat()} · {args.label}", "",
             "> 채점: 각 항목 **점수**(0 / 0.5 / 1)와 **코멘트**를 채운다. 0.5=방향은 맞으나 빠짐·부정확, 0=틀림/지어냄/부적절 거부.",
             "> 규칙 판정은 자동(거부 기대 일치·기대 도구 호출·인용 수·인용 누락). 기준 답이 정해지면 chat_eval_set.json의 must_include에 반영.", "",
             f"항목 {len(rows)} · 기대 도구 호출 {n_tool_ok}/{n_tool} · 실패 {sum(1 for r in rows if r.get('error'))}", ""]
    for r in rows:
        lines += [f"## {r['id']} · {r['type']} · 기대={r['expect']}", "",
                  f"**질문**: {r['question']}", "",
                  f"- 기대 경로(초안): {r['route_hint']}",
                  f"- 규칙 판정: {r.get('rule', '-')}" + (f" · {r.get('ms', 0)//1000}s" if r.get("ms") else ""),
                  f"- 라우팅: intent={r.get('intent', '-')} · 독립형=“{r.get('standalone') or '-'}”" if r.get("tools") is not None and not r.get("route") else "",
                  f"- 도구: {' · '.join(r.get('tools') or []) or '-'}" if not r.get("route") else "",
                  f"- 모델: {r.get('model', '-')} · usage: {r.get('usage', '-')} · timings: {r.get('timings', '-')}" if r.get("model") else "",
                  f"- **점수**: ___ · **코멘트**: ", ""]
        if r.get("route"):
            lines += [f"라우팅: `{r['route']}` (실행 안 함)", ""]
        elif r.get("error"):
            lines += [f"오류: {r['error']}", ""]
        else:
            body = (r.get("answer") or "_(거부 — 답변 없음)_").replace("\n#", "\n####")
            if r.get("steps"):
                lines += ["<details><summary>답변 경로 (서술)</summary>", ""] + [f"{i+1}. {st}" for i, st in enumerate(r["steps"])]
                if r.get("process"):
                    lines += ["", "모델 판단 메모:"] + [f"- {x}" for x in r["process"]]
                lines += ["", "</details>", ""]
            lines += ["<details><summary>답변</summary>", "", body, ""]
            if r["gaps"]:
                lines += ["갭: " + " / ".join(f"[{g.get('type')}] {g.get('note')}" for g in r["gaps"]), ""]
            if r["citations"]:
                lines += ["인용: " + " · ".join(f"[{c['n']}] {c.get('kind', 'doc')} · {c['title'][:40]}" + (f" (doc {c['doc_id']})" if c.get("doc_id") else "")
                                                for c in r["citations"]), ""]
            lines += ["</details>", ""]
    out.write_text("\n".join(l for l in lines if l is not None))
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()
