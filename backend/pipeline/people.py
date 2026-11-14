"""인물 1단계 (ia-redesign §4.23 A안, 단계 0·1) — 이름 자동 정리·역할 자동 분류·전제 '누가' 대응 표·메모 저자 연결. LLM 0.

사용자에게 정리를 넘기지 않는다(no user chores). 규칙으로 확실한 것만 묶고, 애매하면 그대로 둔다 — 틀리게 합치는 것보다
갈라져 있는 쪽이 덜 해롭다.

이름 자동 정리 = **소프트 병합**: 진 쪽 엔티티를 지우지 않는다. `entities.status='merged'` + `entity_merges`
(type='person' · 회사로 잘못 분류된 이름은 'person_company', old_entity_id·rule·prev_status)로 대표 인물에 잇는다.
문서 연결(entity_links)은 옮기지 않고 읽을 때 묶는다(`members`). 되돌리기 = `split`(reverted_at, status 복원) —
되돌린 이름은 다시 묶지 않는다.

묶는 규칙(결정적)
- type_fix 분류 교정: 같은 이름(아래 정규화 포함)의 회사 엔티티(종목코드·티커 없음) → 인물
- spacing 띄어쓰기: 공백·가운뎃점·하이픈만 다른 이름(젠슨황 ↔ 젠슨 황)
- spelling 표기 변형: 외래어 표기 사전(TOKEN_VARIANTS, 낱말 단위 — 워렌/워런, 호워드/하워드, 올트먼/알트먼 …)
- english 영문명: 영문명 ↔ 한글명 사전(EN_KO)
- alias 별칭 사전: 같은 사람의 다른 한글 표기(KO_ALIAS — 도널드 트럼프 → 트럼프)
- cleanup 표기 정리: 추출 잔여물 "{'name': '스콧 베센트'}" → 안의 이름
- abbrev 약칭: 한 낱말 이름(3자 이상)이 정확히 한 사람의 성·이름과 같고, 함께 언급된 엔티티가 겹칠 때만.
  KEEP_APART(워시·머스크)와 후보가 둘 이상인 이름은 묶지 않는다.

역할(사용자 지정 없음, 못 정하면 칩 없음): 정책 = 기관 사전(POLICY), 경영자 = 컨콜 화자 직함(CEO·CFO 등) + 사람 사전(EXECUTIVE),
구루 = 전제 원장 '누가'·메모 저자. 저장 `person_roles`.
전제 '누가' 대응 표 = WHO(코드 상수). 기관(BIS·AQR …)은 링크 없이 텍스트. 인물 엔티티가 없으면 만들지 않는다.
메모 저자 = `raw_documents.source_id LIKE 'oaktree/%'` → 하워드 막스 `entity_links(link_type='author')`.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

# ── 사전 ─────────────────────────────────────────────────────────────

RULE_KO = {"type_fix": "분류 교정", "spacing": "띄어쓰기", "spelling": "표기 변형", "english": "영문명",
           "alias": "별칭 사전", "cleanup": "표기 정리", "abbrev": "약칭"}
RULE_ORDER = ("type_fix", "cleanup", "english", "alias", "spelling", "abbrev", "spacing")

# 외래어 표기 변형 — 낱말 하나를 통째로 바꾼다(부분 문자열은 건드리지 않는다)
TOKEN_VARIANTS = {"워렌": "워런", "호워드": "하워드", "올트먼": "알트먼", "올트만": "알트먼", "베선트": "베센트",
                  "삭스": "색스", "바르": "바", "스탠": "스탠리", "엘론": "일론", "캐빈": "케빈", "드와르케시": "드와케시",
                  }
# 영문명 → 한글 대표 표기(소문자 키). 둘 다 엔티티로 있을 때만 묶인다.
EN_KO = {
    "howard marks": "하워드 막스", "elon musk": "일론 머스크", "trump": "트럼프", "donald trump": "트럼프",
    "jensen huang": "젠슨 황", "sam altman": "샘 알트먼", "warren buffett": "워런 버핏",
    "stanley druckenmiller": "스탠리 드러켄밀러", "stan druckenmiller": "스탠리 드러켄밀러", "ray dalio": "레이 달리오",
    "paul tudor jones": "폴 튜더 존스", "larry summers": "래리 서머스", "lawrence summers": "래리 서머스",
    "mohamed el-erian": "모하메드 엘에리언", "jeremy grantham": "제러미 그랜섬", "satya nadella": "사티아 나델라",
    "mark zuckerberg": "마크 저커버그", "alex karp": "알렉스 카프", "alexander karp": "알렉스 카프", "tim cook": "팀 쿡",
    "sundar pichai": "순다르 피차이", "andy jassy": "앤디 재시", "lisa su": "리사 수", "lip-bu tan": "립부 탄",
    "hock tan": "혹 탄", "tom lee": "톰 리", "dylan patel": "딜런 파텔", "dwarkesh patel": "드와케시 파텔",
    "kevin warsh": "케빈 워시", "jerome powell": "제롬 파월", "scott bessent": "스콧 베센트", "michael barr": "마이클 바",
    "dario amodei": "다리오 아모데이", "colette kress": "콜레트 크레스", "michael burry": "마이클 버리",
    "bill ackman": "빌 애크먼", "vitalik buterin": "비탈릭 부테린", "peter thiel": "피터 틸", "cathie wood": "캐시 우드",
    "jamie dimon": "제이미 다이먼", "larry fink": "래리 핑크", "michael saylor": "마이클 세일러",
    "brian armstrong": "브라이언 암스트롱", "michael dell": "마이클 델", "marc benioff": "마크 베니오프",
    "david solomon": "데이비드 솔로몬", "masayoshi son": "손정의", "demis hassabis": "데미스 하사비스",
    "gavin baker": "개빈 베이커", "david sacks": "데이비드 색스", "christopher waller": "크리스토퍼 월러",
    "john williams": "존 윌리엄스", "lisa cook": "리사 쿡", "philip jefferson": "필립 제퍼슨", "beth hammack": "베스 해맥",
    "howard lutnick": "하워드 러트닉", "jd vance": "JD 밴스", "j.d. vance": "JD 밴스", "marco rubio": "마르코 루비오",
    "christine lagarde": "크리스틴 라가르드", "andrew bailey": "앤드루 베일리", "jeff bezos": "제프 베이조스",
    "nikesh arora": "니케시 아로라", "sanjay mehrotra": "산제이 메흐로트라", "larry ellison": "래리 엘리슨",
    "lawrence ellison": "래리 엘리슨",
}
# 같은 사람의 다른 한글 표기 — 대표 표기로
KO_ALIAS = {"도널드 트럼프": "트럼프", "도널드 j 트럼프": "트럼프"}
# 한 낱말 이름 중 묻지 않고 따로 두는 것(동명이인·일반어 위험, §4.23.7)
KEEP_APART = {"워시", "머스크"}
ABBREV_MIN_CHARS = 3
ABBREV_MIN_SHARED = 3        # 약칭 판정 — 함께 언급된 엔티티가 이만큼 겹치고
ABBREV_MIN_JACCARD = 0.1     # 겹침 비율이 이 이상이고
ABBREV_MIN_FULL_DOCS = 5     # 전체 이름 쪽이 이만큼 쓰인 사람일 때만 묶는다(보우소나루·클린턴 같은 집안 이름은 그대로)
TYPE_FIX_RATIO = 3           # 분류 교정은 인물 쪽 문서가 회사 쪽의 이 배수 이상일 때만(월트 디즈니·세네카 같은 회사 이름은 그대로)

# 역할 사전 — 대표 표기 → (소속, 직함). 국가 지도자·중앙은행·재무·통상 당국
POLICY = {
    "트럼프": ("미국 대통령", None), "JD 밴스": ("미국 부통령", None), "스콧 베센트": ("미국 재무부", "장관"),
    "하워드 러트닉": ("미국 상무부", "장관"), "마르코 루비오": ("미국 국무부", "장관"), "피트 헤그세스": ("미국 국방부", "장관"),
    "파월": ("연준", "의장"), "제롬 파월": ("연준", "의장"), "케빈 워시": ("연준", None), "크리스토퍼 월러": ("연준", "이사"),
    "마이클 바": ("연준", "이사"), "리사 쿡": ("연준", "이사"), "필립 제퍼슨": ("연준", "부의장"),
    "존 윌리엄스": ("뉴욕 연은", "총재"), "베스 해맥": ("클리블랜드 연은", "총재"),
    "크리스틴 라가르드": ("ECB", "총재"), "앤드루 베일리": ("영란은행", "총재"),
    "이재명": ("대통령실", "대통령"), "구윤철": ("기획재정부", "장관"), "김용범": ("대통령실", "정책실장"),
    "이억원": ("금융위원회", "위원장"), "김정관": ("산업통상자원부", "장관"), "이창용": ("한국은행", "총재"),
    "시진핑": ("중국", "국가주석"), "푸틴": ("러시아", "대통령"), "마크롱": ("프랑스", "대통령"),
    "네타냐후": ("이스라엘", "총리"), "김정은": ("북한", None), "룰라": ("브라질", "대통령"), "마크 카니": ("캐나다", "총리"),
    "다카이치 사나에": ("일본", "총리"),
}
# 경영자 사전 — 대표 표기 → (소속, 종목, 직함). 컨콜 화자 직함으로 못 잡는 경영자(국내·비상장·컨콜 미수집)
EXECUTIVE = {
    "일론 머스크": ("테슬라", "TSLA", "CEO"), "젠슨 황": ("NVIDIA", "NVDA", "CEO"), "샘 알트먼": ("OpenAI", None, "CEO"),
    "다리오 아모데이": ("Anthropic", None, "CEO"), "마크 저커버그": ("메타", "META", "CEO"),
    "사티아 나델라": ("마이크로소프트", "MSFT", "CEO"), "앤디 재시": ("아마존", "AMZN", "CEO"), "팀 쿡": ("애플", "AAPL", "CEO"),
    "순다르 피차이": ("알파벳", "GOOGL", "CEO"), "리사 수": ("AMD", "AMD", "CEO"), "알렉스 카프": ("팔란티어", "PLTR", "CEO"),
    "립부 탄": ("인텔", "INTC", "CEO"), "혹 탄": ("브로드컴", "AVGO", "CEO"), "제이미 다이먼": ("JP모건", "JPM", "CEO"),
    "래리 핑크": ("블랙록", "BLK", "CEO"), "마이클 세일러": ("스트래티지", "MSTR", "회장"),
    "브라이언 암스트롱": ("코인베이스", "COIN", "CEO"), "마이클 델": ("델", "DELL", "CEO"),
    "데이비드 솔로몬": ("골드만삭스", "GS", "CEO"), "마크 베니오프": ("세일즈포스", "CRM", "CEO"),
    "최태원": ("SK", "034730", "회장"), "곽노정": ("SK하이닉스", "000660", "CEO"), "이재용": ("삼성전자", "005930", "회장"),
    "정의선": ("현대자동차", "005380", "회장"), "구광모": ("LG", "003550", "회장"), "최윤범": ("고려아연", "010130", "회장"),
    "정기선": ("HD현대", "267250", "회장"), "손정의": ("소프트뱅크", None, "회장"),
}
# 전제 원장(pipeline/era.py layer_premises)의 '누가' 한 칸 → (kind, 대표 표기 후보). 괄호 꼬리는 떼고 찾는다.
WHO = {
    "Marks": ("person", ["하워드 막스", "Howard Marks"]), "Summers": ("person", ["래리 서머스", "Larry Summers"]),
    "El-Erian": ("person", ["모하메드 엘에리언", "Mohamed El-Erian"]),
    "Druckenmiller": ("person", ["스탠리 드러켄밀러", "드러켄밀러", "Stanley Druckenmiller"]),
    "Dalio": ("person", ["레이 달리오", "Ray Dalio"]), "Paul Tudor Jones": ("person", ["폴 튜더 존스", "Paul Tudor Jones"]),
    "Grantham": ("person", ["제러미 그랜섬", "Jeremy Grantham"]), "Fed Barr": ("person", ["마이클 바", "Michael Barr"]),
    "BIS": ("org", []), "AQR": ("org", []), "Man Group": ("org", []), "Bridgewater": ("org", []), "Sequoia Cahn": ("org", []),
}
MEMO_AUTHORS = {"oaktree/": ("하워드 막스", "오크트리 캐피털")}
GURU_ORG = {"하워드 막스": "오크트리 캐피털", "스탠리 드러켄밀러": "듀케인 패밀리 오피스", "레이 달리오": "브리지워터",
            "폴 튜더 존스": "튜더 인베스트먼트", "제러미 그랜섬": "GMO", "래리 서머스": None, "모하메드 엘에리언": None}

# 이름 뒤에 붙은 직함 — 떼고 본다(이재명 대통령 → 이재명, 김성환 기후에너지환경부 장관 → 김성환)
TITLE_TOKENS = {"대통령", "전대통령", "회장", "부회장", "명예회장", "장관", "의장", "총재", "총리", "부총리", "대표", "사장",
                "위원장", "CEO", "의원", "국무장관", "주석"}
ORG_TAIL = re.compile(r"(부|처|청|원|위원회|은행|그룹)$")
EXEC_TITLE = re.compile(r"\b(chief executive officer|chief financial officer|ceo|cfo|president|chairman|chairwoman|founder)\b", re.I)
_JUNK = re.compile(r"""^\{\s*['"]name['"]\s*:\s*['"]([^'"]+)['"]""")


# ── 정규화 ───────────────────────────────────────────────────────────

def canon(name: str) -> tuple[str, set[str]]:
    """이름 → (대표 표기 후보, 쓰인 규칙). 띄어쓰기는 key()가 맡는다."""
    rules: set[str] = set()
    n = (name or "").strip()
    m = _JUNK.match(n)
    if m:
        n, _ = m.group(1).strip(), rules.add("cleanup")
    low = re.sub(r"\s+", " ", n.lower().replace(".", "")).strip()
    if low in EN_KO:
        n, _ = EN_KO[low], rules.add("english")
    if n in KO_ALIAS or low in KO_ALIAS:
        n, _ = KO_ALIAS.get(n, KO_ALIAS.get(low)), rules.add("alias")
    toks = n.split()
    while len(toks) >= 2 and toks[-1] in TITLE_TOKENS:
        toks, _ = toks[:-1], rules.add("cleanup")
        if len(toks) >= 2 and ORG_TAIL.search(toks[-1]) and len(toks[-1]) >= 3:
            toks = toks[:-1]
    out = [TOKEN_VARIANTS.get(t, t) for t in toks]
    if out != toks:
        rules.add("spelling")
    toks = out
    return " ".join(toks), rules


def key(name: str) -> str:
    return re.sub(r"[\s·・\-_.,']+", "", canon(name)[0].lower())


def _tokens(name: str) -> list[str]:
    return canon(name)[0].split()


# ── 읽기 도우미 (병합 반영) ──────────────────────────────────────────

MERGE_TYPES = ("person", "person_company")


def merged_map(conn) -> dict[int, int]:
    """진 쪽 엔티티 id → 대표 인물 id (되돌린 행 제외)."""
    try:
        return {r[0]: r[1] for r in conn.execute(
            "SELECT old_entity_id, survivor_id FROM entity_merges WHERE type IN ('person','person_company') "
            "AND old_entity_id IS NOT NULL AND reverted_at IS NULL")}
    except Exception:  # noqa: BLE001 — 칼럼이 없는 옛 DB
        return {}


def members(conn, pid: int) -> list[int]:
    """대표 인물 + 묶인 이름들의 엔티티 id."""
    return [pid] + [o for o, s in merged_map(conn).items() if s == pid]


def resolve_id(conn, eid: int) -> int | None:
    """엔티티 id → 대표 인물 id. 묶인 이름이면 대표로, 인물이 아니면 None."""
    m = merged_map(conn)
    if eid in m:
        return m[eid]
    r = conn.execute("SELECT type, status FROM entities WHERE id=?", (eid,)).fetchone()
    return eid if r and r["type"] == "person" and r["status"] != "merged" else None


def resolve_name(conn, name: str) -> int | None:
    """이름 → 대표 인물 id. 정확한 인물 이름 → 병합 기록의 옛 이름 → 정규화 키가 같은 인물. 없으면 None(만들지 않는다)."""
    name = (name or "").strip()
    if not name:
        return None
    r = conn.execute("SELECT id FROM entities WHERE type='person' AND name=?", (name,)).fetchone()
    if r:
        return resolve_id(conn, r["id"])
    try:
        r = conn.execute("SELECT survivor_id FROM entity_merges WHERE old_name=? AND type IN ('person','person_company') "
                         "AND reverted_at IS NULL", (name,)).fetchone()
    except Exception:  # noqa: BLE001
        r = None
    if r:
        return r[0]
    k = key(name)
    cands = [row["id"] for row in conn.execute("SELECT id, name FROM entities WHERE type='person' AND status IS NOT 'merged'")
             if key(row["name"]) == k]
    return cands[0] if len(cands) == 1 else None


# ── 이름 자동 정리: 계획(드라이런) ───────────────────────────────────

def _load(conn) -> tuple[dict[int, dict], set[int]]:
    ents: dict[int, dict] = {}
    for r in conn.execute("""SELECT e.id, e.type, e.name, e.status, e.aliases, e.meta_json,
                (SELECT COUNT(DISTINCT doc_id) FROM entity_links l WHERE l.entity_id=e.id) docs
            FROM entities e WHERE e.type='person'"""):
        ents[r["id"]] = dict(r)
    pkeys = {key(e["name"]) for e in ents.values()}
    for r in conn.execute("""SELECT e.id, e.type, e.name, e.status, e.aliases, e.meta_json,
                (SELECT COUNT(DISTINCT doc_id) FROM entity_links l WHERE l.entity_id=e.id) docs
            FROM entities e WHERE e.type='company' AND (e.aliases IS NULL OR e.aliases='')"""):
        meta = json.loads(r["meta_json"] or "{}") if (r["meta_json"] or "").startswith("{") else {}
        if meta.get("ticker") or key(r["name"]) not in pkeys:
            continue
        ents[r["id"]] = dict(r)
    follows = {r[0] for r in conn.execute("SELECT entity_id FROM follows")}
    return ents, follows


def _co_entities(conn, ids: list[int], exclude: set[int], top: int = 30) -> set[int]:
    q = ",".join("?" * len(ids))
    rows = conn.execute(f"""SELECT l2.entity_id, COUNT(*) c FROM entity_links l1
            JOIN entity_links l2 ON l2.doc_id=l1.doc_id AND l2.link_type IN ('stock','person','industry','topic')
            WHERE l1.entity_id IN ({q}) GROUP BY l2.entity_id ORDER BY c DESC LIMIT ?""", (*ids, top + len(exclude)))
    return {r[0] for r in rows if r[0] not in exclude}


def _survivor(ids: list[int], ents: dict[int, dict], follows: set[int], short: set[int] = frozenset()) -> int:
    """대표 = 팔로우한 이름 → (약칭·정리 대상이 아닌) 문서가 가장 많은 인물 이름."""
    people = [i for i in ids if ents[i]["type"] == "person"]
    clean = [i for i in people if "cleanup" not in canon(ents[i]["name"])[1]] or people
    followed = [i for i in clean if i in follows]
    pool = followed or [i for i in clean if i not in short] or clean
    return sorted(pool, key=lambda i: (-ents[i]["docs"], i))[0]


def _rule(loser: dict, survivor: dict, abbrev: bool) -> str:
    if loser["type"] == "company":
        return "type_fix"
    used = canon(loser["name"])[1] | canon(survivor["name"])[1]
    if abbrev:
        used.add("abbrev")
    return next((r for r in RULE_ORDER if r in used), "spacing")


def plan(conn) -> dict:
    """묶을 무리·그대로 둔 이름 → {groups[{survivor_id, survivor_name, members[{id,name,type,docs,rule}]}], held[…]}.

    쓰지 않는다(드라이런). 되돌린 이름(reverted_at)은 다시 묶지 않는다."""
    ents, follows = _load(conn)
    try:
        reverted = {r[0] for r in conn.execute("SELECT old_entity_id FROM entity_merges WHERE reverted_at IS NOT NULL "
                                               "AND old_entity_id IS NOT NULL")}
    except Exception:  # noqa: BLE001
        reverted = set()
    parent = {i: i for i in ents}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    by_key: dict[str, list[int]] = defaultdict(list)
    for i, e in ents.items():
        if i in reverted:
            continue
        by_key[key(e["name"])].append(i)
    for ids in by_key.values():
        for j in ids[1:]:
            union(ids[0], j)
    groups: dict[int, list[int]] = defaultdict(list)
    for i in ents:
        if i not in reverted:
            groups[find(i)].append(i)

    # 약칭: 한 낱말 이름 → 정확히 한 무리의 성·이름
    abbrev_pairs: set[int] = set()
    held = []
    multi: dict[str, list[int]] = defaultdict(list)          # 낱말 → 여러 낱말 이름 무리 대표들
    for root, ids in groups.items():
        if not any(ents[i]["type"] == "person" for i in ids):
            continue
        toks = {tuple(_tokens(ents[i]["name"])) for i in ids}
        for t in toks:
            if len(t) >= 2:
                for w in {t[0], t[-1]}:
                    if root not in multi[w]:
                        multi[w].append(root)
    for root, ids in list(groups.items()):
        if root not in groups or not any(ents[i]["type"] == "person" for i in ids):
            continue
        toks = {tuple(_tokens(ents[i]["name"])) for i in ids}
        if any(len(t) != 1 for t in toks) or len(toks) != 1:
            continue
        word = next(iter(toks))[0]
        if (len(word) < ABBREV_MIN_CHARS and word not in KEEP_APART) or not re.search(r"[가-힣]", word):
            continue
        cands = [c for c in multi.get(word, []) if c != root and c in groups]
        short = _survivor(ids, ents, follows)      # 무리의 대표(묶일 이름이 아니라)
        if not cands:
            continue
        cand_names = [ents[_survivor(groups[c], ents, follows)]["name"] for c in cands]
        cand_names = list(dict.fromkeys(cand_names))
        if word in KEEP_APART:
            held.append({"id": short, "name": ents[short]["name"], "docs": ents[short]["docs"], "reason": "keep_apart",
                         "candidates": cand_names})
            continue
        if len(cands) > 1:
            held.append({"id": short, "name": ents[short]["name"], "docs": ents[short]["docs"], "reason": "several",
                         "candidates": cand_names})
            continue
        other = groups[cands[0]]
        a = _co_entities(conn, ids, set(ids) | set(other))
        b = _co_entities(conn, other, set(ids) | set(other))
        shared = len(a & b)
        jac = shared / len(a | b) if a | b else 0.0
        full_docs = sum(ents[i]["docs"] for i in other if ents[i]["type"] == "person")
        if shared >= ABBREV_MIN_SHARED and jac >= ABBREV_MIN_JACCARD and full_docs >= ABBREV_MIN_FULL_DOCS:
            groups[cands[0]] = other + ids
            del groups[root]
            abbrev_pairs.update(ids)
        else:
            held.append({"id": short, "name": ents[short]["name"], "docs": ents[short]["docs"], "reason": "low_overlap",
                         "candidates": cand_names, "shared": shared, "jaccard": round(jac, 3), "full_docs": full_docs})

    out = []
    for ids in groups.values():
        persons = [i for i in ids if ents[i]["type"] == "person"]
        real = [i for i in persons if "cleanup" not in canon(ents[i]["name"])[1]]
        if not real:
            continue          # 정리 대상 이름뿐 — 기댈 실제 이름이 없다
        top = max(ents[i]["docs"] for i in persons)
        # 분류 교정은 인물 쪽이 훨씬 많이 쓰일 때만(회사가 주인 이름이면 사람이 아니다 — OpenAI·포르쉐·월트 디즈니)
        companies = [i for i in ids if ents[i]["type"] == "company"]
        if top < 2 or any(ents[i]["docs"] * TYPE_FIX_RATIO > top for i in companies):
            ids = [i for i in ids if ents[i]["type"] == "person"]
        if len(ids) < 2:
            continue
        s = _survivor(ids, ents, follows, abbrev_pairs)
        mem = [{"id": i, "name": ents[i]["name"], "type": ents[i]["type"], "docs": ents[i]["docs"],
                "rule": _rule(ents[i], ents[s], i in abbrev_pairs)} for i in sorted(ids, key=lambda i: -ents[i]["docs"]) if i != s]
        out.append({"survivor_id": s, "survivor_name": ents[s]["name"], "survivor_docs": ents[s]["docs"],
                    "followed": s in follows, "members": mem})
    out.sort(key=lambda g: -(g["survivor_docs"] + sum(m["docs"] for m in g["members"])))
    held.sort(key=lambda h: -h["docs"])
    return {"groups": out, "held": held,
            "stats": {"people": sum(1 for e in ents.values() if e["type"] == "person"),
                      "groups": len(out), "names": sum(len(g["members"]) for g in out),
                      "by_rule": dict(Counter(m["rule"] for g in out for m in g["members"])),
                      "held": len(held), "held_by_reason": dict(Counter(h["reason"] for h in held))}}


# ── 적용 · 되돌리기 ──────────────────────────────────────────────────

def _log(conn, target_id: int, verdict: str, rule: str, applied: bool, detail: dict) -> None:
    conn.execute(
        "INSERT INTO curation_log (kind, target_id, verdict, rule, applied, detail_json, decided_at) "
        "VALUES ('person', ?, ?, ?, ?, ?, datetime('now')) "
        "ON CONFLICT(kind, target_id) DO UPDATE SET verdict=excluded.verdict, rule=excluded.rule, applied=excluded.applied, "
        "detail_json=excluded.detail_json, decided_at=excluded.decided_at",
        (target_id, verdict, rule, 1 if applied else 0, json.dumps(detail, ensure_ascii=False)))


def apply(conn, p: dict) -> dict:
    """계획대로 소프트 병합(멱등) + 판정 기록(curation_log kind='person'). → {merged 새로 묶음, kept 이미 같음, moved 대표 바뀜}."""
    stats = Counter()
    current = {r["old_entity_id"]: dict(r) for r in conn.execute(
        "SELECT * FROM entity_merges WHERE type IN ('person','person_company') AND old_entity_id IS NOT NULL")}
    for g in p["groups"]:
        s = g["survivor_id"]
        for m in g["members"]:
            cur = current.get(m["id"])
            if cur and cur["reverted_at"]:
                continue
            typ = "person_company" if m["type"] == "company" else "person"
            if cur and cur["survivor_id"] == s:
                stats["kept"] += 1
            else:
                prev = conn.execute("SELECT status FROM entities WHERE id=?", (m["id"],)).fetchone()["status"]
                if cur:
                    conn.execute("UPDATE entity_merges SET survivor_id=?, rule=?, merged_at=datetime('now') WHERE id=?",
                                 (s, m["rule"], cur["id"]))
                    stats["moved"] += 1
                else:
                    conn.execute("""INSERT INTO entity_merges (old_name, type, survivor_id, rationale, old_entity_id, rule, prev_status)
                                    VALUES (?, ?, ?, ?, ?, ?, ?)
                                    ON CONFLICT(old_name, type) DO UPDATE SET survivor_id=excluded.survivor_id,
                                      rationale=excluded.rationale, old_entity_id=excluded.old_entity_id, rule=excluded.rule,
                                      prev_status=excluded.prev_status, reverted_at=NULL, merged_at=datetime('now')""",
                                 (m["name"], typ, s, f"자동 정리 · {RULE_KO[m['rule']]}", m["id"], m["rule"],
                                  prev if prev != "merged" else "active"))
                    stats["merged"] += 1
                conn.execute("UPDATE entities SET status='merged' WHERE id=?", (m["id"],))
            _log(conn, m["id"], "approve", m["rule"], True,
                 {"survivor_id": s, "survivor_name": g["survivor_name"], "old_name": m["name"], "type": m["type"], "docs": m["docs"]})
    held_ids = [h["id"] for h in p["held"]]
    # 지난 판정에서 보류였지만 이번 계획에 없는 이름(규칙이 바뀌어 묶였거나 후보가 사라짐)은 보류 기록을 지운다
    conn.execute(f"DELETE FROM curation_log WHERE kind='person' AND verdict='hold' "
                 f"AND target_id NOT IN ({','.join('?' * len(held_ids)) or 'NULL'})", held_ids)
    for h in p["held"]:
        _log(conn, h["id"], "hold", h["reason"], False,
             {"old_name": h["name"], "docs": h["docs"], "candidates": h["candidates"],
              **({"shared": h["shared"], "jaccard": h["jaccard"]} if "shared" in h else {})})
    conn.commit()
    return dict(stats)


def split(conn, old_entity_id: int) -> bool:
    """묶은 이름 하나를 되돌린다 — status 복원 + reverted_at. 다음 정리에서 다시 묶지 않는다."""
    r = conn.execute("SELECT id, prev_status FROM entity_merges WHERE old_entity_id=? AND type IN ('person','person_company') "
                     "AND reverted_at IS NULL", (old_entity_id,)).fetchone()
    if not r:
        return False
    conn.execute("UPDATE entity_merges SET reverted_at=datetime('now') WHERE id=?", (r["id"],))
    conn.execute("UPDATE entities SET status=? WHERE id=?", (r["prev_status"] or "active", old_entity_id))
    conn.execute("UPDATE curation_log SET verdict='reject', rule=COALESCE(rule,'') || ' · 되돌림', applied=0, "
                 "decided_at=datetime('now') WHERE kind='person' AND target_id=?", (old_entity_id,))
    conn.commit()
    return True


# ── 메모 저자 연결 ───────────────────────────────────────────────────

def link_authors(conn, dry_run: bool = False) -> dict:
    """출처가 정해진 메모 → 저자 author 링크(INSERT OR IGNORE). → {저자: (문서 수, 새로 넣은 수)}."""
    out = {}
    for prefix, (name, _org) in MEMO_AUTHORS.items():
        pid = resolve_name(conn, name)
        docs = [r[0] for r in conn.execute("SELECT id FROM raw_documents WHERE source_id LIKE ?", (prefix + "%",))]
        if not pid:
            out[name] = {"docs": len(docs), "added": 0, "person": None}
            continue
        have = {r[0] for r in conn.execute("SELECT doc_id FROM entity_links WHERE entity_id=? AND link_type='author'", (pid,))}
        new = [d for d in docs if d not in have]
        if not dry_run:
            conn.executemany("INSERT OR IGNORE INTO entity_links (doc_id, entity_id, link_type, confidence) VALUES (?, ?, 'author', 1.0)",
                             [(d, pid) for d in new])
        out[name] = {"docs": len(docs), "added": len(new), "person": pid}
    if not dry_run:
        conn.commit()
    return out


# ── 전제 '누가' 대응 표 ─────────────────────────────────────────────

def who_people(conn, who: str) -> list[dict]:
    """'Marks · BIS · Summers' → [{label, kind: person|org, entity_id|None, name}]. 인물 엔티티가 없으면 None(만들지 않는다)."""
    out = []
    for part in [p.strip() for p in (who or "").split("·") if p.strip()]:
        base = re.sub(r"\s*\(.*\)\s*$", "", part).strip()
        kind, names = WHO.get(base, ("person", [base]))
        eid = None
        if kind == "person":
            for n in names:
                eid = resolve_name(conn, n)
                if eid:
                    break
        nm = conn.execute("SELECT name FROM entities WHERE id=?", (eid,)).fetchone()["name"] if eid else None
        out.append({"label": part, "kind": kind, "entity_id": eid, "name": nm})
    return out


def premises_by_person(conn) -> tuple[list[dict], dict[int, list[dict]]]:
    """전제 원장(지금 판정) → (전제 목록 + who_people, 인물 id → 그 사람의 전제들)."""
    from pipeline import era
    prem = era.layer_premises(conn, era.layer_meaning(conn))
    by: dict[int, list[dict]] = defaultdict(list)
    for p in prem:
        p["who_people"] = who_people(conn, p["who"])
        for w in p["who_people"]:
            if w["entity_id"]:
                by[w["entity_id"]].append(p)
    return prem, by


# ── 역할 자동 분류 ───────────────────────────────────────────────────

def transcript_executives(conn) -> list[dict]:
    """컨콜 화자 직함 → [{name_en, title, ticker}]. alphavantage `**Name** (Title):` · fool 도입부 'CEO Name'/'Name, CFO'."""
    out: dict[tuple[str, str], dict] = {}
    for r in conn.execute("SELECT t.ticker, t.provider, rd.markdown FROM transcripts t JOIN raw_documents rd ON rd.id=t.raw_doc_id"):
        text = r["markdown"] or ""
        if r["provider"] == "alphavantage":
            for name, title in set(re.findall(r"\*\*([A-Z][\w.'\- ]{2,40}?)\*\*\s*\(([^)]{2,80})\)", text)):
                if EXEC_TITLE.search(title) and "analyst" not in title.lower():
                    out[(name.strip(), r["ticker"])] = {"name_en": name.strip(), "title": _short_title(title), "ticker": r["ticker"]}
        else:
            head = text[:4000]
            for title, name in re.findall(r"\b(CEO|CFO|Chief Executive Officer|Chief Financial Officer)\s+([A-Z][a-z]+(?:\s[A-Z][\w'\-]+){1,2})", head):
                out[(name.strip(), r["ticker"])] = {"name_en": name.strip(), "title": _short_title(title), "ticker": r["ticker"]}
    return list(out.values())


def _short_title(t: str) -> str:
    low = t.lower()
    if "chief executive" in low or re.search(r"\bceo\b", low):
        return "CEO"
    if "chief financial" in low or re.search(r"\bcfo\b", low):
        return "CFO"
    if "chair" in low:
        return "회장"
    return "경영진"


def classify_roles(conn) -> list[dict]:
    """대표 인물 → 역할 하나(정책 > 경영자 > 구루). 못 정하면 넣지 않는다. 쓰지 않는다."""
    roles: dict[int, dict] = {}

    def put(pid, role, org, code, title, source):
        if pid and pid not in roles:
            roles[pid] = {"entity_id": pid, "role": role, "org": org, "org_code": code, "title": title, "source": source}

    for name, (org, title) in POLICY.items():
        put(resolve_name(conn, name), "policy", org, None, title, "dictionary")
    company = {r[0]: r[1] for r in conn.execute("SELECT ticker, company_name FROM transcript_follow")}
    tdocs: dict[str, list[int]] = defaultdict(list)
    for r in conn.execute("SELECT ticker, raw_doc_id FROM transcripts"):
        tdocs[r[0]].append(r[1])
    for ex in transcript_executives(conn):
        ko = EN_KO.get(ex["name_en"].lower())
        pid = resolve_name(conn, ko) if ko else None
        if not pid:
            # 사전에 없는 영문 이름은 그 회사 컨콜 원문에 실제로 걸린 인물일 때만(동명이인 방지 — James Anderson 등)
            cand = resolve_name(conn, ex["name_en"])
            ids, docs = (members(conn, cand) if cand else []), tdocs.get(ex["ticker"], [])
            if cand and docs and conn.execute(
                    f"SELECT 1 FROM entity_links WHERE entity_id IN ({','.join('?' * len(ids))}) "
                    f"AND doc_id IN ({','.join('?' * len(docs))}) LIMIT 1", ids + docs).fetchone():
                pid = cand
        if pid:
            org = EXECUTIVE.get(ko or "", (None,))[0] or company.get(ex["ticker"]) or ex["ticker"]
            put(pid, "executive", org, ex["ticker"], ex["title"], "transcript")
    for name, (org, code, title) in EXECUTIVE.items():
        put(resolve_name(conn, name), "executive", org, code, title, "dictionary")
    for prefix, (name, org) in MEMO_AUTHORS.items():
        put(resolve_name(conn, name), "guru", org, None, None, "memo")
    for base, (kind, names) in WHO.items():
        if kind != "person":
            continue
        for n in names:
            pid = resolve_name(conn, n)
            if pid:
                put(pid, "guru", GURU_ORG.get(names[0]), None, None, "premise")
                break
    return list(roles.values())


def apply_roles(conn, rows: list[dict]) -> int:
    conn.execute("DELETE FROM person_roles WHERE source IN ('dictionary','transcript','premise','memo')")
    conn.executemany("""INSERT OR REPLACE INTO person_roles (entity_id, role, org, org_code, title, source, updated_at)
                        VALUES (:entity_id, :role, :org, :org_code, :title, :source, datetime('now'))""", rows)
    conn.commit()
    return len(rows)


def roles(conn, ids: list[int] | None = None) -> dict[int, dict]:
    try:
        q = "SELECT * FROM person_roles"
        rows = conn.execute(q).fetchall() if ids is None else conn.execute(
            f"{q} WHERE entity_id IN ({','.join('?' * len(ids))})", ids).fetchall() if ids else []
    except Exception:  # noqa: BLE001 — 표 없음
        return {}
    return {r["entity_id"]: dict(r) for r in rows}


# ── 한 번에 ──────────────────────────────────────────────────────────

def curate(conn, apply_changes: bool = True) -> dict:
    """정리 실행 — 계획 → (적용) 소프트 병합 → 메모 저자 → 역할. apply_changes=False면 드라이런."""
    p = plan(conn)
    out = {"plan": p["stats"]}
    if apply_changes:
        out["merge"] = apply(conn, p)
    out["authors"] = link_authors(conn, dry_run=not apply_changes)
    rows = classify_roles(conn)
    out["roles"] = dict(Counter(r["role"] for r in rows))
    if apply_changes:
        apply_roles(conn, rows)
    return out


def run_curation(conn) -> dict:
    """주간 정리(auto_curation.run_curation) 안에서 — 플래그 `person_curation`(기본 on)."""
    from pipeline.ops import flag_enabled
    if not flag_enabled("person_curation", default=True):
        return {"status": "skipped"}
    return curate(conn, apply_changes=True)
