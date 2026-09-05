"""메가 내러티브 — 공유노드 군집의 상위 세계관 서사 (D-031, D-023 §2-4 '머지' 완성).

토픽 내러티브(원자, 버전·드리프트 추적 단위)는 그대로 두고, 인과 노드를 공유하는
내러티브 군집(연결요소, 크기 3+)마다 상위 서사를 생성한다 — "반도체·전력·2차전지가
사실 하나의 AI 슈퍼사이클 이야기"임을 한 층 위에서 읽는다.

- 군집: 살아있는 topic 내러티브 간 공유 인과 노드 1+ 이면 연결 → 연결요소 크기 3+만
- 가드: 멤버 (topic, narrative_id) 집합 해시 — 멤버 구성이나 멤버 버전이 바뀔 때만 opus
- 저장: narratives 테이블 재사용 (kind='mega', topic=군집 라벨(LLM 명명),
  members_json=구성 토픽들, doc_ids_hash=멤버 해시) — 버전·supersede 규약 그대로
"""
import hashlib
import json
import os

from database import get_connection
from pipeline.narrative import (_call, _latest_narrative, causal_subgraph, list_narratives)

MEGA_MODEL = os.getenv("NARRATIVE_MODEL", "opus")   # 최상위 종합 — 내러티브와 같은 티어
MIN_CLUSTER = 3        # 이 수 이상의 내러티브가 엮여야 '세계관'
# 공유 인과 노드 하한 (D-123). 1이면 허브 1개만 겹쳐도 합쳐져 **군집이 곧 전체**가 됐다 —
# 실측: 살아있는 topic 54개 중 49개가 한 군집. 임계별 분할: 1→[49,3] · 2→[21,3] · 3→[4,3] · 4→[3].
# 3에서만 의미가 갈린다(메모리·장비 축 / AI 모델 축). 군집 밖 주제는 델타 목록이 담당(역할 분담).
MIN_SHARED = 3


def _live_topic_narratives(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("""
        SELECT n.id, n.topic, n.title, n.body FROM narratives n
        JOIN (SELECT topic, MAX(version) mv FROM narratives GROUP BY topic) l
          ON l.topic=n.topic AND l.mv=n.version
        WHERE n.title IS NOT NULL AND COALESCE(n.kind,'topic')='topic'""").fetchall()]


def _clusters(conn) -> list[list[dict]]:
    """내러티브 간 공유노드 그래프의 연결요소 — 크기 MIN_CLUSTER 이상만."""
    lives = _live_topic_narratives(conn)
    nodes = {r["topic"]: {n["name"] for n in causal_subgraph(conn, r["id"])["nodes"]}
             for r in lives}
    parent = {r["topic"]: r["topic"] for r in lives}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    topics = list(nodes)
    for i, a in enumerate(topics):
        for b in topics[i + 1:]:
            if len(nodes[a] & nodes[b]) >= MIN_SHARED:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[ra] = rb

    groups: dict[str, list[dict]] = {}
    for r in lives:
        groups.setdefault(find(r["topic"]), []).append(r)
    return [g for g in groups.values() if len(g) >= MIN_CLUSTER]


def _members_hash(members: list[dict]) -> str:
    """멤버 구성 + 각 멤버의 현재 버전(id)이 바뀌면 재생성."""
    key = "|".join(f"{m['topic']}:{m['id']}" for m in sorted(members, key=lambda x: x["topic"]))
    return hashlib.sha256(key.encode()).hexdigest()


def _shared_edges_block(conn, members: list[dict]) -> str:
    """군집 내 2+ 내러티브가 공유하는 노드와 각 멤버의 핵심 인과 — 프롬프트 재료."""
    subs = {m["topic"]: causal_subgraph(conn, m["id"]) for m in members}
    from collections import Counter
    counts = Counter()
    for g in subs.values():
        for n in g["nodes"]:
            counts[n["name"]] += 1
    hubs = [name for name, c in counts.most_common(10) if c >= 2]
    lines = [f"공유 허브 노드(여러 부분 서사가 함께 밟는 지점): {', '.join(hubs) or '(없음)'}"]
    for m in members:
        edges = subs[m["topic"]]["edges"][:4]
        chain = " · ".join(f"{e['from']}→{e['to']}" for e in edges)
        lines.append(f"[{m['topic']}] {m['title']}\n  핵심 인과: {chain}")
    return "\n".join(lines)


def _summary_of(body: str | None) -> str:
    """멤버 내러티브의 3줄 요약 섹션만 추출 (프롬프트 압축)."""
    import re
    if not body:
        return ""
    m = re.search(r"##\s*3줄\s*요약\s*\n(.*?)(?=\n##|\Z)", body, re.S)
    return (m.group(1) if m else body)[:400].strip()


