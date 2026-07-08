"""keyword 티어로 enrich된 기존 문서를 LLM으로 재처리 (1회성 백필).

ENRICH_ENGINE=claude-code 또는 ANTHROPIC_API_KEY 설정 후 실행.
문서당 ~10초(claude-code) — 백그라운드 실행 권장.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db
from pipeline.enrich import llm_engine
from pipeline.store import reenrich_document


def main():
    init_db()
    engine = llm_engine()
    if not engine:
        print("LLM 엔진 없음 — .env에 ENRICH_ENGINE=claude-code 또는 ANTHROPIC_API_KEY 설정 필요")
        sys.exit(1)
    print(f"engine: {engine}")

    conn = get_connection()
    todo = [r["id"] for r in conn.execute("""
        SELECT rd.id FROM raw_documents rd
        LEFT JOIN enrichments en ON en.doc_id = rd.id
        WHERE en.model = 'keyword' OR en.id IS NULL
        ORDER BY rd.id
    """).fetchall()]
    conn.close()
    print(f"대상: {len(todo)}건")

    ok = fail = 0
    for i, doc_id in enumerate(todo):
        model = reenrich_document(doc_id)
        if model and model != "keyword":
            ok += 1
        else:
            fail += 1  # LLM 실패 → keyword fallback으로 저장됨 (다음 실행에서 재시도됨)
        if (i + 1) % 10 == 0:
            print(f"  진행 {i + 1}/{len(todo)} (성공 {ok}, fallback {fail})")

    print(f"완료: LLM {ok}건, keyword fallback {fail}건")


if __name__ == "__main__":
    main()
