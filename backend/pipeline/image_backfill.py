"""이미지 해석 백로그 — 30분 체인에서 회차마다 조금씩 (docs/specs/image-reading.md §9).

랩탑이 켜져 있을 때만 도는 체인에 얹는다(야간 창은 PC가 꺼져 있으면 통째로 놓친다).
- 대상: 게시 7일 밖 문서(7일 안은 수집 경로가 처리). 텔레그램(media/의 옛 파일) 먼저, 블로그·스크랩 다음, 각각 최신순.
- 회차 상한: 호출 수·마감 시각. 문서 하나에 필요한 호출이 남은 예산보다 크면 이번 회차는 거기서 멈춘다.
- 문서의 이미지가 전부 해석(또는 skip·필터·실패 확정)된 뒤에만 본문을 한 번 바꾼다.
- 본문이 바뀌어도 태그는 다시 만들지 않는다: 기존 enrichment를 새 해시로 옮긴다(이미지 정보는 대개 본문과 겹친다).
  청크·검색은 해시 불일치로 다음 build_search_index에서 갱신된다 — 해석 줄이 검색에 들어가는 게 목적.
- 블로그는 이미지가 없어도 줄바꿈 정규화 소급을 같은 패스에서 한다(LLM 0). 문서마다 본문은 한 번만 바뀐다.
"""
import json
import sqlite3
import time

from config import MEDIA_PATH
from database import get_connection
from pipeline import image_reading as ir
from pipeline.base import RawDoc
from pipeline.normalize import to_markdown
from pipeline.store import _hash

MAX_AGE_SQL = f"datetime('now','-{ir.MAX_AGE_DAYS} days')"
MAX_DOCS = 300          # 회차당 처리 문서 상한 — 본문이 바뀐 문서의 검색 인덱스 갱신이 한 회차에 몰리지 않게


def _candidates(conn, source_types: tuple[str, ...], extra: str):
    q = ",".join("?" * len(source_types))
    return conn.execute(f"""
        SELECT rd.id, rd.source_type, rd.source_id, rd.title, rd.url, rd.published_at, rd.raw_content,
               rd.markdown, rd.content_hash, rd.media_json
        FROM raw_documents rd
        WHERE rd.source_type IN ({q}) AND {extra}
          AND rd.id NOT IN (SELECT doc_id FROM image_backfill_docs)
        ORDER BY rd.published_at DESC""", source_types).fetchall()


def _telegram_items(r) -> list[dict]:
    rels = [x for x in json.loads(r["media_json"] or "[]") if isinstance(x, str)]
    return [{"key": rel[:-4] if rel.endswith(".jpg") else rel, "url": "", "file": str(MEDIA_PATH / rel),
             "context": r["raw_content"] or "", "published_at": r["published_at"] or "", "source_url": r["url"] or ""}
            for rel in rels if (MEDIA_PATH / rel).exists()][:ir.MAX_PER_DOC]


def _blog_keys(r) -> list[str]:
    from bs4 import BeautifulSoup
    keys = []
    for img in BeautifulSoup(r["raw_content"] or "", "html.parser").find_all("img"):
        ref = ir.blog_image_ref(img)
        if ref:
            keys.append(ref[0])
    return keys[:ir.MAX_PER_DOC]


def _apply(conn, r, md: str) -> bool:
    """본문 교체 + 기존 태그를 새 해시로 이월(재태깅 없음). 바뀌었으면 True."""
    h = _hash(md)
    changed = h != r["content_hash"]
    if changed:
        conn.execute("UPDATE raw_documents SET markdown=?, content_hash=? WHERE id=?", (md, h, r["id"]))
        conn.execute("UPDATE OR IGNORE enrichments SET content_hash=? WHERE doc_id=? AND content_hash=?",
                     (h, r["id"], r["content_hash"]))
    conn.execute("INSERT OR REPLACE INTO image_backfill_docs (doc_id) VALUES (?)", (r["id"],))
    conn.commit()
    return changed


