"""AI 대화 › 대상 붙이기 계약 (ia-redesign §4.14a, D-311)."""
from typing import Literal

from pydantic import BaseModel, Field

TargetKind = Literal["stock", "us_stock", "narrative", "question", "doc", "person", "theme", "peer_group", "report"]


class AttachmentRef(BaseModel):
    """요청 본문의 붙인 대상 — 이름 대신 식별자로 근거를 모은다."""
    kind: TargetKind
    ref: str = Field(min_length=1, max_length=100)   # 종목코드·티커·서사 topic·질문 id·doc_id·엔티티 id·Peer 그룹 id·리포트 topic
    label: str = Field(default="", max_length=200)


class TargetRef(BaseModel):
    """응답의 붙인 대상(보낸 질문 위 칩). 길이 검사는 요청에서 끝났다 — 응답 계약에는 길이 제약을 두지 않는다."""
    kind: TargetKind
    ref: str
    label: str = ""


class ChatTarget(TargetRef):
    """후보·대화에 붙어 있는 대상 — 칩 표시 정보 포함."""
    sub: str | None = None           # 두 번째 줄 (코드·업종·시장 / 서사 제목 / 출처 …)
    date: str | None = None          # YYYY-MM-DD — 서사·자료·리포트 날짜, 종목은 시세 기준일
    code: str | None = None          # 종목코드·티커·질문 '#7'
    change_pct: float | None = None  # 종목 등락 · Peer 그룹 20일 평균
    available: bool = True           # False = 사라짐(보관된 서사·지운 자료) — 칩을 흐리게, 보낼 때 뺀다


class ChatTargetGroup(BaseModel):
    kind: TargetKind
    items: list[ChatTarget]


class ChatTargetSearch(BaseModel):
    query: str
    kind: TargetKind | None
    groups: list[ChatTargetGroup]
