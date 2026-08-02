"""텔레그램 답글 인용문 잘림 백필 (D-103).

구 스크래퍼가 답글 메시지의 인용문(잘린 '…')을 본문으로 저장한 문제 교정.
markdown이 '…'로 끝나는 짧은(<500자) 텔레그램 문서를 개별 임베드에서 js-message_text 전문으로
재수집 → 바뀌면 markdown·title 갱신 + reenrich_document(entity_links 재생성).

멀티메시지 버스트 오손 방지: '…로 끝 + 짧음'(단일 답글 인용문 시그니처)만 대상, 새 본문이 더 짧으면 skip.
기본 dry-run(계획만). --apply로 실제 갱신. --limit N.

사용법: python scripts/backfill_telegram_truncated.py [--limit 200] [--apply]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection
from services.telegram_service import fetch_message_body
from pipeline.store import reenrich_document


def _parse(url: str):
    # https://t.me/{channel}/{msg_id}
    tail = (url or "").split("t.me/", 1)[-1].strip("/")
    parts = tail.split("/")
    return (parts[0], parts[1]) if len(parts) >= 2 and parts[1].isdigit() else (None, None)


def main():
    apply = "--apply" in sys.argv
    limit = 500
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    conn = get_connection()
    rows = conn.execute(
        "SELECT id, url, markdown FROM raw_documents WHERE source_type='telegram' "
        "AND trim(markdown) LIKE '%…' AND length(markdown) < 500 ORDER BY id DESC LIMIT ?",
        (limit,)).fetchall()
    conn.close()
    print(f"[backfill] 후보 {len(rows)}건 (…로 끝·<500자) · mode={'APPLY' if apply else 'DRY-RUN'}")

    fixed = skipped = failed = 0
    for r in rows:
        channel, msg_id = _parse(r["url"])
        if not channel:
            failed += 1
            continue
        body = fetch_message_body(channel, msg_id)
        stored = (r["markdown"] or "").strip()
        if not body or body.strip() == stored:
            skipped += 1
            continue
        if len(body.strip()) < len(stored):   # 새 본문이 더 짧으면 버스트 오손 위험 → skip
            skipped += 1
            continue
        fixed += 1
        print(f"  #{r['id']} {channel}/{msg_id}: {len(stored)}→{len(body.strip())}자  {body.strip()[:44]!r}")
        if apply:
            title = body.strip().split("\n", 1)[0][:80]
            conn = get_connection()
            conn.execute("UPDATE raw_documents SET markdown=?, title=? WHERE id=?",
                         (body.strip(), title, r["id"]))
            conn.commit()
            conn.close()
            reenrich_document(r["id"])   # entity_links 재생성

    print(f"[backfill] 갱신 {fixed} · skip {skipped} · 실패 {failed}"
          + ("" if apply else "  (dry-run — --apply로 실제 반영)"))


if __name__ == "__main__":
    main()
