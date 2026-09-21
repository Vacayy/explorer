"""Fixed, read-only export boundary between Explorer and generated analysis code.

This module deliberately does not import Explorer's database helpers or services.
The caller owns the trusted destination parent; generated code never chooses it.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
import time
from datetime import date, datetime, timezone
from typing import Callable

import pyarrow as pa
import pyarrow.parquet as pq


SCHEMA_VERSION = 1
EXPORT_TIMEOUT_SECONDS = 60
MAX_PRICE_ROWS = 5_000_000
MAX_COMPANY_ROWS = 100_000
DAILY_COLUMNS = ("code", "date", "open", "high", "low", "close", "volume", "mktcap", "shares")
DAILY_SCHEMA = pa.schema(
    [("code", pa.string()), ("date", pa.string())]
    + [(name, pa.float64()) for name in DAILY_COLUMNS[2:]]
)
UNIVERSE_SCHEMA = pa.schema([(name, pa.string()) for name in ("code", "name", "market")])


class SnapshotError(RuntimeError):
    """An export was cancelled, unsafe, oversized, or inconsistent."""


def _iso_date(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("as_of must be an ISO market date (YYYY-MM-DD)")
    return date.fromisoformat(value).isoformat()


def _regular_file(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise SnapshotError("source must be a regular, non-linked database file")


def _reject_link_ancestors(path: Path) -> None:
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise SnapshotError("symlinks are not allowed in snapshot paths")


def _digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def _number(value: object) -> float | None:
    try:
        number = float(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number is not None and math.isfinite(number) else None


def _bad_prices(row: dict) -> bool:
    o, h, low, c = (row[key] for key in ("open", "high", "low", "close"))
    return (
        any(value is None or value <= 0 for value in (o, h, low, c))
        or h < max(o, low, c)
        or low > min(o, h, c)
        or row["volume"] is None
        or row["volume"] < 0
    )


def source_fingerprint(source_db: Path, as_of: str | None = None) -> str:
    """원본이 바뀌었는지 판별하는 내용 지문 (D-193 스냅샷 재사용).

    실행마다 137만 행을 다시 내보내지 않기 위해, 내보내기가 읽는 모든 원천(stock_prices·companies·
    수집 이력 DB의 prices/coverage/metadata)의 행 수·최신일·합계와 요청 기준일, 그리고 이 파일 자체의
    해시(내보내기 로직이 바뀌면 재사용하지 않음)를 sha256으로 접는다. 읽기 전용, 실측 0.4초.
    """
    source_db = Path(source_db).absolute()
    if as_of is not None:
        as_of = _iso_date(as_of)
    _reject_link_ancestors(source_db)
    _regular_file(source_db)
    source_db = source_db.resolve(strict=True)
    history_path = source_db.with_name("market_history.sqlite")
    has_history = history_path.exists() or history_path.is_symlink()
    connection = sqlite3.connect(source_db.as_uri() + "?mode=ro", uri=True, timeout=2)
    try:
        connection.execute("PRAGMA query_only=ON")
        parts: dict = {"as_of": as_of, "export_code": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        parts["main"] = list(connection.execute(
            "SELECT COUNT(*), MAX(trade_date), MIN(trade_date), TOTAL(close), TOTAL(volume), TOTAL(market_cap) "
            "FROM stock_prices WHERE (? IS NULL OR trade_date <= ?)", (as_of, as_of)).fetchone())
        parts["companies"] = list(connection.execute(
            "SELECT COUNT(*), TOTAL(LENGTH(corp_name)), TOTAL(LENGTH(market)) FROM companies WHERE stock_code IS NOT NULL").fetchone())
        if has_history:
            _reject_link_ancestors(history_path)
            _regular_file(history_path)
            connection.execute("ATTACH DATABASE ? AS history", (history_path.as_uri() + "?mode=ro",))
            parts["history"] = {
                "metadata": sorted(connection.execute("SELECT key,value FROM history.metadata").fetchall()),
                "coverage": list(connection.execute("SELECT COUNT(*), TOTAL(LENGTH(code)) FROM history.coverage WHERE status='collected'").fetchone()),
                "prices": list(connection.execute(
                    "SELECT COUNT(*), MAX(date), MIN(date), TOTAL(close), TOTAL(volume) FROM history.prices "
                    "WHERE (? IS NULL OR date <= ?)", (as_of, as_of)).fetchone()),
            }
    finally:
        connection.close()
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def export_snapshot(
    source_db: Path,
    destination: Path,
    as_of: str | None = None,
    cancel: Callable[[], bool] | None = None,
) -> dict:
    """Publish a fresh immutable Parquet snapshot using one bounded read transaction.

    ``destination.parent`` must already be a host-owned directory outside every
    sandbox workspace. The source connection uses SQLite ``mode=ro`` (not
    ``immutable``), so committed WAL records participate in the consistent read.
    Source paths and unrelated tables are never exposed in the manifest.
    """
    source_db, destination = Path(source_db).absolute(), Path(destination).absolute()
    if as_of is not None:
        as_of = _iso_date(as_of)
    _reject_link_ancestors(source_db)
    _reject_link_ancestors(destination)
    _regular_file(source_db)
    parent_info = destination.parent.lstat()
    if not stat.S_ISDIR(parent_info.st_mode) or destination.parent.is_symlink():
        raise SnapshotError("snapshot parent must be a trusted non-symlink directory")
    if destination.exists() or destination.is_symlink():
        raise SnapshotError("snapshot destination must be fresh")
    source_db = source_db.resolve(strict=True)
    destination = destination.parent.resolve(strict=True) / destination.name
    started = time.monotonic()

    def check() -> None:
        if cancel and cancel():
            raise SnapshotError("snapshot export cancelled")
        if time.monotonic() - started > EXPORT_TIMEOUT_SECONDS:
            raise SnapshotError("snapshot export timed out")

    check()
    staging = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=destination.parent))
    connection = None
    try:
        connection = sqlite3.connect(source_db.as_uri() + "?mode=ro", uri=True, timeout=2)
        connection.execute("PRAGMA query_only=ON")
        # A trusted ETL can publish coherent provider-adjusted history beside
        # the original DB. Never splice that vendor's rows into old price bases.
        history_path = source_db.with_name('market_history.sqlite')
        history_meta, history_codes = None, set()
        has_history = history_path.exists() or history_path.is_symlink()
        if has_history:
            _reject_link_ancestors(history_path)
            _regular_file(history_path)
            connection.execute('ATTACH DATABASE ? AS history', (history_path.as_uri() + '?mode=ro',))
        # A progress handler also bounds a SELECT before it produces any rows.
        def progress() -> int:
            try:
                check()
                return 0
            except SnapshotError:
                return 1

        connection.set_progress_handler(progress, 10000)
        connection.execute("BEGIN")
        if has_history:
            history_meta = {key: json.loads(value) for key, value in connection.execute('SELECT key,value FROM history.metadata')}
            if history_meta.get('schema_version') != 1 or (history_meta.get('provider') or {}).get('name') != 'NAVER':
                raise SnapshotError('unsupported collected history schema or provider')
            history_codes = {row[0] for row in connection.execute("SELECT code FROM history.coverage WHERE status='collected'")}
        actual_as_of = connection.execute(
            "SELECT MAX(trade_date) FROM stock_prices WHERE (? IS NULL OR trade_date <= ?)",
            (as_of, as_of),
        ).fetchone()[0]
        if actual_as_of is None:
            raise SnapshotError("no market data available at the requested date")
        actual_as_of = _iso_date(actual_as_of)
        source_latest_date = actual_as_of
        if history_meta and history_meta['as_of'] < actual_as_of:
            actual_as_of = _iso_date(history_meta['as_of'])
        quality: dict[str, dict] = {}
        observed_dates: set[str] = set()
        per_code_dates: dict[str, set[str]] = {}
        rows = 0
        invalid_identifiers = 0
        if history_meta:
            cursor = connection.execute('''
                SELECT p.code,p.date,p.open,p.high,p.low,p.close,p.volume,s.market_cap,s.shares
                FROM history.prices p LEFT JOIN main.stock_prices s ON s.stock_code=p.code AND s.trade_date=p.date
                WHERE p.date<=?
                UNION ALL
                SELECT s.stock_code,s.trade_date,s.open,s.high,s.low,s.close,s.volume,s.market_cap,s.shares
                FROM main.stock_prices s WHERE s.trade_date<=? AND NOT EXISTS
                    (SELECT 1 FROM history.coverage h WHERE h.code=s.stock_code AND h.status='collected')
                ORDER BY 1,2''', (actual_as_of, actual_as_of))
        else:
            cursor = connection.execute(
                "SELECT stock_code, trade_date, open, high, low, close, volume, market_cap, shares "
                "FROM stock_prices WHERE trade_date <= ? ORDER BY stock_code, trade_date",
                (actual_as_of,),
            )
        with pq.ParquetWriter(staging / "daily.parquet", DAILY_SCHEMA, compression="zstd") as writer:
            while batch := cursor.fetchmany(8192):
                check()
                rows += len(batch)
                if rows > MAX_PRICE_ROWS:
                    raise SnapshotError("snapshot price row limit exceeded")
                records = []
                for raw in batch:
                    code, day = raw[0], raw[1]
                    try:
                        # KRX identifiers include alphabetic characters in new
                        # listings and preferred shares (e.g. 0001A0, 00088K).
                        valid = isinstance(code, str) and re.fullmatch(r"[0-9A-Z]{6}", code)
                        _iso_date(day)
                    except (ValueError, TypeError):
                        valid = False
                    if not valid:
                        invalid_identifiers += 1
                        continue
                    row = dict(zip(DAILY_COLUMNS, (code, day, *map(_number, raw[2:]))))
                    records.append(row)
                    observed_dates.add(day)
                    days = per_code_dates.setdefault(code, set())
                    info = quality.setdefault(code, {
                        "first_date": day, "last_date": day, "rows": 0,
                        "invalid_ohlcv_rows": 0, "duplicate_dates": 0,
                        "missing_market_cap_rows": 0, "missing_shares_rows": 0,
                        "price_adjustment": "adjusted" if code in history_codes else "unknown",
                        "source": "NAVER" if code in history_codes else "unknown",
                    })
                    info["rows"] += 1
                    info["last_date"] = day
                    info["invalid_ohlcv_rows"] += int(_bad_prices(row))
                    info["duplicate_dates"] += int(day in days)
                    info["missing_market_cap_rows"] += int(row["mktcap"] is None)
                    info["missing_shares_rows"] += int(row["shares"] is None)
                    days.add(day)
                if records:
                    writer.write_table(pa.Table.from_pylist(records, schema=DAILY_SCHEMA))
        check()
        companies: dict[str, list[tuple[str, str]]] = {}
        # No private fields or arbitrary user SQL can enter the export.
        cursor = connection.execute(
            "SELECT stock_code, corp_name, market FROM companies "
            "WHERE stock_code IS NOT NULL ORDER BY stock_code, corp_name, market"
        )
        company_count = 0
        while batch := cursor.fetchmany(8192):
            check()
            company_count += len(batch)
            if company_count > MAX_COMPANY_ROWS:
                raise SnapshotError("snapshot company row limit exceeded")
            for code, name, market in batch:
                if code in quality:
                    companies.setdefault(code, []).append((str(name or code), str(market or "UNKNOWN")))
        # End the read transaction before hashing/quality checks or any model call.
        connection.rollback()
        connection.close()
        connection = None
        universe = []
        calendar_dates = sorted(observed_dates)
        if not calendar_dates:
            raise SnapshotError("no valid stock/date identifiers available")
        for code, info in quality.items():
            check()
            matches = companies.get(code, [])
            name, market = matches[0] if matches else (code, "UNKNOWN")
            if len({entry[1] for entry in matches}) > 1:
                market = "UNKNOWN"
            universe.append({"code": code, "name": name, "market": market})
            info["company_status"] = "ambiguous" if len(matches) > 1 else ("known" if matches else "missing")
            info["security_type"] = "unknown"
            info["as_of_present"] = actual_as_of in per_code_dates[code]
            info["observed_missing_dates"] = [
                day for day in calendar_dates
                if info["first_date"] <= day <= info["last_date"] and day not in per_code_dates[code]
            ]
        pq.write_table(pa.Table.from_pylist(universe, schema=UNIVERSE_SCHEMA), staging / "universe.parquet", compression="zstd")
        all_adjusted = bool(quality) and all(info['price_adjustment'] == 'adjusted' for info in quality.values())
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": destination.name,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "requested_as_of": as_of,
            "as_of": actual_as_of,
            "latest_date": actual_as_of,
            "source_latest_date": source_latest_date,
            "first_date": calendar_dates[0] if calendar_dates else None,
            "rows": rows - invalid_identifiers,
            "symbols": len(universe),
            "files": {name: {"sha256": _digest(staging / name), "bytes": (staging / name).stat().st_size}
                      for name in ("daily.parquet", "universe.parquet")},
            "columns": {"daily": list(DAILY_COLUMNS), "universe": ["code", "name", "market"]},
            "price_adjustment": {"status": "adjusted" if all_adjusted else "unknown",
                                 "source": "NAVER_via_FinanceDataReader" if all_adjusted else "mixed_or_unrecorded"},
            "history_collection": history_meta,
            "calendar": {"source": "observed_price_date_union", "version": 1,
                         "status": "provisional", "dates": calendar_dates},
            "quality": quality,
            "excluded": {"invalid_code_or_date_rows": invalid_identifiers},
            "warnings": [
                *(["가격 조정 여부와 공급자 이력이 확인되지 않은 기존 시세가 포함되어 있습니다."] if not all_adjusted else []),
                *(["가격은 별도 수집한 네이버 수정주가 이력이며 시총은 Explorer 기준일 저장값입니다."] if history_meta else []),
                *([f"수정주가 이력은 {actual_as_of}까지 수집되어 있습니다. 원천 최신일 {source_latest_date}까지 추가 수집이 필요합니다."]
                  if actual_as_of < source_latest_date else []),
                "거래일 목록은 보유 시세 날짜의 합집합이며 공식 거래소 달력이 아닙니다.",
                "종목 유형을 확인하지 못해 보통주 전용 유니버스로 간주할 수 없습니다.",
                *([f"종목 코드 또는 날짜 형식이 잘못된 {invalid_identifiers}개 시세 행은 내보내지 않았습니다."]
                  if invalid_identifiers else []),
            ],
        }
        check()
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        for path in staging.iterdir():
            path.chmod(0o444)
        if destination.exists() or destination.is_symlink():
            raise SnapshotError("snapshot destination appeared during export")
        os.rename(staging, destination)
        return manifest
    except sqlite3.OperationalError as exc:
        if str(exc) == "interrupted":
            check()
        raise SnapshotError(f"read-only market export failed: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()
        if staging.exists():
            shutil.rmtree(staging)
