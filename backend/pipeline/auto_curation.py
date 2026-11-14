"""정리 작업 자동 처리 (D-294) — 별칭·노드 병합·지식 승격 제안을 규칙으로 판정한다.

사용자에게 정리 작업을 넘기지 않는다: 확실한 것만 결정적 규칙으로 승인·거부하고, 애매한 것은
인박스에 올리지 않고 'held'(보류)로 둔 뒤 관리자 기록(`curation_log`)에만 남긴다.

두 플래그로 나눈다:
- `auto_curation`(기본 on): 판정만 해서 `curation_log`에 남긴다(드라이런). DB 대상은 건드리지 않는다.
- `auto_curation_apply`(기본 off): 판정대로 실제 적용한다. 켜면 정리 작업이 인박스에서 빠진다.

노드 병합은 진 쪽 엔티티를 지우므로(`vocab.merge_entities`) 적용 전에 진 쪽 행과 재배선될 행의 rowid를
`curation_log.detail_json`에 남긴다(되돌리기 재료).
"""
import json
import re
import time

from pipeline.vocab import _entity_fk_columns, merge_entities

# ── 공통 ──────────────────────────────────────────────────────────────

CODE_RE = re.compile(r"^[0-9A-Z]{6}$")


def _log(conn, kind: str, target_id: int, verdict: str, rule: str, applied: bool, detail: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO curation_log (kind, target_id, verdict, rule, applied, detail_json, decided_at) "
        "VALUES (?, ?, ?, ?, ?, ?, datetime('now')) "
        "ON CONFLICT(kind, target_id) DO UPDATE SET verdict=excluded.verdict, rule=excluded.rule, "
        "applied=MAX(curation_log.applied, excluded.applied), "
        "detail_json=COALESCE(excluded.detail_json, curation_log.detail_json), decided_at=excluded.decided_at",
        (kind, target_id, verdict, rule, 1 if applied else 0,
         json.dumps(detail, ensure_ascii=False) if detail else None))


def _norm(s: str) -> str:
    return re.sub(r"[\s·・/\-_.,()（）㈜]|주식회사", "", (s or "").lower())


# ── 1. 별칭 ───────────────────────────────────────────────────────────

NOISE = {
    "없음", "언급", "언급 없음", "미정", "미상", "추정", "관련", "당사", "우리 회사", "동사", "자사", "해당 기업",
    "해당 회사", "이 회사", "회사", "기업", "본사", "그룹", "계열사", "자회사", "모회사", "n/a", "na", "none", "unknown",
}
GENERIC = {
    "메모리", "반도체", "hbm", "ai", "코스피", "코스닥", "한국", "미국", "중국", "일본", "디램", "dram", "낸드", "nand",
    "파운드리", "배터리", "2차전지", "이차전지", "조선", "방산", "원전", "바이오", "증권", "은행", "보험", "건설", "자동차",
    "전력", "에너지", "화학", "철강", "게임", "엔터", "플랫폼", "클라우드", "데이터센터", "로봇", "우주", "항공",
}
GROUP_PREFIX = {
    "lg", "sk", "삼성", "한화", "신한", "하나", "우리", "kb", "gs", "ls", "hd현대", "현대", "db", "대신", "롯데", "cj",
    "두산", "효성", "카카오", "nh", "미래에셋", "한국투자", "키움", "메리츠", "교보", "한진",
}
# 자회사·사업부·제품·서비스·공장·그룹 표시 — 모회사 별칭으로 묶지 않는다(D-294 범위 정책)
NOT_ALIAS_MARK = re.compile(
    r"(그룹|부문|사업부|파운드리|공장|캠퍼스|라인|재단|연구원|연구소|증권|은행|생명|손해보험|손보|카드|캐피탈|자산운용|"
    r"서비스|몰|백화점|클라우드|데이터랩|밴드|톡|이츠|페이|뱅크|SSD|Pro|Galaxy|갤럭시|폴드|플립|M\d+|P\d+|SR\d+)",
    re.IGNORECASE)
