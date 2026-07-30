"""미국 종목 도시에 API 스키마 (docs/specs/us-dossier.md)."""
from typing import Any

from pydantic import BaseModel


class UsDossier(BaseModel):
    ticker: str
    name: str
    entity_id: int | None = None
    fundamentals: dict[str, Any] | None = None   # yfinance 스냅샷 (price·fwd_pe·estimates…)
    latest_transcript: dict[str, Any] | None = None  # 최근 컨콜 메타 (있으면)
