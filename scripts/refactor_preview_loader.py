"""Load one read-only rehearsal snapshot into a disposable local preview DB."""
import os
import re
import sqlite3
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path
import psycopg
from psycopg import sql
from pipeline.postgres_snapshot import load_snapshot


def main():
    dsn=os.environ['REFACTOR_POSTGRES_DSN']
    schema=os.environ['REFACTOR_FIXTURE_SCHEMA']
    target=psycopg.conninfo.conninfo_to_dict(dsn)
    if (os.environ.get('REFACTOR_TEST_DISPOSABLE') != '1' or
        (target.get('host'),target.get('dbname'),target.get('user')) != ('pg','fixture','fixture') or
        not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}',schema)):
        raise ValueError('Disposable local preview required')
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    def factory(): return psycopg.connect(dsn,options=f'-c search_path={schema}')
    with factory() as conn:
        conn.execute((Path(__file__).resolve().parents[1]/'backend/refactor_sql/document_projection.sql').read_text())
        if os.getenv('REFACTOR_INCLUDE_SECTOR') == '1':
            conn.execute((Path(__file__).resolve().parents[1]/'backend/refactor_sql/sector_market.sql').read_text())
    source=sqlite3.connect('file:/data/stock_explorer.db?mode=ro',uri=True)
    source.row_factory=sqlite3.Row
    include_centroids=os.getenv('REFACTOR_INCLUDE_CENTROIDS') == '1'
    if include_centroids:
        import sqlite_vec
        source.enable_load_extension(True)
        try:
            sqlite_vec.load(source)
        finally:
            source.enable_load_extension(False)
    source.execute('PRAGMA query_only=ON')
    source.execute('BEGIN')
    try:
        include_sector=os.getenv('REFACTOR_INCLUDE_SECTOR') == '1'
        peer=None
        if include_sector:
            raw=Path('/inputs/peers.json').read_bytes()
            peer=json.loads(raw)
            captured=os.environ['REFACTOR_PEER_CAPTURED_AT']
            when=datetime.fromisoformat(captured.replace('Z','+00:00'))
            if when.tzinfo is None or when.utcoffset() is None:
                raise ValueError('Peer capture time must include timezone')
        result=load_snapshot(source,factory,snapshot_at=datetime.now(timezone.utc).isoformat(),
                             include_linking=True,include_signals=True,include_claims=True,
                             include_centroids=include_centroids,include_sector=include_sector,
                             include_us=include_sector,peer_runtime=peer,
                             include_transcript_follow=os.getenv('REFACTOR_INCLUDE_TRANSCRIPT_FOLLOW') == '1')
        if include_sector:
            with factory() as conn:
                conn.execute('CREATE TABLE preview_peer_provenance (captured_at TIMESTAMPTZ NOT NULL,sha256 TEXT NOT NULL)')
                conn.execute('INSERT INTO preview_peer_provenance VALUES (%s,%s)',(when,hashlib.sha256(raw).hexdigest()))
        print('Preview snapshot loaded:',result,flush=True)
    finally:
        source.close()


if __name__ == '__main__': main()
