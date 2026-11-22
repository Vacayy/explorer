"""이미지 해석 복구 — 맥미니 수집분 중 해석 없이 게시된 문서를 문서 ID로 골라 본문에 넣는다 (images 작업).

피드 수집은 COLLECT_FEED_STRICT_IMAGES로 새 이미지를 읽지 않고 게시한다(모델 예산 분리). 이 작업이 그 몫을
별도 예산으로 채운다. image_backfill과 다른 점:
- 대상은 게시일이 아니라 문서 ID(맥미니 대역 이상, 아직 처리 표시가 없는 것). 늦게 수집한 문서를 놓치지 않는다.
- 텔레그램은 게시 후 이미지 주소가 남지 않으므로 그 메시지 주변 공개 미리보기를 한 번 다시 받아, 저장된 묶음
  판정으로 같은 문서를 재구성한다. 원문이 저장본과 정확히 같을 때만 해석 줄을 넣는다(새 묶음 판정은 하지 않는다).
- 문서의 이미지가 전부 해석(또는 skip·필터·실패 확정)된 뒤에만 본문을 한 번 바꾸고 처리 표시를 남긴다.
  본문 변경의 PG 게시는 작업 경로(refactor_collect_job의 문서 변경 게시)가 같은 회차에 한다.
- reconcile: 실패한 회차가 작업본에만 남긴 본문을 projection(PG) 본문으로 되돌린다. 보류를 풀기 전에 쓴다.
"""
import sqlite3
import time

from database import get_connection
from pipeline import image_backfill as ib
from pipeline import image_reading as ir

BAND = 100_000_000                  # 맥미니가 발급한 문서 ID (pipeline.postgres_id_bands.BAND)
SOURCES = ("telegram", "blog", "scrap")
JOB = "image_recovery"
TELEGRAM_SOURCE = "증권·산업 리서치 텔레그램 글"


def candidates(conn, ids=None):
    cols = ("rd.id, rd.source_type, rd.source_id, rd.title, rd.url, rd.published_at, rd.raw_content, "
            "rd.markdown, rd.content_hash, rd.media_json")
    if ids:
        q = ",".join("?" * len(ids))
        return conn.execute(f"SELECT {cols} FROM raw_documents rd WHERE rd.id IN ({q}) ORDER BY rd.id", list(ids)).fetchall()
    q = ",".join("?" * len(SOURCES))
    return conn.execute(f"""
        SELECT {cols} FROM raw_documents rd
        WHERE rd.id >= ? AND rd.source_type IN ({q})
          AND rd.id NOT IN (SELECT doc_id FROM image_backfill_docs)
        ORDER BY rd.id""", (BAND, *SOURCES)).fetchall()


def telegram_messages(r, scrape=None):
    """그 문서의 첫 메시지 주변 공개 미리보기 한 페이지 → (채널, 메시지 | None, 건너뛴 이유 | None)."""
    from pipeline.connectors.telegram import MAX_GROUP
    if scrape is None:
        from services.telegram_service import scrape_channel as scrape
    channel, _, head = (r["source_id"] or "").rpartition("/")
    if not channel or not head.isdigit():
        return channel, None, "source id"
    messages = scrape(channel, before=int(head) + MAX_GROUP + 1)
    if not any(m.get("message_id") == head for m in messages):
        return channel, None, "message not on page"
    return channel, messages, None


def telegram_document(r, channel, messages, reader=None, only=()):
    """그 문서를 수집기와 같은 방식으로 다시 만든다 → (RawDoc | None, 이미지 항목, 건너뛴 이유 | None).
    reader가 없으면 이미지를 읽지 않고 항목만 모은다. reader는 only에 든 키(이 문서 몫)만 읽는다."""
    from pipeline.base import SourceRef
    from pipeline.connectors.telegram import TelegramConnector
    from pipeline.telegram_deferred import ExistingMarks, NeedsAnalysis, no_new_group_decision

    class StoredMarks(ExistingMarks):
        """저장된 묶음 판정만 쓴다. 판정이 없는 메시지(이 페이지에 함께 실린 미수집 메시지)는 이어지지 않는 것으로 본다 —
        이 문서의 구성원이 그렇게 잘려 나가면 원문이 저장본과 달라져 아래에서 건너뛴다."""
        def get(self, channel, msg_id):
            return super().get(channel, msg_id) or {"joins_prev": 0}

    calls = []          # 수집기는 묶음마다 한 번, 문서 순서대로 이미지 읽기를 부른다

    def collect(items, **kwargs):
        calls.append(items)
        mine = [it for it in items if it["key"] in only]
        return reader(mine, **kwargs) if reader and mine else {}

    connector = TelegramConnector(mark_store=StoredMarks(), judge=no_new_group_decision, image_reader=collect)
    try:
        docs = connector.fetch(SourceRef(key=channel, meta={"channel": channel, "messages": messages}))
    except NeedsAnalysis:
        return None, [], "new grouping decision"
    found = [i for i, d in enumerate(docs) if d.source_id == r["source_id"]]
    if not found or len(calls) != len(docs):
        return None, [], "group differs"
    doc = docs[found[0]]
    if (doc.raw_content or "") != (r["raw_content"] or ""):
        return None, [], "content differs"
    return doc, calls[found[0]][:ir.MAX_PER_DOC], None


