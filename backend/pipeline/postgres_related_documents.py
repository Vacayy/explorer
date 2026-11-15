"""Related-document support for a disposable PostgreSQL fixture generation."""
import math
import re
import sqlite3
import struct
import threading

from pipeline.search import RELATED_MIN_SIM, RELATED_PER_SOURCE, RELATED_RECENCY_W, _days, _norm_title
from pipeline.sources import source_names_from_rows


def capture_centroids(source, destination, generation):
    if not source.in_transaction or source.execute('PRAGMA query_only').fetchone()[0] != 1:
        raise ValueError('A query-only SQLite transaction is required')
    database, schema = destination.execute('SELECT current_database(), current_schema()').fetchone()
    if database != 'fixture' or not schema or not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', schema):
        raise ValueError('Only a disposable fixture is supported')
    if source.execute('SELECT count(*) FROM doc_centroid_vec v LEFT JOIN raw_documents d ON d.id=v.rowid WHERE d.id IS NULL').fetchone()[0]:
        raise ValueError('Centroid without source document')
    destination.execute('TRUNCATE document_centroids, document_centroid_metadata')
    count = 0
    with destination.cursor().copy('COPY document_centroids (document_id,embedding) FROM STDIN') as copy:
        for ident, blob in source.execute('SELECT rowid,embedding FROM doc_centroid_vec'):
            blob = bytes(blob)
            if len(blob) != 1536 or not all(math.isfinite(v[0]) for v in struct.iter_unpack('<f', blob)):
                raise ValueError('Invalid document centroid')
            copy.write_row((ident, blob))
            count += 1
    destination.execute('INSERT INTO document_centroid_metadata(generation_id,vector_count) VALUES (%s,%s)',
                        (generation, count))
    return count


class CentroidIndex:
    def __init__(self, generation, rows):
        import sqlite_vec
        self.generation = str(generation)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(':memory:', check_same_thread=False)
        try:
            self.db.enable_load_extension(True)
            sqlite_vec.load(self.db)
            self.db.enable_load_extension(False)
            self.db.execute('CREATE VIRTUAL TABLE doc_centroid_vec USING vec0(embedding float[384])')
            self.db.executemany('INSERT INTO doc_centroid_vec(rowid,embedding) VALUES (?,?)', rows)
        except Exception:
            self.db.close()
            raise

    @classmethod
    def from_postgres(cls, connection):
        database, schema = connection.execute('SELECT current_database(), current_schema()').fetchone()
        if database != 'fixture' or not schema or not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}', schema):
            raise ValueError('Only a disposable fixture is supported')
        if (connection.execute('SHOW transaction_isolation').fetchone()[0] not in ('repeatable read', 'serializable')
                or connection.execute('SHOW transaction_read_only').fetchone()[0] != 'on'):
            raise ValueError('A read-only repeatable-read transaction is required')
        metadata = connection.execute('SELECT c.generation_id,s.generation_id,c.vector_count '
                                      'FROM document_centroid_metadata c CROSS JOIN snapshot_metadata s '
                                      'WHERE c.singleton AND s.singleton').fetchone()
        if metadata is None or metadata[0] != metadata[1]:
            raise ValueError('Centroids do not match the current generation')
        with connection.cursor(name='fixture_document_centroids') as cursor:
            cursor.execute('SELECT document_id,embedding FROM document_centroids ORDER BY document_id')
            index = cls(metadata[0], ((ident, bytes(blob)) for ident, blob in cursor))
        if index.db.execute('SELECT count(*) FROM doc_centroid_vec').fetchone()[0] != metadata[2]:
            index.close()
            raise ValueError('Incomplete centroid generation')
        return index

    def nearest(self, doc_id):
        with self.lock:
            row = self.db.execute('SELECT embedding FROM doc_centroid_vec WHERE rowid=?', (doc_id,)).fetchone()
            if row is None:
                return []
            return self.db.execute('SELECT rowid,distance FROM doc_centroid_vec '
                                   'WHERE embedding MATCH ? AND k=60 ORDER BY distance', (row[0],)).fetchall()

    def close(self):
        with self.lock:
            self.db.close()


