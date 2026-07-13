"""공고화(consolidation) — 반복 관측된 주장을 지식으로 승격 (K0).

설계: docs/specs/knowledge-hierarchy-design.md
- 승격 기준: 독립 관측 2+ (릴레이 접기, A-3) × 시간 분산 (간격 요건, F-1)
  × 느린 층만 (event 제외, A-5) × 증거 doc_id 인용 강제 (환각 방어)
- 확증편향 보정: 후보마다 반대 증거 탐색 1회 의무 (A-6)
- 산출은 승인 큐(review_status='proposed') — 사람이 홈에서 결정 (E-1)
- activation은 저장하지 않는다 — 조회 시 ln(Σ t^-d), 층별 감쇠 (A-2)
"""
import json
import math
import os
import struct
import subprocess
from datetime import datetime, timezone

from database import get_connection
from pipeline.enrich import _claude_bin, llm_engine

# 지식 승격·심사는 다층 판단이라 opus (stakeholder 지정, 2026-07-13)
KNOWLEDGE_MODEL = os.getenv("KNOWLEDGE_MODEL", "opus")


def _call_claude_knowledge(prompt: str) -> str:
    """지식 라인 공용 opus 텍스트 호출 (승격·모순·반증 판정 공통 티어)."""
    proc = subprocess.run(
        [_claude_bin(), "-p", "--model", KNOWLEDGE_MODEL, "--output-format", "json", prompt],
        capture_output=True, text=True, timeout=400)
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p 실패: {proc.stderr[:200]}")
    return json.loads(proc.stdout).get("result", "")


def _call_json(prompt: str) -> dict:
    raw = _call_claude_knowledge(prompt)
    s, e = raw.find("{"), raw.rfind("}")
    return json.loads(raw[s:e + 1])

WINDOW_DAYS = 14          # 승격 검토 창
MIN_DOCS = 4              # 엔티티당 최소 언급 (후보 대상 선정)
MAX_ENTITIES = 8          # 배치당 검토 엔티티 상한
RELAY_SIM = 0.88          # 이 이상 유사하면 동일 관측 (릴레이 접기)
MIN_INDEPENDENT = 2       # 독립 관측 하한
SLOW_LAYERS = ("cycle", "structure", "regime")

# 층별 감쇠율 d — pace layer가 반감기를 결정 (A-5)
LAYER_DECAY = {"event": 1.0, "flow": 0.6, "cycle": 0.35, "structure": 0.2, "regime": 0.1}


def activation(observed_ats: list[str], layer: str, now: datetime | None = None) -> float:
    """ACT-R 기저 활성화 ln(Σ t^-d) — 저장하지 않고 조회 시 계산."""
    now = now or datetime.now(timezone.utc)
    d = LAYER_DECAY.get(layer, 0.35)
    total = 0.0
    for ts in observed_ats:
        try:
            t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        days = max((now - t).total_seconds() / 86400, 0.05)
        total += days ** (-d)
    return math.log(total) if total > 0 else float("-inf")


def _embeddings(conn, doc_ids: list[int]) -> dict[int, list[float]]:
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except Exception:
        return {}
    out = {}
    for d in doc_ids:
        row = conn.execute("SELECT embedding FROM doc_vec WHERE rowid=?", (d,)).fetchone()
        if row:
            out[d] = list(struct.unpack(f"{len(row[0]) // 4}f", row[0]))
    return out


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1
    nb = math.sqrt(sum(x * x for x in b)) or 1
    return dot / (na * nb)


def mark_independence(conn, docs: list[dict]) -> list[dict]:
    """릴레이 접기 (A-3): 유사도 RELAY_SIM+ 문서 묶음은 첫 건만 독립으로."""
    embs = _embeddings(conn, [d["id"] for d in docs])
    independent_ids: list[int] = []
    for d in docs:
        e = embs.get(d["id"])
        dup = False
        if e:
            for ind_id in independent_ids:
                e2 = embs.get(ind_id)
                if e2 and _cosine(e, e2) >= RELAY_SIM:
                    dup = True
                    break
        d["independent"] = not dup
        if not dup:
            independent_ids.append(d["id"])
    return docs


STATEMENT_SIM = 0.86  # 이 이상 유사한 주장 = 같은 지식 (병합, 파편화 방지)

_embed_model = None


def _embed_statements(texts: list[str]) -> list[list[float]]:
    global _embed_model
    if _embed_model is None:
        from fastembed import TextEmbedding
        from pipeline.search import EMBED_MODEL
        _embed_model = TextEmbedding(EMBED_MODEL)
    return [list(e) for e in _embed_model.embed(texts)]


