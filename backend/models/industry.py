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


# ---------- 미국 (GET /api/spine/industry/us/*, pipeline/us_sectors, ia-redesign §4.36) ----------

class UsEtfRow(BaseModel):
    ticker: str                            # 섹터 ETF (XLK · SMH …)
    name: str                              # 한국어 섹터·업종 이름
    full_name: str                         # ETF 정식 이름
    parent: str | None                     # 상위 GICS ETF (GICS 섹터 자신이면 null)
    last: float | None                     # ETF 종가 (USD)
    last_date: str | None
    chg_1d: float | None                   # %
    ret_1m: float | None                   # % — 21거래일
    ret_3m: float | None                   # % — 63거래일
    chg_1w: float | None                   # % — 7일(달력)
    rs_long: float | None                  # 24개 ETF 간 백분위 — 장기 91일 수익률
    rs_short: float | None                 # 단기 7일 수익률
    trail: list[RsTrail]                   # 1·2·3·4주 전 RS
    coverage: int                          # 내 커버리지(팔로우 종목 중 이 섹터·업종) 수


class UsMapSector(UsEtfRow):
    series: list[float]                    # ETF 최근 61거래일 종가


class UsIndustryMapResponse(BaseModel):
    as_of: str | None                      # SPY 마지막 거래일(뉴욕)
    spy: list[float]                       # SPY 최근 61거래일 (카드 점선)
    sectors: list[UsMapSector]             # 카드 벽 순서(GICS 순, 세부 업종은 상위 뒤)


class UsSibling(BaseModel):
    ticker: str
    name: str
    parent: str | None
    ret_1m: float | None
    ret_3m: float | None
    rs_long: float | None
    rs_short: float | None


class UsMember(BaseModel):
    ticker: str
    name: str
    market_cap: float | None
    industry: str | None                   # Yahoo 업종 (대응 업종은 한국어)
    ret_1w: float | None                   # % — 7일(달력)
    ret_1m: float | None                   # % — 21거래일
    ret_3m: float | None                   # % — 63거래일
    closes: list[float]                    # 최근 64거래일 종가 (3개월 추이)


class UsSectorDoc(BaseModel):
    id: int
    type: Literal["blog", "scrap", "web", "youtube", "transcript", "earnings_release"]
    title: str
    published_at: str | None
    hits: int                              # 붙은 커버리지 종목 수


class UsDataLink(BaseModel):
    kind: Literal["usSeason", "valuechain", "taiwan", "krSector"]
    label: str
    title: str
    value: float | None
    value_kind: Literal["usd", "pct"] | None
    change: float | None
    sub: str
    count: int
    href: str
    filtered: bool
    verdict: str | None                    # 실적 시즌 판정 · 한국 섹터 'RS 장기·단기'


class UsSeriesPoint(BaseModel):
    d: str
    v: float                               # ETF 종가
    k: float | None                        # 같은 날 SPY


class UsSectorDetailResponse(UsEtfRow):
    as_of: str | None
    zone: Literal["주도", "숨 고르기", "반등 시도", "소외"] | None
    parent_name: str | None
    series: list[UsSeriesPoint]            # 저장된 ETF 종가 전부(최대 3년)
    siblings: list[UsSibling]              # 같은 상위 GICS 안(상위 자신 먼저)
    members: list[UsMember]                # 내 커버리지, 시총 순
    docs: list[UsSectorDoc]                # 최근 10일, 커버리지 종목이 붙은 자료(붙은 수 많은 순)
    data_links: list[UsDataLink]
