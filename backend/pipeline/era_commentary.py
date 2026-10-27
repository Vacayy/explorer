"""지금 시장 읽기 — LLM 해설 (docs/specs/market-regimes.md §8).

판정은 era.get_state()가 규칙으로 끝낸다. LLM은 그 결과를 투자자가 읽을 문장으로 옮길 뿐이다 — 새 숫자·예측·매매 권유 금지.
입력(판정 결과 + 최신 Marks 메모 발췌)의 해시가 같으면 다시 만들지 않는다(era_commentary.input_hash). 버튼 주도, 자동 생성 없음.
"""
import hashlib
import json
import os

from database import get_connection
from pipeline import llm
from pipeline.era import get_state

MODEL = os.getenv("ERA_COMMENTARY_MODEL", "sonnet")
MEMO_EXCERPT = 2500

SYSTEM = """너는 개인 투자자에게 '지금 시장이 어떤 상태인지'를 설명하는 해설가다. 아래 JSON은 규칙으로 이미 판정한 결과다.
규칙:
- 한국어, 쉬운 말. 전문 용어는 처음 나올 때 괄호로 한 번 풀어 쓴다.
- JSON에 있는 숫자만 쓴다. 새 숫자·날짜·전망치를 만들지 않는다.
- 판정을 바꾸지 않는다. '가설'·'반증 불가'·'데이터 없음' 표시는 그대로 전한다.
- 앞으로 오를지 내릴지 예측하지 않고, 사라·팔아라 같은 권유를 하지 않는다. '어디에 있는가'만 말한다.
- 숫자에는 항상 단위(%, %p, bp, 배)를 붙인다.
- 인명은 한국어 표기로 통일한다: 하워드 막스, 레이 달리오, 스탠리 드러켄밀러.
- 하워드 막스 메모 발췌가 있으면 '구루 전제 점검' 섹션에서 그의 관점과 지금 숫자가 어디서 맞고 어디서 어긋나는지 한두 문장으로 잇는다. 인용은 30단어 이하.
- '이 해설의 한계'에는 규칙의 한계·빈 데이터·사후 통계라는 점만 쓴다.
- 하락 국면은 두 단계다: 경계(월말 종가 < 12개월선, 빠르지만 헛경보 있음)와 확정(1년 신저가 이탈 또는 200일선 하락, 늦지만 헛경보 적음). stage가 none·warn·confirm 중 무엇인지, 과거 켜졌을 때 이후 얼마나 더 빠졌는지(통계)를 전한다. outcome은 bear=약세장, rebound=약세 직후 반등, correction=−15% 이상 조정, false=헛경보.
- market_pricing은 매일 브리핑에서 이어 본 '시장이 전제로 삼는 기대'의 최근 변화다(new=새로 등장, stronger, weaker, faded=사라짐). '시장이 가격에 반영하는 것' 섹션에서 가장 중요한 두세 개를 전하고, 가격 지표와 어긋나 보이면 그렇게만 짚는다.
- 아래 제목 그대로 마크다운 섹션 8개, 전체 1,400~2,000자.
## 한 줄 요약
## 지금 하락 국면인가
## 금리는 지금 무슨 뜻인가
## 막스식 온도
## 시장이 가격에 반영하는 것
## 구루 전제 점검
## 지켜볼 것
## 이 해설의 한계"""


def _inputs() -> dict:
    s = get_state()
    m = dict(s["meaning"])
    m.pop("corr_series", None)
    conn = get_connection()
    try:
        row = conn.execute("SELECT title, published_at, markdown FROM raw_documents WHERE source_type='memo' "
                           "ORDER BY published_at DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    memo = {"title": row["title"], "date": (row["published_at"] or "")[:10], "excerpt": (row["markdown"] or "")[:MEMO_EXCERPT]} if row else None
    premises = [{k: p[k] for k in ("claim", "who", "kind", "evidence", "status", "rule")} for p in s["premises"]]
    from pipeline.pricing_ledger import brief
    pricing = brief(2)
    pricing = {"as_of": pricing["as_of"], "summary": pricing["summary"],
               "claims": [c for c in pricing["claims"] if c["status"] in ("new", "stronger", "weaker", "faded")][:8]}
    return {"state": _state_brief(s["state"]), "market_pricing": pricing, "meaning": m, "temperature": s["temperature"], "premises": premises, "latest_marks_memo": memo}


def _state_brief(st: dict) -> dict:
    """경로 배열은 빼고 판정·통계·최근 에피소드 요약만 — LLM 입력 크기를 줄인다."""
    if not st.get("available"):
        return st
    brief = {k: v for k, v in st.items() if k not in ("warn", "confirm", "current_path")}
    for key in ("warn", "confirm"):
        sig = st[key]
        brief[key] = {k: v for k, v in sig.items() if k not in ("episodes", "median_path")}
        brief[key]["recent_episodes"] = [{k: e[k] for k in ("date", "outcome", "drawdown_at", "min_after", "ret_after")} for e in sig["episodes"][-4:]]
        done = [e for e in sig["episodes"] if e["complete"]]
        brief[key]["outcome_counts"] = {o: sum(e["outcome"] == o for e in done) for o in ("bear", "rebound", "correction", "false")}
    return brief


def _hash(inputs: dict) -> str:
    """입력 + 프롬프트·모델 — 프롬프트를 고치면 저장본이 낡은 것으로 표시된다."""
    return hashlib.sha1(json.dumps([inputs, SYSTEM, MODEL], ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def latest() -> dict:
    inputs = _inputs()
    h = _hash(inputs)
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM era_commentary ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    if not row:
        return {"body": None, "created_at": None, "model": None, "stale": True}
    return {"body": row["body"], "created_at": row["created_at"].replace(" ", "T") + "Z", "model": row["model"],
            "stale": row["input_hash"] != h}


def generate() -> dict:
    inputs = _inputs()
    h = _hash(inputs)
    conn = get_connection()
    try:
        if conn.execute("SELECT 1 FROM era_commentary WHERE input_hash=?", (h,)).fetchone():
            return latest()
    finally:
        conn.close()
    res = llm.run(json.dumps(inputs, ensure_ascii=False, default=str), system=SYSTEM, model=MODEL, timeout=300, job="era.commentary")
    body = llm.visible_text(res.text).strip()
    if not body:
        raise RuntimeError("LLM이 빈 해설을 돌려줬습니다")
    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO era_commentary (input_hash, input_json, body, model, cost_usd) VALUES (?,?,?,?,?)",
                     (h, json.dumps(inputs, ensure_ascii=False, default=str), body, res.label, res.cost_usd))
        conn.commit()
    finally:
        conn.close()
    return latest()
