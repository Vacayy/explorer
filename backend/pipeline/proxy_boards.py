"""프록시 보드 (D-240) — 보드 항목 값 조립(LLM 0)과 보드 만들 때 한 번 도는 지표 제안(sonnet 1회).

제안은 실제 데이터가 있는 어댑터 참조만 후보로 받는다. 모델이 낸 참조는 전부 어댑터 카탈로그로 다시 검증하고,
원천이 없거나 검증에 실패한 것은 버리지 않고 needs_source로 따로 돌려준다(지어낸 참조는 받지 않는다).
"""
from __future__ import annotations

import json
import re

from pipeline import proxy_adapters as pa

MAX_CANDIDATES = 10
# 카탈로그 요약 — 어댑터별 (키워드 매칭에 더해 채울 기본 개수, 상한)
SUMMARY_LIMITS = {"credit": (40, 40), "trade": (16, 30), "call_momentum": (5, 15), "indicator": (40, 40), "retail": (22, 22),
                  "sector": (36, 36), "price": (0, 15), "transcript": (5, 15), "corpus": (5, 15)}
_STOP = {"그리고", "관련", "지표", "보드", "추이", "변화", "the", "and", "of"}

PROMPT = """너는 바이사이드 리서치 애널리스트다. 사용자가 '{topic}' 주제를 지켜볼 지표 보드를 만든다.
{context}
아래는 이 시스템에 **실제로 데이터가 있는** 지표 목록이다(어댑터별 `참조 | 이름 | 단위`). 이 주제의 선행 신호와 확정 신호가 되는
지표 5~10개를 골라 정의하라.

규칙:
- adapter_ref는 반드시 아래 목록에 있는 참조를 그대로 쓴다. 목록에 없는 참조를 지어내지 마라.
  형식 규칙으로 만들 수 있는 변형만 허용한다: {variants}
- 주제에 꼭 필요한데 목록에 원천이 없는 지표는 adapter와 adapter_ref를 null로 두고 needed에 필요한 데이터를 적어라(최대 3개).
- warn_direction: 이 지표가 어느 방향으로 움직이면 이 주제에 '주의' 신호인가(up|down).
- rationale: 왜 이 주제의 선행/확정 신호인가, 한두 문장.
- lead_or_confirm: lead(먼저 움직이는 신호) | confirm(뒤따라 확정하는 신호).

[데이터가 있는 지표]
{catalog}

JSON 배열만 출력:
[{{"label":"지표 이름","adapter":"credit","adapter_ref":"credit:ORCL","unit":"bp","warn_direction":"up","rationale":"...","lead_or_confirm":"lead","needed":null}}]"""


# ── 보드 항목 값 ────────────────────────────────────────────────────────────

def effective_ref(row) -> str | None:
    """보드 항목의 원천 참조. 결정적 어댑터면 adapter_ref, 기존 질문 프록시면 modality로 transcript/corpus."""
    if row["adapter_ref"]:
        return row["adapter_ref"]
    if row["proxy_id"] is None:
        return None
    return f"{'corpus' if row['modality'] == 'sentiment' else 'transcript'}:{row['proxy_id']}"


def item_view(conn, row, days: int | None = None) -> dict:
    if row["missing"]:
        empty = pa.empty_latest(None)
        return {"proxy_id": row["proxy_id"], "position": row["position"], "label": "(지워진 지표)", "adapter": None, "adapter_ref": None,
                "unit": None, "warn_direction": None, "rationale": None, "missing": True, "latest": empty, "in_warn": False, "series": []}
    ref = effective_ref(row)
    snap = pa.snapshot(conn, ref, days) if ref else {"latest": pa.empty_latest(None), "series": []}
    latest = snap["latest"]
    warn = row["warn_direction"]
    return {"proxy_id": row["proxy_id"], "position": row["position"], "label": row["label"],
            "adapter": ref.partition(":")[0] if ref else None, "adapter_ref": ref, "unit": row["unit"] or latest["unit"],
            "warn_direction": warn, "rationale": row["rationale"], "missing": False,
            "latest": latest, "in_warn": bool(warn and latest["direction"] == warn), "series": snap["series"]}


ITEM_SQL = ("SELECT bi.proxy_id, bi.position, pr.id IS NULL AS missing, pr.label, pr.unit, pr.modality, pr.adapter, pr.adapter_ref, "
            "pr.warn_direction, pr.rationale FROM proxy_board_items bi LEFT JOIN proxy_registry pr ON pr.id = bi.proxy_id "
            "WHERE bi.board_id=? ORDER BY bi.position, bi.proxy_id")


def board_items(conn, board_id: int, days: int | None = None) -> list[dict]:
    return [item_view(conn, r, days) for r in conn.execute(ITEM_SQL, (board_id,)).fetchall()]


# ── 지표 제안 (보드 만들 때만, sonnet 1회) ───────────────────────────────────

def keywords(*texts: str | None) -> list[str]:
    out: list[str] = []
    for t in texts:
        for w in re.findall(r"[A-Za-z][A-Za-z0-9&]+|[가-힣]{2,}|\d{4,}", t or ""):
            if w.lower() not in _STOP and w not in out:
                out.append(w)
    return out[:12]