def run(*, images: int, minutes: float = 8, ids=None, dry_run: bool = False, scrape=None) -> dict:
    """한 회차: 남은 이미지 예산(images)으로 문서 단위로 읽는다. 문서 하나의 미해석 이미지가 예산보다 많으면 거기서 멈춘다."""
    conn = get_connection()
    rows = candidates(conn, ids)
    conn.close()
    bf = ir.Backfill(calls_left=images, deadline=time.time() + minutes * 60, job=JOB)
    stats = {"candidates": len(rows), "changed": 0, "no_images": 0, "waiting": 0, "skipped": {}, "calls": 0,
             "stopped": None, "documents": []}

    def skip(r, reason):
        stats["skipped"][reason] = stats["skipped"].get(reason, 0) + 1
        stats["documents"].append({"id": r["id"], "result": f"skipped: {reason}"})

    def apply(r, md):
        conn = get_connection()
        try:
            changed = ib._apply(conn, r, md)      # 본문 교체 + 태그 해시 이월 + 처리 표시
        finally:
            conn.close()
        stats["changed"] += changed
        stats["documents"].append({"id": r["id"], "result": "changed" if changed else "unchanged"})

    with ir.backfill_mode(bf):
        for r in rows:
            if bf.offline:
                stats["stopped"] = "offline"
                break
            if time.time() >= bf.deadline:
                stats["stopped"] = "time"
                break
            if r["source_type"] == "telegram":
                channel, messages, reason = telegram_messages(r, scrape)
                if not reason:
                    _, items, reason = telegram_document(r, channel, messages)
                if reason:
                    skip(r, reason)
                    continue
                keys = [it["key"] for it in items]
            else:
                keys = ib._blog_keys(r)
            if not keys:
                if not dry_run:
                    ib._mark(r["id"])
                stats["no_images"] += 1
                stats["documents"].append({"id": r["id"], "result": "no images"})
                continue
            need = ir.unresolved(keys)
            if need > images:             # 한 회차 예산으로는 끝까지 못 읽는다 — 뒤 문서를 막지 않게 넘긴다
                skip(r, "more readings than a run")
                continue
            if need > bf.calls_left:
                stats["stopped"] = "calls"
                stats["documents"].append({"id": r["id"], "result": f"needs {need} readings"})
                break
            if dry_run:
                stats["documents"].append({"id": r["id"], "result": f"would read {need} of {len(keys)}"})
                bf.calls_left -= need
                continue
            before = bf.calls_left
            if r["source_type"] == "telegram":
                doc, _, reason = telegram_document(r, channel, messages, reader=ir.read_images, only=set(keys))
                if reason:
                    skip(r, reason)
                    continue
                md = doc.markdown or doc.raw_content
            else:
                md = ib._blog_md(r)
            stats["calls"] += before - bf.calls_left
            if ir.unresolved(keys):       # 재시도 가능한 실패가 남았다 — 본문은 그대로, 다음 회차에 다시
                stats["waiting"] += 1
                stats["documents"].append({"id": r["id"], "result": "waiting"})
                continue
            apply(r, md)
    return stats


def reconcile(projection_path: str = "/projection/current.db") -> dict:
    """작업본에만 있는 해석 줄(실패한 회차의 미게시 본문)을 projection 본문으로 되돌린다."""
    origin = sqlite3.connect(f"file:{projection_path}?mode=ro", uri=True)
    origin.row_factory = sqlite3.Row
    conn = get_connection()
    restored = []
    try:
        q = ",".join("?" * len(SOURCES))
        for r in conn.execute(f"SELECT id, markdown, content_hash FROM raw_documents WHERE id >= ? AND source_type IN ({q})",
                              (BAND, *SOURCES)).fetchall():
            o = origin.execute("SELECT markdown, content_hash FROM raw_documents WHERE id=?", (r["id"],)).fetchone()
            if o is None or o["content_hash"] == r["content_hash"] or ir.AI_PREFIX not in (r["markdown"] or ""):
                continue
            conn.execute("UPDATE raw_documents SET markdown=?, content_hash=? WHERE id=?", (o["markdown"], o["content_hash"], r["id"]))
            conn.execute("UPDATE OR IGNORE enrichments SET content_hash=? WHERE doc_id=? AND content_hash=?",
                         (o["content_hash"], r["id"], r["content_hash"]))
            conn.execute("DELETE FROM image_backfill_docs WHERE doc_id=?", (r["id"],))
            restored.append(r["id"])
        conn.commit()
    finally:
        conn.close()
        origin.close()
    return {"restored": restored}
