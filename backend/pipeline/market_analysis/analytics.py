"""Deterministic, standalone market skills; safe to copy into a read-only sandbox.

Only immutable Parquet inputs are read. No Explorer imports, network, SQL on the
source database, file writes, or generated-code evaluation occur in this module.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import deque
from datetime import date, timedelta
import hashlib
import json
import math
import re
from pathlib import Path
import stat

import duckdb


SKILL_VERSION = "market-screen-v1"
PATTERN_DEFINITION = {
    "version": "consecutive-pivots-v1",
    "trough_selection": "three_consecutive_confirmed_local_minima",
    "neckline": "line_through_highest_confirmed_peak_between_each_pair_of_troughs",
    "min_shoulder_depth": 0.05,
    "prior_window": 20,
    "prior_rise": 0.05,
    "breakout": "close_crosses_strictly_above_neckline",
    "pivot_ties": "excluded",
    "formation_duration_limit": None,
    "signal_type": "retrospective_screen_with_confirmation_dates",
}
DEFAULT_SPEC = {
    "mode": "pattern", "strategy_conditions": [], "expression": None, "universe_codes": None,
    "market": "all", "as_of": None, "min_market_cap": 500_000_000_000,
    "pattern": "inverse_head_shoulders", "lookback_days": 90,
    "window_scope": "breakout", "pivot_width": 5, "shoulder_tolerance": 0.15,
    "require_52w": True, "include_same_day": False, "ma_period": 20,
    "hold_days": 14, "price_basis": "close", "require_ma": True,
    "price_adjustment": "unknown",
}


def _normalise_spec(spec: dict) -> dict:
    if not isinstance(spec, dict) or set(spec) - set(DEFAULT_SPEC):
        raise ValueError("unknown analysis fields")
    defaults = dict(DEFAULT_SPEC)
    if spec.get("mode") == "catalog":
        defaults.update(min_market_cap=0, pattern="none", require_52w=False, require_ma=False)
    values = {**defaults, **spec}
    for key, allowed in {
        "mode": ("pattern", "catalog"),
        "market": ("all", "KOSPI", "KOSDAQ"),
        "pattern": ("none", "inverse_head_shoulders"),
        "window_scope": ("breakout", "formation"),
        "price_basis": ("close", "low"),
        "price_adjustment": ("unknown", "adjusted"),
    }.items():
        if values[key] not in allowed:
            raise ValueError(f"unsupported {key}")
    for key, minimum, maximum in (("lookback_days", 1, 756), ("pivot_width", 1, 30),
                                   ("ma_period", 1, 252), ("hold_days", 1, 252)):
        if type(values[key]) is not int or not minimum <= values[key] <= maximum:
            raise ValueError(f"invalid {key}")
    for key, minimum, maximum in (("shoulder_tolerance", 0, 1), ("min_market_cap", 0, 1e18)):
        if isinstance(values[key], bool) or not isinstance(values[key], (int, float)):
            raise ValueError(f"invalid {key}")
        if not math.isfinite(values[key]) or not minimum <= values[key] <= maximum:
            raise ValueError(f"invalid {key}")
    for key in ("require_52w", "include_same_day", "require_ma"):
        if type(values[key]) is not bool:
            raise ValueError(f"invalid {key}")
    if values["as_of"] is not None:
        if date.fromisoformat(values["as_of"]).isoformat() != values["as_of"]:
            raise ValueError("as_of must be an ISO date")
    conditions = values["strategy_conditions"]
    if not isinstance(conditions, list) or len(conditions) > 12:
        raise ValueError("invalid strategy conditions")
    if conditions:
        if __package__:
            from .strategies import normalize_condition
        else:
            from strategies import normalize_condition
        values["strategy_conditions"] = [normalize_condition(item) for item in conditions]
        ids = [item["strategy_id"] for item in values["strategy_conditions"]]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate strategy conditions")
    if values["expression"] is not None:
        if __package__:
            from .expression import normalize_expression
        else:
            from expression import normalize_expression
        values["expression"] = normalize_expression(values["expression"])
        if conditions:
            raise ValueError("expression and strategy_conditions are mutually exclusive")
    codes = values["universe_codes"]
    if codes is not None:
        if not isinstance(codes, list) or len(codes) > 10000 or any(not isinstance(c, str) or not re.fullmatch(r"[0-9A-Z]{6}", c) for c in codes):
            raise ValueError("invalid universe_codes")
        values["universe_codes"] = sorted(set(codes))
    if values["mode"] == "catalog" and ((not conditions and values["expression"] is None) or values["pattern"] != "none"
                                         or values["require_52w"] or values["require_ma"]):
        raise ValueError("catalog requires explicit strategy conditions only")
    return values


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _input(data_dir: str | Path) -> tuple[Path, dict]:
    folder = Path(data_dir)
    if folder.is_symlink():
        raise ValueError("linked snapshot directory")
    for name in ("manifest.json", "daily.parquet", "universe.parquet"):
        info = (folder / name).lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("snapshot files must be regular non-linked files")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported snapshot version")
    for name in ("daily.parquet", "universe.parquet"):
        if _sha256(folder / name) != manifest["files"][name]["sha256"]:
            raise ValueError("snapshot input hash mismatch")
    return folder, manifest


def _connection():
    # In-memory connection only; extension downloads and writes are not needed.
    return duckdb.connect(":memory:", config={"threads": "1", "enable_external_access": "true",
                                             "autoload_known_extensions": "false",
                                             "autoinstall_known_extensions": "false"})


def _series(connection, folder: Path, as_of: str, code: str | None = None):
    cursor = connection.execute(
        "SELECT code,date,open,high,low,close,volume,mktcap,shares "
        "FROM read_parquet(?) WHERE date <= ? AND (? IS NULL OR code = ?) ORDER BY code,date",
        [str(folder / "daily.parquet"), as_of, code, code],
    )
    # Arrow batches converted in C (to_pylist) halve the row-materialisation cost
    # versus dict(zip(...)) per row; values keep the same Python types (str/float/None).
    current, records = None, []
    for batch in cursor.to_arrow_reader(4096):
        for row in batch.to_pylist():
            code_value = row["code"]
            if current is not None and code_value != current:
                yield current, records
                records = []
            current = code_value
            records.append(row)
    if current is not None:
        yield current, records


def _valid_price(row: dict) -> bool:
    values = [row[key] for key in ("open", "high", "low", "close", "volume")]
    if any(value is None or not math.isfinite(value) for value in values):
        return False
    o, high, low, close, volume = values
    return min(o, high, low, close) > 0 and high >= max(o, low, close) and low <= min(o, high, close) and volume >= 0


def _moving_average(rows: list[dict], period: int) -> list[float | None]:
    window, total, result = deque(), 0.0, []
    for row in rows:
        value = row["close"]
        # Bad rows are never made into tradable candles or silently imputed.
        if value is None or not math.isfinite(value) or value <= 0:
            window.clear()
            total = 0.0
            result.append(None)
            continue
        window.append(value)
        total += value
        if len(window) > period:
            total -= window.popleft()
        result.append(total / period if len(window) == period else None)
    return result


def _pivots(rows: list[dict], width: int, key: str, low: bool) -> list[int]:
    result = []
    for index in range(width, len(rows) - width):
        value = rows[index][key]
        neighbors = [rows[j][key] for j in range(index - width, index + width + 1) if j != index]
        if (value < min(neighbors)) if low else (value > max(neighbors)):
            result.append(index)
    return result


def _patterns(rows: list[dict], spec: dict, window_start: str) -> list[dict]:
    width = spec["pivot_width"]
    troughs = _pivots(rows, width, "low", True)
    peaks = _pivots(rows, width, "high", False)
    candidates = []
    for left, head, right in zip(troughs, troughs[1:], troughs[2:]):
        if spec["window_scope"] == "formation" and rows[left]["date"] < window_start:
            continue
        ls, hd, rs = (rows[i]["low"] for i in (left, head, right))
        if not hd < min(ls, rs) or abs(ls - rs) / min(ls, rs) > spec["shoulder_tolerance"]:
            continue
        left_peaks = peaks[bisect_left(peaks, left + 1):bisect_left(peaks, head)]
        right_peaks = peaks[bisect_left(peaks, head + 1):bisect_left(peaks, right)]
        if not left_peaks or not right_peaks or left < PATTERN_DEFINITION["prior_window"]:
            continue
        p1 = max(left_peaks, key=lambda i: rows[i]["high"])
        p2 = max(right_peaks, key=lambda i: rows[i]["high"])
        slope = (rows[p2]["high"] - rows[p1]["high"]) / (p2 - p1)
        def neckline(index):
            return rows[p1]["high"] + slope * (index - p1)
        if not all(rows[i]["low"] <= neckline(i) * (1 - PATTERN_DEFINITION["min_shoulder_depth"])
                   for i in (left, right)):
            continue
        prior_high = max(row["high"] for row in rows[left - PATTERN_DEFINITION["prior_window"]:left])
        if prior_high < ls * (1 + PATTERN_DEFINITION["prior_rise"]):
            continue
        breakout = next((i for i in range(right + 1, len(rows))
                         if rows[i]["close"] > neckline(i) and rows[i - 1]["close"] <= neckline(i - 1)), None)
        if breakout is None or rows[breakout]["date"] < window_start:
            continue
        confirmed = max(right + width, p2 + width)
        candidates.append({
            "definition_version": PATTERN_DEFINITION["version"],
            "left_shoulder": rows[left]["date"], "head": rows[head]["date"],
            "right_shoulder": rows[right]["date"], "peak1": rows[p1]["date"], "peak2": rows[p2]["date"],
            "ls_low": ls, "head_low": hd, "rs_low": rs,
            "peak1_high": rows[p1]["high"], "peak2_high": rows[p2]["high"],
            "neck_slope": slope, "prior_max_high": prior_high,
            "breakout_date": rows[breakout]["date"], "breakout_close": rows[breakout]["close"],
            "breakout_neck": neckline(breakout), "pivot_confirmed_at": rows[confirmed]["date"],
            "known_at": rows[max(confirmed, breakout)]["date"], "retrospective": breakout < confirmed,
        })
    return sorted(candidates, key=lambda item: item["breakout_date"], reverse=True)


def _high52_events(rows: list[dict], start: str) -> list[dict]:
    """Strict close > max(high) on dates [event - 365 days, event), with full history."""
    previous, events = deque(), []
    earliest = rows[0]["date"]
    for row in rows:
        threshold = (date.fromisoformat(row["date"]) - timedelta(days=365)).isoformat()
        while previous and previous[0]["date"] < threshold:
            previous.popleft()
        if row["date"] >= start and earliest <= threshold and previous and row["close"] > previous[0]["high"]:
            events.append({"date": row["date"], "close": row["close"], "high": row["high"], "previous_high": previous[0]["high"],
                           "window_start": threshold, "window_end_exclusive": row["date"]})
        while previous and previous[-1]["high"] <= row["high"]:
            previous.pop()
        previous.append(row)
    return events


def screen(data_dir: str | Path, spec: dict) -> dict:
    """Dispatch all requested conditions through the same deterministic verifier."""
    spec = _normalise_spec(spec)
    if spec["expression"] is not None:
        if __package__:
            from .expression_screen import screen_expression
        else:
            from expression_screen import screen_expression
        base = _screen_pattern(data_dir, spec) if spec["mode"] == "pattern" else None
        return screen_expression(data_dir, spec, base_result=base)
    if not spec["strategy_conditions"]:
        return _screen_pattern(data_dir, spec)
    if __package__:
        from .strategy_screen import screen_catalog
    else:
        from strategy_screen import screen_catalog
    base = _screen_pattern(data_dir, spec) if spec["mode"] == "pattern" else None
    return screen_catalog(data_dir, spec, base_result=base)


def _screen_pattern(data_dir: str | Path, spec: dict) -> dict:
    """Evaluate the supported conditions without treating missing history as failure."""
    spec = _normalise_spec(spec)
    folder, manifest = _input(data_dir)
    requested = spec["as_of"] or manifest["as_of"]
    calendar = [day for day in manifest["calendar"]["dates"] if day <= requested]
    if not calendar:
        raise ValueError("no snapshot prices at the requested date")
    as_of = calendar[-1]
    adjusted = manifest.get("price_adjustment", {}).get("status") == "adjusted"
    official_calendar = manifest.get("calendar", {}).get("status") == "verified"
    warnings = list(manifest.get("warnings", []))
    if not adjusted:
        warnings.append("수정주가 여부가 확인되지 않아 가격 조건의 일치 결과는 잠정 결과입니다.")
    if not official_calendar:
        warnings.append("거래일은 관측일 기준이며 거래정지·휴장·원천 누락을 완전히 구분하지 못합니다.")
    if as_of != requested:
        warnings.append(f"요청 기준일 {requested} 대신 마지막 관측일 {as_of}까지 계산했습니다.")
    if spec["pattern"] != "none":
        warnings.append("역헤드앤숄더 v1은 연속된 세 저점 피벗을 사용하며 PoC의 모든 저점 조합 탐색과 다릅니다.")
    window_start = calendar[max(0, len(calendar) - spec["lookback_days"])]
    history_sessions = 1
    if spec["require_ma"]:
        history_sessions = max(history_sessions, spec["ma_period"] + spec["hold_days"] - 1)
    if spec["pattern"] != "none":
        history_sessions = max(history_sessions, spec["lookback_days"] + PATTERN_DEFINITION["prior_window"] + 2 * spec["pivot_width"])
    if spec["require_52w"]:
        history_sessions = max(history_sessions, spec["lookback_days"])
    required_start = calendar[max(0, len(calendar) - history_sessions)]
    if spec["require_52w"]:
        required_start = min(required_start, (date.fromisoformat(window_start) - timedelta(days=365)).isoformat())
    counts = {"universe": 0, "evaluated": 0, "matched": 0, "excluded": 0, "failed": 0, "unevaluated": 0}
    items, excluded, seen = [], [], set()
    scope = set(spec["universe_codes"]) if spec.get("universe_codes") is not None else None
    with _connection() as connection:
        universe = {code: {"name": name, "market": market} for code, name, market in connection.execute(
            "SELECT code,name,market FROM read_parquet(?)", [str(folder / "universe.parquet")]).fetchall()}
        for code, rows in _series(connection, folder, as_of):
            if scope is not None and code not in scope:
                continue
            seen.add(code)
            info = universe.get(code, {"name": code, "market": "UNKNOWN"})
            if spec["market"] != "all" and info["market"] not in (spec["market"], "UNKNOWN"):
                continue
            counts["universe"] += 1
            reason = None
            if spec["market"] != "all" and info["market"] == "UNKNOWN":
                reason = "unknown_market"
            elif rows[-1]["date"] != as_of:
                reason = "missing_as_of"
            cap = rows[-1]["mktcap"]
            cap = cap if cap is not None and math.isfinite(cap) and cap >= 0 else None
            if reason is None and spec["min_market_cap"] > 0 and cap is None:
                reason = "missing_market_cap"
            if reason is None and spec["min_market_cap"] > 0 and cap < spec["min_market_cap"]:
                counts["evaluated"] += 1
                counts["failed"] += 1
                continue
            days = [row["date"] for row in rows]
            # Breakout-window patterns may have formed before the search
            # window, so their supplied pre-window history must also be clean.
            code_start = min(required_start, days[0]) if spec["pattern"] != "none" else required_start
            relevant = [row for row in rows if row["date"] >= code_start]
            if reason is None and (len(rows) < history_sessions or days[0] > code_start):
                reason = "insufficient_history"
            elif reason is None and len(days) != len(set(days)):
                reason = "duplicate_dates"
            elif reason is None and any(not _valid_price(row) for row in relevant):
                reason = "invalid_ohlcv"
            elif reason is None and set(day for day in calendar if code_start <= day <= as_of).difference(days):
                reason = "missing_observed_sessions"
            if reason:
                excluded.append({"code": code, "name": info["name"], "reason": reason,
                                 "first_date": days[0], "last_date": days[-1], "required_start": code_start})
                continue
            averages = _moving_average(rows, spec["ma_period"])
            ma_pass = all(value is not None and row[spec["price_basis"]] >= value
                          for row, value in zip(rows[-spec["hold_days"]:], averages[-spec["hold_days"]:]))
            candidates = _patterns(rows, spec, window_start) if spec["pattern"] != "none" else [None]
            events = []
            # Include the row at/before the 365-day boundary in the coverage
            # check, even if the calendar boundary itself is a holiday.
            if spec["require_52w"]:
                events = _high52_events([row for row in rows if _valid_price(row)], window_start)
            selected, event = None, None
            matched = False
            for candidate in candidates:
                qualifying = [entry for entry in events if candidate is None
                              or entry["date"] > candidate["breakout_date"]
                              or (spec["include_same_day"] and entry["date"] == candidate["breakout_date"])]
                if spec["require_52w"] and not qualifying:
                    continue
                if spec["require_ma"] and not ma_pass:
                    continue
                selected, event, matched = candidate, (qualifying[0] if qualifying else None), True
                break
            counts["evaluated"] += 1
            if not matched:
                counts["failed"] += 1
                continue
            checks = {
                "market_cap": {"status": "pass" if spec["min_market_cap"] > 0 else "not_requested",
                               "value": cap, "minimum": spec["min_market_cap"], "date": as_of},
                "pattern": {"status": "pass" if selected else "not_requested", "version": PATTERN_DEFINITION["version"],
                            "window_start": window_start, "window_scope": spec["window_scope"]},
                "high52": {"status": "pass" if event else "not_requested", **(event or {}),
                           "same_day_allowed": spec["include_same_day"], "basis": "close"},
                "ma": {"status": "pass" if spec["require_ma"] else "not_requested", "period": spec["ma_period"],
                       "hold_days": spec["hold_days"], "price_basis": spec["price_basis"], "value": averages[-1]},
                "price_adjustment": {"status": "pass" if adjusted else "unverified", "source_status": "adjusted" if adjusted else "unknown"},
                "calendar": {"status": "pass" if official_calendar else "unverified", "source": manifest["calendar"]["source"]},
            }
            items.append({"code": code, "name": info["name"], "market": info["market"], "market_cap": cap,
                          "as_of_close": rows[-1]["close"], "ma_value": averages[-1],
                          "breakout_date": selected["breakout_date"] if selected else None,
                          "high52_date": event["date"] if event else None,
                          "status": "verified" if adjusted and official_calendar else "provisional",
                          "checks": checks, "pattern": selected})
    for code in sorted((scope if scope is not None else set(universe)) - seen):
        info = universe.get(code, {"name": code, "market": "UNKNOWN"})
        if spec["market"] != "all" and info["market"] not in (spec["market"], "UNKNOWN"):
            continue
        counts["universe"] += 1
        excluded.append({"code": code, "name": info["name"], "reason": "missing_as_of"})
    counts["matched"] = len(items)
    counts["excluded"] = counts["unevaluated"] = len(excluded)
    incomplete = bool(excluded or not adjusted or not official_calendar or manifest.get("excluded", {}).get("invalid_code_or_date_rows"))
    return {"status": "partial" if incomplete else "completed", "as_of": as_of, "spec": spec,
            "snapshot_id": manifest["snapshot_id"], "skill_version": SKILL_VERSION,
            "pattern_definition": PATTERN_DEFINITION, "counts": counts, "items": items,
            "excluded": excluded, "warnings": list(dict.fromkeys(warnings))}


def chart_data(data_dir: str | Path, code: str, spec: dict, *, verified_result: dict | None = None) -> dict:
    """Build candles and evidence markers from the exact selected screen pattern."""
    result = verified_result if verified_result is not None else screen(data_dir, spec)
    selected = next((item for item in result["items"] if item["code"] == code), None)
    folder, _ = _input(data_dir)
    with _connection() as connection:
        collected = list(_series(connection, folder, result["as_of"], code))
        name_row = connection.execute("SELECT name FROM read_parquet(?) WHERE code = ?",
                                      [str(folder / "universe.parquet"), code]).fetchone()
    if not collected:
        raise ValueError("stock not present in snapshot")
    rows = collected[0][1]
    averages = _moving_average(rows, result["spec"]["ma_period"])
    prices = [{"time": row["date"], **{key: row[key] for key in ("open", "high", "low", "close", "volume")}}
              for row in rows if _valid_price(row)]
    ma = [{"time": row["date"], "value": value} for row, value in zip(rows, averages) if value is not None]
    markers, neckline = [], []
    pattern = selected.get("pattern") if selected else None
    if pattern:
        for key, price, label in (("left_shoulder", "ls_low", "왼쪽 어깨"), ("head", "head_low", "머리"),
                                  ("right_shoulder", "rs_low", "오른쪽 어깨"), ("breakout_date", "breakout_close", "넥라인 돌파")):
            markers.append({"time": pattern[key], "price": pattern[price], "kind": key, "label": label})
        positions = {row["date"]: i for i, row in enumerate(rows)}
        first = positions[pattern["peak1"]]
        for index in range(first, positions[pattern["breakout_date"]] + 1):
            neckline.append({"time": rows[index]["date"], "value": pattern["peak1_high"] + pattern["neck_slope"] * (index - first)})
    if selected and selected.get("high52_date"):
        markers.append({"time": selected["high52_date"], "price": selected["checks"]["high52"]["close"],
                        "kind": "high52", "label": "52주 신고가"})
    if result["spec"].get("mode") == "catalog":
        # Do not imply an unrequested MA20 or pattern was part of this search.
        ma = []
    by_day = {row["date"]: row["close"] for row in rows}
    lines = []
    for key, check in (selected or {}).get("checks", {}).items():
        if check.get("status") == "pass" and check.get("date") in by_day and check.get("label"):
            markers.append({"time": check["date"], "price": by_day[check["date"]],
                            "kind": key, "label": check["label"]})
        # Price-structure evidence (D-187): the swing points and fitted lines that produced the verdict.
        evidence = check.get("evidence") if isinstance(check.get("evidence"), dict) else {}
        label = check.get("label") or key
        for point in evidence.get("pivots", []):
            if point.get("date") in by_day:
                markers.append({"time": point["date"], "price": point["price"], "kind": "pivot", "label": "스윙"})
        if evidence.get("line"):
            lines.append({"id": key, "label": label, "points": [{"time": pt["date"], "value": pt["price"]} for pt in evidence["line"]]})
        for side, name in (("upper", "상단"), ("lower", "하단")):
            for pts in [evidence.get("channel", {}).get(side)] if evidence.get("channel") else []:
                lines.append({"id": f"{key}:{side}", "label": f"{label} {name}", "points": [{"time": pt["date"], "value": pt["price"]} for pt in pts]})
    # Several conditions can share a swing point; show each once.
    markers = list({(m["time"], m["kind"], m["price"]): m for m in markers}.values())
    markers.sort(key=lambda marker: marker["time"])
    return {"code": code, "name": name_row[0] if name_row else code, "prices": prices, "ma": ma,
            "markers": markers, "neckline": neckline, "lines": lines, "as_of": result["as_of"],
            "status": selected["status"] if selected else "not_matched"}
