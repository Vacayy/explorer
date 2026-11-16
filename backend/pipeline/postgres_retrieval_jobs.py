"""Retrieval jobs for the single-path compute worker: queries in, related documents out.

Features that need the legacy chunk search and reranker (too large for the preview API) put a job
here; the worker (`pipeline.postgres_compute_worker`) runs the job's handler with the legacy
retrieval pointed at the chunk index and the projection. Document claims and AI-answer
tools (`chat_tool`) use it.
"""
import sqlite3

from psycopg.types.json import Jsonb

from pipeline.postgres_graph_fixture import _guard


def initialize(conn):
    _guard(conn)
    with conn.transaction():
        if conn.execute("SELECT to_regclass('retrieval_jobs')").fetchone()[0] is not None:
            raise ValueError('Retrieval jobs already initialized')
        conn.execute("CREATE TABLE retrieval_jobs (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,kind TEXT NOT NULL,"
                     "subject TEXT NOT NULL,request JSONB NOT NULL,result JSONB,status TEXT NOT NULL DEFAULT 'queued' "
                     "CHECK(status IN ('queued','done','failed')),error TEXT,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
                     'updated_at TIMESTAMPTZ NOT NULL DEFAULT now())')
        conn.execute("CREATE INDEX retrieval_jobs_queued ON retrieval_jobs (created_at) WHERE status='queued'")


def enqueue(conn, kind, subject, request):
    return conn.execute('INSERT INTO retrieval_jobs(kind,subject,request) VALUES (%s,%s,%s) RETURNING id',
                        (kind, subject, Jsonb(request))).fetchone()[0]


def legacy_retrieval(chunks_path, projection_path):
    """Point the unchanged legacy retrieval modules at the chunk index with the projection attached."""
    import sys

    import database
    from pipeline import chat_tools, chunks, quotes, rag, search, visibility

    def connection():
        conn = sqlite3.connect(chunks_path, timeout=30)
        conn.execute('ATTACH DATABASE ? AS projection', (f'file:{projection_path}?mode=ro',))
        conn.row_factory = sqlite3.Row
        return conn

    original = database.get_connection
    database.get_connection = connection  # modules imported later bind this one
    for module in list(sys.modules.values()):  # each bound get_connection at import
        if getattr(module, 'get_connection', None) is original:
            module.get_connection = connection
    for module in (chat_tools, chunks, rag, search):
        module.get_connection = connection
    quotes.fetch_quotes = stored_quotes  # the candidate does not collect: saved closes, never a live request
    # The owner's personal mute is not applied without per-user identity (all collected material shows),
    # and retrieval shown to users does not drop unverified sources (scrap) either (PM decision).
    visibility.get_muted = lambda conn: {'telegram': set(), 'blog': []}
    visibility.UNVERIFIED_SOURCES = frozenset()
    return connection


# AI-answer tools run here unchanged on the chunk index and projection (evidence search with chunk hybrid
# search and rerank, the causal graph, narratives, knowledge, questions, regime, market and owner records).
# All are reads without model calls; quotes are saved closes (`stored_quotes`).
WORKER_CHAT_TOOLS = ('search_docs', 'get_worldmodel', 'get_narrative', 'get_knowledge', 'get_questions', 'get_regime',
                     'get_us_briefing', 'get_pricing_ledger', 'get_proxies', 'get_trade', 'get_study', 'list_recent',
                     'get_lens', 'get_saved', 'get_portfolio', 'get_quote', 'get_price_history')
STORED_QUOTE_TITLE = '저장 종가 (실시간 시세 아님 — 후보에서는 시세를 수집하지 않음)'


def stored_quotes(codes):
    """fetch_quotes' shape from the projection's saved daily closes (latest two trading days)."""
    from database import get_connection
    conn = get_connection()
    try:
        out = []
        for code in dict.fromkeys(c.strip() for c in codes if c and c.strip()):
            rows = conn.execute('SELECT trade_date,close FROM stock_prices WHERE stock_code=? AND close IS NOT NULL '
                                'ORDER BY trade_date DESC LIMIT 2', (code,)).fetchall()
            if not rows:
                continue
            last, prev = rows[0], rows[1] if len(rows) > 1 else None
            change = last[1] - prev[1] if prev else 0
            out.append({'stock_code': code, 'price': last[1], 'change': change,
                        'change_pct': change / prev[1] * 100 if prev and prev[1] else 0, 'volume': None,
                        'market_status': 'CLOSE', 'traded_at': last[0]})
        return out
    finally:
        conn.close()


def chat_tool(factory, request):
    from pipeline import chat_tools
    name = request['name']
    if name not in WORKER_CHAT_TOOLS:
        raise ValueError(f'{name} does not run in the compute worker')
    allowed = chat_tools.TOOLS[name]['args'] | ({'k'} if name == 'search_docs' else set())
    result = chat_tools.TOOLS[name]['fn'](**{key: value for key, value in request['args'].items()
                                             if key in allowed and value is not None})
    items = result.items
    if name == 'get_quote':  # the legacy title says real time; these are saved closes
        items = [{**item, 'title': STORED_QUOTE_TITLE} if item.get('kind') == 'quote' else item for item in items]
    note = result.note
    if name == 'get_quote' and note == '시세 조회 실패':
        note = '저장된 시세 없음 (최신 시세 미반영 — 후보에서는 시세를 수집하지 않음)'
    return {'args': result.args, 'items': items, 'note': note, 'assumed': result.assumed}


def run_queued(factory, handlers):
    """Run every queued job whose kind has a handler; `handler(factory, request) -> result` may raise."""
    with factory() as conn:
        jobs = conn.execute("SELECT id,kind,request FROM retrieval_jobs WHERE status='queued' AND kind=ANY(%s) "
                            'ORDER BY created_at', (list(handlers),)).fetchall()
    done = []
    for ident, kind, request in jobs:
        try:
            result, status, error = handlers[kind](factory, request), 'done', None
        except Exception as exc:  # noqa: BLE001 - kept with its reason; not retried automatically
            result, status, error = None, 'failed', f'{type(exc).__name__}: {str(exc)[:300]}'
        with factory() as conn:
            conn.execute('UPDATE retrieval_jobs SET status=%s,result=%s,error=%s,updated_at=now() WHERE id=%s',
                         (status, Jsonb(result) if result is not None else None, error, ident))
        done.append((ident, kind, status))
    return done