def catalog_summary(conn, kws: list[str]) -> str:
    """어댑터별 기본 상위 몇 개 + 주제 키워드에 걸린 참조(상한까지). 원천이 빈 어댑터는 줄을 쓰지 않는다."""
    blocks = []
    for kind, adapter in pa.ADAPTERS.items():
        base, cap = SUMMARY_LIMITS.get(kind, (10, 20))
        seen: dict[str, dict] = {e["ref"]: e for e in pa.catalog(conn, kind, limit=base)} if base else {}
        for kw in kws:
            if kind == "price" and kw.isascii() and len(kw) <= 3:   # 종목명 부분 일치에 'AI' 같은 짧은 영문은 잡음뿐
                continue
            for e in pa.catalog(conn, kind, q=kw, limit=cap):
                seen.setdefault(e["ref"], e)
        if not seen:
            continue
        lines = [f"{e['ref']} | {e['label']} | {e['unit'] or '-'}" for e in list(seen.values())[:cap]]
        blocks.append(f"## {kind} — {adapter.label}: {adapter.description}\n" + "\n".join(lines))
    return "\n\n".join(blocks)


def _context(conn, question_id: int | None, narrative_id: int | None) -> tuple[str, list[str]]:
    lines, texts = [], []
    if question_id:
        q = conn.execute("SELECT text FROM questions WHERE id=?", (question_id,)).fetchone()
        if q:
            lines.append(f"연결된 핵심질문: {q['text']}")
            texts.append(q["text"])
    if narrative_id:
        n = conn.execute("SELECT topic, title FROM narratives WHERE id=?", (narrative_id,)).fetchone()
        if n:
            lines.append(f"연결된 서사: {n['title'] or n['topic']}")
            texts.append(n["topic"])
    return "\n".join(lines), texts


def _parse(raw: str) -> list[dict]:
    start, end = raw.find("["), raw.rfind("]")
    if start < 0 or end <= start:
        raise ValueError("JSON 배열이 없다")
    data = json.loads(raw[start:end + 1])
    if not isinstance(data, list):
        raise ValueError("JSON 배열이 아니다")
    return [d for d in data if isinstance(d, dict)]


def validate(conn, proposals: list[dict]) -> tuple[list[dict], list[dict]]:
    """모델 제안 → (검증된 후보, 원천 없음). 아무것도 조용히 버리지 않는다(중복 ref만 합친다)."""
    candidates, needs, seen = [], [], set()
    for p in proposals:
        label = str(p.get("label") or "").strip() or "(이름 없음)"
        kind = p.get("adapter")
        kind = kind.strip() if isinstance(kind, str) and kind.strip().lower() not in ("", "none", "null") else None
        ref = p.get("adapter_ref")
        ref = ref.strip() if isinstance(ref, str) and ref.strip() else None
        rationale = p.get("rationale") if isinstance(p.get("rationale"), str) else None
        miss = {"label": label, "adapter": kind, "adapter_ref": ref, "rationale": rationale}
        if not kind or not ref:
            needs.append({**miss, "reason": str(p.get("needed") or rationale or "원천 없음 — 추가 수집 필요")})
            continue
        if kind not in pa.ADAPTERS:
            needs.append({**miss, "reason": f"알 수 없는 어댑터 '{kind}' — 추가 수집 필요"})
            continue
        meta = pa.describe(conn, ref, kind)
        if not meta:
            needs.append({**miss, "reason": f"원천에 없는 참조 '{ref}' — 추가 수집 필요"})
            continue
        if not pa.series(conn, meta["ref"], "1900-01-01"):
            needs.append({**miss, "reason": f"'{meta['ref']}' 원천에 값이 아직 없다"})
            continue
        if meta["ref"] in seen:
            continue
        if len(candidates) >= MAX_CANDIDATES:
            needs.append({**miss, "reason": f"후보 상한 {MAX_CANDIDATES}개 초과"})
            continue
        seen.add(meta["ref"])
        warn = p.get("warn_direction") if p.get("warn_direction") in ("up", "down") else None
        loc = p.get("lead_or_confirm") if p.get("lead_or_confirm") in ("lead", "confirm") else None
        candidates.append({"label": label, "adapter": kind, "adapter_ref": meta["ref"], "unit": meta["unit"], "warn_direction": warn,
                           "rationale": rationale, "lead_or_confirm": loc, "source_label": meta["label"]})
    return candidates, needs


def suggest(conn, topic: str, question_id: int | None = None, narrative_id: int | None = None, call=None) -> dict:
    """LLM 1회. call은 테스트 주입용 — 기본은 llm_calls 원장에 남는 _call_claude_code(sonnet)."""
    if call is None:
        from pipeline.enrich import _call_claude_code
        call = lambda prompt: _call_claude_code(prompt, model="sonnet", timeout=240)  # noqa: E731
    context, texts = _context(conn, question_id, narrative_id)
    variants = "; ".join(f"{a.ref_format}" for a in pa.ADAPTERS.values())
    prompt = PROMPT.format(topic=topic, context=context, variants=variants, catalog=catalog_summary(conn, keywords(topic, *texts)))
    proposals = _parse(call(prompt))
    candidates, needs = validate(conn, proposals)
    return {"topic": topic, "candidates": candidates, "needs_source": needs}