def _find_similar_knowledge(conn, statement: str) -> int | None:
    """기존(proposed+active) 지식 중 같은 주장 찾기 — 있으면 병합 대상 id."""
    rows = conn.execute("""
        SELECT id, statement FROM knowledge
        WHERE review_status IN ('proposed','active') AND valid_to IS NULL""").fetchall()
    if not rows:
        return None
    embs = _embed_statements([statement] + [r["statement"] for r in rows])
    target = embs[0]
    best_id, best_sim = None, 0.0
    for r, e in zip(rows, embs[1:]):
        sim = _cosine(target, e)
        if sim > best_sim:
            best_id, best_sim = r["id"], sim
    return best_id if best_sim >= STATEMENT_SIM else None


def _merge_into(conn, kid: int, entity_id: int, ev_docs: list[dict]):
    """같은 주장 발견 시: 새 증거·엔티티를 기존 지식에 병합 (corroboration 증가)."""
    conn.execute("INSERT OR IGNORE INTO knowledge_entities (knowledge_id, entity_id) VALUES (?, ?)",
                 (kid, entity_id))
    existing_docs = {r["doc_id"] for r in conn.execute(
        "SELECT doc_id FROM knowledge_evidence WHERE knowledge_id=?", (kid,))}
    for d in ev_docs:
        if d["id"] in existing_docs:
            continue
        conn.execute("""
            INSERT INTO knowledge_evidence (knowledge_id, doc_id, stance, independent, observed_at)
            VALUES (?, ?, 'support', ?, ?)""",
            (kid, d["id"], int(d.get("independent", True)),
             d["published_at"] or datetime.now(timezone.utc).isoformat()))
    conn.commit()


def promote_batch() -> dict:
    """주간 승격 배치 — 후보를 knowledge(proposed)로 생성. 반환: 통계."""
    if llm_engine() != "claude-code":
        return {"skipped": "claude-code 엔진 아님"}

    conn = get_connection()
    targets = conn.execute(f"""
        SELECT e.id entity_id, e.name, count(DISTINCT rd.id) n
        FROM entity_links el
        JOIN entities e ON el.entity_id = e.id
        JOIN raw_documents rd ON el.doc_id = rd.id
        WHERE el.link_type IN ('stock','industry','topic','person')
          AND rd.published_at >= datetime('now', '-{WINDOW_DAYS} days')
        GROUP BY e.id HAVING n >= {MIN_DOCS}
        ORDER BY n DESC LIMIT {MAX_ENTITIES}
    """).fetchall()

    stats = {"entities": len(targets), "proposed": 0, "rejected_by_rule": 0, "failed": 0}
    for ent in targets:
        docs = [dict(r) for r in conn.execute(f"""
            SELECT DISTINCT rd.id, rd.title, rd.published_at, rd.source_type,
                   substr(rd.markdown, 1, 400) ex
            FROM entity_links el JOIN raw_documents rd ON el.doc_id = rd.id
            WHERE el.entity_id = ? AND rd.published_at >= datetime('now', '-{WINDOW_DAYS} days')
            ORDER BY rd.published_at DESC LIMIT 25
        """, (ent["entity_id"],))]
        if len(docs) < MIN_DOCS:
            continue

        existing = [r["statement"] for r in conn.execute("""
            SELECT k.statement FROM knowledge k
            JOIN knowledge_entities ke ON ke.knowledge_id = k.id
            WHERE ke.entity_id = ? AND k.review_status != 'rejected'
              AND k.valid_to IS NULL""", (ent["entity_id"],))]

        ctx = "\n\n".join(f"[{i+1}] ({d['source_type']}, {(d['published_at'] or '')[:10]}) "
                          f"{d['title']}\n{d['ex'] or ''}" for i, d in enumerate(docs))
        existing_block = ("\n\n[이미 승격된 지식 — 중복 금지]\n" + "\n".join(f"- {s}" for s in existing)) if existing else ""
        prompt = (
            f"너는 리서치센터의 지식 편집자다. 아래는 '{ent['name']}' 관련 최근 {WINDOW_DAYS}일 문서들이다.\n"
            "여러 문서에서 반복 관측되는, '느린 층'의 주장만 0~2개 추출해라.\n"
            "- 느린 층: cycle(사이클 국면) | structure(경쟁구도·계약·지배구조) | regime(제도·패러다임)\n"
            "- 오늘의 시세·단발 이벤트(event)나 단순 수급(flow)은 제외\n"
            "- 각 주장은 한 문장, 문서에 실제로 있는 내용만, 근거 문서 번호를 반드시 나열\n"
            '- 반복 관측이 없으면 빈 배열: {"claims": []}\n'
            'JSON만 출력: {"claims": [{"statement": "…", "pace_layer": "cycle|structure|regime", '
            '"evidence": [문서 번호들]}]}'
            f"{existing_block}\n\n[문서]\n{ctx}"
        )
        try:
            data = _call_json(prompt)
        except Exception:
            stats["failed"] += 1
            continue

        for claim in (data.get("claims") or [])[:2]:
            st = str(claim.get("statement") or "").strip()
            layer = str(claim.get("pace_layer") or "").strip()
            ev_idx = [i for i in (claim.get("evidence") or []) if isinstance(i, int) and 1 <= i <= len(docs)]
            ev_docs = [docs[i - 1] for i in ev_idx]
            # 규칙 검증: 인용 강제 · 느린 층 · 간격(서로 다른 날짜 2+) · 독립 관측 2+
            if not st or layer not in SLOW_LAYERS or len(ev_docs) < 2:
                stats["rejected_by_rule"] += 1
                continue
            dates = {(d["published_at"] or "")[:10] for d in ev_docs}
            if len(dates) < 2:
                stats["rejected_by_rule"] += 1   # 몰림 ≠ 반복 확인 (간격 요건)
                continue
            ev_docs = mark_independence(conn, ev_docs)
            if sum(1 for d in ev_docs if d["independent"]) < MIN_INDEPENDENT:
                stats["rejected_by_rule"] += 1   # 릴레이 재방송뿐 (독립성)
                continue

            # 파편화 방지: 같은 주장이 이미 있으면(배치 내 형제 포함) 병합 — 새 행 대신
            # corroboration 증가 (A-1 '스키마 일치 시 빠른 편입')
            dup = _find_similar_knowledge(conn, st)
            if dup:
                _merge_into(conn, dup, ent["entity_id"], ev_docs)
                stats["merged"] = stats.get("merged", 0) + 1
                continue

            # 확증편향 보정: 반대 증거 탐색 1회 (A-6)
            refutes = _find_refutes(conn, st, {d["id"] for d in ev_docs})

            kid = conn.execute("""
                INSERT INTO knowledge (statement, epistemic_status, review_status, pace_layer,
                                       confidence, valid_from, model)
                VALUES (?, 'observed', 'proposed', ?, ?, date('now'), 'claude-code/haiku')
            """, (st, layer, round(min(0.5 + 0.1 * len(ev_docs), 0.9), 2))).lastrowid
            conn.execute("INSERT OR IGNORE INTO knowledge_entities (knowledge_id, entity_id) VALUES (?, ?)",
                         (kid, ent["entity_id"]))
            for d in ev_docs:
                conn.execute("""
                    INSERT INTO knowledge_evidence (knowledge_id, doc_id, stance, independent, observed_at)
                    VALUES (?, ?, 'support', ?, ?)""",
                    (kid, d["id"], int(d["independent"]), d["published_at"] or datetime.now(timezone.utc).isoformat()))
            for rd_id, rd_at in refutes:
                conn.execute("""
                    INSERT INTO knowledge_evidence (knowledge_id, doc_id, stance, independent, observed_at)
                    VALUES (?, ?, 'refute', 1, ?)""", (kid, rd_id, rd_at))
            conn.commit()
            stats["proposed"] += 1

    conn.execute("INSERT OR REPLACE INTO pipeline_runs (name, last_run_at) VALUES ('promote', datetime('now'))")
    conn.commit()
    conn.close()
    return stats


