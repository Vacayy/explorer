"""문서 교차 종합 (D-104) — 사람이 고른 문서 묶음을 엮어 '이게 의미하는 바'를 뽑는다.

기존 종합은 앵커가 자동 선정된다(질문 D-093·기간 다이제스트·토픽 내러티브).
여기선 **사람이 저장해둔 문서 중 직접 고른 묶음**이 앵커 — 큐레이션이 곧 입력.

- 산출물 = 프레임(가설). 교차 축·상충·**질문 + 각 질문의 잠정 추론**·감시 지표.
  재료에 없는 것 금지, 미판정은 미판정으로(PHILOSOPHY §1).
- read-only 격리: 인과 그래프·질문 트래커에 아무것도 안 쓴다(논지 감사 규율 계승).
- 일회성 append-only: 같은 조합 재생성 = 새 행. 캐시 가드(inputs_hash) 없음 — 버튼이 곧 의도.
- 모델 sonnet: 원문 위의 종합·프레이밍(D-093 결산과 같은 결). opus는 4단계 모델링 엔진용.
"""
import json

from database import get_connection
from pipeline.enrich import _call_claude_code, llm_available

SYNTHESIS_MODEL = "sonnet"
MAX_DOCS = 12
_HEAD, _TAIL = 6000, 2000  # 초과분은 앞+뒤로 — 컨콜 Q&A·결론부 보존
_SOURCE_KO = {"telegram": "텔레그램 채널 글", "blog": "블로그 분석글", "youtube": "유튜브 영상 정리",
              "transcript": "실적 컨콜 원문", "news": "뉴스 기사", "article": "기고·아티클",
              "note": "내 노트", "canon": "정전 자료"}


def _clip(text: str) -> str:
    text = (text or "").strip()
    if len(text) <= _HEAD + _TAIL:
        return text
    return f"{text[:_HEAD]}\n\n…(중략)…\n\n{text[-_TAIL:]}"


def _gather(conn, doc_ids: list[int]) -> list[dict]:
    """엮을 문서 본문 + 출처 채널명 — markdown 우선, 없으면 raw_content (LLM 0).

    채널명은 본문이 **번호가 아니라 자연어로 출처를 밝히게** 하는 재료(D-105).
    """
    if not doc_ids:
        return []
    ph = ",".join("?" * len(doc_ids))
    rows = conn.execute(
        f"SELECT id, title, source_type, source_id, published_at, url, markdown, raw_content "
        f"FROM raw_documents WHERE id IN ({ph})", doc_ids).fetchall()
    from routers.spine_feed import resolve_channels
    channels = resolve_channels(conn, rows)
    by_id = {r["id"]: r for r in rows}
    docs = []
    for did in doc_ids:  # 사용자가 고른 순서 유지
        r = by_id.get(did)
        if not r:
            continue
        docs.append({
            "id": r["id"], "title": r["title"], "source_type": r["source_type"],
            "published_at": r["published_at"], "url": r["url"],
            "channel": (channels.get(r["id"]) or {}).get("name"),
            "text": _clip(r["markdown"] or r["raw_content"] or ""),
        })
    return docs


def _describe(d: dict) -> str:
    """자료의 정체 — 본문이 자연어로 출처를 밝힐 때 쓸 재료(누가·어떤 자료·언제)."""
    bits = [_SOURCE_KO.get(d["source_type"] or "", d["source_type"] or "자료")]
    if d.get("channel"):
        bits.append(f"출처 '{d['channel']}'")
    if d.get("published_at"):
        bits.append(f"{d['published_at'][:10]}")
    return " · ".join(bits)


