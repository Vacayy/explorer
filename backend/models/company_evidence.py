"""기업 관련 자료(도시에 자료 탭·개요 미리보기) 응답 — GET /api/spine/feed/company-evidence."""
from typing import Literal

from pydantic import BaseModel


class EvidenceItem(BaseModel):
    id: str
    doc_id: int | None
    title: str
    url: str
    excerpt: str                   # 태그를 걷은 본문 앞부분(최대 600자, 없으면 '')
    source_type: str
    publisher: str
    published_at: str
    local_date: str
    time_precision: Literal["date", "time"]
    status: Literal["within", "after", "uncertain"]
    relation: str


class EvidenceCoverage(BaseModel):
    source: str
    first: str
    last: str
    count: int


class EvidenceFlowDay(BaseModel):
    date: str
    count: int


class EvidenceFlowSource(BaseModel):
    source: str
    count: int


class EvidenceFlow(BaseModel):
    """최근 30일 언급 흐름 — 출처·검색어와 무관하게 이 기업 자료 전체(시장 시간대 날짜)."""
    start: str
    end: str
    days: list[EvidenceFlowDay]
    sources: list[EvidenceFlowSource]


class CompanyEvidenceResponse(BaseModel):
    items: list[EvidenceItem]
    total: int
    page: int
    size: int
    has_more: bool
    coverage: list[EvidenceCoverage]
    undated_count: int
    uncertain_count: int
    timezone: str
    as_of: str
    flow: EvidenceFlow
