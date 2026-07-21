"""통합 리포트 — 공유 인과로 엮인 내러티브들을 애널리스트 참고자료로 취합하고,
같은 종목의 '내러티브별 다른 파급'을 다 모은 뒤 반영해 종목을 다시 분석 → Top-down 리포트.

연쇄 LLM(오케스트레이션 도구 아님, scenario/mega처럼 순차 호출):
  취합(LLM 0) → 종목별 다각도 재분석 ×M(sonnet) → 리포트 종합 ×1(opus). 전부 캐시.
스펙: docs/specs/integrated-report.md. 선례: mega_narrative(공유 노드 서사).
"""
import hashlib
import json

from pipeline.enrich import _call_claude_code, llm_engine
from pipeline.upside_model import _anchor

TOP_RELATED = 5    # 공유 이웃 내러티브 상위
TOP_STOCKS = 6     # 종목 재분석 대상 (교차 현저성 순)
BODY_EXCERPT = 600
SCEN_EXCERPT = 700


def _latest_narr(conn, topic: str):
    return conn.execute(
        "SELECT id, topic, title, body, version FROM narratives "
        "WHERE topic=? AND COALESCE(kind,'topic')='topic' ORDER BY version DESC LIMIT 1",
        (topic,)).fetchone()


def _members_hash(members: list[tuple[str, int]]) -> str:
    return hashlib.sha256("|".join(f"{t}:{v}" for t, v in sorted(members)).encode()).hexdigest()


def _parse_json(raw: str) -> dict:
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    s, e = raw.find("{"), raw.rfind("}")
    if s < 0 or e <= s:
        raise ValueError(f"JSON 없음: {raw[:80]!r}")
    return json.loads(raw[s:e + 1])


def _anchor_line(a: dict) -> str:
    """앵커 재무를 한 줄로 (없으면 미상)."""
    def v(x, unit=""):
        return f"{x}{unit}" if x is not None else "미상"
    return (f"현재가 {v(a.get('price'))} · PER {v(a.get('per'), '배')} · "
            f"매출 {v(a.get('revenue'))} · 순이익률 {v(a.get('net_margin'), '%')} · 시총 {v(a.get('market_cap'))}")


def _synth_stock(a: dict, code: str, name: str, angles: list[dict]) -> dict | None:
    """종목 다각도 재분석 (sonnet, 연쇄 1콜) — 여러 내러티브의 파급을 관통하는 통합 투자 포인트."""
    angle_block = "\n".join(
        f"- [{ag['narrative']}] ({ag.get('rel') or '수혜'}) {ag.get('reason') or ''}" for ag in angles)
    prompt = (
        f"너는 애널리스트다. '{name}'({code})가 여러 산업 내러티브에서 각각 어떻게 영향받는지 아래에 모았다. "
        "같은 종목이라도 내러티브마다 파급 논리가 다르다 — 이 다각도를 관통하는 **하나의 통합 투자 포인트**로 "
        "종합해라(각 파급의 단순 나열 금지). 근거 없는 수치는 만들지 말고, 재무는 아래 값만 참고.\n"
        "JSON만 출력(코드블록·머리말 없이): "
        '{"thesis": "2~3문장 통합 논지(마크다운)", "key_points": ["핵심 투자 포인트 2~4개"], '
        '"risks": ["리스크·무효화 조건 1~3개"]}\n'
        f"[재무 앵커] {_anchor_line(a)}\n"
        f"[내러티브별 파급]\n{angle_block}")
    try:
        d = _parse_json(_call_claude_code(prompt, model="sonnet", timeout=240))
    except Exception:
        return None
    return {"code": code, "name": name,
            "thesis": d.get("thesis") or "",
            "key_points": d.get("key_points") or [],
            "risks": d.get("risks") or []}


def _synth_report(anchor_topic: str, narr_material: list[dict], stock_blocks: list[dict]) -> dict:
    """Top-down 리포트 종합 (opus, 1콜) — 산업 → 기업 → 투자 전략."""
    narr_block = "\n\n".join(
        f"### {m['topic']} — {m['title'] or ''}\n{(m['body'] or '')[:BODY_EXCERPT]}"
        + (f"\n[파급] {m['scenario'][:SCEN_EXCERPT]}" if m.get("scenario") else "")
        for m in narr_material)
    stock_block = "\n\n".join(
        f"### {s['name']}({s['code']})\n{s['thesis']}\n포인트: {' · '.join(s['key_points'])}\n"
        f"리스크: {' · '.join(s['risks'])}" for s in stock_blocks) or "(분석 종목 없음)"
    prompt = (
        "너는 1인 리서치센터의 수석 애널리스트다. 아래는 공유 인과로 엮인 산업 내러티브들(참고자료)과, "
        "그것들을 관통해 이미 종합한 종목별 투자 포인트다. 이를 하나의 **Top-down 투자 리포트**로 써라. "
        "참고자료를 요약 나열하지 말고, 산업의 구조적 그림에서 개별 기업으로 내려가는 하나의 논리로.\n"
        "JSON만 출력(코드블록·머리말 없이): "
        '{"title": "리포트 제목(질문형/주장형 한 줄)", "body": "마크다운 리포트"}\n'
        "body 구조(섹션 고정):\n"
        "## 산업 분석\n엮인 내러티브·파급을 관통하는 산업의 구조적 동인과 전개 갈래 (근본원인→전개), "
        "그리고 이 그림이 흔들리는 조건 1~2개.\n"
        "## 기업 분석\n위 종목별 투자 포인트를 산업 논리에 배치 — 왜 이 종목들인지, 각 종목의 핵심 한두 줄. "
        "종목명은 그대로 쓰되 없는 수치 창작 금지.\n"
        "## 투자 포인트 · 전략\n종합 판단 + 비대칭(하방 제한 vs 상방 여지) 프레이밍 + 감시할 무효화 조건 + "
        "타이밍은 추세추종 렌즈(RS·52주)로 별도임을 명시. 단정 금지, 범위+조건부.\n"
        "규율: 참고자료에 없는 사실을 지어내지 마라. 전체 1000자 내외. 내부 코드·약어 노출 금지.\n\n"
        f"[앵커 주제] {anchor_topic}\n\n[참고 내러티브·파급]\n{narr_block}\n\n[종목별 투자 포인트]\n{stock_block}")
    d = _parse_json(_call_claude_code(prompt, model="opus", timeout=300))
    return {"title": d.get("title") or f"{anchor_topic} 통합 리포트", "body": d.get("body") or ""}


