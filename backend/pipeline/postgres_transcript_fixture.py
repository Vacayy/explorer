"""Disposable read adapter for existing earnings-call detail and quarters."""
from datetime import datetime, timedelta, timezone
from pipeline.postgres_signals_fixture import _guard_read
from pipeline.postgres_doc_graph_fixture import document_graph
from pipeline.transcript import cy_label
from routers.spine_transcript import Detail, QuarterRow, RecentCall, list_follow_from_connection


def _ready(conn):
    _guard_read(conn)
    required={'transcripts','transcript_follow','raw_documents','entities','entity_links','entity_relations'}
    present={row[0] for row in conn.execute('SELECT table_name FROM legacy_snapshot_tables WHERE table_name=ANY(%s)',(list(required),))}
    if present != required: raise ValueError('Transcript snapshot incomplete')


def quarters(conn, ticker):
    _ready(conn)
    ticker=ticker.upper()
    follow=conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='transcript_follow' AND row_data->>'ticker'=%s ORDER BY row_ordinal LIMIT 1",(ticker,)).fetchone()
    fye=follow[0].get('fiscal_year_end') if follow else None
    rows=conn.execute("SELECT row_data FROM legacy_snapshot_rows WHERE table_name='transcripts' AND row_data->>'ticker'=%s "
                      "ORDER BY (row_data->>'fiscal_year')::integer DESC NULLS LAST,row_data->>'fiscal_period' DESC NULLS LAST,row_ordinal",(ticker,)).fetchall()
    return [QuarterRow(transcript_id=r['id'],fiscal_year=r.get('fiscal_year'),fiscal_period=r.get('fiscal_period'),
                       cy=cy_label(r.get('fiscal_year'),r.get('fiscal_period'),fye),call_date=r.get('call_date'),has_digest=bool(r.get('digest'))) for (r,) in rows]


def recent_calls(conn, *, days=7, limit=40, now=None):
    """Apply the original recent-call cutoff and ordering to the captured rows."""
    _ready(conn)
    if days<0:
        return []  # SQLite's original '--N day' modifier produces NULL.
    cutoff=((now or datetime.now(timezone.utc))-timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    rows=conn.execute("SELECT t.row_data,f.row_data FROM legacy_snapshot_rows t LEFT JOIN legacy_snapshot_rows f "
        "ON f.table_name='transcript_follow' AND f.row_data->>'ticker'=t.row_data->>'ticker' "
        "WHERE t.table_name='transcripts' AND t.row_data->>'fetched_at'>=%s "
        "ORDER BY t.row_data->>'fetched_at' DESC,t.row_ordinal,f.row_ordinal LIMIT %s",
        (cutoff,None if limit<0 else limit)).fetchall()
    result=[]
    for transcript,follow in rows:
        follow=follow or {}
        result.append(RecentCall(transcript_id=transcript['id'],ticker=transcript['ticker'],
            company_name=follow.get('company_name'),fiscal_year=transcript.get('fiscal_year'),
            fiscal_period=transcript.get('fiscal_period'),cy=cy_label(transcript.get('fiscal_year'),transcript.get('fiscal_period'),follow.get('fiscal_year_end')),
            call_date=transcript.get('call_date'),provider=transcript.get('provider'),fetched_at=transcript.get('fetched_at'),
            has_digest=bool(transcript.get('digest'))))
    return result


def follow_list(conn):
    """Run the original follow calculation on only its captured inputs."""
    from pipeline.postgres_urgent_selection_fixture import open_snapshot
    _ready(conn)
    tables=('transcript_follow','transcripts','entity_keywords','earnings_releases',
            'transcript_calendar','earnings_expectations','earnings_events','raw_documents')
    ids=[row[0] for row in conn.execute("SELECT DISTINCT row_data->>'doc_id' FROM legacy_snapshot_rows "
                                       "WHERE table_name='earnings_releases' AND row_data->>'doc_id' IS NOT NULL")]
    db,_,_=open_snapshot(conn,tables,document_ids=ids)
    try:
        from pipeline.postgres_legacy_projection import derive_owner_transcript_follow
        derive_owner_transcript_follow(db,conn)  # the owner's additions and core pins, as legacy reads see them
        return list_follow_from_connection(db)
    finally:
        db.close()


def transcript_detail(conn, transcript_id):
    _ready(conn)
    row=conn.execute("""
      SELECT t.row_data,d.row_data,f.row_data FROM legacy_snapshot_rows t
      JOIN legacy_snapshot_rows d ON d.table_name='raw_documents' AND d.row_data->>'id'=t.row_data->>'raw_doc_id'
      LEFT JOIN legacy_snapshot_rows f ON f.table_name='transcript_follow' AND f.row_data->>'ticker'=t.row_data->>'ticker'
      WHERE t.table_name='transcripts' AND t.row_data->>'id'=%s ORDER BY f.row_ordinal LIMIT 1
    """,(str(transcript_id),)).fetchone()
    if row is None: return None
    transcript,doc,follow=row
    follow=follow or {}
    graph=document_graph(conn,transcript['raw_doc_id'])
    return Detail(transcript_id=transcript['id'],ticker=transcript['ticker'],company_name=follow.get('company_name') or transcript['ticker'],
                  fiscal_year=transcript.get('fiscal_year'),fiscal_period=transcript.get('fiscal_period'),
                  cy=cy_label(transcript.get('fiscal_year'),transcript.get('fiscal_period'),follow.get('fiscal_year_end')),
                  call_date=transcript.get('call_date'),digest=transcript.get('digest'),body=doc.get('markdown') or '',
                  nodes=graph['nodes'],causal_edges=graph['edges'])
