"""Rows the candidate collected into supplement tables that the MacBook file lacks, kept across the cutover's whole
replacement of those tables (architect #3 6945482451 item 2; PM 6945436466: the user's decision to keep collected data).

The publication replaces every supplement table with the MacBook's rows. For an accumulating table (events, time
series, observations: rows only ever added) a candidate row whose natural key the MacBook file lacks is captured before
the replacement and added back after it, under a band id where the table has an integer id (map: candidate_id_remap,
kind 'supplement:<table>'); a key both sides have keeps the MacBook's row. For a state table (rewritten or pruned as a
whole) the MacBook's rows stand; candidate-only rows are archived and counted. A table is accumulating when its
natural key carries a date or time (the list below, derived from the base's keys) or it records collected or derived
items (added below); configuration, lists and current state are state tables.
job_runs is an operation record and is never carried (the candidate's own runs are in candidate_job_runs).
"""
import json
from datetime import datetime, timedelta, timezone

from psycopg.types.json import Jsonb

from pipeline.postgres_graph_fixture import _guard
from pipeline.postgres_id_bands import start

ACCUMULATING = {'business_segments': ('corp_code', 'bsns_year', 'reprt_code', 'segment_type', 'segment_name'),
                'call_momentum': ('ticker', 'event_date'),
                'consensus': ('stock_code', 'data_source', 'fiscal_year'),
                'consensus_estimates': ('stock_code', 'fetched_date', 'fiscal_year'),
                'consensus_snapshots': ('ticker', 'snap_date', 'period'),
                'credit_quotes': ('symbol', 'date'),
                'earnings_events': ('ticker', 'fiscal_year', 'fiscal_period'),
                'earnings_expectations': ('ticker', 'fiscal_year', 'fiscal_period', 'snapshot'),
                'entity_digests': ('entity_id', 'period', 'period_start'),
                'ext_series': ('series', 'period'),
                'financial_statements': ('corp_code', 'bsns_year', 'reprt_code', 'fs_div', 'sj_div', 'account_nm'),
                'fundamentals': ('stock_code', 'trade_date'),
                'index_intraday': ('key', 'trade_date', 'hhmm'),
                'investor_flows': ('stock_code', 'trade_date'),
                'kalshi_candles': ('market_ticker', 'day'),
                'kalshi_events': ('fetched_at', 'event_ticker'),
                'kr_movers': ('trade_date', 'rank'),
                'kr_preliminary_earnings': ('stock_code', 'period'),
                'macro_signals': ('as_of',),
                'market_indicators': ('snapshot_date', 'indicator'),
                'market_today': ('trade_date', 'slot'),
                'pricing_days': ('trade_date',),
                'pricing_observations': ('trade_date', 'claim_id'),
                'retail_flows': ('date',),
                'sector_benchmark_prices': ('ticker', 'trade_date'),
                'sector_index': ('sector', 'trade_date'),
                'signals': ('signal_type', 'entity_id', 'date'),
                'stock_prices': ('stock_code', 'trade_date'),
                'trade_stats': ('hs_code', 'period'),
                'transcript_probe': ('ticker', 'fiscal_year', 'fiscal_period'),
                'transcripts': ('ticker', 'fiscal_year', 'fiscal_period'),
                'treasury_curve': ('date', 'tenor'),
                'tw_monthly_revenue': ('code', 'ym'),
                'us_briefings': ('trade_date',),
                'us_macro_issues': ('trade_date',),
                'us_movers': ('trade_date', 'rank'),
                'us_prices': ('stock_code', 'trade_date'),
                'watch_evaluations': ('rule_id', 'stock_code', 'as_of')}
# Record tables without a date in their key (PM #3 6945939798: collected and derived records are kept): their writers
# only add or refresh rows by a source key (no table is ever wiped whole), so they accumulate too. With a source key:
ACCUMULATING.update({'agent_proposals': ('kind', 'dedup_key'), 'capital_raise_details': ('rcp_no',),
                     'chain_node_notes': ('node_key', 'inputs_hash'), 'corporate_actions': ('rcp_no',),
                     'disclosures': ('rcp_no',), 'earnings_releases': ('accession', 'exhibit_type'),
                     'era_commentary': ('input_hash',),
                     'expectation_claims': ('source', 'url', 'node_key', 'subject', 'metric', 'target_period'),
                     'image_readings': ('image_key',), 'macro_news': ('url',), 'media_analysis': ('image_path',),
                     'research_candidates': ('stock_code', 'detected_date'), 'scrap_links': ('url',),
                     'telegram_group_marks': ('channel', 'msg_id'),
                     'us_customer_concentration': ('ticker', 'period_end', 'period_kind', 'customer', 'benchmark'),
                     'us_pt_changes': ('ticker', 'graded_at', 'firm'), 'us_quarterly': ('ticker', 'q', 'metric'),
                     'us_segments': ('ticker', 'q', 'segment_name'), 'us_ticker_news': ('ticker', 'url'),
                     'narratives': ('topic', 'version'), 'company_profiles': ('stock_code', 'version'),
                     'retail_snapshots': ('episode',)})
# keyed by the document or transcript they are about:
ACCUMULATING.update({'call_extracts': ('doc_id',), 'exp_feed_docs': ('doc_id',), 'image_backfill_docs': ('doc_id',),
                     'knowledge_doc_scans': ('doc_id',), 'transcript_reactions': ('transcript_id',)})
# and keyed by their own id (candidate rows carry band ids; an earlier one is added back under band + old id):
ACCUMULATING.update({table: ('id',) for table in (
    'catalysts', 'knowledge_evidence', 'lens_readings', 'chain_reports', 'stock_briefs', 'thesis_audits')})
