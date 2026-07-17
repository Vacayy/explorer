"""문서 강화(enrich).

엔진 선택 (opt-in — cron이 몰래 quota/비용을 쓰지 않도록 env로 명시):
  ENRICH_ENGINE=claude-code  → claude -p --model haiku (Claude Code 구독, API 키 불필요)
  ANTHROPIC_API_KEY 존재     → Anthropic API (Haiku — 태깅은 가성비 티어)
  둘 다 없음                 → 키워드 fallback

반환: {summary, sentiment, model, industries[], topics[], stocks[]?}
- stocks는 LLM이 별칭·약칭('하이닉스'→'SK하이닉스')을 정식 종목명으로 정규화한 결과.
  존재하면 store._link가 substring 매칭 대신 이것을 confidence 0.9로 사용한다.
"""
import json
import os
import shutil
import subprocess

from services.tagging_service import INDUSTRY_KEYWORDS, TOPIC_KEYWORDS

HAIKU_API_MODEL = "claude-haiku-4-5-20251001"
MAX_DOC_CHARS = 4000  # 토큰 통제 — 태깅에는 앞부분이면 충분


def _claude_bin() -> str | None:
    return os.getenv("CLAUDE_BIN") or shutil.which("claude")


def llm_engine() -> str | None:
    if os.getenv("ENRICH_ENGINE", "").strip().lower() == "claude-code" and _claude_bin():
        return "claude-code"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "api"
    return None


def llm_available() -> bool:
    return llm_engine() is not None


def classify_temporal(title: str, summary: str) -> dict:
    """시간 방향만 값싸게 분류 (백필용) — 전체 재태깅 없이 title+요약으로.

    반환: {time_orientation, reference_period}. 실패/미가용 시 빈 값.
    """
    if not llm_available():
        return {"time_orientation": None, "reference_period": None}
    prompt = (
        "다음 한국 투자 문서의 제목+요약을 읽고 '내용이 가리키는 시간'만 분류해 JSON만 출력.\n"
        '{"time_orientation": "past|current|forward|mixed", "reference_period": "실제 대상 시기 또는 null"}\n'
        "- past=이미 벌어진 일 회고, current=지금 상태·방금 사건, forward=미래 전망, mixed=과거+전망.\n"
        "- **글 작성일이 아니라 다루는 내용의 시점 기준.** reference_period: 발행 시점과 다른 특정 "
        "시기 대상이면 짧게(예: '2027 전망'), 아니면 null.\n"
        f"제목: {title}\n요약: {(summary or '')[:600]}"
    )
    try:
        engine = llm_engine()
        raw = _call_claude_code(prompt) if engine == "claude-code" else _call_api(prompt)
        data = _parse_json(raw)
    except Exception:
        return {"time_orientation": None, "reference_period": None}
    orient = str(data.get("time_orientation") or "").strip().lower()
    ref = str(data.get("reference_period") or "").strip()
    return {
        "time_orientation": orient if orient in ("past", "current", "forward", "mixed") else None,
        "reference_period": ref[:60] if ref and ref.lower() not in ("null", "none", "") else None,
    }


def enrich(title: str, markdown: str) -> dict:
    if llm_available():
        try:
            return _enrich_llm(title, markdown)
        except Exception as e:
            print(f"[enrich] LLM 실패, 키워드 fallback: {e}")
    return _enrich_keyword(title, markdown)


def _enrich_keyword(title: str, markdown: str) -> dict:
    text_upper = f"{title} {markdown}".upper()
    industries = [
        tag for tag, kws in INDUSTRY_KEYWORDS.items()
        if any(kw.upper() in text_upper for kw in kws)
    ]
    topics = [
        tag for tag, kws in TOPIC_KEYWORDS.items()
        if any(kw.upper() in text_upper for kw in kws)
    ]
    summary = (markdown or "").strip().replace("\n", " ")[:200]
    return {
        "summary": summary,
        "sentiment": None,
        "model": "keyword",
        "industries": industries,
        "topics": topics,
    }


