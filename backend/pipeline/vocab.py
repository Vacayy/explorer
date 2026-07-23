"""어휘 통합 (vocab consolidation, D-033) — theme·macro·sector 노드 파편화 치유(sector: D-062).

쓰기 시 = 결정적 해소(_resolve_or_create_node + entity_merges redirect),
배치 = 의미적 치유(여기): 후보 생성(fastembed) → 판정(sonnet) → 병합.

- 후보 생성: 같은 type 노드 이름을 fastembed(search.py 인프라 재사용, 384d 다국어 MiniLM)로
  임베딩 → 인메모리 전수 코사인 ≥ threshold 쌍 (theme 745·macro 149 규모라 sqlite-vec 불필요).
- 판정: claude -p sonnet 배치 (여러 쌍/콜) — same|different + 근거 한 문장.
- 병합: survivor로 FK 전수 재배선(entity_relations는 UNIQUE 충돌 시 두 엣지 병합) → loser 삭제.
"""
import math

from pipeline.enrich import _call_claude_code, _parse_json, llm_engine

MERGE_TYPES = ("theme", "macro", "sector", "event")  # sector·event 추가(D-062·D-063): 섹터/사건 파편 치유
DEFAULT_THRESHOLD = 0.90
JUDGE_BATCH = 15


# ── 1. 후보 생성 (LLM 0) ─────────────────────────────────────────────

def find_merge_candidates(conn, types=MERGE_TYPES, threshold=DEFAULT_THRESHOLD) -> dict:
    """같은 type 노드 이름 쌍 중 코사인 유사도 ≥ threshold.

    반환: {"candidates": [{a_id,a_name,b_id,b_name,type,cosine}], "reason": None|str}.
    fastembed 미설치 시 graceful degrade — 빈 리스트 + 사유.
    """
    try:
        from pipeline.search import _get_model
        model = _get_model()
    except Exception as e:  # noqa: BLE001 — 미설치·로드 실패 모두 degrade
        return {"candidates": [], "reason": f"fastembed 미가용: {str(e)[:120]}"}

    candidates: list[dict] = []
    for type_ in types:
        rows = conn.execute(
            "SELECT id, name FROM entities WHERE type=? AND status IS NOT 'merged' ORDER BY id",
            (type_,)).fetchall()
        if len(rows) < 2:
            continue
        names = [r["name"] for r in rows]
        vecs = [_normalize(v) for v in model.embed(names)]
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                cos = _dot(vecs[i], vecs[j])
                if cos >= threshold:
                    candidates.append({
                        "a_id": rows[i]["id"], "a_name": rows[i]["name"],
                        "b_id": rows[j]["id"], "b_name": rows[j]["name"],
                        "type": type_, "cosine": round(cos, 4),
                    })
    candidates.sort(key=lambda c: -c["cosine"])
    return {"candidates": candidates, "reason": None}


def _normalize(vec) -> list[float]:
    v = list(vec)
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


# ── 2. 판정 (sonnet) ─────────────────────────────────────────────────

def judge_pairs(pairs: list[dict]) -> list[dict]:
    """후보 쌍을 sonnet 배치로 same|different 판정.

    반환: 입력 pairs에 verdict('same'|'different') + rationale 를 얹은 리스트.
    llm_engine()이 claude-code가 아니면 판정 불가 → RuntimeError.
    """
    if llm_engine() != "claude-code":
        raise RuntimeError("쌍 판정은 claude-code 엔진 필요 — .env ENRICH_ENGINE=claude-code")
    out: list[dict] = []
    for i in range(0, len(pairs), JUDGE_BATCH):
        batch = pairs[i:i + JUDGE_BATCH]
        raw = _call_claude_code(_build_judge_prompt(batch), model="sonnet", timeout=300)
        verdicts = _parse_verdicts(_parse_json(raw), len(batch))
        for j, pair in enumerate(batch):
            v = verdicts.get(j, {})
            verdict = v.get("verdict")
            out.append({
                **pair,
                "verdict": verdict if verdict in ("same", "different") else "different",
                "rationale": (v.get("rationale") or "").strip()[:200] or (
                    "판정 누락 — 안전하게 different 처리" if verdict not in ("same", "different") else ""),
            })
    return out


