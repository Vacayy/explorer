"""가설·메모 커넥터 — vault/notes/*.md (사람 소유 마크다운 원본).

소유권 분할 원칙 (docs/specs/hypothesis-vault.md):
- vault/notes/ 의 마크다운이 원본(source of record). DB는 검색/그래프 조인용 파생 인덱스.
- 본문의 [[엔티티명]] 위키링크는 store._link에서 confidence 1.0으로 흡수된다.
"""
from datetime import datetime, timezone
from pathlib import Path

from config import VAULT_PATH
from pipeline.base import RawDoc, SourceRef


class NoteConnector:
    source_type = "note"

    def __init__(self, vault: Path | None = None):
        self._notes_dir = (vault or VAULT_PATH) / "notes"

    def discover(self) -> list[SourceRef]:
        if not self._notes_dir.is_dir():
            return []
        return [SourceRef(key=str(p)) for p in sorted(self._notes_dir.rglob("*.md"))]

    def fetch(self, ref: SourceRef) -> list[RawDoc]:
        p = Path(ref.key)
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            return []
        # 제목: 첫 '# ' 헤딩, 없으면 파일명
        title = p.stem
        for line in text.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat()
        return [RawDoc(
            source_type="note",
            source_id=str(p.relative_to(self._notes_dir)),
            title=title,
            url="",  # 로컬 파일 — 원문 링크 없음
            published_at=mtime,
            raw_content=text,
            kind="text",
        )]
