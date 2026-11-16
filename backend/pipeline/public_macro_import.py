"""Offline direct-source import. Never fetches data or opens the operating database."""
from datetime import date
from calendar import monthrange
import codecs
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import xml.etree.ElementTree as ET
from zipfile import ZipFile

MAX_ZIP = 16 * 1024 * 1024
MAX_XML = 150 * 1024 * 1024
MAX_XML_DEPTH = 32
MAX_OBSERVATIONS = 2_000_000
IMPORTER_VERSION = 'board-nyfed-import-v2'
SCHEMA = 'public_macro_direct_v1'
BOARD = {
    'h15': {
        'us2y': ('RIFLGFCY02_N.B', {'FREQ':'9', 'UNIT':'Percent:_Per_Year', 'UNIT_MULT':'1', 'CURRENCY':'NA', 'INSTRUMENT':'TCMNOM', 'MATURITY':'Y2'}, 1),
        'us10y': ('RIFLGFCY10_N.B', {'FREQ':'9', 'UNIT':'Percent:_Per_Year', 'UNIT_MULT':'1', 'CURRENCY':'NA', 'INSTRUMENT':'TCMNOM', 'MATURITY':'Y10'}, 1),
    },
    'h41': {
        'fed_bs': ('RESPPMA_N.WW', {'FREQ':'19', 'UNIT':'Currency', 'UNIT_MULT':'1000000', 'CURRENCY':'USD', 'DISTRIBUTION':'TOTC', 'SERIESTYPE':'L'}, 1),
        'tga': ('RESPPLLDT_XAW_N.WW', {'FREQ':'19', 'UNIT':'Currency', 'UNIT_MULT':'1000000', 'CURRENCY':'USD', 'COMPONENT':'DEPUSTG', 'SERIESTYPE':'A'}, 1),
    },
    'h6': {
        'm2': ('M2.M', {'FREQ':'129', 'UNIT':'Currency', 'UNIT_MULT':'1e+09', 'CURRENCY':'USD', 'ADJUSTED':'SA'}, 1),
    },
}
INDICATORS = {'us2y':'risk_us2y', 'us10y':'risk_us10y', 'fed_bs':'macro_fed_bs',
              'tga':'macro_tga', 'm2':'macro_m2', 'rrp':'macro_rrp'}
RRP_URL = 'https://markets.newyorkfed.org/api/rp/reverserepo/all/results/last/200.json'


def board_url(release):
    return f'https://www.federalreserve.gov/releases/{release}/data/FRB_{release}_xml.zip'


def _date(value, monthly=False):
    if monthly and isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        parsed = date.fromisoformat(value)
        if parsed.day != monthrange(parsed.year, parsed.month)[1]:
            raise ValueError('Monthly Board observation must be a month-end date')
        return parsed.replace(day=1).isoformat()
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}' if monthly else r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Invalid observation date')
    value = value + '-01' if monthly else value
    date.fromisoformat(value)
    return value


def _number(value):
    if isinstance(value, bool):
        raise ValueError('Invalid numeric value')
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError('Invalid numeric value') from None
    if not math.isfinite(value):
        raise ValueError('Nonfinite observation')
    return value


class _BoundedXML:
    def __init__(self, source):
        self.source, self.count, self.tail = source, 0, b''
        self.decoder = codecs.getincrementaldecoder('utf-8-sig')('strict')

    def read(self, size=-1):
        data = self.source.read(min(size if size >= 0 else 65536, 65536))
        self.count += len(data)
        if self.count > MAX_XML:
            raise ValueError('XML size limit exceeded')
        # Board data is UTF-8. Reject UTF-16/32 before ElementTree can select
        # another encoding and thereby bypass the byte-level DTD/entity check.
        if b'\x00' in data:
            raise ValueError('Only UTF-8 XML is supported')
        try:
            self.decoder.decode(data, final=not data)
        except UnicodeError:
            raise ValueError('Only UTF-8 XML is supported') from None
        probe = (self.tail + data).upper()
        if b'<!DOCTYPE' in probe or b'<!ENTITY' in probe:
            raise ValueError('XML declarations are not supported')
        self.tail = probe[-16:]
        return data