def promote_due(conn, days: int = 7) -> bool:
    """주간 승격이 밀렸는가 — cron 누락(PC 꺼짐) 시 수집 체인이 catch-up."""
    r = conn.execute("SELECT last_run_at FROM pipeline_runs WHERE name='promote'").fetchone()
    if not r:
        return True
    return bool(conn.execute(
        "SELECT datetime(?) <= datetime('now', ?)", (r["last_run_at"], f"-{days} days")).fetchone()[0])


def _find_refutes(conn, statement: str, exclude: set[int]) -> list[tuple[int, str]]:
    """주장에 대한 반대 증거 탐색 — 검색 top5 중 반박 문서를 haiku가 판별."""
    try:
        from pipeline.search import search
        hits = [h["doc_id"] for h in search(statement, k=8) if h["doc_id"] not in exclude][:5]
        if not hits:
            return []
        ph = ",".join("?" for _ in hits)
        docs = conn.execute(f"""
            SELECT id, title, published_at, substr(markdown, 1, 300) ex
            FROM raw_documents WHERE id IN ({ph})""", hits).fetchall()
        ctx = "\n".join(f"[{d['id']}] {d['title']}: {d['ex'] or ''}" for d in docs)
        data = _call_json(
            f"주장: \"{statement}\"\n아래 문서 중 이 주장과 명백히 모순되거나 반박하는 것의 id만 골라라. "
            '없으면 빈 배열. JSON만: {"refute_ids": []}\n' + ctx)
        ids = {i for i in (data.get("refute_ids") or []) if isinstance(i, int)}
        return [(d["id"], d["published_at"] or "") for d in docs if d["id"] in ids]
    except Exception:
        return []
