from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from models.regimes import (BrkResponse, EraCheckBody, EraCommentaryResponse, EraStateResponse, RegimeCollectResponse,
                            RegimesResponse)
from pipeline import era, era_commentary
from pipeline.regimes import collect, get_brk, get_regimes
from services.shared_result import shared

router = APIRouter(prefix='/api/spine/regimes', tags=['spine'])


@router.get('', response_model=RegimesResponse)
def regimes():
    """S&P500 국면(Lunde–Timmermann 20/20)·조정·10개월선 추세·NBER 침체. 저장 읽기만(docs/specs/market-regimes.md)."""
    return get_regimes()


@router.get('/brk', response_model=BrkResponse)
def brk(bench: Literal['sp500tr', 'sp500', 'nasdaq'] = 'sp500tr',
        span: Literal['1y', '3y', '5y', '10y', '20y', 'all'] = Query('all', alias='range')):
    """버크셔 vs 지수 — 누적·상대강도·롤링 12M 초과수익·국면별 초과수익."""
    return get_brk(bench, span)


@router.post('/collect', response_model=RegimeCollectResponse)
def collect_now():
    return collect()


@router.get('/state', response_model=EraStateResponse)
def state():
    """지금 시장 읽기 네 층(상태·의미 국면·온도·전제 원장). 규칙 판정, 저장 읽기만."""
    return shared(('era.state',), era.get_state)   # /commentary도 같은 계산을 쓴다(동시 호출이면 하나만)


@router.put('/checks/{key}')
def put_check(key: str, body: EraCheckBody):
    """Marks 온도 체크리스트 정성 항목을 사람이 기록(state=null이면 지움)."""
    try:
        return era.set_check(key, body.state, body.note)
    except KeyError:
        raise HTTPException(404, f"알 수 없는 항목: {key}")


@router.get('/commentary', response_model=EraCommentaryResponse)
def commentary():
    """마지막 LLM 해설과 지금 입력과의 일치 여부(stale)."""
    return era_commentary.latest()


@router.post('/commentary', response_model=EraCommentaryResponse)
def make_commentary():
    """입력이 바뀌었을 때만 새로 만든다(같으면 저장본). 1~2분 걸리는 동기 호출."""
    try:
        return era_commentary.generate()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