def _build_prompt(docs: list[dict]) -> str:
    lines = []
    for i, d in enumerate(docs, 1):
        lines.append(f"\n[자료 {i}] {d['title'] or '(제목 없음)'}\n({_describe(d)})\n{d['text']}")
    return (
        "너는 업황(산업 판세)을 읽는 리서치 애널리스트다. 아래 자료들은 **한 사람이 직접 골라 엮은 묶음**이다. "
        "각 자료를 따로 요약하지 말고, 함께 놓았을 때 **이 산업이 어떻게 돌아가고 있는지**를 종합해라.\n"
        "\n"
        "가장 중요한 두 규율:\n"
        "**(1) 층위 = 업황·판세.** 개별 종목의 투자 판단(밸류에이션·목표주가·매수매도·그 회사만의 리스크)으로 "
        "좁히지 마라. 자료가 특정 기업의 것이어도 그 기업은 **산업을 읽는 표본**으로 다룬다 — 이 사실이 산업의 "
        "수요·공급·가격·자본조달·경쟁구조 중 **무엇이 어디로 움직이는 증거**인지로 옮겨라. "
        "질문도 업황 층위로: '이 회사 주가가 오를까'가 아니라 '이 구조가 지속되는가·무엇이 판을 뒤집는가'. "
        "단, 재료가 한 기업 이야기뿐이라 산업으로 넓힐 근거가 없으면 **억지 일반화 대신 무엇이 부족한지**를 말해라.\n"
        "**(2) 본문은 그 자체로 완결.** `[자료 1]`·'문서 2에 따르면' 같은 **번호 참조 금지** — 독자가 원문을 "
        "찾아가야 알 수 있는 표기는 쓰지 않는다. 출처는 문장 안에 자연어로 녹여라: 자료의 성격(경영진 컨콜 발언·"
        "제3자 분석·현직자 글·기자 보도)과 필요하면 채널·작성자명·시점을 함께. "
        "예: \"네비우스 2분기 컨콜에서 경영진은 …\", \"AWS 2분기를 분석한 블로그는 …\", \"현직자가 쓴 글에 따르면 …\". "
        "누구의 주장인지 읽는 사람이 본문만으로 알 수 있어야 한다.\n"
        "\n"
        "그 밖의 규율:\n"
        "- 개별 요약 나열 금지. 자료 사이를 잇는 것(구조·어긋남)이 산출물이다.\n"
        "- 재료에 없는 사실을 지어내지 말 것. 예측 단언 금지 — 알 수 없는 것은 '미판정'이라고 정직하게.\n"
        "- 주장 주체의 성격 차이(자사 이해관계가 걸린 1인칭 발언 vs 제3자 관찰)를 같은 무게로 다루지 말 것.\n"
        "- 질문은 던지고 끝내지 말고, **각 질문에 이 재료로 지금 말할 수 있는 잠정 추론**을 붙인다"
        "(무엇이 답을 가리키는지 / 무엇이 아직 비었는지).\n"
        "- 내부코드·약어 노출 금지, 자연어로.\n"
        + "\n".join(lines) + "\n\n"
        "\n출력 형식 — **JSON 아님, 마크다운 그대로**(산문에 따옴표·개행이 많아 JSON 이스케이프가 깨진다):\n"
        "첫 줄에 `# ` + 제목(이 묶음이 말하는 업황을 한 줄로, 20자 내외 제목투). 빈 줄 하나. 이후 본문.\n"
        "본문 구조:\n"
        "- 첫 문단 2~3문장 — 이 자료들이 업황에 대해 공통으로 말하는 것(판이 어디로 가는가)\n"
        "- `### 판의 구조` — 3~4개, 각 항목이 산업의 수요·공급·가격·자본·경쟁 중 무엇을 어디로 움직이는지\n"
        "- `### 상충·긴장` — 자료 간 어긋나는 지점·주장 주체의 성격 차이(없으면 없다고)\n"
        "- `### 업황이 던지는 질문` — 2~4개(산업 층위), 각 질문 아래 잠정 추론\n"
        "- `### 감시 지표` — 무엇이 관측되면 확인/무효화\n"
        "코드펜스·머리말·맺음말 없이 위 내용만 출력."
    )


