"""텔레그램 커넥터 — 기존 services/telegram_service.scrape_channel만 이식.

이미지: 파일은 저장하지 않는다. 이미지가 전달하려는 메시지를 AI가 해석해 그 메시지 뒤에 한 줄로 넣는다
(docs/specs/image-reading.md). raw_content는 원문 그대로, 해석 줄은 markdown에만.
예전에 받아둔 media/telegram/ 파일은 그대로 두고 media_json으로 계속 가리킨다.
"""
import os
import re
from datetime import datetime

from config import MEDIA_PATH
from pipeline import image_reading
from pipeline.base import RawDoc, SourceRef
from database import get_connection
from services.telegram_service import scrape_channel

# 연속 타이핑 병합: 하나의 의도(메시지1+2+3 = 실제 메시지)를 한 문서로.
# 2단 판정: ① 시간 창(JUDGE_WINDOW) 이내 = '심사 자격' ② haiku가 실제로
# 이어지는 말인지 판별 → 메시지당 1회 판정을 영구 캐시 (재수집 멱등성의 근간).
# LLM 불가 시 GROUP_GAP_SEC 시간 규칙으로 fallback.
# 문서 source_id = 채널/첫메시지ID — 그룹이 자라도 키가 안정적이라
# content_hash 변경 → 기존 update+재enrich 경로가 그대로 동작.
GROUP_GAP_SEC = int(os.getenv("TELEGRAM_GROUP_GAP_SEC", "300"))
JUDGE_WINDOW_SEC = int(os.getenv("TELEGRAM_GROUP_JUDGE_WINDOW_SEC", "600"))
MAX_GROUP = 15


def _parse_dt(s: str):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except Exception:
        return None


def _judge_continuation(prev_text: str, cur_text: str, gap: float = 0) -> bool | None:
    """haiku 판정: cur가 prev의 연장인가. LLM 불가/실패 시 None.

    판별 기준은 주제가 아니라 구조 — B가 단독으로 완결된 새 글인지.
    출력은 JSON 대신 단어 토큰 (haiku의 형식 이탈에 강건).
    """
    from pipeline.enrich import llm_engine, _call_claude_code
    if llm_engine() != "claude-code":
        return None
    prompt = (
        f"한 텔레그램 채널에 {int(gap)}초 간격으로 연속으로 올라온 두 메시지다. "
        "이 채널 주인은 하나의 논지를 채팅 치듯 여러 메시지로 끊어 올리는 습관이 있다.\n"
        "질문: 메시지B는 무엇인가?\n"
        "- CONTINUATION: 메시지A의 연장 — B가 A 없이는 맥락이 잡히지 않는 조각"
        "(수치·표·만기일·'end.' 같은 마무리·부연·같은 논지의 전개)\n"
        "- SEPARATE: 단독으로 완결된 새 글 — B 혼자 읽어도 이해되는 독립 뉴스·"
        "다른 종목/이슈의 새 분석 (제목형 문장으로 시작하는 경우가 많다)\n"
        "마지막 줄에 정확히 한 단어만: CONTINUATION 또는 SEPARATE\n\n"
        f"[메시지A]\n{(prev_text or '')[:600]}\n\n[메시지B]\n{(cur_text or '')[:600]}"
    )
    try:
        raw = _call_claude_code(prompt)
        hits = re.findall(r"\b(CONTINUATION|SEPARATE)\b", raw)
        if not hits:
            return None
        return hits[-1] == "CONTINUATION"
    except Exception:
        return None


def _joins_prev(channel: str | None, msg_id: int, gap: float,
                prev_text: str, cur_text: str) -> bool:
    """이 메시지가 직전 메시지의 연장인지 — 캐시 → 판정 → 시간 fallback 순."""
    if gap > JUDGE_WINDOW_SEC:
        return False
    if channel:
        conn = get_connection()
        row = conn.execute(
            "SELECT joins_prev FROM telegram_group_marks WHERE channel=? AND msg_id=?",
            (channel, msg_id)).fetchone()
        conn.close()
        if row is not None:
            return bool(row["joins_prev"])
    verdict = _judge_continuation(prev_text, cur_text, gap)
    model = "judge"
    if verdict is None:
        verdict = gap <= GROUP_GAP_SEC
        model = "gap"
    if channel:
        conn = get_connection()
        conn.execute(
            "INSERT OR REPLACE INTO telegram_group_marks (channel, msg_id, joins_prev, model) "
            "VALUES (?, ?, ?, ?)", (channel, msg_id, int(verdict), model))
        conn.commit()
        conn.close()
    return verdict


