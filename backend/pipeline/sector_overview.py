"""산업 개괄 (AI, ia-redesign §4.35, D-327-3) — 섹터에 걸린 내러티브와 최근 자료로 '지금 이 산업의 질문' 한 줄 + 세 줄 요약.

- 입력: `sector_view.sector_narratives`(살아 있는 내러티브: topic·제목·핵심 질문)와 `sector_docs`(최근 10일 자료 제목 상위 10).
  웹 검색은 넣지 않는다(수집 자료 기반).
- 입력 해시 = 걸린 내러티브의 (id) 목록. 내러티브가 새 버전으로 바뀌면 id가 바뀐다 → 그때만 다시 쓴다.
  같은 섹터는 주 1회(WEEK_DAYS)를 넘겨 다시 쓰지 않는다(비용 상한, cost-conscious). 걸린 내러티브가 없으면 쓰지 않는다.
- sonnet 1콜/섹터, json_schema 강제 출력. 결과는 `sector_overviews`(섹터당 한 행, 덮어쓰기).
- 관리자 플래그 `sector_overview`(기본 off) — 켜야 launchd `sectoroverview`(scripts/compute_sector_overview.py)가 돈다.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

JOB = "sector_overview"
MODEL = "sonnet"
WEEK_DAYS = 7
MAX_NARRATIVES = 8
MAX_DOCS = 10
SCHEMA = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "description": "지금 이 산업의 질문 — 합니다체 한 문장"},
        "bullets": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3},
    },
    "required": ["question", "bullets"],
}
SYSTEM = ("당신은 한국 주식 섹터를 정리하는 애널리스트입니다. 주어진 내러티브와 자료 제목만 근거로 씁니다. "
          "없는 사실·숫자를 지어내지 않습니다. 존댓말(합니다체)로, 짧고 구체적으로 씁니다.")


def input_hash(narratives: list[dict]) -> str:
    return hashlib.sha256(",".join(str(n["id"]) for n in sorted(narratives, key=lambda n: n["id"])).encode()).hexdigest()[:16]


def prompt(sector: str, narratives: list[dict], docs: list[dict]) -> str:
    lines = [f"섹터: {sector}", "", "이 섹터에 걸린 내러티브(주제 · 제목 · 핵심 질문):"]
    for n in narratives[:MAX_NARRATIVES]:
        lines.append(f"- [{n['topic']}] {n['title']}" + (f" / 질문: {n['core_question']}" if n.get("core_question") else ""))
    if docs:
        lines += ["", "최근 10일 자료 제목:"] + [f"- {d['title']}" for d in docs[:MAX_DOCS]]
    lines += ["", "1) question: 지금 이 산업에서 시장이 다투는 질문을 한 문장으로.",
              "2) bullets: 그 질문을 이루는 흐름 세 줄. 각 줄은 한 문장, 내러티브 내용에서만."]
    return "\n".join(lines)


def _due(row, h: str, now: datetime) -> str | None:
    """다시 쓸 이유가 없으면 건너뛸 사유를 돌려준다."""
    if row is None:
        return None
    if row["input_hash"] == h:
        return "내러티브 변화 없음"
    at = datetime.strptime(row["generated_at"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    if now - at < timedelta(days=WEEK_DAYS):
        return "주 1회 상한"
    return None


def clean(out: dict | None) -> tuple[str, list[str]] | None:
    if not isinstance(out, dict):
        return None
    q = str(out.get("question") or "").strip()
    bullets = [str(b).strip() for b in (out.get("bullets") or []) if str(b).strip()][:3]
    return (q, bullets) if q and len(bullets) == 3 else None


def run(sectors: list[str] | None = None, now: datetime | None = None, call=None) -> dict:
    """섹터별로 필요할 때만 생성 → {made, skipped, failed}. call = 테스트용 LLM 대역(prompt → dict)."""
    from database import get_connection
    from pipeline.sector_view import sector_docs, sector_narratives
    now = now or datetime.now(timezone.utc)
    conn = get_connection()
    made, skipped, failed = [], {}, []
    try:
        latest = conn.execute("SELECT max(trade_date) FROM stock_prices").fetchone()[0]
        names = sectors or [r[0] for r in conn.execute("SELECT DISTINCT group_name FROM sector_map ORDER BY group_name")]
        for sector in names:
            nars = sector_narratives(conn, sector)
            if not nars:
                skipped[sector] = "연결된 내러티브 없음"
                continue
            h = input_hash(nars)
            row = conn.execute("SELECT input_hash, generated_at FROM sector_overviews WHERE sector = ?", (sector,)).fetchone()
            reason = _due(row, h, now)
            if reason:
                skipped[sector] = reason
                continue
            docs = sector_docs(conn, sector, [], latest) if latest else []
            text = prompt(sector, nars, docs)
            try:
                if call:
                    out = call(text)
                else:
                    from pipeline.llm import extract_json, run as llm
                    res = llm(text, system=SYSTEM, model=MODEL, job=JOB, json_schema=SCHEMA, timeout=180)
                    out = extract_json(res.text)   # json_schema면 본문이 그 JSON이다
            except Exception as e:  # noqa: BLE001 — 한 섹터 실패가 나머지를 막지 않는다
                failed.append(f"{sector}({type(e).__name__})")
                continue
            got = clean(out)
            if not got:
                failed.append(f"{sector}(형식)")
                continue
            conn.execute("""INSERT INTO sector_overviews (sector, question, bullets_json, narrative_ids, input_hash, model, generated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(sector) DO UPDATE SET question=excluded.question,
                bullets_json=excluded.bullets_json, narrative_ids=excluded.narrative_ids, input_hash=excluded.input_hash,
                model=excluded.model, generated_at=excluded.generated_at""",
                         (sector, got[0], json.dumps(got[1], ensure_ascii=False), ",".join(str(n["id"]) for n in nars[:MAX_NARRATIVES]),
                          h, MODEL, now.strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
            made.append(sector)
    finally:
        conn.close()
    out = {"made": made, "skipped": skipped, "failed": failed}
    if failed:
        out["status"] = "partial" if made else "error"
    return out