def build_report(conn, anchor_topic: str, force: bool = False) -> dict:
    """앵커 주제 → 공유 이웃 취합 → 종목 다각도 재분석 → Top-down 리포트 (연쇄 LLM, 캐시)."""
    if llm_engine() != "claude-code":
        return {"error": "LLM 엔진 없음 (ENRICH_ENGINE=claude-code 필요)"}
    anchor = _latest_narr(conn, anchor_topic)
    if not anchor:
        return {"error": f"'{anchor_topic}' 내러티브 없음 — 먼저 내러티브를 생성하세요"}

    # 1. 앵커 + 공유 이웃 (LLM 0)
    from pipeline.narrative import related_narratives
    rel = related_narratives(conn, anchor["id"]).get("related", [])
    member_narrs, seen = [dict(anchor)], {anchor_topic}
    for r in rel:
        if r["topic"] in seen:
            continue
        m = _latest_narr(conn, r["topic"])
        if m:
            member_narrs.append(dict(m)); seen.add(r["topic"])
        if len(member_narrs) > TOP_RELATED:
            break
    members = [(m["topic"], m["version"]) for m in member_narrs]
    mhash = _members_hash(members)

    # 캐시: 구성원 해시 동일 & 비-refresh → 저장분
    if not force:
        cur = conn.execute(
            "SELECT title, body, stocks_json, members_json, members_hash, created_at "
            "FROM reports WHERE anchor_topic=?", (anchor_topic,)).fetchone()
        if cur and cur["members_hash"] == mhash:
            return {"status": "ok", "title": cur["title"], "answer": cur["body"],
                    "members": json.loads(cur["members_json"] or "[]"),
                    "stocks": json.loads(cur["stocks_json"] or "[]"),
                    "cached": True, "created_at": cur["created_at"]}

    # 2. 자료 수집 + 종목별 다각도 집계 (LLM 0, 캐시된 scenario 재사용)
    narr_material, stock_angles = [], {}
    for m in member_narrs:
        sc = conn.execute(
            "SELECT answer, beneficiaries FROM scenarios WHERE topic=?", (m["topic"],)).fetchone()
        bens = json.loads(sc["beneficiaries"]) if (sc and sc["beneficiaries"]) else []
        narr_material.append({"topic": m["topic"], "title": m["title"], "body": m["body"],
                              "scenario": sc["answer"] if sc else None})
        for b in bens:
            code = b.get("stock_code")
            if not code:
                continue
            slot = stock_angles.setdefault(code, {"name": b.get("name") or code, "angles": []})
            slot["angles"].append({"narrative": m["topic"], "rel": b.get("rel"), "reason": b.get("reason")})

    # 3. 랭킹 = 등장 내러티브 수(교차 현저성)
    ranked = sorted(stock_angles.items(), key=lambda kv: -len(kv[1]["angles"]))[:TOP_STOCKS]

    # 4. 종목별 재분석 (sonnet, 연쇄)
    stock_blocks = []
    for code, info in ranked:
        blk = _synth_stock(_anchor(conn, code), code, info["name"], info["angles"])
        if blk:
            stock_blocks.append(blk)

    # 5. 리포트 종합 (opus)
    rpt = _synth_report(anchor_topic, narr_material, stock_blocks)

    # 6. 적재
    stocks = [{"code": s["code"], "name": s["name"]} for s in stock_blocks]
    conn.execute(
        "INSERT INTO reports (anchor_topic, title, body, members_json, stocks_json, members_hash, "
        "model, created_at) VALUES (?,?,?,?,?,?,?,datetime('now')) "
        "ON CONFLICT(anchor_topic) DO UPDATE SET title=excluded.title, body=excluded.body, "
        "members_json=excluded.members_json, stocks_json=excluded.stocks_json, "
        "members_hash=excluded.members_hash, model=excluded.model, created_at=excluded.created_at",
        (anchor_topic, rpt["title"], rpt["body"], json.dumps([m["topic"] for m in member_narrs], ensure_ascii=False),
         json.dumps(stocks, ensure_ascii=False), mhash, "claude-code/opus+sonnet"))
    conn.commit()
    return {"status": "ok", "title": rpt["title"], "answer": rpt["body"],
            "members": [m["topic"] for m in member_narrs], "stocks": stocks,
            "cached": False, "created_at": None}
