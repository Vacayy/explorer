"""텔레그램 커넥터 — 기존 services/telegram_service.scrape_channel만 이식.

이미지: CDN URL은 만료될 수 있어 MEDIA_PATH에 다운로드해 상대경로로 보관.
파일명이 결정적(채널_메시지ID_순번)이라 재수집 시 중복 다운로드 없음.
"""
import os
from datetime import datetime

import requests
import urllib3

from config import MEDIA_PATH
from pipeline.base import RawDoc, SourceRef
from database import get_connection
from services.telegram_service import scrape_channel

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# 연속 타이핑 병합: 같은 채널에서 GAP 이내 간격으로 이어진 메시지들은 하나의
# 의도(메시지1+2+3 = 실제 메시지)로 보고 한 문서로 저장한다.
# 문서 source_id = 채널/첫메시지ID — 그룹이 자라도 키가 안정적이라
# content_hash 변경 → 기존 update+재enrich 경로가 그대로 동작 (멱등).
GROUP_GAP_SEC = int(os.getenv("TELEGRAM_GROUP_GAP_SEC", "300"))
MAX_GROUP = 15


def _parse_dt(s: str):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except Exception:
        return None


def group_bursts(messages: list[dict], gap_sec: int = GROUP_GAP_SEC) -> list[list[dict]]:
    """메시지들을 연속 타이핑 묶음으로 그룹핑 (msg_id 오름차순 입력 가정 안 함)."""
    msgs = sorted(messages, key=lambda m: int(str(m.get("message_id") or 0) or 0))
    groups: list[list[dict]] = []
    for m in msgs:
        dt = _parse_dt(m.get("date", ""))
        if groups and len(groups[-1]) < MAX_GROUP:
            prev_dt = _parse_dt(groups[-1][-1].get("date", ""))
            if dt and prev_dt and 0 <= (dt - prev_dt).total_seconds() <= gap_sec:
                groups[-1].append(m)
                continue
        groups.append([m])
    return groups


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
        for group in group_bursts(messages):
            head = group[0]
            head_id = head.get("message_id", "")
            contents, images = [], []
            for m in group:
                if (m.get("content") or "").strip():
                    contents.append(m["content"])
                images += _download_images(channel, m.get("message_id", ""), m.get("images", []))
            content = "\n\n".join(contents)
            title = content.split("\n", 1)[0][:80] if content else (
                f"[이미지] {channel} #{head_id}" if images else "")
            docs.append(RawDoc(
                source_type="telegram",
                source_id=f"{channel}/{head_id}",
                title=title,
                url=head.get("link", ""),
                published_at=head.get("date", ""),
                raw_content=content,
                kind="text",
                images=images,
            ))
        return docs
