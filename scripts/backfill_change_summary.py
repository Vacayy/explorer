"""바뀐 서사 change_summary 백필 — change_summary가 없는 최근 버전만 (2026-10-17, 일회성).

새 버전은 서사 생성 호출이 change_summary를 같이 내지만(narrative._change_block), 그 전에 만든 버전은
고리 나열식 드리프트 문장밖에 없어 '서사가 어떻게 옮겨 갔나'로 읽히지 않았다. 직전 버전과 이번 버전의
제목·3줄 요약만 주고 haiku 1콜/버전으로 같은 규칙의 1~2문장을 받는다.

  python scripts/backfill_change_summary.py --days 7 [--dry-run]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection  # noqa: E402
from pipeline.enrich import _call_claude_code  # noqa: E402
from pipeline.narrative import _summary, normalize_change_summary  # noqa: E402


def prompt(prev, cur) -> str:
    return (
        "같은 주제의 서사가 새 버전으로 바뀌었다. 직전 서사에서 이번 서사로 **이야기의 무게가 어떻게 옮겨 갔는지** "
        "한국어 평서문 1~2문장, 80자 이내로 써라. 인과 고리(A→B)를 나열하지 말고 서사의 핵심 이동만 써라"
        "(예: '공급 부족 이야기에서 장기 계약·사이클 장기화 이야기로 무게가 옮겨 갔다'). "
        "큰 변화가 없으면 '큰 줄기는 그대로이고 ~가 더해졌다'처럼 써라. 문장만 출력하라.\n\n"
        f"[직전 v{prev['version']}] 제목: {prev['title'] or '(없음)'}\n3줄 요약: {_summary(prev['body']) or '(없음)'}\n\n"
        f"[이번 v{cur['version']}] 제목: {cur['title'] or '(없음)'}\n3줄 요약: {_summary(cur['body']) or '(없음)'}\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    conn = get_connection()
    rows = conn.execute("""
        SELECT n.id, n.topic, n.version, n.title, n.body FROM narratives n
        WHERE n.created_at >= datetime('now', ?) AND (n.change_summary IS NULL OR n.change_summary = '')
          AND COALESCE(n.kind, 'topic') = 'topic' ORDER BY n.created_at DESC""", (f"-{args.days} days",)).fetchall()
    done = failed = 0
    for cur in rows:
        prev = conn.execute("SELECT version, title, body FROM narratives WHERE topic=? AND version<? "
                            "ORDER BY version DESC LIMIT 1", (cur["topic"], cur["version"])).fetchone()
        if not prev:
            continue
        if args.dry_run:
            print(f"[dry] {cur['topic']} v{prev['version']}→v{cur['version']}")
            continue
        try:
            text = normalize_change_summary(_call_claude_code(prompt(prev, cur), model="haiku", timeout=120))
        except Exception as e:  # noqa: BLE001 — 한 건 실패로 멈추지 않고 사유를 남긴다
            failed += 1
            print(f"[fail] {cur['topic']} v{cur['version']}: {type(e).__name__}: {str(e)[:120]}")
            continue
        if text:
            conn.execute("UPDATE narratives SET change_summary=? WHERE id=?", (text, cur["id"]))
            conn.commit()
            done += 1
            print(f"[ok] {cur['topic']} v{cur['version']}: {text}")
    conn.close()
    print(f"[backfill] 대상 {len(rows)} · 저장 {done} · 실패 {failed}")
    return 1 if failed and not done else 0


if __name__ == "__main__":
    sys.exit(main())
