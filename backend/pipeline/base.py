"""커넥터 인터페이스와 데이터 구조.

새 소스 = SourceConnector 하나 구현. discover()로 무엇을 가져올지 정하고,
fetch(ref)로 실제 문서들을 반환한다. normalize/enrich/store는 공통 파이프라인이 담당.
"""
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class RawDoc:
    source_type: str            # blog | telegram | note | ...
    source_id: str              # 소스 내 고유 자연키 (dedup용)
    title: str = ""
    url: str = ""
    published_at: str = ""
    raw_content: str = ""       # 원본 (text/html) 또는 파일 경로(pdf)
    kind: str = "text"          # text | html | pdf  (normalize 힌트)
    images: list[str] = field(default_factory=list)  # 로컬 저장된 미디어 상대경로 (/media 기준)


@dataclass
class SourceRef:
    key: str                    # feed url / channel name 등 fetch 대상 식별자
    meta: dict = field(default_factory=dict)


@runtime_checkable
class SourceConnector(Protocol):
    source_type: str

    def discover(self) -> list[SourceRef]:
        """무엇을 가져올지 (증분/신규 대상 목록)."""
        ...

    def fetch(self, ref: SourceRef) -> list[RawDoc]:
        """대상 하나를 수집해 문서 리스트 반환 (feed/channel은 다건)."""
        ...