def _live_vocab() -> tuple[list[str], list[str]]:
    """온톨로지의 현재 어휘 — DB의 sector/theme 엔티티, 사용 빈도순 상위 40.

    고정 사전이 아니라 살아있는 어휘: 새 라벨이 한 번 생성되면 다음 문서부터
    '기존 어휘'로 제시돼 표기가 수렴한다 (Web3 vs 웹3 파편화 방지).
    DB 접근 실패 시 시드 사전으로 fallback.
    """
    inds: list[str] = []
    tops: list[str] = []
    try:
        from database import get_connection
        conn = get_connection()
        inds = [r["name"] for r in conn.execute("""
            SELECT e.name, count(el.doc_id) c FROM entities e
            JOIN entity_links el ON el.entity_id = e.id AND el.link_type = 'industry'
            WHERE e.type = 'sector' GROUP BY e.id ORDER BY c DESC LIMIT 40""")]
        tops = [r["name"] for r in conn.execute("""
            SELECT e.name, count(el.doc_id) c FROM entities e
            JOIN entity_links el ON el.entity_id = e.id AND el.link_type = 'topic'
            WHERE e.type = 'theme' GROUP BY e.id ORDER BY c DESC LIMIT 40""")]
        conn.close()
    except Exception:
        pass
    # 시드 어휘 병합 (사용 빈도순 유지, 중복 제거)
    inds = list(dict.fromkeys([*inds, *INDUSTRY_KEYWORDS]))
    tops = list(dict.fromkeys([*tops, *TOPIC_KEYWORDS]))
    return inds, tops


def _person_vocab() -> list[str]:
    """기존 person 엔티티 (표기 수렴용) — 사용 빈도순 상위 40."""
    try:
        from database import get_connection
        conn = get_connection()
        names = [r["name"] for r in conn.execute("""
            SELECT e.name, count(el.doc_id) c FROM entities e
            JOIN entity_links el ON el.entity_id = e.id AND el.link_type = 'person'
            WHERE e.type = 'person' GROUP BY e.id ORDER BY c DESC LIMIT 40""")]
        conn.close()
        return names
    except Exception:
        return []


def _foreign_company_vocab() -> list[str]:
    """종목코드 없는 기업(해외·비상장) 정본 표기 — 재파편화 방지(메타/Meta 분리 차단).
    빈도순 상위 40. 시딩·병합으로 확립된 정본을 haiku가 그대로 쓰게."""
    try:
        from database import get_connection
        conn = get_connection()
        names = [r["name"] for r in conn.execute("""
            SELECT e.name, count(el.doc_id) c FROM entities e
            LEFT JOIN entity_links el ON el.entity_id = e.id
            WHERE e.type='company' AND e.aliases IS NULL AND e.status IS NOT 'merged'
            GROUP BY e.id ORDER BY c DESC LIMIT 40""")]
        conn.close()
        return names
    except Exception:
        return []


def _build_prompt(title: str, markdown: str) -> str:
    doc = f"{title}\n{(markdown or '')[:MAX_DOC_CHARS]}"
    inds, tops = _live_vocab()
    persons = _person_vocab()
    companies = _foreign_company_vocab()
    return (
        "다음 한국 투자 관련 문서를 분석해 JSON만 출력해. 설명·코드블록 금지.\n"
        '형식: {"stocks": [{"name": "정식 종목명", "as_written": "본문 표기", "listed": "KR|해외|비상장"}], '
        '"industries": [], "topics": [], "label_parents": {"신규라벨": "상위라벨"}, "people": [], '
        '"summary": "핵심 2문장", "sentiment": "positive|neutral|negative", '
        '"time_orientation": "past|current|forward|mixed", "reference_period": "실제 대상 시기 또는 null"}\n'
        "규칙:\n"
        "- time_orientation: 이 글의 '내용'이 시간상 어디를 가리키나 — past(이미 벌어진 일 회고), "
        "current(지금 상태·방금 일어난 사건), forward(미래 전망·예상), mixed(과거 짚고 전망까지). "
        "**중요: 글이 작성된 날짜가 아니라 다루는 내용의 시점 기준.** 예: '내년 반도체는 좋을 것'=forward, "
        "'어제 CFTC가 승인했다'=current, '2020년 사이클을 돌아보면'=past.\n"
        "- reference_period: 글이 발행일과 명백히 다른 특정 시기를 대상으로 하면 짧게 명시 "
        "(예: '2026 2분기 실적', '2027 전망', '2025 하반기'). 발행 시점 얘기면 null.\n"
        "- stocks: 실제로 논의 대상인 상장사만 (스쳐 지나가는 언급 제외). 한국 상장사는 별칭·약칭"
        "(하이닉스=SK하이닉스, 삼전=삼성전자)을 정식 종목명으로 정규화하고 listed=KR. "
        "해외 주요 상장사(엔비디아, 브로드컴, TSMC, 마이크론, 오라클, 팔란티어 등)도 논의 대상이면 "
        "통용 한국어 표기로, listed=해외. "
        "비상장 주요 기업(오픈AI, 앤트로픽, xAI, 데이터브릭스, Figure AI, Cognition, Harvey 등 "
        "AI 모델·소프트웨어·로보틱스)도 논의 대상이면 stocks에 listed=비상장으로 포함 — "
        "상장 여부와 무관하게 투자 세계관의 핵심 주체다.\n"
        "- **해외/비상장 기업은 아래 '기존 기업 표기'에 있으면 반드시 그 표기를 그대로 써라** "
        "(Meta→메타, Nvidia→엔비디아 식으로 통일 — 같은 회사가 한/영으로 쪼개지면 안 된다).\n"
        "- industries/topics: 넓은 영역과 세부 주제를 함께 라벨링 — 세부가 더 가치 있다 "
        "(예: Web3 문서면 'Web3'와 함께 '스테이블코인'/'RWA'/'STO' 등 구체 주제도). "
        "아래 기존 라벨과 같거나 유사한 개념이면 반드시 기존 라벨을 그대로 사용, "
        "명백히 새로우면 신규 허용 (1~2단어, 통용 한국어 표기).\n"
        "- label_parents: 이번에 새로 만든 라벨이 있으면 그것의 상위 개념을 기존/사용 라벨 중에서 지정 "
        '(예: {"스테이블코인": "Web3"}). 상위가 없으면 생략.\n'
        "- people: 문서가 실질적으로 다루는 실존 인물(기업가·투자자·정책결정자·석학)만, "
        "통용 한국어 표기로 정규화 (Sam Altman=샘 알트먼, 최태원 회장=최태원). 스쳐가는 이름 제외.\n"
        f"- 기존 인물 표기 (있으면 그대로 사용): {', '.join(persons) if persons else '(아직 없음)'}\n"
        f"- 기존 기업 표기 (해외/비상장, 있으면 그대로 사용): {', '.join(companies) if companies else '(아직 없음)'}\n"
        f"- 기존 산업 라벨: {', '.join(inds)}\n"
        f"- 기존 토픽 라벨: {', '.join(tops)}\n"
        f"문서:\n{doc}"
    )


