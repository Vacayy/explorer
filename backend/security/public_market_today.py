"""Stored market briefing, with reviewed source links and no private narrative reads."""
from contextlib import closing
from pathlib import Path
import sqlite3

from config import DB_PATH
from pipeline.market_today import read_snapshot
from models.market_today import MarketToday
from security.public_documents import PublicDocuments, DocumentUnavailable, ReadBudget

COLUMNS = {'id','trade_date','slot','created_at','items_json','sources_json','counts_json','market_json',
           'window_start','window_end','doc_count','links_at'}


def authorize(action, table, column, database, source):
    if action == sqlite3.SQLITE_SELECT: return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and database == 'main' and table == 'market_today' and column in COLUMNS:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and column in {'max','min'}: return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def public_market_today(day=None, slot=None, *, path=None, publications=None):
    # Stored briefs are generated from collected Telegram/news, not personal
    # portfolios/questions. Public source links still require current approval.
    with closing(sqlite3.connect(Path(path or DB_PATH).resolve().as_uri()+'?mode=ro',uri=True,timeout=3)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        conn.set_authorizer(authorize)
        result = read_snapshot(conn,day,slot,include_links=False)
    current = result['current']
    if current:
        service = publications or PublicDocuments.from_environment()
        budget = ReadBudget()
        documents = {}
        for topic in current['topics']:
            visible = []
            for source in topic['sources']:
                doc_id = source.get('doc_id')
                if not isinstance(doc_id,int) or doc_id <= 0: continue
                if doc_id not in documents:
                    try: documents[doc_id] = service.published(doc_id,budget=budget).document
                    except DocumentUnavailable: documents[doc_id] = None
                doc = documents[doc_id]
                if doc is not None:
                    visible.append(dict(ref=source['ref'],kind=doc.source_type,publisher=doc.channel.name if doc.channel else (doc.source_type or '출처'),
                                        title=doc.title,url=doc.url,doc_id=doc.id,published_at=doc.published_at,echo=source.get('echo',1)))
            topic['sources'] = visible
            topic['refs'] = [source['ref'] for source in visible]
            topic['narratives'] = []
        current['links_ready'] = False
    return MarketToday.model_validate(result)
