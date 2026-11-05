"""산업·섹터 → Peer 그룹 대응 (GET /api/spine/sector-map/peers, pipeline/sector_peers)."""
from typing import Literal

from pydantic import BaseModel


class SectorPeerLink(BaseModel):
    group_id: str
    group_name: str
    scope: Literal["product", "value_chain"]
    source: Literal["seed", "auto"]          # seed = 사람이 정한 대응표, auto = 구성 종목 섹터 분포로 붙인 제안(저장 안 함)
    partial: bool                            # 섹터의 일부 업종만 덮는 연결(사람 판단)
    members: int                             # 그룹 구성 종목 수
    classified: int                          # 그중 산업 맵 섹터를 아는 종목 수
    in_sector: int                           # 그중 이 섹터 종목 수
    share: float | None                      # in_sector / classified (분류된 종목이 없으면 null)


class SectorPeerEntry(BaseModel):
    sector: str
    partial: bool
    note: str | None
    links: list[SectorPeerLink]


class SectorPeersResponse(BaseModel):
    catalog_as_of: str
    auto_share: float
    sectors: list[SectorPeerEntry]
