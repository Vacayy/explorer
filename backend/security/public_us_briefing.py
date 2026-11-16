"""Stored US market briefs and numeric movers, without private enrichment or jobs."""
from contextlib import closing
from pathlib import Path
import sqlite3

from config import DB_PATH
from models.us import UsBriefing, UsBriefingListItem
from pipeline.us_briefing import _read_synthesis, _build_movers, _clusters, _flag_idiosyncratic, _staleness
from pipeline.us_movers import read_snapshot, last_completed_session
from security.public_documents import PublicDocuments, DocumentUnavailable, ReadBudget

COLUMNS = {
    'us_briefings': {'trade_date', 'created_at', 'synthesis_json'},
    'us_movers': {'trade_date','rank','ticker','name','close','volume','dollar_volume','change_pct',
                  'sector','industry','exchange','market_cap','is_adr','is_new','fetched_at'},
}


def authorize(action, table, column, database, source):
    if action == sqlite3.SQLITE_SELECT: return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and database == 'main' and column in COLUMNS.get(table, set()):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and column == 'max': return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def connection(path=None):
    conn = sqlite3.connect(Path(path or DB_PATH).resolve().as_uri()+'?mode=ro',uri=True,timeout=3)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    conn.execute('BEGIN')
    conn.set_authorizer(authorize)
    return conn


def briefing_dates(limit=30, *, path=None):
    with closing(connection(path)) as conn:
        return [UsBriefingListItem(**dict(row)) for row in conn.execute(
            'SELECT trade_date, created_at FROM us_briefings ORDER BY trade_date DESC LIMIT ?', (limit,))]


def stored_briefing(day=None, *, path=None, publications=None):
    with closing(connection(path)) as conn:
        if day is None:
            # Latest stored session, not today's date invented for an older text.
            dates = [conn.execute('SELECT max(trade_date) FROM '+table).fetchone()[0] for table in COLUMNS]
            day = max((d for d in dates if d), default=None)
        synthesis = _read_synthesis(conn, day)
        snapshot = read_snapshot(conn, day) if day else []
        made = conn.execute('SELECT created_at FROM us_briefings WHERE trade_date=?', (day,)).fetchone()
        movers = _build_movers(conn, snapshot, include_coverage=False)
        clusters = _clusters(movers)
        _flag_idiosyncratic(movers, clusters)
    if synthesis:
        service = publications or PublicDocuments.from_environment()
        budget = ReadBudget()
        visible = []
        for source in synthesis['sources']:
            doc_id = source.get('doc_id')
            if not isinstance(doc_id, int) or doc_id <= 0: continue
            try: doc = service.published(doc_id, budget=budget).document
            except DocumentUnavailable: continue
            visible.append(dict(n=source['n'],kind=doc.source_type,publisher=doc.channel.name if doc.channel else doc.source_type,
                                title=doc.title,url=doc.url,doc_id=doc.id,published_at=doc.published_at))
        synthesis['sources'] = visible
        synthesis['source_gaps'] = []  # collector diagnostics are operator-only
    return UsBriefing(status='ok' if snapshot and synthesis else 'partial' if snapshot or synthesis else 'error',
        trade_date=day, fetched_at=snapshot[0]['fetched_at'] if snapshot else None,
        stale_days=_staleness(day), expected_session=last_completed_session(),
        synthesized_at=made['created_at'] if made else None,
        error=None if snapshot else '이 날짜의 거래대금 자료가 없습니다.' if synthesis else '저장된 브리핑이 없습니다.',
        movers=movers, clusters=clusters, idiosyncratic=[m for m in movers if m['flags']], synthesis=synthesis)