def parse_board_zip(path, release):
    """Return canonical key -> sorted (ISO date, value), retaining Board source units.

    fed_bs/tga remain USD millions; m2 remains USD billions. The existing
    numeric macro calculator performs its own millions-to-billions conversion."""
    release = release.lower()
    specs = BOARD[release]
    if Path(path).stat().st_size > MAX_ZIP:
        raise ValueError('ZIP size limit exceeded')
    selected = {item[0]: (key, item[1], item[2]) for key, item in specs.items()}
    out, seen = {key: {} for key in specs}, set()
    with ZipFile(path) as archive:
        entries = [i for i in archive.infolist() if i.filename == f'{release.upper()}_data.xml']
        if len(entries) != 1 or entries[0].file_size > MAX_XML or entries[0].flag_bits & 1:
            raise ValueError('Invalid Board data member')
        with archive.open(entries[0]) as stream:
            active, stack, observations = None, [], 0
            parser = ET.XMLParser(encoding='utf-8')
            for event, element in ET.iterparse(_BoundedXML(stream), events=('start', 'end'), parser=parser):
                tag = element.tag.rsplit('}', 1)[-1]
                if event == 'start':
                    stack.append(element)
                    if len(stack) > MAX_XML_DEPTH:
                        raise ValueError('XML depth limit exceeded')
                    if tag == 'Obs':
                        observations += 1
                        if observations > MAX_OBSERVATIONS:
                            raise ValueError('Observation count limit exceeded')
                    if tag == 'Series':
                        active = selected.get(element.get('SERIES_NAME'))
                        if active:
                            key, attributes, scale = active
                            if key in seen or any(element.get(k) != v for k, v in attributes.items()):
                                raise ValueError('Duplicate series or unexpected Board metadata')
                            seen.add(key)
                    continue
                if tag == 'Obs' and active:
                    key, attributes, scale = active
                    stamp = _date(element.get('TIME_PERIOD'), monthly=release == 'h6')
                    status = element.get('OBS_STATUS')
                    if status not in {'A', 'NA', 'ND', 'NC'}:
                        raise ValueError('Unknown observation status')
                    if status == 'A':
                        value = _number(element.get('OBS_VALUE')) * scale
                        if stamp in out[key]:
                            raise ValueError('Duplicate observation date')
                        out[key][stamp] = value
                if tag == 'Series':
                    active = None
                # Remove each completed node, including irrelevant series/observations.
                stack.pop()
                if stack:
                    stack[-1].remove(element)
                element.clear()
    if any(not values for values in out.values()):
        raise ValueError('Required Board series is missing or empty')
    return {key: sorted(values.items()) for key, values in out.items()}


def parse_rrp(payload):
    """Treasury overnight reverse repos; distinct operations on one date are summed.

    Duplicate operation IDs are rejected, not double-counted. Non-Treasury
    tranches and non-overnight/non-reverse operations do not enter the series.
    """
    operations = payload['repo']['operations']
    if not isinstance(operations, list) or len(operations) > 1000:
        raise ValueError('Invalid RRP operation list')
    seen, amounts = set(), {}
    for operation in operations:
        identifier = operation.get('operationId')
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise ValueError('Missing or duplicate RRP operation ID')
        seen.add(identifier)
        if operation.get('operationType') != 'Reverse Repo' or operation.get('term') != 'Overnight':
            continue
        stamp = _date(operation.get('operationDate'))
        details = operation.get('details')
        if not isinstance(details, list):
            raise ValueError('Missing RRP tranche details')
        treasury = [item for item in details if item.get('securityType') == 'Treasury']
        if len(treasury) > 1:
            raise ValueError('Duplicate Treasury tranche')
        if not treasury:
            continue
        amount = _number(treasury[0].get('amtAccepted'))
        if amount < 0:
            raise ValueError('Negative accepted amount')
        amounts[stamp] = amounts.get(stamp, 0) + amount / 1e9
        if not math.isfinite(amounts[stamp]):
            raise ValueError('RRP total overflow')
    if not amounts:
        raise ValueError('No Treasury overnight reverse repos')
    return {'rrp': sorted(amounts.items())}


def write_snapshot(output, series, receipts):
    """Publish a verified new SQLite file atomically; existing destinations never change.

    Receipts are keyed by canonical key and require source_url, sha256, series_id.
    Fetched time and source attributes should additionally be retained by caller.
    """
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if set(series) != set(INDICATORS) or set(receipts) != set(INDICATORS):
        raise ValueError('Exactly six series and receipts are required')
    rows, receipt_rows = [], []
    for key, indicator in INDICATORS.items():
        expected = next(((rel, spec) for rel, items in BOARD.items() for k, spec in items.items() if k == key), None)
        source, identifier = (board_url(expected[0]), expected[1][0]) if expected else (RRP_URL, 'overnight_treasury_rrp')
        receipt = receipts[key]
        if (receipt.get('source_url') != source or receipt.get('series_id') != identifier
                or not isinstance(receipt.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', receipt['sha256'])):
            raise ValueError('Invalid direct-source receipt')
        receipt_rows.append((key, json.dumps(receipt, allow_nan=False, sort_keys=True)))
        values = {}
        for stamp, value in series[key]:
            stamp = _date(stamp)
            if stamp in values:
                raise ValueError('Duplicate snapshot observation')
            values[stamp] = _number(value)
        if not values:
            raise ValueError('Empty snapshot series')
        rows.extend((indicator, stamp, value) for stamp, value in sorted(values.items())[-400:])
    fd, temporary = tempfile.mkstemp(prefix='.public-macro-', suffix='.sqlite', dir=output.parent)
    os.close(fd)
    try:
        conn = sqlite3.connect(temporary)
        try:
            conn.executescript('''
                CREATE TABLE market_indicators(indicator TEXT NOT NULL, snapshot_date TEXT NOT NULL, value REAL NOT NULL,
                                               PRIMARY KEY(indicator,snapshot_date));
                CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE source_receipts(key TEXT PRIMARY KEY,receipt_json TEXT NOT NULL);
            ''')
            conn.executemany('INSERT INTO market_indicators VALUES (?,?,?)', rows)
            conn.executemany('INSERT INTO source_receipts VALUES (?,?)', receipt_rows)
            conn.execute('INSERT INTO meta VALUES (?,?)', ('schema', SCHEMA))
            conn.commit()
            if conn.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('Snapshot integrity check failed')
        finally:
            conn.close()
        os.chmod(temporary, 0o600)
        with open(temporary, 'rb') as stream:
            os.fsync(stream.fileno())
        # Same-filesystem link is atomic and refuses an existing name, including
        # a destination created after the initial check. Never use os.replace.
        os.link(temporary, output)
    finally:
        os.unlink(temporary)
    return output
