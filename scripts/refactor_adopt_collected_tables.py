"""Hand the collector-only base tables of the single-path candidate to the supplement layer (once).

Only tables no user route writes and no overlay touches; each table's visible rows
must hash the same before and after. Run through scripts/refactor_run_collector_once.sh.
"""
import hashlib
import json
import os

import psycopg

from pipeline.postgres_legacy_supplement import adopt_base_tables

# Written only by scheduled collectors (coverage table P3). Not here: document and graph
# tables (revisions), owner ledgers, narrative_candidates (admin decisions), and tables
# on-demand compute routes write (source_digests, scenarios, reports, doc_claims).
TABLES = ('call_extracts', 'call_momentum', 'catalysts', 'companies', 'earnings_events', 'earnings_expectations',
          'earnings_releases', 'entity_digests', 'entity_merges', 'knowledge_evidence', 'market_today',
          'market_today_links', 'narratives', 'portfolio_alerts_sent', 'portfolio_quotes', 'signals',
          'telegram_group_marks', 'trade_stats', 'transcript_calendar', 'transcripts')

conn = psycopg.connect(os.environ['REFACTOR_POSTGRES_DSN'], autocommit=True)
conn.execute(f"SET search_path TO {os.environ['REFACTOR_FIXTURE_SCHEMA']}")


def digest(table):
    rows = conn.execute("SELECT row_ordinal,row_data FROM legacy_snapshot_rows WHERE table_name=%s ORDER BY row_ordinal", (table,))
    return hashlib.sha256(json.dumps(rows.fetchall(), sort_keys=True, default=str).encode()).hexdigest()


before = {table: digest(table) for table in TABLES}
counts = adopt_base_tables(conn, TABLES)
changed = [table for table in TABLES if digest(table) != before[table]]
print({'adopted': len(counts), 'rows': sum(counts.values()), 'changed': changed})
