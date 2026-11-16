"""Add a sector snapshot to a disposable preview; never touches source data."""
import json
import os
import re
import shutil
import sqlite3
from pathlib import Path
import psycopg

from pipeline.postgres_sector_market import load_sector_market


def main():
    dsn=os.environ['REFACTOR_POSTGRES_DSN']
    schema=os.environ['REFACTOR_FIXTURE_SCHEMA']
    target=psycopg.conninfo.conninfo_to_dict(dsn)
    if (os.environ.get('REFACTOR_TEST_DISPOSABLE')!='1' or
            tuple(target.get(k) for k in ('host','dbname','user'))!=('pg','fixture','fixture') or
            not re.fullmatch(r'refactor_fixture_[0-9a-f]{32}',schema)):
        raise ValueError('Disposable preview required')
    if shutil.disk_usage('/').free < 22 * 1024**3:
        raise ValueError('Insufficient VM free space')
    peer=json.loads(Path('/inputs/peers.json').read_text())
    source=sqlite3.connect('file:/data/stock_explorer.db?mode=ro',uri=True)
    source.row_factory=sqlite3.Row
    source.execute('PRAGMA query_only=ON')
    source.execute('BEGIN')
    try:
        with psycopg.connect(dsn,options='-c search_path='+schema) as target_conn:
            if target_conn.execute("SELECT to_regclass('sector_market_metadata')").fetchone()[0] is not None:
                raise ValueError('Sector tables already exist; refusing replacement')
            generation=target_conn.execute('SELECT generation_id FROM snapshot_metadata WHERE singleton').fetchone()
            if not generation or not generation[0]:
                raise ValueError('Document generation required')
            target_conn.execute((Path(__file__).resolve().parents[1]/'backend/refactor_sql/sector_market.sql').read_text())
            result=load_sector_market(source,target_conn,peer_runtime=peer,document_generation=generation[0],include_us=True)
        print('Sector fixture load completed:',result,flush=True)
    finally:
        source.close()


if __name__=='__main__':
    main()
