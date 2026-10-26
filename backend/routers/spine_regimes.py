from typing import Literal

from fastapi import APIRouter, Query
from models.regimes import BrkResponse, RegimeCollectResponse, RegimesResponse
from pipeline.regimes import collect, get_brk, get_regimes

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