def _build_prompt(members: list[dict], shared_block: str) -> str:
    from pipeline.lenses import LENS_WORLDVIEW
    parts = "\n\n".join(
        f"### {m['topic']} — {m['title']}\n{_summary_of(m['body'])}" for m in members)
    return (
        "너는 1인 리서치센터의 수석 전략가다. 아래 부분 서사들은 각각 다른 주제로 생성됐지만 "
        "같은 인과 노드들을 밟고 있다 — 즉 하나의 더 큰 이야기의 단면들이다. 이들을 관통하는 "
        "**상위 세계관 서사** 하나를 써라. 부분 서사의 요약 나열이 아니라, 단면들을 꿰는 "
        "하나의 구조(근본 동인 → 전개 갈래들 → 긴장과 관전 포인트)로.\n"
        'JSON만 출력: {"cluster_name": "군집 이름 (2~5단어, 예: AI 슈퍼사이클)", '
        '"title": "주장형 제목", "narrative": "마크다운 서사"}\n'
        "title: 이 세계관이 말하는 결론을 한 문장으로 단언(질문형 금지 — 제목만 읽어도 전달돼야 "
        "한다, D-120). 코퍼스가 뒷받침하는 것만, 수치 예측·과장 부사 금지.\n"
        "narrative 구조(섹션 고정):\n"
        "## 하나의 이야기\n부분 서사들이 왜 한 이야기인지 — 근본 동인과 전개 구조를 3~5문장으로.\n"
        "## 갈래들\n각 부분 서사가 이 세계관의 어느 단면인지 — '- **주제**: 한 줄' 불릿.\n"
        "## 세계관의 긴장\n이 거대 서사 전체가 딛고 선 전제와, 그것이 흔들리는 조건 1~2개.\n"
        "## 관전 포인트\n부분이 아니라 전체의 방향을 판가름할 신호 2~3개 ('- ' 불릿).\n"
        "규율: 부분 서사에 없는 사실을 지어내지 마라. 전체 700자 내외. 내부 코드·약어 노출 금지.\n"
        f"\n{LENS_WORLDVIEW}\n"
        f"\n[공유 구조]\n{shared_block}\n\n[부분 서사들]\n{parts}"
    )


def compute_mega_narratives() -> dict:
    """군집 스캔 → 멤버 해시 가드 → stale 군집만 opus 생성 (멱등, cron 편승용)."""
    from pipeline.enrich import llm_engine
    conn = get_connection()
    results = {}
    for members in _clusters(conn):
        h = _members_hash(members)
        # 이 군집의 기존 메가 찾기 — 멤버 토픽 겹침 최대인 살아있는 mega
        # 군집 정체성 (D-123) — 겹침이 **가장 큰** live mega를 이 군집의 전신으로 본다.
        # 전엔 '첫 교집합'에서 break 해, live mega가 여럿이면 회차마다 다른 것을 집어
        # 여러 lineage가 동시에 살아남았다(실측: 같은 49개 군집이 3개 mega로 갈려 각각 서술).
        topics_now = {m["topic"] for m in members}
        lives = conn.execute(
            "SELECT * FROM narratives WHERE kind='mega' AND superseded_at IS NULL").fetchall()
        scored = sorted(
            ((len(set(json.loads(r["members_json"] or "[]")) & topics_now), r) for r in lives),
            key=lambda x: (-x[0], -x[1]["id"]))
        prev = scored[0][1] if scored and scored[0][0] > 0 else None
        # 같은 군집에 걸린 다른 live mega는 중복 lineage — 여기서 접는다(라벨만 다른 같은 이야기)
        for overlap, r in scored[1:]:
            if overlap > 0:
                conn.execute("UPDATE narratives SET superseded_at=datetime('now') WHERE id=?", (r["id"],))
                print(f"[mega] 중복 lineage 접음: {r['topic']} (겹침 {overlap})")
        label = prev["topic"] if prev else f"군집({members[0]['topic']} 외 {len(members)-1})"
        if prev and prev["doc_ids_hash"] == h:
            results[label] = "cached"
            continue
        if llm_engine() != "claude-code":
            results[label] = "unavailable"
            continue
        try:
            data = _call(_build_prompt(members, _shared_edges_block(conn, members)),
                         model=MEGA_MODEL)
        except Exception as e:  # noqa: BLE001 — 배치라 한 군집 실패가 전체를 막지 않게
            results[label] = f"error:{str(e)[:80]}"
            continue
        # 라벨은 **최초 생성 시에만** LLM 이름을 쓴다 (D-123). 매 회차 `cluster_name`으로 덮어쓰면
        # topic 값이 드리프트해("AI 병목의 하강"→"AI 캐펙스 병목 하강"→…) 같은 군집이 새 lineage로
        # 갈라지고, 버전 히스토리도 끊긴다. 전신이 있으면 그 이름을 물려받는다.
        name = prev["topic"] if prev else (data.get("cluster_name") or label).strip()[:40]
        # 버전은 **그 topic의 MAX+1** (D-123). prev는 '최대 겹침'으로 고르므로 최신 버전이 아닐 수
        # 있고, 라벨 드리프트 시절 같은 이름이 여러 lineage에 재사용돼 `prev.version+1`이
        # 기존 행과 충돌했다(실측: v23을 prev로 잡았는데 v24가 이미 있어 UNIQUE 위반 → 롤백).
        mx = conn.execute("SELECT MAX(version) m FROM narratives WHERE topic=?", (name,)).fetchone()["m"]
        version = (mx or 0) + 1
        if prev:
            conn.execute("UPDATE narratives SET superseded_at=datetime('now') WHERE id=?",
                         (prev["id"],))
        conn.execute(
            "INSERT INTO narratives (topic, version, title, body, kind, members_json, "
            "doc_count, doc_ids_hash, model) VALUES (?, ?, ?, ?, 'mega', ?, ?, ?, ?)",
            (name, version, data.get("title"), data.get("narrative"),
             json.dumps([m["topic"] for m in members], ensure_ascii=False),
             len(members), h, f"claude-code/{MEGA_MODEL}"))
        conn.commit()
        results[name] = "fresh"
    conn.close()
    return results


def list_mega(conn) -> list[dict]:
    """살아있는 메가 내러티브 목록 (표면용)."""
    return [{
        "id": r["id"], "name": r["topic"], "title": r["title"], "narrative": r["body"],
        "members": json.loads(r["members_json"] or "[]"), "version": r["version"],
        "created_at": r["created_at"],
    } for r in conn.execute(
        "SELECT * FROM narratives WHERE kind='mega' AND superseded_at IS NULL "
        "ORDER BY doc_count DESC").fetchall()]