CODE_OR_PCT = re.compile(r"\d{6}|[+\-−]?\d+(\.\d+)?%")
PREFIX_MIN = 4
PREFIX_DOC_CAP = 50


def _company_names(conn) -> list[tuple[int, str]]:
    return [(r["id"], r["name"]) for r in conn.execute("SELECT id, name FROM entities WHERE type='company'")]


def classify_alias(conn, entity_id: int, keyword: str, names: list[tuple[int, str]] | None = None) -> tuple[str, str]:
    """(verdict, rule) — verdict: approve | reject | hold. 문서 수 상한은 apply 단계에서 따로 본다."""
    kw = (keyword or "").strip()
    ent = conn.execute("SELECT name, type, aliases FROM entities WHERE id=?", (entity_id,)).fetchone()
    if not ent:
        return "reject", "대상 엔티티 없음"
    name = ent["name"] or ""
    low = kw.lower()
    if low in NOISE or len(kw) < 2:
        return "reject", "잡음어"
    if low in GENERIC:
        return "reject", "일반어"
    if "," in kw or "/" in kw or "、" in kw:
        return "reject", "여러 이름을 묶은 표기"
    if CODE_OR_PCT.search(kw):
        return "reject", "이름+코드·등락률 표기"
    if low.replace(" ", "") in GROUP_PREFIX and _norm(kw) != _norm(name):
        return "reject", "그룹 접두어 단독"
    if re.search(r"우$|우B$|\d우$", kw) and kw.rstrip("우B0123456789") == name:
        return "reject", "우선주"
    if re.sub(r"\s*그룹$", "", kw) == name:
        # 'LG그룹'→LG(지주)는 맞지만 '현대자동차그룹'→현대자동차(계열사)는 아니다 — 규칙으로 못 가른다
        return "hold", "그룹명 → 같은 이름 회사(지주인지 계열사인지 판단 불가)"
    if NOT_ALIAS_MARK.search(kw) and not NOT_ALIAS_MARK.search(name):
        return "reject", "자회사·사업부·제품·공장·그룹 표기(모회사 별칭 아님)"
    has_code = bool(ent["aliases"] and CODE_RE.match(str(ent["aliases"])))
    if not has_code:
        return "hold", "대상 엔티티에 종목 코드 없음(중복 엔티티 가능)"
    # 다른 엔티티의 이름·활성 키워드와 겹치면 판단 불가
    if conn.execute("SELECT 1 FROM entities WHERE name=? AND id!=?", (kw, entity_id)).fetchone():
        return "hold", "같은 이름의 다른 엔티티 있음"
    if conn.execute("SELECT 1 FROM entity_keywords WHERE keyword=? AND entity_id!=? "
                    "AND (status IS NULL OR status IN ('active','search_only','proposed','held'))",
                    (kw, entity_id)).fetchone():
        return "hold", "같은 키워드가 다른 엔티티에도 걸림"
    if _norm(kw) == _norm(name):
        return "approve", "이름과 공백·대소문자·기호만 다름"
    if len(kw) >= PREFIX_MIN and name.startswith(kw):
        names = names if names is not None else _company_names(conn)
        if any(n != name and n.startswith(kw) for i, n in names if i != entity_id):
            return "hold", "앞부분 약칭이 다른 회사 이름과 겹침"
        return "approve_if_small", f"앞부분 약칭(소급 {PREFIX_DOC_CAP}건 이하일 때)"
    return "hold", "규칙 밖(사람 판단 필요 없음 — 보류로 둠)"


