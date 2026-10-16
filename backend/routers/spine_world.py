"""월드모델 읽기 전용 API — '지금' 랜딩·서사 체크포인트·홈 위젯 (docs/specs/world-model.md).

이 라우터의 GET은 저장된 행만 읽는다. 생성(서사·세계관·drift 요약)을 일으키는 경로는 부르지 않는다
— 위젯과 랜딩이 열릴 때마다 LLM이 돌지 않게. tests/test_world_reads.py가 이를 지킨다.
"""
from fastapi import APIRouter, Query

from database import get_connection
from models.world import BigPicture, Checkpoint, Contested, MyStockNarratives, NarrativeChanges
from pipeline import world_reads

router = APIRouter(prefix="/api/spine/world", tags=["spine"])


def _read(fn, *args):
    conn = get_connection()
    try:
        return fn(conn, *args)
    finally:
        conn.close()


@router.get("/big-picture", response_model=BigPicture)
def big_picture():
    """이번 주 큰 그림 — 살아 있는 메가 서사 + 저장된 세계관 브리핑(없으면 null)."""
    return _read(world_reads.big_picture)


@router.get("/changes", response_model=NarrativeChanges)
def changes(days: int = Query(7, ge=1, le=60), limit: int = Query(20, ge=1, le=100)):
    """최근 days일에 새 버전이 나온 서사 — 바뀐 것 한 줄 + 추가·삭제 고리."""
    return _read(world_reads.narrative_changes, days, limit)


@router.get("/contested", response_model=Contested)
def contested(limit: int = Query(10, ge=1, le=50)):
    """흔들리는 전제 — 충돌 중인 활성 지식과 최근 반례 문서."""
    return _read(world_reads.contested, limit)


@router.get("/my-stocks", response_model=MyStockNarratives)
def my_stocks(per_stock: int = Query(3, ge=1, le=10)):
    """내 종목을 움직이는 서사 — 종목 묶음(보유·관심) × 출처 확인 엣지 × 주제별 최신 서사."""
    return _read(world_reads.stock_narratives, per_stock)


@router.get("/checkpoint", response_model=Checkpoint)
def checkpoint(topic: str):
    """서사 상세 체크포인트 — 핵심질문·흔들릴 조건·수혜 후보·걸린 내 종목."""
    return _read(world_reads.checkpoint, topic)
