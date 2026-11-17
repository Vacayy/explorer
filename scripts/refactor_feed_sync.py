"""Append one published feed document into an isolated collector work copy.

Run only after a consistent backup and with every collector stopped. Never replaces
existing rows: any unexpected divergence refuses the entire SQLite transaction.
"""
import sqlite3

TABLES = ('raw_documents', 'enrichments', 'entity_links', 'entities', 'entity_keywords', 'entity_relations')


def append_group_marks(src, dst):
    """Append only identical-or-new grouping marks within the caller's transaction."""
    columns = [r[1] for r in src.execute('PRAGMA table_info(telegram_group_marks)')]
    other = [r[1] for r in dst.execute('PRAGMA table_info(telegram_group_marks)')]
    if not columns and not other:
        return 0
    if columns != other or not {'channel', 'msg_id'}.issubset(columns):
        raise ValueError('Grouping mark schemas differ')
    positions = (columns.index('channel'), columns.index('msg_id'))
    key = lambda row: tuple(row[i] for i in positions)  # noqa: E731
    left = iter(src.execute('SELECT * FROM telegram_group_marks ORDER BY channel,msg_id'))
    right = iter(dst.execute('SELECT * FROM telegram_group_marks ORDER BY channel,msg_id'))
    a, b, new = next(left, None), next(right, None), []
    while a is not None or b is not None:
        if b is None or (a is not None and key(a) < key(b)):
            new.append(a)
            a = next(left, None)
        elif a is None or key(b) < key(a):
            raise ValueError('Target has a grouping mark missing from feed')
        else:
            if a != b:
                raise ValueError('Existing grouping marks differ')
            a, b = next(left, None), next(right, None)
    dst.executemany('INSERT INTO telegram_group_marks VALUES (' + ','.join('?' for _ in columns) + ')', new)
    return len(new)


def sync(source_path, target_path, *, allow_noop=False):
    src = sqlite3.connect(f'file:{source_path}?mode=ro', uri=True)
    dst = sqlite3.connect(target_path)
    try:
        src.execute('BEGIN')
        dst.execute('BEGIN IMMEDIATE')
        floor_tables = (('document_floor', 'raw_documents'), ('entity_floor', 'entities'),
                        ('keyword_floor', 'entity_keywords'), ('relation_floor', 'entity_relations'))
        for name, table in floor_tables:
            for conn in (src, dst):
                row = conn.execute('SELECT value FROM candidate_publish_floor WHERE name=?', (name,)).fetchone()
                maximum = conn.execute(f'SELECT COALESCE(max(id),0) FROM "{table}"').fetchone()[0]
                if row is None or row[0] != maximum:
                    raise ValueError('A work copy contains unpublished rows or lacks its publication floor')
        additions = {}
        for table in TABLES:
            source_columns = [r[1] for r in src.execute(f'PRAGMA table_info("{table}")')]
            target_columns = [r[1] for r in dst.execute(f'PRAGMA table_info("{table}")')]
            if not source_columns or source_columns != target_columns or source_columns[0] != 'id':
                raise ValueError('Work schemas differ')
            source = iter(src.execute(f'SELECT * FROM "{table}" ORDER BY id'))
            target = iter(dst.execute(f'SELECT * FROM "{table}" ORDER BY id'))
            a, b = next(source, None), next(target, None)
            new = []
            while a is not None or b is not None:
                if b is None or (a is not None and a[0] < b[0]):
                    new.append(a)
                    a = next(source, None)
                elif a is None or b[0] < a[0]:
                    raise ValueError('Target contains rows absent from feed work')
                else:
                    if a != b:
                        raise ValueError('An existing row differs between work copies')
                    a, b = next(source, None), next(target, None)
            additions[table] = (source_columns, new)
        documents = additions['raw_documents'][1]
        if allow_noop and not any(rows for _, rows in additions.values()):
            if append_group_marks(src, dst):
                if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Target integrity check failed')
                dst.commit()
            else:
                dst.rollback()
            return {'raw_documents': 0, 'enrichments': 0, 'entity_links': 0}
        if not 1 <= len(documents) <= 5:
            raise ValueError('Expected one to five documents')
        doc_ids = {row[0] for row in documents}
        for table in ('enrichments', 'entity_links'):
            cols, rows = additions[table]
            if any(row[cols.index('doc_id')] not in doc_ids for row in rows):
                raise ValueError('An added row belongs to another document')
        enrichment_cols, enrichments = additions['enrichments']
        if len(enrichments) != len(documents) or {row[enrichment_cols.index('doc_id')] for row in enrichments} != doc_ids:
            raise ValueError('Expected one completed enrichment per document')
        link_columns, links = additions['entity_links']
        linked = {row[link_columns.index('entity_id')] for row in links}
        relation_columns, relations = additions['entity_relations']
        if any(row[relation_columns.index('source_doc_id')] not in doc_ids for row in relations):
            raise ValueError('An added relation belongs to another document')
        for row in relations:
            linked.update((row[relation_columns.index('src_id')], row[relation_columns.index('dst_id')]))
        keyword_columns, keywords = additions['entity_keywords']
        linked.update(row[keyword_columns.index('entity_id')] for row in keywords)
        if any(row[0] not in linked for row in additions['entities'][1]):
            raise ValueError('An added entity is not connected to the new documents')
        for table in ('raw_documents', 'enrichments', 'entities', 'entity_keywords', 'entity_relations', 'entity_links'):
            cols, rows = additions[table]
            dst.executemany(f'INSERT INTO "{table}" VALUES ({",".join("?" for _ in cols)})', rows)
        append_group_marks(src, dst)
        dst.execute("UPDATE candidate_publish_floor SET value=? WHERE name='document_floor'", (max(doc_ids),))
        for table, floor in (('entities', 'entity_floor'), ('entity_keywords', 'keyword_floor'),
                             ('entity_relations', 'relation_floor')):
            if additions[table][1]:
                dst.execute('UPDATE candidate_publish_floor SET value=? WHERE name=?', (additions[table][1][-1][0], floor))
        if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Target integrity check failed')
        dst.commit()
        return {table: len(additions[table][1]) for table in ('raw_documents', 'enrichments', 'entity_links')}
    except BaseException:
        dst.rollback()
        raise
    finally:
        src.close()
        dst.close()


if __name__ == '__main__':
    print('work rows appended:', sync('/feed/work.db', '/target/work.db', allow_noop=True))