def _mark(doc_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("INSERT OR REPLACE INTO image_backfill_docs (doc_id) VALUES (?)", (doc_id,))
        conn.commit()
    finally:
        conn.close()


def _telegram_md(r, keys: list[str], notes: dict) -> str:
    # 옛 문서는 메시지 경계를 모른다 — 해석 줄은 글 끝에 이미지 순서대로
    return "\n\n".join([r["raw_content"]] * bool(r["raw_content"]) + [n for n in (notes.get(k) for k in keys) if n])


def _blog_md(r) -> str:
    return to_markdown(RawDoc(source_type=r["source_type"], source_id=r["source_id"], title=r["title"] or "",
                              url=r["url"] or "", published_at=r["published_at"] or "",
                              raw_content=r["raw_content"] or "", kind="html"))


def run(*, calls: int = 200, minutes: float = 8, dry_run: bool = False) -> dict:
    """순서: ① 7일 안 블로그·스크랩 중 수집 때 예산에 밀려 못 읽은 것 ② 텔레그램 옛 파일 ③ 블로그·스크랩 과거분.
    텔레그램 7일 안 문서는 수집 경로가 메시지 자리에 넣으므로 건드리지 않는다(블로그는 수집 경로와 결과가 같다)."""
    conn = get_connection()
    recent = f"rd.published_at >= {MAX_AGE_SQL}"
    groups = [
        ("blog", _candidates(conn, ("blog", "scrap"), recent)),
        ("telegram", _candidates(conn, ("telegram",), f"rd.media_json IS NOT NULL AND NOT ({recent})")),
        ("blog", _candidates(conn, ("blog", "scrap"), f"NOT ({recent})")),
    ]
    conn.close()

    if dry_run:
        tg = groups[1][1]
        return {"blog_recent_docs": len(groups[0][1]), "telegram_docs": len(tg),
                "telegram_calls": sum(ir.unresolved([i["key"] for i in _telegram_items(r)]) for r in tg),
                "blog_old_docs": len(groups[2][1]), "note": "블로그 호출 수는 본문 파싱이 필요해 실행 중에 센다"}

    bf = ir.Backfill(calls_left=calls, deadline=time.time() + minutes * 60)
    stats = {"docs": 0, "changed": 0, "waiting": 0, "calls": 0, "stopped": None}

    def finish(r, keys, md):
        if ir.unresolved(keys):          # 재시도 가능한 실패가 남았다 — 다음 회차에 다시, 본문은 그대로
            stats["waiting"] += 1
            return
        conn = get_connection()
        try:
            stats["changed"] += _apply(conn, r, md)
        finally:
            conn.close()
        stats["docs"] += 1

    def stop_reason(need: int) -> str | None:
        if bf.offline:
            return "offline"
        if stats["docs"] >= MAX_DOCS:
            return "docs"
        if time.time() >= bf.deadline:
            return "time"
        if need > bf.calls_left:
            return "calls"
        return None

    try:
        with ir.backfill_mode(bf):
            for source, rows in groups:
                if source == "blog":
                    for r in rows:
                        keys = _blog_keys(r)
                        if (reason := stop_reason(ir.unresolved(keys))):
                            stats["stopped"] = reason
                            break
                        before = bf.calls_left
                        md = _blog_md(r)
                        stats["calls"] += before - bf.calls_left
                        finish(r, keys, md)
                else:
                    # 텔레그램 문서는 대개 이미지 1장 — 여러 문서를 한 번에 읽어야 병렬 처리가 산다
                    batch: list[tuple] = []
                    for r in rows + [None]:
                        if r is not None:
                            items = _telegram_items(r)
                            keys = [i["key"] for i in items]
                            need = ir.unresolved(keys)
                            if not need and ir.AI_PREFIX in (r["markdown"] or ""):
                                _mark(r["id"])       # 수집 경로가 이미 메시지 자리에 넣은 문서 — 배치를 바꾸지 않는다
                                stats["docs"] += 1
                                continue
                            if sum(len(b[1]) for b in batch) + len(items) <= ir.MAX_PER_DOC:
                                batch.append((r, items, keys, need))
                                continue
                        if batch:
                            if (reason := stop_reason(sum(b[3] for b in batch))):
                                stats["stopped"] = reason
                                break
                            before = bf.calls_left
                            notes = ir.read_images([i for b in batch for i in b[1]], published_at="",
                                                   source="증권·산업 리서치 텔레그램 글")
                            stats["calls"] += before - bf.calls_left
                            for br, _, bkeys, _ in batch:
                                finish(br, bkeys, _telegram_md(br, bkeys, notes))
                        batch = [(r, items, keys, need)] if r is not None else []
                if stats["stopped"]:
                    break
    except sqlite3.OperationalError as e:
        if "locked" not in str(e):
            raise
        # PC가 깨어날 때 밀린 정기 작업이 한꺼번에 DB를 쓴다 — 이번 회차만 접고 다음 회차에 이어 간다
        stats["stopped"], stats["status"] = "locked", "partial"
    conn = get_connection()
    stats["remaining_docs"] = conn.execute(f"""
        SELECT COUNT(*) FROM raw_documents WHERE id NOT IN (SELECT doc_id FROM image_backfill_docs)
          AND ((source_type='telegram' AND media_json IS NOT NULL AND published_at < {MAX_AGE_SQL})
               OR source_type IN ('blog','scrap'))""").fetchone()[0]
    conn.close()
    return stats