def _parse(out: str) -> dict | None:
    """`# 제목` + 마크다운 본문 → {title, body}.

    JSON을 쓰지 않는 이유(D-105): 산출물이 산문이고 따옴표 인용을 권장하므로
    JSON 문자열 이스케이프가 실측에서 반복 실패했다(개행·따옴표 둘 다). 마크다운은 이스케이프가 없다.
    """
    text = (out or "").strip()
    if text.startswith("```"):  # 혹시 펜스로 감싸면 벗긴다
        text = text.split("\n", 1)[-1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    lines = text.strip().split("\n")
    title = None
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip() or None
        body = "\n".join(lines[1:]).strip()
    else:
        body = text.strip()
    if not body:
        return None
    return {"title": title, "body": body}


def _generate(docs: list[dict]) -> dict | None:
    try:
        out = _call_claude_code(_build_prompt(docs), model=SYNTHESIS_MODEL, timeout=600)
    except Exception as e:  # noqa: BLE001
        print(f"[doc_synthesis] LLM 호출 실패: {e}")  # 실패 원인이 502에 안 실리므로 서버 로그로
        return None
    result = _parse(out)
    if not result:
        print(f"[doc_synthesis] 빈 응답 (raw {len(out)}자)")
    return result


def create_synthesis(doc_ids: list[int]) -> dict:
    """고른 문서들을 엮어 종합 생성 → doc_syntheses 적재 → 단건 반환."""
    if not llm_available():
        return {"status": "unavailable"}
    ids = list(dict.fromkeys(int(d) for d in doc_ids))[:MAX_DOCS]  # 중복 제거·상한
    conn = get_connection()
    docs = _gather(conn, ids)
    conn.close()
    if len(docs) < 2:
        return {"status": "empty"}  # 엮을 게 없다 — 2건 이상이어야 교차 종합

    result = _generate(docs)
    if not result:
        return {"status": "failed"}

    found_ids = [d["id"] for d in docs]
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO doc_syntheses (doc_ids, title, body, model) VALUES (?,?,?,?)",
        (json.dumps(found_ids), result["title"], result["body"], f"claude-code/{SYNTHESIS_MODEL}"))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return {"status": "ok", **get_synthesis(new_id)}


def _doc_meta(conn, doc_ids: list[int]) -> list[dict]:
    """엮은 문서 칩용 메타 — 원문이 사라진 id는 메타 없이 그대로 노출(Partial)."""
    if not doc_ids:
        return []
    ph = ",".join("?" * len(doc_ids))
    rows = {r["id"]: r for r in conn.execute(
        f"SELECT id, title, source_type, published_at FROM raw_documents WHERE id IN ({ph})",
        doc_ids).fetchall()}
    return [{"id": did, "title": (rows[did]["title"] if did in rows else None),
             "source_type": (rows[did]["source_type"] if did in rows else None),
             "published_at": (rows[did]["published_at"] if did in rows else None)}
            for did in doc_ids]


def get_synthesis(synthesis_id: int) -> dict | None:
    """단건 + 엮은 문서 메타 (LLM 0)."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM doc_syntheses WHERE id=?", (synthesis_id,)).fetchone()
    if not row:
        conn.close()
        return None
    try:
        ids = [int(x) for x in json.loads(row["doc_ids"])]
    except Exception:  # noqa: BLE001
        ids = []
    docs = _doc_meta(conn, ids)
    conn.close()
    return {"id": row["id"], "title": row["title"], "body": row["body"],
            "model": row["model"], "created_at": row["created_at"], "docs": docs}


def list_syntheses(limit: int = 20) -> list[dict]:
    """최신순 목록 — 일회성 산출물의 재열람 경로 (LLM 0)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, title, doc_ids, created_at FROM doc_syntheses ORDER BY id DESC LIMIT ?",
        (limit,)).fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            n = len(json.loads(r["doc_ids"]))
        except Exception:  # noqa: BLE001
            n = 0
        out.append({"id": r["id"], "title": r["title"], "doc_count": n, "created_at": r["created_at"]})
    return out