def retro_link_keyword(conn, entity_id: int, kw: str, docs=None) -> int:
    """키워드를 기존 문서 전체에 소급 매칭 (routers.spine_keywords와 같은 규칙)."""
    rx = _kw_regex(kw)
    linked = 0
    rows = docs if docs is not None else conn.execute("SELECT id, title, markdown FROM raw_documents").fetchall()
    for doc in rows:
        text = f"{doc['title'] or ''}\n{doc['markdown'] or ''}"
        if kw in text and rx.search(text):
            linked += conn.execute(
                "INSERT OR IGNORE INTO entity_links (doc_id, entity_id, link_type, confidence) "
                "VALUES (?, ?, 'stock', 0.7)", (doc["id"], entity_id)).rowcount
    return linked


def _kw_regex(kw: str):
    pat = rf"(?<![0-9A-Za-z가-힣]){re.escape(kw)}"
    if len(kw) <= 2:
        pat += r"(?![0-9A-Za-z가-힣])"
    return re.compile(pat)


def curate_aliases(conn, apply: bool) -> dict:
    rows = conn.execute("SELECT id, entity_id, keyword FROM entity_keywords WHERE status IN ('proposed','held')").fetchall()
    names = _company_names(conn)
    judged = [(r, *classify_alias(conn, r["entity_id"], r["keyword"], names)) for r in rows]
    docs = None
    if any(v in ("approve", "approve_if_small") for _, v, _ in judged):
        docs = conn.execute("SELECT id, title, markdown FROM raw_documents").fetchall()
    stats = {"approve": 0, "reject": 0, "hold": 0}
    for r, verdict, rule in judged:
        detail = None
        if verdict in ("approve", "approve_if_small"):
            rx, kw = _kw_regex(r["keyword"]), r["keyword"]
            n = sum(1 for d in docs if kw in f"{d['title'] or ''}\n{d['markdown'] or ''}"
                    and rx.search(f"{d['title'] or ''}\n{d['markdown'] or ''}"))
            detail = {"matching_docs": n}
            if verdict == "approve_if_small" and n > PREFIX_DOC_CAP:
                verdict, rule = "hold", f"앞부분 약칭인데 소급 {n}건 — 상한 {PREFIX_DOC_CAP}건 초과"
            else:
                verdict = "approve"
        if apply:
            if verdict == "approve":
                conn.execute("UPDATE entity_keywords SET status='active' WHERE id=?", (r["id"],))
                detail = {**(detail or {}), "linked": retro_link_keyword(conn, r["entity_id"], r["keyword"], docs)}
            elif verdict == "reject":
                conn.execute("UPDATE entity_keywords SET status='rejected' WHERE id=?", (r["id"],))
            else:
                conn.execute("UPDATE entity_keywords SET status='held' WHERE id=?", (r["id"],))
        _log(conn, "alias", r["id"], verdict, rule, apply, detail)
        stats[verdict] += 1
    return stats


# ── 2. 노드 병합 ──────────────────────────────────────────────────────

SUFFIX = re.compile(r"(섹터|업종|산업)$")
AUTO_COSINE = 0.97


def _merge_key(name: str) -> str:
    return SUFFIX.sub("", _norm(name))


def classify_merge(payload: dict) -> tuple[str, str]:
    a, b, typ = payload.get("survivor_name") or "", payload.get("loser_name") or "", payload.get("type") or ""
    if _merge_key(a) and _merge_key(a) == _merge_key(b):
        return "approve", "공백·대소문자·기호·접미어만 다름"
    if typ == "event":
        return "hold", "사건은 표기가 달라도 다른 날일 수 있음"
    cos = payload.get("cosine") or 0
    if typ == "company":
        short = min(a, b, key=len)
        if len(short.split()) <= 2 and (short in max(a, b, key=len)):
            return "hold", "회사 약칭 — 다른 회사일 수 있음"
    if cos >= AUTO_COSINE:
        return "approve", f"LLM 판정 같음 + 유사도 {cos:.3f} ≥ {AUTO_COSINE}"
    return "hold", f"유사도 {cos:.3f} < {AUTO_COSINE}"


