"""텔레그램 커넥터 — 기존 services/telegram_service.scrape_channel만 이식.

이미지: CDN URL은 만료될 수 있어 MEDIA_PATH에 다운로드해 상대경로로 보관.
파일명이 결정적(채널_메시지ID_순번)이라 재수집 시 중복 다운로드 없음.
"""
import requests
import urllib3

from config import MEDIA_PATH
from pipeline.base import RawDoc, SourceRef
from database import get_connection
from services.telegram_service import scrape_channel

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def _download_images(channel: str, msg_id: str, urls: list[str]) -> list[str]:
    """CDN 이미지 → media/telegram/ 저장. 반환: /media 기준 상대경로 목록."""
    saved = []
    out_dir = MEDIA_PATH / "telegram"
    for i, url in enumerate(urls):
        rel = f"telegram/{channel}_{msg_id}_{i}.jpg"
        dest = MEDIA_PATH / rel
        if dest.exists():
            saved.append(rel)
            continue
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=20, verify=False)
            if resp.status_code == 200 and resp.content:
                out_dir.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(resp.content)
                saved.append(rel)
        except Exception:
            continue  # 개별 이미지 실패는 문서 수집을 막지 않는다
    return saved


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
            msg_id = m.get("message_id", "")
            images = _download_images(channel, msg_id, m.get("images", []))
            title = content.split("\n", 1)[0][:80] if content else (
                f"[이미지] {channel} #{msg_id}" if images else "")
            docs.append(RawDoc(
                source_type="telegram",
                source_id=f"{channel}/{msg_id}",
                title=title,
                url=m.get("link", ""),
                published_at=m.get("date", ""),
                raw_content=content,
                kind="text",
                images=images,
            ))
        return docs