def _build_judge_prompt(pairs: list[dict]) -> str:
    lines = "\n".join(
        f'{k + 1}. "{p["a_name"]}" vs "{p["b_name"]}" (type={p["type"]})'
        for k, p in enumerate(pairs))
    return (
        "아래는 인과 그래프 노드(theme·macro·sector·event 등) 이름 쌍이다. 각 쌍이 "
        "'같은 개념(same)'인지 '다른 개념(different)'인지 판정해 JSON만 출력해. 설명·코드블록 금지.\n"
        "판정 규율:\n"
        "- 수준/방향/시점이 다르면 different. 예: '금리'와 '금리 상승'은 different — "
        "하나는 지표, 하나는 방향 주장이다. '반도체'와 '반도체 업황 개선'도 different.\n"
        "- 표기·언어 변형만 다르면 same. 예: 'AI Agent'와 'AI 에이전트', 'Web3'와 '웹3'.\n"
        "- 같은 대상을 가리키는 동의어·축약·어순·병기 차이는 same. "
        "예: 'AI 거품론·고점론'과 'AI 고점론', 'AI 데이터센터 투자'와 'AI 데이터센터 투자 확대'는 "
        "판단 대상 — 후자는 '확대'라는 방향이 붙었으니 애매하면 different로.\n"
        "- 사건(event)은 특정 발생이다. 같은 발생을 표현·구체성만 달리하면 same 예: "
        "'SK하이닉스 ADR 상장'과 'SK하이닉스 나스닥 ADR 상장'('나스닥'은 상장 장소 특정일 뿐 동일 사건). "
        "다른 시점·다른 주체·상위/하위 사건이거나 방향이 반대면 different 예: "
        "'반도체 공급 부족'과 '반도체 공급 완화'(반대 방향), '반도체 종목 급락'과 '반도체 대장주 급락'(범위 다름).\n"
        "- 애매하면 different (병합은 되돌리기 비싸다).\n"
        f'형식: {{"results": [{{"pair": 1, "verdict": "same|different", "rationale": "한 문장 근거"}}, ...]}}\n'
        f"results는 정확히 {len(pairs)}개, pair 번호는 입력 그대로.\n\n"
        f"[쌍들]\n{lines}"
    )


def _parse_verdicts(data: dict, n: int) -> dict:
    out: dict[int, dict] = {}
    for r in (data.get("results") or []):
        try:
            idx = int(r.get("pair")) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= idx < n:
            out[idx] = r
    return out


# ── 3. 병합 (결정적) ─────────────────────────────────────────────────

def causal_degree(conn, entity_id: int) -> int:
    """인과 엣지 참조 수 — entity_relations에서 src 또는 dst로 등장한 횟수 (survivor 선정 기준)."""
    return conn.execute(
        "SELECT COUNT(*) c FROM entity_relations WHERE src_id=? OR dst_id=?",
        (entity_id, entity_id)).fetchone()["c"]


def pick_survivor(conn, id_a: int, id_b: int) -> tuple[int, int]:
    """survivor, loser 반환 — 인과 엣지 참조 많은 쪽이 survivor, 동률이면 낮은 id(오래된 쪽)."""
    da, db = causal_degree(conn, id_a), causal_degree(conn, id_b)
    if da != db:
        return (id_a, id_b) if da > db else (id_b, id_a)
    return (id_a, id_b) if id_a < id_b else (id_b, id_a)


# entity_relations의 COALESCE(non-null 우선, survivor 엣지 기준) 대상 컬럼
_EDGE_MERGE_COLS = (
    "mechanism", "reference_period", "time_orientation",
    "feedback_note", "promoted_knowledge_id", "narrative_id",
)


def merge_entities(conn, survivor_id: int, loser_id: int, rationale: str | None) -> dict:
    """loser를 survivor로 병합 — 하나의 트랜잭션. 반환: 요약 dict.

    a. entity_relations 특수 처리 (UNIQUE 충돌 시 두 엣지 병합, evidence 이관)
    b. 나머지 entities FK 참조 테이블 전수 재배선 (PRAGMA로 동적 발견)
    c. loser 행 DELETE + entity_merges 기록
    """
    if survivor_id == loser_id:
        return {"status": "noop", "reason": "survivor == loser"}
    loser = conn.execute("SELECT id, name, type FROM entities WHERE id=?", (loser_id,)).fetchone()
    if loser is None:
        return {"status": "noop", "reason": "loser 없음"}
    if conn.execute("SELECT 1 FROM entities WHERE id=?", (survivor_id,)).fetchone() is None:
        return {"status": "noop", "reason": "survivor 없음"}
    try:
        rewired_edges = _rewire_relations(conn, survivor_id, loser_id)
        _rewire_generic_fks(conn, survivor_id, loser_id)
        conn.execute("DELETE FROM entities WHERE id=?", (loser_id,))
        conn.execute(
            "INSERT OR IGNORE INTO entity_merges (old_name, type, survivor_id, rationale) "
            "VALUES (?, ?, ?, ?)",
            (loser["name"], loser["type"], survivor_id, rationale))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"status": "merged", "survivor_id": survivor_id, "loser_id": loser_id,
            "old_name": loser["name"], "type": loser["type"], "edges_rewired": rewired_edges}