def group_bursts(messages: list[dict], channel: str | None = None) -> list[list[dict]]:
    """메시지들을 연속 타이핑 묶음으로 그룹핑 (msg_id 오름차순 입력 가정 안 함).

    channel을 주면 판정을 캐시한다 (없으면 시간 규칙만 — 테스트/드라이런용).
    """
    msgs = sorted(messages, key=lambda m: int(str(m.get("message_id") or 0) or 0))
    groups: list[list[dict]] = []
    for m in msgs:
        dt = _parse_dt(m.get("date", ""))
        if groups and len(groups[-1]) < MAX_GROUP:
            prev = groups[-1][-1]
            prev_dt = _parse_dt(prev.get("date", ""))
            if dt and prev_dt:
                gap = (dt - prev_dt).total_seconds()
                if 0 <= gap and (
                    (channel and _joins_prev(channel, int(str(m.get("message_id") or 0) or 0),
                                             gap, prev.get("content", ""), m.get("content", "")))
                    or (not channel and gap <= GROUP_GAP_SEC)
                ):
                    groups[-1].append(m)
                    continue
        groups.append([m])
    return groups


def _existing_images(channel: str, msg_id: str, urls: list[str]) -> list[str]:
    """예전에 내려받아 둔 이미지 파일(/media 기준 상대경로) — 새로 받지는 않는다."""
    rels = [f"telegram/{channel}_{msg_id}_{i}.jpg" for i in range(len(urls))]
    return [r for r in rels if (MEDIA_PATH / r).exists()]


class TelegramConnector:
    source_type = "telegram"

    def __init__(self, channels: list[str] | None = None):
        self._channels = channels

    def discover(self) -> list[SourceRef]:
        if self._channels is not None:
            return [SourceRef(key=c) for c in self._channels]
        conn = get_connection()
        rows = conn.execute(
            # is_active=개인 노출(뮤트), collect_enabled=수집 자체 (D-126) — 축이 다르다
            "SELECT channel_name FROM telegram_channels WHERE COALESCE(collect_enabled,1)=1"
        ).fetchall()
        conn.close()
        return [SourceRef(key=r["channel_name"]) for r in rows]

    def fetch(self, ref: SourceRef) -> list[RawDoc]:
        channel = ref.key
        messages = scrape_channel(channel)
        docs = []
        for group in group_bursts(messages, channel=channel):
            head = group[0]
            head_id = head.get("message_id", "")
            contents, images, slots = [], [], []
            for m in group:
                text = (m.get("content") or "").strip()
                if text:
                    contents.append(m["content"])
                mid = m.get("message_id", "")
                urls = m.get("images", [])
                images += _existing_images(channel, mid, urls)
                slots.append((m["content"] if text else None,
                              [{"key": f"telegram/{channel}_{mid}_{i}", "url": u} for i, u in enumerate(urls)]))
            content = "\n\n".join(contents)
            notes = image_reading.read_images(
                [{**it, "context": content} for _, its in slots for it in its],
                published_at=head.get("date", ""), source="증권·산업 리서치 텔레그램 글",
                source_url=head.get("link", ""))
            pieces = []
            for text, its in slots:
                if text:
                    pieces.append(text)
                pieces += [n for n in (notes.get(it["key"]) for it in its) if n]
            markdown = "\n\n".join(pieces)
            title = content.split("\n", 1)[0][:80] if content else (
                f"[이미지] {channel} #{head_id}" if any(its for _, its in slots) else "")
            docs.append(RawDoc(
                source_type="telegram",
                source_id=f"{channel}/{head_id}",
                title=title,
                url=head.get("link", ""),
                published_at=head.get("date", ""),
                raw_content=content,
                kind="text",
                images=images,
                markdown=markdown if markdown != content else None,
            ))
        return docs