def related_documents(connection, index, doc_id, *, k=5):
    """Apply the original related-document rules to captured fixture data."""
    if (connection.execute('SHOW transaction_isolation').fetchone()[0] not in ('repeatable read', 'serializable')
            or connection.execute('SHOW transaction_read_only').fetchone()[0] != 'on'):
        raise ValueError('A read-only repeatable-read transaction is required')
    generation = connection.execute('SELECT generation_id FROM snapshot_metadata WHERE singleton').fetchone()
    if generation is None or str(generation[0]) != index.generation:
        raise ValueError('Centroid generation expired')
    hits = index.nearest(doc_id)
    sims = {ident: 1 - distance ** 2 / 2 for ident, distance in hits if ident != doc_id}
    sims = {ident: score for ident, score in sims.items() if score >= RELATED_MIN_SIM}
    if not sims:
        return []
    ids = [doc_id, *sims]
    records = connection.execute(
        "SELECT row_data FROM legacy_snapshot_rows WHERE table_name='raw_documents' AND row_data->>'id'=ANY(%s)",
        ([str(ident) for ident in ids],),
    ).fetchall()
    meta = {row[0]['id']: row[0] for row in records}
    if doc_id not in meta:
        return []
    source_rows = connection.execute(
        "SELECT table_name,row_data FROM legacy_snapshot_rows WHERE "
        "table_name IN ('telegram_channels','blog_sources','youtube_channels') OR "
        "(table_name='scrap_links' AND row_data->>'doc_id'=ANY(%s)) ORDER BY row_ordinal",
        ([str(ident) for ident in ids],),
    ).fetchall()
    telegram, blogs, youtube, scraps = {}, [], {}, {}
    for table, value in source_rows:
        if table == 'telegram_channels':
            telegram[value['channel_name']] = value['display_name'] or value['channel_name']
        elif table == 'blog_sources':
            blogs.append((value['url'], value['blog_name'] or value['url']))
        elif table == 'youtube_channels':
            youtube[value['channel_id']] = value['title']
        elif value['channel']:
            scraps[value['doc_id']] = value['channel']
    blogs.sort(key=lambda item: (item[0] is not None, len(item[0] or '')), reverse=True)
    channels = source_names_from_rows(list(meta.values()), telegram=telegram, blogs=blogs, youtube=youtube, scraps=scraps)
    me = meta[doc_id]
    ranked = sorted((ident for ident in sims if ident in meta), key=lambda ident: -(
        sims[ident] + RELATED_RECENCY_W * math.exp(-_days(meta[ident]['published_at'], me['published_at']) / 30)))
    selected, titles, per_source = [], {_norm_title(me['title'])}, {}
    for ident in ranked:
        title, channel = _norm_title(meta[ident]['title']), (channels.get(ident) or {}).get('name')
        if (title and title in titles) or (channel and per_source.get(channel, 0) >= RELATED_PER_SOURCE):
            continue
        titles.add(title)
        if channel:
            per_source[channel] = per_source.get(channel, 0) + 1
        selected.append(ident)
        if len(selected) >= k:
            break
    reasons = _shared_entities(connection, doc_id, selected)
    return [{'id': ident, 'source_type': meta[ident]['source_type'], 'title': meta[ident]['title'],
             'published_at': meta[ident]['published_at'], 'channel': (channels.get(ident) or {}).get('name'),
             'similarity': round(sims[ident], 3), 'reasons': reasons.get(ident, [])} for ident in selected]


def _shared_entities(connection, doc_id, ids):
    if not ids:
        return {}
    rows = connection.execute(
        "SELECT l.row_data,e.row_data FROM legacy_snapshot_rows l JOIN legacy_snapshot_rows e "
        "ON e.table_name='entities' AND e.row_data->>'id'=l.row_data->>'entity_id' "
        "WHERE l.table_name='entity_links' AND l.row_data->>'doc_id'=ANY(%s) ORDER BY l.row_ordinal",
        ([str(ident) for ident in [doc_id, *ids]],),
    ).fetchall()
    def eligible(link):
        return link['link_type'] in ('stock', 'person', 'industry') and (
            link['link_type'] != 'stock' or (link['confidence'] is not None and link['confidence'] >= 0.7))
    mine = {link['entity_id']: entity for link, entity in rows if link['doc_id'] == doc_id and eligible(link)}
    if not mine:
        return {}
    counts = connection.execute(
        "SELECT (row_data->>'entity_id')::bigint,count(*) FROM legacy_snapshot_rows "
        "WHERE table_name='entity_links' AND row_data->>'entity_id'=ANY(%s) GROUP BY 1",
        ([str(ident) for ident in mine],),
    ).fetchall()
    frequency = dict(counts)
    kinds = {'stock': 0, 'person': 1, 'industry': 2}
    result = {}
    for link, entity in rows:
        ident, entity_id = link['doc_id'], link['entity_id']
        if ident not in ids or not eligible(link) or entity_id not in mine:
            continue
        name = entity['name']
        values = result.setdefault(ident, [])
        if name not in [item[2] for item in values]:
            values.append((kinds[link['link_type']], frequency.get(entity_id, 0), name))
    return {ident: [name for _, _, name in sorted(values)[:3]] for ident, values in result.items()}
