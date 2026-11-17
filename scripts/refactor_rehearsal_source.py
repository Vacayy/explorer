"""The 'MacBook latest' stand-in of the sync rehearsal (agent-whiteboard sync-rehearsal-runbook.md R0).

Applies the runbook's synthetic changes to an APFS clone of the 11-14 backup (never the backup itself), so that the
rehearsal's source replacement is not an empty operation:
  documents: three new (blog, telegram, youtube), one existing changed (body and summary), one deleted;
  an entity alias added; user records: a portfolio transaction and a follow added, a saved item deleted;
  a row in a table the base snapshot had empty (proxy_boards).
Every synthetic text says so ('[리허설 합성]'). Writes the manifest of touched ids beside the file and prints only ids
and counts (no content).

  python3 scripts/refactor_rehearsal_source.py <clone.db>
"""
import hashlib
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

MARK = '[리허설 합성]'


def apply(path):
    path = Path(path)
    if path.name == 'stock_explorer.db' or 'staging' in path.parts:
        raise SystemExit('Refusing: give the rehearsal clone, never the backup')
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA foreign_keys=ON')
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    run = uuid.uuid4().hex[:8]
    out = {'run': run, 'at': now}
    with conn:
        added = []
        for kind in ('blog', 'telegram', 'youtube'):
            body = f'{MARK} {kind} 문서 {run}. 동기화 리허설의 새 문서 대역입니다.'
            added.append(conn.execute(
                'INSERT INTO raw_documents (source_type, source_id, title, url, published_at, raw_content, markdown, '
                'content_hash) VALUES (?,?,?,?,?,?,?,?)',
                (kind, f'rehearsal-{run}-{kind}', f'{MARK} {kind} {run}', f'https://rehearsal.invalid/{run}/{kind}', now,
                 body, body, hashlib.sha256(body.encode()).hexdigest())).lastrowid)
        out['documents_added'] = added
        changed = conn.execute('SELECT d.id FROM raw_documents d JOIN enrichments e ON e.doc_id = d.id '
                               "WHERE d.source_type = 'blog' ORDER BY d.id DESC LIMIT 1").fetchone()[0]
        conn.execute("UPDATE raw_documents SET markdown = coalesce(markdown,'') || ?, raw_content = coalesce(raw_content,'') || ? "
                     'WHERE id = ?', (f'\n\n{MARK} 본문 변경 {run}', f'\n\n{MARK} 본문 변경 {run}', changed))
        conn.execute("UPDATE enrichments SET summary = coalesce(summary,'') || ? WHERE doc_id = ?", (f' {MARK} 요약 변경', changed))
        out['document_changed'] = changed
        deleted = conn.execute("SELECT id FROM raw_documents WHERE source_type = 'telegram' AND id NOT IN (?,?,?) "
                               'ORDER BY id LIMIT 1 OFFSET 100', added).fetchone()[0]
        conn.execute('DELETE FROM raw_documents WHERE id = ?', (deleted,))
        out['document_deleted'] = deleted
        entity = conn.execute("SELECT entity_id FROM entity_keywords WHERE status = 'active' ORDER BY entity_id LIMIT 1").fetchone()[0]
        out['alias_added'] = {'entity_id': entity, 'id': conn.execute(
            'INSERT INTO entity_keywords (entity_id, keyword) VALUES (?, ?)', (entity, f'리허설합성{run}')).lastrowid}
        group = conn.execute("SELECT id FROM stock_groups WHERE kind = 'portfolio' ORDER BY id LIMIT 1").fetchone()[0]
        out['transaction_added'] = conn.execute(
            "INSERT INTO portfolio_transactions (group_id, trade_date, kind, stock_code, amount, price, note) "
            "VALUES (?, ?, 'buy', '005930', 1, 1, ?)", (group, now[:10], MARK)).lastrowid
        follow = conn.execute('SELECT id FROM entities WHERE id NOT IN (SELECT entity_id FROM follows) ORDER BY id LIMIT 1').fetchone()[0]
        out['follow_added'] = {'entity_id': follow, 'id': conn.execute('INSERT INTO follows (entity_id) VALUES (?)', (follow,)).lastrowid}
        saved = conn.execute('SELECT id FROM saved_items ORDER BY id DESC LIMIT 1').fetchone()[0]
        conn.execute('DELETE FROM saved_items WHERE id = ?', (saved,))
        out['saved_deleted'] = saved
        out['proxy_board_added'] = conn.execute('INSERT INTO proxy_boards (name, description) VALUES (?, ?)',
                                                (f'{MARK} 보드 {run}', MARK)).lastrowid
    out['integrity'] = conn.execute('PRAGMA integrity_check').fetchone()[0]
    out['counts'] = {t: conn.execute(f'SELECT count(*) FROM {t}').fetchone()[0]
                     for t in ('raw_documents', 'entity_keywords', 'portfolio_transactions', 'follows', 'saved_items', 'proxy_boards')}
    conn.close()
    (path.parent / 'synthetic-changes.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out


if __name__ == '__main__':
    print(json.dumps(apply(sys.argv[1]), ensure_ascii=False))