def _rewire_relations(conn, survivor_id: int, loser_id: int) -> int:
    """loser를 src/dst로 갖는 entity_relations 엣지를 survivor로 재배선.

    UNIQUE(src_id,dst_id,rel_type,valid_from) 충돌 시 두 엣지를 병합:
    confidence=max, _EDGE_MERGE_COLS는 non-null 우선(survivor 엣지 기준 COALESCE),
    loser 엣지의 narrative_edge_evidence를 survivor 엣지로 이관(INSERT OR IGNORE) 후 loser 엣지 삭제.
    """
    edges = conn.execute(
        "SELECT * FROM entity_relations WHERE src_id=? OR dst_id=?",
        (loser_id, loser_id)).fetchall()
    rewired = 0
    for e in edges:
        new_src = survivor_id if e["src_id"] == loser_id else e["src_id"]
        new_dst = survivor_id if e["dst_id"] == loser_id else e["dst_id"]
        if new_src == new_dst:  # 병합으로 생긴 자기순환(survivor→survivor)은 무의미 — 폐기
            _move_evidence_and_drop(conn, e["id"], None)
            continue
        target = conn.execute(
            "SELECT * FROM entity_relations WHERE src_id=? AND dst_id=? AND rel_type=? "
            "AND valid_from IS ?",
            (new_src, new_dst, e["rel_type"], e["valid_from"])).fetchone()
        if target is None:
            conn.execute(
                "UPDATE entity_relations SET src_id=?, dst_id=? WHERE id=?",
                (new_src, new_dst, e["id"]))
            rewired += 1
            continue
        if target["id"] == e["id"]:
            continue
        # 충돌 — survivor 엣지(target)에 loser 엣지(e)를 흡수
        conf = max(target["confidence"] or 0.0, e["confidence"] or 0.0)
        sets, params = ["confidence=?"], [conf]
        for col in _EDGE_MERGE_COLS:
            sets.append(f"{col}=COALESCE({col}, ?)")
            params.append(e[col])
        params.append(target["id"])
        conn.execute(f"UPDATE entity_relations SET {', '.join(sets)} WHERE id=?", params)
        _move_evidence_and_drop(conn, e["id"], target["id"])
        rewired += 1
    return rewired


def _move_evidence_and_drop(conn, from_edge_id: int, to_edge_id: int | None) -> None:
    """loser 엣지의 narrative_edge_evidence를 survivor 엣지로 이관(중복 무시) 후 loser 엣지 삭제."""
    if to_edge_id is not None:
        conn.execute(
            "UPDATE OR IGNORE narrative_edge_evidence SET entity_relation_id=? "
            "WHERE entity_relation_id=?",
            (to_edge_id, from_edge_id))
    conn.execute("DELETE FROM narrative_edge_evidence WHERE entity_relation_id=?", (from_edge_id,))
    conn.execute("DELETE FROM entity_relations WHERE id=?", (from_edge_id,))


def _entity_fk_columns(conn) -> list[tuple[str, str]]:
    """entities(id)를 참조하는 (테이블, 컬럼) 전수 — sqlite_master + PRAGMA foreign_key_list로 동적 발견.
    entity_relations는 별도 특수 처리하므로 제외."""
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    cols: list[tuple[str, str]] = []
    for t in tables:
        if t == "entity_relations":
            continue
        for fk in conn.execute(f"PRAGMA foreign_key_list({t})"):
            if fk["table"] == "entities" and (fk["to"] in ("id", None)):
                cols.append((t, fk["from"]))
    return cols


def _rewire_generic_fks(conn, survivor_id: int, loser_id: int) -> None:
    """entity_relations 외 모든 entities FK 참조를 survivor로 재배선.
    UNIQUE 충돌 안전: UPDATE OR IGNORE 후 잔여(충돌로 갱신 안 된) loser 참조 행 DELETE."""
    for table, col in _entity_fk_columns(conn):
        conn.execute(
            f"UPDATE OR IGNORE {table} SET {col}=? WHERE {col}=?", (survivor_id, loser_id))
        conn.execute(f"DELETE FROM {table} WHERE {col}=?", (loser_id,))