def _parse_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"JSON 없음: {text[:80]}")
    return json.loads(text[start:end + 1])


def _call_claude_code(prompt: str) -> str:
    proc = subprocess.run(
        [_claude_bin(), "-p", "--model", "haiku", "--output-format", "json", prompt],
        capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0:
        # claude는 오류(사용량 한도·미로그인 등)를 stdout에 쓴다 — stderr만 보면 원인이 비어 보임
        raise RuntimeError(f"claude -p 실패 rc={proc.returncode} "
                           f"out={proc.stdout.strip()[:200]!r} err={proc.stderr.strip()[:120]!r}")
    envelope = json.loads(proc.stdout)
    return envelope.get("result", "")


def _call_api(prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=HAIKU_API_MODEL, max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if b.type == "text")


def _enrich_llm(title: str, markdown: str) -> dict:
    engine = llm_engine()
    prompt = _build_prompt(title, markdown)
    raw = _call_claude_code(prompt) if engine == "claude-code" else _call_api(prompt)
    data = _parse_json(raw)
    stocks = [s for s in (data.get("stocks") or []) if isinstance(s, dict) and s.get("name")]
    kr = [s for s in stocks if str(s.get("listed", "KR")).upper() in ("KR", "K", "KOREA")]
    foreign = [s for s in stocks if s not in kr]
    orient = str(data.get("time_orientation") or "").strip().lower()
    ref = str(data.get("reference_period") or "").strip()
    return {
        "summary": data.get("summary"),
        "sentiment": data.get("sentiment"),
        "time_orientation": orient if orient in ("past", "current", "forward", "mixed") else None,
        "reference_period": ref[:60] if ref and ref.lower() not in ("null", "none", "") else None,
        "model": f"{engine}/haiku",
        "industries": data.get("industries") or [],
        "topics": data.get("topics") or [],
        "label_parents": data.get("label_parents") or {},
        "people": [str(x).strip()[:30] for x in (data.get("people") or []) if str(x).strip()],
        "stocks": [s["name"] for s in kr],
        "foreign_stocks": [s["name"] for s in foreign],
        # 별칭 자동 학습: 본문 표기가 정식명과 다르면 ('삼전'→삼성전자) 후보로 전달
        "stock_aliases": [
            {"name": s["name"], "alias": str(s.get("as_written") or "").strip()}
            for s in kr
            if s.get("as_written") and str(s["as_written"]).strip() != s["name"]
        ],
    }
