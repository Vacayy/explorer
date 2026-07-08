"""vault 동기화 — 소유권 분할 + 단방향 흐름 2개 (docs/specs/hypothesis-vault.md).

  python scripts/vault_sync.py --export   # 기계→사람: DB → vault/entities/*.md 투영 (덮어씀)
  python scripts/vault_sync.py --notes    # 사람→기계: vault/notes/*.md → 척추 흡수
  python scripts/vault_sync.py            # 둘 다

- vault/entities/ 는 자동 생성 파일 — 수정해도 다음 export에서 덮어쓴다.
- vault/notes/ 는 사람이 원본 소유 — 여기 마크다운이 진실이고 DB는 인덱스.
- Obsidian은 이 폴더를 여는 선택적 뷰어일 뿐 (종속 없음).
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from config import VAULT_PATH
from database import get_connection, init_db


def _safe_filename(name: str) -> str:
    return re.sub(r'[/\\:*?"<>|]', "_", name).strip() or "_"


def export_entities():
    """활동이 있는 엔티티(언급·신호·왓치리스트)만 도시에 페이지로 투영."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT DISTINCT e.id, e.type, e.name, e.aliases
        FROM entities e
        WHERE e.id IN (SELECT entity_id FROM entity_links)
           OR e.id IN (SELECT entity_id FROM signals)
           OR e.aliases IN (SELECT stock_code FROM watchlist)
    """).fetchall()

    out_dir = VAULT_PATH / "entities"
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for e in rows:
        sectors = [r["name"] for r in conn.execute("""
            SELECT e2.name FROM entity_relations r JOIN entities e2 ON r.dst_id=e2.id
            WHERE r.src_id=? AND r.rel_type='MEMBER_OF'""", (e["id"],))]
        signals = conn.execute("""
            SELECT signal_type, date, payload_json FROM signals
            WHERE entity_id=? ORDER BY date DESC LIMIT 5""", (e["id"],)).fetchall()
        docs = conn.execute("""
            SELECT rd.title, rd.url, rd.published_at, rd.source_type
            FROM entity_links el JOIN raw_documents rd ON el.doc_id=rd.id
            WHERE el.entity_id=? AND rd.source_type != 'note'
            ORDER BY rd.published_at DESC LIMIT 10""", (e["id"],)).fetchall()

        lines = [
            "---",
            f"type: {e['type']}",
            *( [f"stock_code: \"{e['aliases']}\""] if e["aliases"] else [] ),
            "generated: true   # 자동 생성 — 수정 금지 (다음 export에서 덮어씀)",
            "---",
            "",
            f"# {e['name']}",
            "",
        ]
        if sectors:
            lines += [f"섹터: {', '.join(f'[[{s}]]' for s in sectors)}", ""]
        if signals:
            lines += ["## 신호", ""]
            for s in signals:
                p = json.loads(s["payload_json"] or "{}")
                if s["signal_type"] == "mention_surge":
                    detail = f"7일 {p.get('count_7d')}회 언급 (직전 {p.get('baseline_7d')}회)"
                elif s["signal_type"] == "high_52w":
                    detail = f"고가 {p.get('high'):,} — 전고점 {p.get('prior_high_52w'):,} 경신 (+{p.get('breakout_pct')}%)"
                else:
                    detail = s["signal_type"]
                lines.append(f"- {s['date']} **{s['signal_type']}** — {detail}")
            lines.append("")
        if docs:
            lines += ["## 최근 언급", ""]
            for d in docs:
                date = (d["published_at"] or "")[:10]
                lines.append(f"- {date} [{d['title']}]({d['url']}) ({d['source_type']})")
            lines.append("")

        (out_dir / f"{_safe_filename(e['name'])}.md").write_text("\n".join(lines), encoding="utf-8")
        n += 1
    conn.close()
    print(f"[export] entities → {out_dir} ({n}개 페이지)")


def ingest_notes():
    from pipeline.connectors.notes import NoteConnector
    from pipeline.runner import run_source

    (VAULT_PATH / "notes").mkdir(parents=True, exist_ok=True)
    stats = run_source(NoteConnector())
    print(f"[notes] {stats}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--notes", action="store_true")
    args = parser.parse_args()

    init_db()
    if not args.export and not args.notes:
        args.export = args.notes = True
    if args.notes:
        ingest_notes()
    if args.export:
        export_entities()