# Rewritten whole by its writer (DELETE FROM sector_index, then the full index): a state table.
ACCUMULATING.pop('sector_index', None)
# Accumulating tables whose writer rewrites one part at a time (delete that part, write it again): a candidate row goes
# back only when the MacBook file has nothing of its part, so a part is never half one side and half the other.
PARTITIONS = {'kr_movers': ('trade_date',), 'us_movers': ('trade_date',), 'pricing_observations': ('trade_date',),
              'us_quarterly': ('ticker', 'metric'), 'us_segments': ('ticker', 'q'),
              'us_customer_concentration': ('ticker', 'period_end', 'period_kind', 'benchmark'),
              'catalysts': ('stock_code', 'event_type', 'event_date')}
# Pruned by age (macro_news.py RETAIN_DAYS): only candidate rows inside the MacBook's window go back.
RETENTION = {'macro_news': ('fetched_at', 14)}
NEVER = {'job_runs'}


def _key(row, columns):
    return tuple(str(row.get(c)) for c in columns)


def capture(pg, source):
    """Before the replacement: per table, candidate rows whose natural key the MacBook file lacks."""
    captured, state, excluded = {}, {}, {}
    tables = [t for (t,) in pg.execute('SELECT table_name FROM legacy_supplement_tables ORDER BY 1') if t not in NEVER]
    for table in tables:
        if source.execute('SELECT 1 FROM sqlite_master WHERE name=?', (table,)).fetchone() is None:
            continue
        info = source.execute(f'PRAGMA table_info("{table}")').fetchall()
        columns = ACCUMULATING.get(table)
        if columns == ('id',):  # a surrogate id only: matched by the row's own content (architect #3 6946013683)
            columns = tuple(r[1] for r in info if r[1] != 'id')
        if columns is None:
            columns = tuple(r[1] for r in info if r[5]) or tuple(r[1] for r in info)
        have = {tuple(str(v) for v in row) for row in source.execute(
            f'SELECT {",".join(chr(34) + c + chr(34) for c in columns)} FROM "{table}"')}
        rows = [data for (data,) in pg.execute('SELECT row_data FROM legacy_supplement_rows WHERE table_name=%s '
                                               'ORDER BY row_ordinal', (table,)) if _key(data, columns) not in have]
        if rows and table in ACCUMULATING:
            if table in PARTITIONS:
                part = PARTITIONS[table]
                macbook_parts = {tuple(str(v) for v in row) for row in source.execute(
                    f'SELECT DISTINCT {",".join(chr(34) + c + chr(34) for c in part)} FROM "{table}"')}
                kept = [row for row in rows if _key(row, part) not in macbook_parts]
                excluded[table] = {'part_on_macbook': len(rows) - len(kept)}
                rows = kept
            if table in RETENTION:
                column, days = RETENTION[table]
                cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
                kept = [row for row in rows if str(row.get(column) or '') >= cutoff]
                excluded.setdefault(table, {})['outside_retention'] = len(rows) - len(kept)
                rows = kept
        if rows:
            (captured if table in ACCUMULATING else state)[table] = rows
    return captured, state, excluded


def restore(pg, captured, state):
    """After the replacement: add the accumulating candidate-only rows back, archive the state ones; one transaction."""
    _guard(pg)
    report = {}
    with pg.transaction():
        pg.execute("ALTER TABLE candidate_id_remap ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'candidate'")
        pg.execute('CREATE TABLE IF NOT EXISTS candidate_record_archive (id BIGSERIAL PRIMARY KEY, ledger TEXT NOT NULL, '
                   'record_key JSONB NOT NULL, candidate_row JSONB, source_row JSONB, computed BOOLEAN NOT NULL, '
                   "reason TEXT NOT NULL DEFAULT 'conflict: MacBook value applied', archived_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        for table, rows in captured.items():
            ordinal = pg.execute('SELECT COALESCE(max(row_ordinal), -1) + 1 FROM legacy_supplement_rows WHERE table_name=%s',
                                 (table,)).fetchone()[0]
            renumbered = 0
            for row in rows:
                if isinstance(row.get('id'), int) and row['id'] < start(table):
                    new = start(table) + row['id']
                    pg.execute('INSERT INTO candidate_id_remap (kind, old_id, new_id) VALUES (%s,%s,%s) '
                               'ON CONFLICT (kind, old_id) DO UPDATE SET new_id=excluded.new_id',
                               (f'supplement:{table}', row['id'], new))
                    row, renumbered = {**row, 'id': new}, renumbered + 1
                pg.execute('INSERT INTO legacy_supplement_rows (table_name, row_ordinal, row_data) VALUES (%s,%s,%s)',
                           (table, ordinal, Jsonb(row)))
                ordinal += 1
            pg.execute('UPDATE legacy_supplement_tables SET row_count = (SELECT count(*) FROM legacy_supplement_rows '
                       'WHERE table_name=%s) WHERE table_name=%s', (table, table))
            report[table] = {'kind': 'accumulating', 'added_back': len(rows), 'renumbered': renumbered}
        for table, rows in state.items():
            for row in rows:
                pg.execute('INSERT INTO candidate_record_archive (ledger, record_key, candidate_row, source_row, computed, reason) '
                           "VALUES (%s,%s,%s,NULL,false,'state table: the MacBook rows replaced it')",
                           (f'supplement:{table}', Jsonb([]), Jsonb(row)))
            report[table] = {'kind': 'state', 'archived': len(rows)}
    return report
