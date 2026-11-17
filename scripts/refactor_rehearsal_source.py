"""The 'MacBook latest' stand-in of the sync rehearsal (agent-whiteboard sync-rehearsal-runbook.md R0).

Applies the runbook's synthetic changes to an APFS clone of the 11-14 backup (never the backup itself), so that the
rehearsal's source replacement is not an empty operation:
  documents: three new (blog, telegram, youtube), one existing changed (body and summary), one deleted;
  an entity alias added; user records: a portfolio transaction and a follow added, a saved item deleted;
  a row in a table the base snapshot had empty (proxy_boards).
With --week, it also adds a real-scale week of change (architect #3 6942322316 condition 2), measured from the
11-14 copy's last week: every document fetched in that week again as a new one (its enrichment and entity links with
it, dates seven days later), 300 existing documents revised, 50 entity aliases and the relations of that week again,
and the last five trading days of prices again seven days later.
Every synthetic text says so ('[리허설 합성]'). Writes the manifest of touched ids beside the file and prints only ids
and counts (no content).

  python3 scripts/refactor_rehearsal_source.py <clone.db> [--week]
"""
import hashlib
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

MARK = '[리허설 합성]'


def week(conn, run, now):
    """A week of change at the scale the 11-14 copy shows (documents, revisions, graph, prices)."""
    out = {}
    since = conn.execute("SELECT date(max(fetched_at), '-7 days') FROM raw_documents").fetchone()[0]
    docs = conn.execute('SELECT id FROM raw_documents WHERE fetched_at >= ? ORDER BY id', (since,)).fetchall()
    mapping = {}
    for (old,) in docs:
        mapping[old] = conn.execute(
            "INSERT INTO raw_documents (source_type, source_id, title, url, published_at, fetched_at, raw_content, markdown, "
            "content_hash, media_json) SELECT source_type, 'rehearsal-' || ? || '-' || source_id, ? || ' ' || coalesce(title,''), "
            "url, datetime(published_at, '+7 days'), datetime(fetched_at, '+7 days'), raw_content, markdown, content_hash, "
            'media_json FROM raw_documents WHERE id = ?', (run, MARK, old)).lastrowid
    for old, new in mapping.items():
        conn.execute("INSERT INTO enrichments (doc_id, summary, sentiment, model, content_hash, enriched_at, time_orientation, "
                     "reference_period) SELECT ?, summary, sentiment, model, content_hash, datetime(enriched_at, '+7 days'), "
                     'time_orientation, reference_period FROM enrichments WHERE doc_id = ?', (new, old))
        conn.execute('INSERT INTO entity_links (doc_id, entity_id, link_type, confidence) '
                     'SELECT ?, entity_id, link_type, confidence FROM entity_links WHERE doc_id = ?', (new, old))
    out['documents_added'] = len(mapping)
    revised = [row[0] for row in conn.execute(
        'SELECT d.id FROM raw_documents d JOIN enrichments e ON e.doc_id = d.id WHERE d.fetched_at < ? '
        'ORDER BY d.id DESC LIMIT 300', (since,))]
    for doc in revised:
        conn.execute("UPDATE raw_documents SET markdown = coalesce(markdown,'') || ? WHERE id = ?", (f'\n\n{MARK} 개정 {run}', doc))
        conn.execute("UPDATE enrichments SET summary = coalesce(summary,'') || ? WHERE doc_id = ?", (f' {MARK} 개정', doc))
    out['documents_revised'] = len(revised)
    entities = [row[0] for row in conn.execute("SELECT DISTINCT entity_id FROM entity_keywords WHERE status = 'active' "
                                               'ORDER BY entity_id LIMIT 50 OFFSET 1')]
    for entity in entities:
        conn.execute('INSERT INTO entity_keywords (entity_id, keyword) VALUES (?, ?)', (entity, f'리허설합성{run}-{entity}'))
    out['aliases_added'] = len(entities)
    out['relations_added'] = conn.execute(
        "INSERT OR IGNORE INTO entity_relations (src_id, dst_id, rel_type, epistemic_type, confidence, source_doc_id, valid_from, "
        "valid_to, created_at, mechanism, reference_period, time_orientation, narrative_id) SELECT src_id, dst_id, rel_type, "
        "epistemic_type, confidence, source_doc_id, date(valid_from, '+7 days'), valid_to, datetime(created_at, '+7 days'), "
        "mechanism, reference_period, "
        "time_orientation, narrative_id FROM entity_relations WHERE created_at >= ?", (since,)).rowcount
    days = [row[0] for row in conn.execute('SELECT DISTINCT trade_date FROM stock_prices ORDER BY trade_date DESC LIMIT 5')]
    out['prices_added'] = conn.execute(
        "INSERT OR IGNORE INTO stock_prices (stock_code, trade_date, open, high, low, close, volume, market_cap, shares, fetched_at) "
        "SELECT stock_code, date(trade_date, '+7 days'), open, high, low, close, volume, market_cap, shares, ? FROM stock_prices "
        f"WHERE trade_date IN ({','.join('?' * len(days))})", (now, *days)).rowcount
    out['price_dates'] = sorted(days)
    return out


def apply(path, scale_week=False):
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
        if scale_week:
            out['week'] = week(conn, run, now)
    out['integrity'] = conn.execute('PRAGMA integrity_check').fetchone()[0]
    out['counts'] = {t: conn.execute(f'SELECT count(*) FROM {t}').fetchone()[0]
                     for t in ('raw_documents', 'enrichments', 'entity_links', 'entity_keywords', 'entity_relations',
                               'stock_prices', 'portfolio_transactions', 'follows', 'saved_items', 'proxy_boards')}
    conn.close()
    (path.parent / 'synthetic-changes.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out


if __name__ == '__main__':
    print(json.dumps(apply(sys.argv[1], '--week' in sys.argv[2:]), ensure_ascii=False))
