"""산업 › 섹터 지도 · 섹터 화면 (GET /api/spine/industry/*, pipeline/sector_view, ia-redesign §4.35, D-327)."""
from typing import Literal

from pydantic import BaseModel


class Benchmark(BaseModel):
    kind: Literal["etf", "computed"]       # etf = 대표 ETF 종가 · computed = Explorer 계산 지수(시총 가중)
    ticker: str | None                     # ETF 6자리 코드 (computed면 null)
    name: str | None                       # ETF 이름 (예: KODEX 반도체)
    tracks: str | None                     # 기초지수 (예: KRX 반도체)
    note: str | None                       # 섹터 구성과 다른 점 · ETF가 없는 이유


class RsTrail(BaseModel):
    weeks_ago: int
    rs_long: float | None
    rs_short: float | None


class MapSector(BaseModel):
    name: str
    benchmark: Benchmark
    last: float | None                     # 대표지수 마지막 값
    last_date: str | None
    chg_1d: float | None                   # % — 대표지수 기준
    ret_1m: float | None                   # % — 21거래일
    ret_3m: float | None                   # % — 63거래일
    rs_long: float | None                  # 산업 맵 RS (섹터 종목 시총 가중, sector_rs)
    rs_short: float | None
    chg_5d: float
    trail: list[RsTrail]
    market_cap: float
    stocks: int
    peer_groups: int | None                # 연결 그룹 + 그 아래 제품 그룹 수 (Peer 자료를 못 읽으면 null)
    series: list[float]                    # 대표지수 최근 61거래일


class OutsideGroup(BaseModel):
    id: str
    name: str
    members: int


class IndustryMapResponse(BaseModel):
    as_of: str | None
    kospi: list[float]                     # 코스피 최근 61거래일 (카드 점선)
    sectors: list[MapSector]
    outside_groups: list[OutsideGroup]     # 어느 섹터에도 걸리지 않은 Peer 그룹(상위 그룹만)
    peers_available: bool


class SeriesPoint(BaseModel):
    d: str
    v: float                               # 대표지수
    k: float | None                        # 같은 날 코스피


class Constituent(BaseModel):
    stock_code: str
    corp_name: str
    market_cap: float | None
    weight: float                          # 섹터 시총 비중 %
    chg_1d: float | None
    ret_1m: float | None
    rs_long: float | None
    rs_short: float | None


class SectorNarrative(BaseModel):
    id: int
    topic: str
    title: str
    core_question: str | None
    docs: int | None
    updated_at: str | None


class SectorOverview(BaseModel):
    question: str
    bullets: list[str]
    model: str | None
    generated_at: str
    narrative_ids: list[int]


class SectorDoc(BaseModel):
    id: int
    type: Literal["blog", "scrap", "web", "youtube"]
    title: str
    published_at: str | None


class PeerPreview(BaseModel):
    id: str
    name: str
    members: int
    med_60d: float | None
    series: list[float]                    # 그룹 중앙값 60거래일, 시작 = 100


class DataLink(BaseModel):
    kind: Literal["trade", "taiwan", "valuechain", "usSeason", "credit"]
    label: str
    title: str
    value: float | None
    value_kind: Literal["usd", "pct"] | None
    change: float | None                   # % (수출입 전년 대비)
    sub: str
    count: int
    href: str
    filtered: bool                         # 링크가 이 섹터로 걸러 여는가
    verdict: str | None


class SectorDetailResponse(BaseModel):
    as_of: str | None
    name: str
    benchmark: Benchmark
    last: float | None
    last_date: str | None
    chg_1d: float | None
    ret_1m: float | None
    ret_3m: float | None
    rs_long: float | None
    rs_short: float | None
    chg_5d: float
    trail: list[RsTrail]
    market_cap: float
    stocks: int
    series: list[SeriesPoint]              # 저장된 대표지수 전부(최대 3년)
    top_weights: list[Constituent]         # 섹터 시총 비중 상위 8
    constituents: list[Constituent]        # 시총 순 전체
    narratives: list[SectorNarrative]
    overview: SectorOverview | None        # AI 산업 개괄 (아직 없으면 null)
    docs: list[SectorDoc]                  # 최근 10일 주요 자료
    peer_groups: int | None
    peer_preview: list[PeerPreview]
    data_links: list[DataLink]
    feed_industry: str | None              # 피드 문서 검색 industry 값(섹터를 대표하는 업종 엔티티 이름)
    entity_id: int | None                  # 그 업종 엔티티 id — 팔로우 · AI 대화 대상(theme)


class SectorPeerGroup(BaseModel):
    id: str
    name: str
    scope: Literal["product", "value_chain"]
    parent: str | None                     # 상위 그룹 id (연결 그룹 자신이면 null)
    partial: bool
    auto: bool                             # 자동 제안 연결
    members: int
    med_20d: float | None
    med_60d: float | None


class SectorPeerListResponse(BaseModel):
    sector: str
    catalog_as_of: str
    prices_as_of: str
    groups: list[SectorPeerGroup]