def _code_of(conn, eid: int) -> bool:
    r = conn.execute("SELECT aliases FROM entities WHERE id=?", (eid,)).fetchone()
    return bool(r and r["aliases"] and CODE_RE.match(str(r["aliases"])))


def _links(conn, eid: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM entity_links WHERE entity_id=?", (eid,)).fetchone()[0]


def _survivor(conn, a: int, b: int) -> tuple[int, int]:
    """코드 있는 쪽 > 링크 많은 쪽 > 낮은 id."""
    ka = (_code_of(conn, a), _links(conn, a), -a)
    kb = (_code_of(conn, b), _links(conn, b), -b)
    return (a, b) if ka >= kb else (b, a)


def _snapshot(conn, loser_id: int) -> dict:
    """되돌리기 재료 — 진 쪽 엔티티 행과, 재배선될 각 테이블 행의 rowid."""
    ent = conn.execute("SELECT * FROM entities WHERE id=?", (loser_id,)).fetchone()
    refs = {}
    for table, col in _entity_fk_columns(conn):
        ids = [r[0] for r in conn.execute(f"SELECT rowid FROM {table} WHERE {col}=?", (loser_id,))]
        if ids:
            refs[f"{table}.{col}"] = ids
    edges = [r[0] for r in conn.execute("SELECT id FROM entity_relations WHERE src_id=? OR dst_id=?", (loser_id, loser_id))]
    return {"entity": dict(ent) if ent else None, "refs": refs, "relations": edges}


def curate_merges(conn, apply: bool) -> dict:
    rows = conn.execute("SELECT id, payload_json FROM agent_proposals WHERE kind='vocab_merge' "
                        "AND status IN ('proposed','held') ORDER BY id").fetchall()
    stats = {"approve": 0, "hold": 0, "skip": 0}
    for r in rows:
        p = json.loads(r["payload_json"] or "{}")
        verdict, rule = classify_merge(p)
        a, b = p.get("survivor_id"), p.get("loser_id")
        exists = all(conn.execute("SELECT 1 FROM entities WHERE id=?", (x,)).fetchone() for x in (a, b))
        if not exists:   # 사슬 앞 병합으로 한쪽이 이미 흡수됨 — 이 제안은 끝난 것
            if apply:
                conn.execute("UPDATE agent_proposals SET status='dismissed', actioned_at=datetime('now') WHERE id=?", (r["id"],))
            _log(conn, "vocab_merge", r["id"], "skip", "한쪽 엔티티가 이미 병합됨", apply)
            stats["skip"] += 1
            continue
        detail = None
        if verdict == "approve":
            s, l = _survivor(conn, a, b)
            detail = {"survivor_id": s, "loser_id": l}
            if apply:
                detail["snapshot"] = _snapshot(conn, l)
                res = merge_entities(conn, s, l, f"자동 정리(D-294): {rule}")
                detail["result"] = res
                conn.execute("UPDATE agent_proposals SET status='actioned', actioned_at=datetime('now'), result_json=? WHERE id=?",
                             (json.dumps({"merged": res.get("status") == "merged", "auto": True}, ensure_ascii=False), r["id"]))
        elif apply:
            conn.execute("UPDATE agent_proposals SET status='held' WHERE id=?", (r["id"],))
        _log(conn, "vocab_merge", r["id"], verdict, rule, apply, detail)
        stats[verdict] += 1
    return stats


# ── 3. 지식 승격 ──────────────────────────────────────────────────────

FALSIFIER_DAILY_CAP = 5
DUP_JACCARD = 0.8


def _tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[\s,.·()\[\]'\"]+", (s or "").lower()) if len(t) > 1}


def _is_duplicate(statement: str, others: list[str]) -> bool:
    a = _tokens(statement)
    if not a:
        return False
    for o in others:
        b = _tokens(o)
        if b and len(a & b) / len(a | b) >= DUP_JACCARD:
            return True
    return False


def classify_knowledge(conn, kid: int, statement: str, active: list[str]) -> tuple[str, str]:
    c = conn.execute("""SELECT COUNT(*) total,
            SUM(CASE WHEN stance='support' AND independent=1 THEN 1 ELSE 0 END) ind,
            SUM(CASE WHEN stance='refute' THEN 1 ELSE 0 END) ref
        FROM knowledge_evidence WHERE knowledge_id=?""", (kid,)).fetchone()
    total, ind, ref = c["total"] or 0, c["ind"] or 0, c["ref"] or 0
    if total == 0:
        return "reject", "근거 문서 0건"
    if _is_duplicate(statement, active):
        return "reject", "이미 승격된 지식과 같은 주장"
    if ref >= 1:
        return "hold", f"반박 근거 {ref}건 — 엇갈림"
    if ind >= 2:
        return "approve", f"독립 근거 {ind}건 · 반박 0"
    return "hold", f"독립 근거 {ind}건(2건 미만)"


def _falsifiers_today(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM curation_log WHERE kind='knowledge' AND verdict='approve' "
                        "AND applied=1 AND date(decided_at)=date('now')").fetchone()[0]


def curate_knowledge(conn, apply: bool, cap: int = FALSIFIER_DAILY_CAP) -> dict:
    rows = conn.execute("SELECT id, statement FROM knowledge WHERE review_status IN ('proposed','held') "
                        "ORDER BY created_at").fetchall()
    active = [r["statement"] for r in conn.execute("SELECT statement FROM knowledge WHERE review_status='active'")]
    stats = {"approve": 0, "reject": 0, "hold": 0, "deferred": 0}
    budget = cap - _falsifiers_today(conn)
    for r in rows:
        verdict, rule = classify_knowledge(conn, r["id"], r["statement"], active)
        if apply and verdict == "approve" and budget <= 0:
            stats["deferred"] += 1          # 오늘 예산 소진 — 다음 실행에서
            continue
        if apply:
            if verdict == "approve":
                ind = conn.execute("SELECT COUNT(*) FROM knowledge_evidence WHERE knowledge_id=? "
                                   "AND stance='support' AND independent=1", (r["id"],)).fetchone()[0]
                conn.execute("UPDATE knowledge SET review_status='active', epistemic_status=? WHERE id=?",
                             ("corroborated" if ind >= 2 else "observed", r["id"]))
                _log(conn, "knowledge", r["id"], verdict, rule, True)
                conn.commit()
                from pipeline.falsifiers import generate_falsifiers
                try:
                    generate_falsifiers(conn, r["id"], r["statement"])
                except Exception as e:  # noqa: BLE001 — 승격은 유지, 반증 조건은 다음에
                    _log(conn, "knowledge", r["id"], verdict, f"{rule} · 반증 조건 생성 실패: {str(e)[:80]}", True)
                active.append(r["statement"])
                budget -= 1
                stats[verdict] += 1
                continue
            conn.execute("UPDATE knowledge SET review_status=? WHERE id=?",
                         ("rejected" if verdict == "reject" else "held", r["id"]))
        _log(conn, "knowledge", r["id"], verdict, rule, apply)
        stats[verdict] += 1
    return stats


# ── 실행 ──────────────────────────────────────────────────────────────

def run_curation(conn) -> dict:
    """주간 제안 스캔(agent_proposals.run_all) 끝에서 호출. 판정은 `auto_curation`, 적용은 `auto_curation_apply`."""
    from pipeline.ops import flag_enabled
    if not flag_enabled("auto_curation", default=True):
        return {"status": "skipped"}
    apply = flag_enabled("auto_curation_apply", default=False)
    t0 = time.time()
    out = {"apply": apply,
           "alias": curate_aliases(conn, apply),
           "vocab_merge": curate_merges(conn, apply)}
    conn.commit()
    out["knowledge"] = curate_knowledge(conn, apply)
    conn.commit()
    out["ms"] = int((time.time() - t0) * 1000)
    return out
