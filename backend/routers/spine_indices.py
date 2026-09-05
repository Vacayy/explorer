"""주요 지수 API (D-110).

GET  /api/spine/indices          — 지수 종가·등락률·1Y 추이·개장 상태 (저장분 읽기, LLM 0)
POST /api/spine/indices/snapshot — 강제 재수집(수동 갱신, 동기)

**GET은 절대 외부 fetch를 기다리지 않는다** — TTL이 만료되면 갱신을 백그라운드로 넘기고 저장분을
즉시 돌려준다(홈 첫 로딩이 yfinance 응답에 걸리면 안 됨; 실측에서 콜드 상태 100초 목격).
그래서 지수별 '수집 시각'을 화면에 노출한다 — 지금 보는 값이 언제 것인지 사용자가 알아야 한다.
개장 중엔 TTL 10분(프론트 폴링 주기와 맞춤), 전 시장 휴장이면 60분.
"""
from fastapi import APIRouter, BackgroundTasks

from pipeline.indices import any_market_open, get_indices, snapshot_indices
from services.cache_service import invalidate_cache, is_cached, set_cache

router = APIRouter(prefix="/api/spine/indices", tags=["spine"])

CACHE_KEY = "indices_snapshot"
TTL_OPEN = 10 * 60
TTL_CLOSED = 60 * 60


def _ttl() -> int:
    return TTL_OPEN if any_market_open() else TTL_CLOSED


def _refresh_bg():
    """백그라운드 갱신 — 전부 실패하면 TTL 선점을 풀어 다음 요청이 곧바로 재시도하게."""
    result = snapshot_indices()
    if not result["indices"]:
        invalidate_cache(CACHE_KEY)


@router.get("")
def api_indices(background: BackgroundTasks):
    if not is_cached(CACHE_KEY):
        set_cache(CACHE_KEY, _ttl())      # 먼저 선점 — 동시 요청이 갱신을 중복 예약하지 않게
        background.add_task(_refresh_bg)  # 응답을 먼저 보내고 그 다음 수집
    return get_indices()


@router.post("/snapshot")
def api_snapshot():
    invalidate_cache(CACHE_KEY)
    result = snapshot_indices()
    if result["indices"]:
        set_cache(CACHE_KEY, _ttl())
    return result
