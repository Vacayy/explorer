"""포트폴리오 — 거래 원장 입력과 비율 전용 조회 (D-212, docs/specs/portfolio-ledger.md).

response_model이 금액·수량 필드를 갖지 않으므로 실수로 섞여도 응답에서 걸러진다.
"""
from fastapi import APIRouter, HTTPException, Query

from models.portfolio import (Exposure, HistoryPoint, HoldingFlow, PortfolioEvent, PortfolioSummary, Principle, PrincipleCreate,
                              PrincipleParse, PrincipleParseRequest, PrincipleText, ThesisCreate, TransactionCreate, TransactionItem)
from pipeline import portfolio as pf
from pipeline import portfolio_events as pe
from pipeline import portfolio_exposure as px
from pipeline import portfolio_flow as fl
from pipeline import portfolio_principles as pp
from pipeline import portfolio_thesis as pt

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("", response_model=PortfolioSummary)
def get_summary():
    conn = pf.connect()
    try:
        return pf.summary(conn)
    finally:
        conn.close()


@router.get("/history", response_model=list[HistoryPoint])
def get_history():
    conn = pf.connect()
    try:
        return pf.history(conn)
    finally:
        conn.close()


@router.get("/exposure", response_model=Exposure)
def get_exposure():
    """공통 변수 — 보유 종목들이 함께 기대는 변수와 걸린 비중(인과 그래프·동시 언급·밸류체인, LLM 0)."""
    conn = pf.connect()
    try:
        holdings = [{"code": h["code"], "name": h["name"], "weight_pct": h["weight_pct"]} for h in pf.summary(conn)["holdings"]]
        return px.cached_exposure(conn, holdings) if holdings else {"drivers": [], "coverage": {}, "held": []}
    finally:
        conn.close()


@router.get("/events", response_model=list[PortfolioEvent])
def get_events(days: int = Query(45, ge=1, le=120)):
    """다가오는 이벤트 — 확정(DART 예고 공시)·예상(작년 같은 분기·법정 기한)·관련 해외 실적일. 수집은 16:50 pfclose."""
    from datetime import date
    conn = pf.connect()
    try:
        holdings = [{"code": h["code"], "name": h["name"], "weight_pct": h["weight_pct"]} for h in pf.summary(conn)["holdings"]]
        if not holdings:
            return []
        return pe.upcoming(conn, holdings, px.chains_of(conn, holdings), date.today(), days)
    finally:
        conn.close()


@router.get("/flow", response_model=list[HoldingFlow])
def get_flow():
    """자료 흐름 — 보유 종목별 14일 언급·논조와 최신 1D 요약(읽기만, 생성은 16:50 pfclose)."""
    from datetime import datetime
    conn = pf.connect()
    try:
        holdings = [{"code": h["code"], "name": h["name"]} for h in pf.summary(conn)["holdings"]]
        return fl.flow(conn, holdings, datetime.now(fl.KST).date())
    finally:
        conn.close()


@router.get("/thesis")
def get_theses():
    """보유 종목별 추적 중인 논지 — 판정(선행·확정·괴리)·하위 질문(반증 조건)·나빠진 신호."""
    conn = pf.connect()
    try:
        codes = [h["code"] for h in pf.summary(conn)["holdings"]]
        judging = pt.judging()
        return {code: {**t, "warnings": pt.warnings(t), "judging": judging} for code, t in pt.theses(conn, codes).items()}
    finally:
        conn.close()


@router.post("/thesis", status_code=201)
def create_thesis(body: ThesisCreate):
    """논지 감시 시작 — 기존 핵심질문 추적기로 분해(sonnet 1회, 1~3분). 이후 매일 07:40 판정."""
    conn = pf.connect()
    try:
        held = {h["code"]: h["name"] for h in pf.summary(conn)["holdings"]}
    finally:
        conn.close()
    if body.stock_code not in held:
        raise HTTPException(404, "보유 종목이 아닙니다.")
    r = pt.start(body.stock_code, held[body.stock_code], body.why, body.falsifier)
    if "error" in r:
        raise HTTPException(503, r["error"])
    return {"id": r["id"]}


@router.post("/quotes/refresh")
def refresh_quotes():
    """'시세 갱신' 버튼 — 30분 주기·장 시간과 무관하게 보유 종목 네이버 실시간 시세를 지금 받는다."""
    conn = pf.connect()
    try:
        return pf.refresh_now(conn)
    finally:
        conn.close()


@router.get("/transactions", response_model=list[TransactionItem])
def list_transactions():
    conn = pf.connect()
    try:
        return pf.transactions(conn)
    finally:
        conn.close()


@router.post("/transactions")
def create_transaction(body: TransactionCreate):
    conn = pf.connect()
    try:
        tx = body.model_dump(exclude={"fund_shortfall"})
        return {"ok": True, "id": pf.add_transaction(conn, tx, fund_shortfall=body.fund_shortfall)}
    except pf.LedgerError as e:
        raise HTTPException(409, str(e))
    finally:
        conn.close()


@router.delete("/transactions/{tx_id}")
def remove_transaction(tx_id: int):
    conn = pf.connect()
    try:
        pf.delete_transaction(conn, tx_id)
        return {"ok": True}
    except pf.LedgerError as e:
        raise HTTPException(409, str(e))
    finally:
        conn.close()


# ── 운용 원칙 (D-227) — 원문은 로컬 DB에만. 위반은 화면이 아니라 텔레그램으로만 알린다 ─────────────

@router.get("/principles", response_model=list[Principle])
def list_principles():
    conn = pf.connect()
    try:
        return pp.principles(conn)
    finally:
        conn.close()


@router.post("/principles/parse", response_model=PrincipleParse)
def parse_principle(body: PrincipleParseRequest):
    """원칙 문장 → 수치 규칙 미리보기(haiku 1회, 저장하지 않음). 원장은 모델에 보내지 않는다."""
    try:
        return pp.parse(body.text)
    except Exception as e:  # noqa: BLE001 — 모델 실패는 503으로
        raise HTTPException(503, f"원칙을 해석하지 못했습니다: {type(e).__name__}")


@router.post("/principles", status_code=201)
def create_principle(body: PrincipleCreate):
    conn = pf.connect()
    try:
        return {"id": pp.add(conn, body.text, [r.model_dump(exclude={"summary"}) for r in body.rules], body.notes)}
    except ValueError as e:
        raise HTTPException(422, str(e))
    finally:
        conn.close()


@router.patch("/principles/{principle_id}")
def update_principle_text(principle_id: int, body: PrincipleText):
    """원문만 수정 — 점검 규칙은 그대로."""
    conn = pf.connect()
    try:
        if not pp.update_text(conn, principle_id, body.text):
            raise HTTPException(404, "원칙을 찾을 수 없습니다.")
        return {"ok": True}
    finally:
        conn.close()


@router.put("/principles/{principle_id}")
def replace_principle(principle_id: int, body: PrincipleCreate):
    """다시 풀기 — 원문·점검 규칙·참고 목록을 함께 교체."""
    conn = pf.connect()
    try:
        if not pp.replace(conn, principle_id, body.text, [r.model_dump(exclude={"summary"}) for r in body.rules], body.notes):
            raise HTTPException(404, "원칙을 찾을 수 없습니다.")
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(422, str(e))
    finally:
        conn.close()


@router.delete("/principles/{principle_id}")
def delete_principle(principle_id: int):
    conn = pf.connect()
    try:
        pp.remove(conn, principle_id)
        return {"ok": True}
    finally:
        conn.close()
