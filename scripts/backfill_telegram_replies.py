"""텔레그램 답글 인용문 오손 전면 백필 (D-103 후속).

'…' 유무·길이와 무관하게, 개별 메시지의 인용문(reply)과 본문(body)을 대조해
저장분이 **인용문과 일치**하면(=본문 대신 잘린 인용문을 저장) 본문으로 교체 + 재enrich.
정밀 판별(reply==stored)이라 오탐 없음(답글 아니면 reply=None → skip). 짧은(<=300) 텔레그램 전수 스캔.

스캔(네트워크)은 병렬, 교체+재enrich(LLM)는 순차. 재실행 안전(남은 오손만 처리).
사용법: python scripts/backfill_telegram_replies.py [--limit N] [--apply]  (기본 dry-run)
"""
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection
from services.telegram_service import fetch_message_parts
from pipeline.store import reenrich_document


def _parse(url: str):
    tail = (url or "").split("t.me/", 1)[-1].strip("/").split("/")
    return (tail[0], tail[1]) if len(tail) >= 2 and tail[1].isdigit() else (None, None)


def _norm(s: str) -> str:
    return " ".join((s or "").split())


def _detect(row):
    """오손이면 (id, body) 반환, 아니면 None. (병렬 실행 — 네트워크만)"""
    channel, msg_id = _parse(row["url"])
    if not channel:
        return None
    p = fetch_message_parts(channel, msg_id)
    st, rep, bod = _norm(row["markdown"]), _norm(p.get("reply")), _norm(p.get("body"))
    if not (rep and bod) or st == bod:
        return None
    # 저장분이 인용문과 같다(또는 인용문의 앞부분과 일치) = 본문 대신 인용문을 저장한 것
    if st == rep or (len(st) >= 20 and rep.startswith(st[:120])):
        return (row["id"], p["body"])
    return None


def main():
    apply = "--apply" in sys.argv
    limit = 5000
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    conn = get_connection()
    rows = conn.execute(
        "SELECT id, url, markdown FROM raw_documents WHERE source_type='telegram' "
        "AND length(markdown)<=300 AND trim(markdown) NOT LIKE '%…' ORDER BY id DESC LIMIT ?",
        (limit,)).fetchall()
    conn.close()
    print(f"[replies] 스캔 후보 {len(rows)}건 (짧은 non-… 텔레그램) · mode={'APPLY' if apply else 'DRY-RUN'}")

    with ThreadPoolExecutor(max_workers=12) as ex:
        found = [r for r in ex.map(_detect, rows) if r]
    print(f"[replies] 오손 확정 {len(found)}건")

    for doc_id, body in found:
        body = body.strip()
        print(f"  #{doc_id}: → 본문 {len(body)}자  {body[:44]!r}")
        if apply:
            conn = get_connection()
            conn.execute("UPDATE raw_documents SET markdown=?, title=? WHERE id=?",
                         (body, body.split("\n", 1)[0][:80], doc_id))
            conn.commit()
            conn.close()
            reenrich_document(doc_id)

    print(f"[replies] {'교체+재enrich ' + str(len(found)) if apply else 'dry-run — --apply로 반영'}")


if __name__ == "__main__":
    main()
