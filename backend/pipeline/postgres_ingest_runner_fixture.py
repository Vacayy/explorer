"""Run existing connector/embedding code only against disposable PG fixtures.

The caller must isolate the process from external networks. No LLM is invoked.
The embedding cache must already exist; this module never downloads a model.
"""
import os
import re
from datetime import datetime, timezone
from pipeline import runner, search
from pipeline.postgres_ingest_fixture import store_raw_doc, store_embedding


def _guard(conn):
    database, schema = conn.execute('SELECT current_database(),current_schema()').fetchone()
    if (os.getenv('REFACTOR_TEST_DISPOSABLE') != '1' or database != 'fixture' or
            not schema or not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}',schema)):
        raise ValueError('Disposable fixture schema required')


def registered_connector(factory, source):
    """Read configured blog/Telegram sources from the captured fixture registry."""
    from pipeline.connectors.blog import BlogConnector
    from pipeline.connectors.telegram import TelegramConnector
    config = {'blog': ('blog_sources', 'url', BlogConnector),
              'telegram': ('telegram_channels', 'channel_name', TelegramConnector)}
    if source not in config:
        raise ValueError('Only blog and Telegram registries are supported')
    table, key, connector = config[source]
    with factory() as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        _guard(conn)
        if not conn.execute('SELECT 1 FROM legacy_snapshot_tables WHERE table_name=%s', (table,)).fetchone():
            raise ValueError('Source registry missing from snapshot')
        records = conn.execute('SELECT row_data FROM legacy_snapshot_rows WHERE table_name=%s ORDER BY row_ordinal', (table,)).fetchall()
    sources = []
    for (row,) in records:
        enabled = row.get('collect_enabled')
        if enabled is None or enabled == 1:
            value = row.get(key)
            if not isinstance(value, str) or not value:
                raise ValueError('Invalid source in registry')
            sources.append(value)
    return connector(sources)


def initialize_youtube_registry(conn):
    """Initialize the fixture's writable registry from its captured source."""
    _guard(conn)
    if not conn.execute("SELECT 1 FROM legacy_snapshot_tables WHERE table_name='youtube_channels'").fetchone():
        raise ValueError('YouTube registry missing from snapshot')
    if conn.execute('SELECT 1 FROM ingest_youtube_registry_state').fetchone():
        raise ValueError('YouTube registry already initialized')
    rows = conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='youtube_channels' ORDER BY row_ordinal").fetchall()
    for (row,) in rows:
        conn.execute('INSERT INTO ingest_youtube_registry VALUES (%s,%s,%s,%s)',
                     (row['channel_id'], row.get('title'), row.get('is_active'), row.get('collect_enabled')))
    conn.execute('INSERT INTO ingest_youtube_registry_state DEFAULT VALUES')


def registered_youtube_connector(factory, *, channel_ids=None):
    """Create a YouTube connector backed by the disposable registry and ledger."""
    from pipeline.connectors.youtube import YouTubeConnector
    def registry(ids):
        with factory() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            _guard(conn)
            if not conn.execute('SELECT 1 FROM ingest_youtube_registry_state').fetchone():
                raise ValueError('YouTube registry is not initialized')
            rows = conn.execute('SELECT channel_id,title,is_active,collect_enabled FROM ingest_youtube_registry ORDER BY channel_id').fetchall()
            seen = {r[0].split('/')[-1] for r in conn.execute("SELECT source_id FROM ingest_documents WHERE source_type='youtube'")}
        channels = [{'channel_id': cid, 'title': title} for cid,title,active,enabled in rows
                    if (cid in ids if ids else active == 1 and (enabled is None or enabled == 1))]
        return channels, seen
    def repair(cid, title):
        if not title or title == cid:
            return
        with factory() as conn:
            _guard(conn)
            conn.execute("UPDATE ingest_youtube_registry SET title=%s WHERE channel_id=%s "
                         "AND (title IS NULL OR btrim(title)='' OR btrim(title)=channel_id)", (title,cid))
    return YouTubeConnector(channel_ids=channel_ids,registry_loader=registry,title_repair=repair)


