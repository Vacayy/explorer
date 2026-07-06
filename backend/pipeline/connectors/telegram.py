"""텔레그램 커넥터 — 기존 services/telegram_service.scrape_channel만 이식."""
from pipeline.base import RawDoc, SourceRef
from database import get_connection
from services.telegram_service import scrape_channel


class TelegramConnector:
    source_type = "telegram"

    def __init__(self, channels: list[str] | None = None):
        self._channels = channels

    def discover(self) -> list[SourceRef]:
        if self._channels is not None:
            return [SourceRef(key=c) for c in self._channels]
        conn = get_connection()
        rows = conn.execute(
            "SELECT channel_name FROM telegram_channels WHERE is_active=1"
        ).fetchall()
        conn.close()
        return [SourceRef(key=r["channel_name"]) for r in rows]

    def fetch(self, ref: SourceRef) -> list[RawDoc]:
        channel = ref.key
        messages = scrape_channel(channel)
        docs = []
        for m in messages:
            content = m.get("content", "")
            title = content.split("\n", 1)[0][:80] if content else ""
            docs.append(RawDoc(
                source_type="telegram",
                source_id=f"{channel}/{m.get('message_id', '')}",
                title=title,
                url=m.get("link", ""),
                published_at=m.get("date", ""),
                raw_content=content,
                kind="text",
            ))
        return docs