def initialize_telegram_marks(conn):
    _guard(conn)
    if not conn.execute("SELECT 1 FROM legacy_snapshot_tables WHERE table_name='telegram_group_marks'").fetchone():
        raise ValueError('Telegram grouping marks missing from snapshot')
    if conn.execute('SELECT 1 FROM ingest_telegram_marks_state').fetchone():
        raise ValueError('Telegram marks already initialized')
    for (row,) in conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='telegram_group_marks' ORDER BY row_ordinal"):
        conn.execute('INSERT INTO ingest_telegram_group_marks VALUES (%s,%s,%s,%s)',
                     (row['channel'],row['msg_id'],bool(row['joins_prev']),row.get('model')))
    conn.execute('INSERT INTO ingest_telegram_marks_state DEFAULT VALUES')


def registered_telegram_connector(factory, *, image_reader, image_finder, judge):
    """Use captured grouping marks and explicit image dependencies in a fixture."""
    from pipeline.connectors.telegram import TelegramConnector
    if not all(callable(value) for value in (image_reader,image_finder,judge)):
        raise ValueError('Explicit image and grouping dependencies are required')
    with factory() as conn:
        _guard(conn)
        if not conn.execute('SELECT 1 FROM ingest_telegram_marks_state').fetchone():
            raise ValueError('Telegram marks are not initialized')
    channels = registered_connector(factory,'telegram')._channels
    class Marks:
        def get(self, channel, msg_id):
            with factory() as conn:
                conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                _guard(conn)
                if not conn.execute('SELECT 1 FROM ingest_telegram_marks_state').fetchone():
                    raise ValueError('Telegram marks are not initialized')
                row=conn.execute('SELECT joins_prev FROM ingest_telegram_group_marks WHERE channel=%s AND msg_id=%s',(channel,msg_id)).fetchone()
                return {'joins_prev':row[0]} if row else None
        def put(self, channel, msg_id, verdict, model):
            with factory() as conn:
                _guard(conn)
                if not conn.execute('SELECT 1 FROM ingest_telegram_marks_state').fetchone():
                    raise ValueError('Telegram marks are not initialized')
                conn.execute('INSERT INTO ingest_telegram_group_marks VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                             (channel,msg_id,verdict,model))
                return conn.execute('SELECT joins_prev FROM ingest_telegram_group_marks WHERE channel=%s AND msg_id=%s',(channel,msg_id)).fetchone()[0]
    return TelegramConnector(channels,mark_store=Marks(),image_reader=image_reader,image_finder=image_finder,judge=judge)


def run_source(connector, factory, *, clock=lambda: datetime.now(timezone.utc), on_stored=None):
    from pipeline.connectors.telegram import TelegramConnector
    if isinstance(connector, TelegramConnector):
        marks = connector._mark_store
        if (connector._channels is None or marks is None or not callable(getattr(marks,'get',None)) or not callable(getattr(marks,'put',None))
                or not all(callable(value) for value in (connector._image_reader,connector._image_finder,connector._judge))):
            raise ValueError('Telegram fixture requires explicit grouping and image dependencies')
    with factory() as conn:
        _guard(conn)
    if getattr(connector,'after_store',None):
        raise ValueError('Connector side-effect hooks are not supported')
    def store(doc):
        observed=clock()
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError('A timezone-aware collection time is required')
        with factory() as conn:
            _guard(conn)
            result=store_raw_doc(conn,doc,fetched_at=observed.astimezone(timezone.utc).isoformat())
        if on_stored is not None:
            on_stored(result)
        return result
    return runner.run_source(connector,store=store)


def embed_document(factory, document_id):
    with factory() as conn:
        _guard(conn)
        row=conn.execute('SELECT title,markdown,revision FROM ingest_documents WHERE id=%s',(document_id,)).fetchone()
    if row is None:
        return False
    title,markdown,revision=row
    # Matches build_index's title + first 2000 characters, with local files only.
    vector=search._serialize(next(iter(search._get_model(local_files_only=True).embed([f'{title}\n{(markdown or "")[:2000]}']))))
    with factory() as conn:
        _guard(conn)
        return store_embedding(conn,document_id=document_id,revision=revision,embedding=vector,model=search.EMBED_MODEL)
