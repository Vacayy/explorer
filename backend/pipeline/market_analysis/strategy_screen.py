"""Read-only catalog screening over the same immutable inputs as pattern search."""
from __future__ import annotations

import bisect
import math

if __package__:
    from .analytics import _input, _connection, _series, _valid_price, SKILL_VERSION
    from .strategies import CATALOG_VERSION, catalog, evaluate_strategy, history_requirement
else:
    from analytics import _input, _connection, _series, _valid_price, SKILL_VERSION
    from strategies import CATALOG_VERSION, catalog, evaluate_strategy, history_requirement


def screen_catalog(data_dir, spec: dict, *, base_result: dict | None = None) -> dict:
    folder, manifest = _input(data_dir)
    requested = spec["as_of"] or manifest["as_of"]
    calendar = [day for day in manifest["calendar"]["dates"] if day <= requested]
    if not calendar:
        raise ValueError("no snapshot prices at the requested date")
    as_of = calendar[-1]
    conditions = spec["strategy_conditions"]
    definitions = {item["id"]: item for item in catalog()}
    ranks = [c for c in conditions if definitions[c["strategy_id"]]["category"] == "순위종목"]
    adjusted = manifest.get("price_adjustment", {}).get("status") == "adjusted"
    official = manifest.get("calendar", {}).get("status") == "verified"
    warnings = list((base_result or manifest).get("warnings", []))
    if not adjusted:
        warnings.append("수정주가 여부가 확인되지 않아 가격 조건의 일치 결과는 잠정 결과입니다.")
    if not official:
        warnings.append("거래일은 관측일 기준이며 거래정지·휴장·원천 누락을 완전히 구분하지 못합니다.")
    if requested != as_of:
        warnings.append(f"요청 기준일 {requested} 대신 마지막 관측일 {as_of}까지 계산했습니다.")
    requirements = {}
    for condition in conditions:
        key = condition["strategy_id"]
        requirement = history_requirement(condition, as_of)
        # The snapshot supplies observed sessions, so calendar-based extrema
        # need no weekday/calendar-day approximation for the event window.
        earliest_event = calendar[max(0, len(calendar) - condition["within_days"])]
        exact_boundary = history_requirement({**condition, "within_days": 1}, earliest_event)
        requirement["start_date"] = exact_boundary.get("start_date")
        sessions = requirement["sessions"]
        start = calendar[max(0, len(calendar) - sessions)]
        if requirement.get("start_date"):
            start = min(start, requirement["start_date"])
        requirements[key] = {**requirement, "required_start": start}

    counts = {"universe": 0, "evaluated": 0, "matched": 0, "excluded": 0, "failed": 0, "unevaluated": 0}
    excluded, candidates, seen = [], [], set()
    scope = set(spec["universe_codes"]) if spec.get("universe_codes") is not None else None
    base_items = {item["code"]: item for item in (base_result or {}).get("items", [])}
    base_excluded = {item["code"]: item for item in (base_result or {}).get("excluded", [])}
    with _connection() as connection:
        universe = {code: {"name": name, "market": market} for code, name, market in connection.execute(
            "SELECT code,name,market FROM read_parquet(?)", [str(folder / "universe.parquet")]).fetchall()}
        for code, rows in _series(connection, folder, as_of):
            if scope is not None and code not in scope:
                continue
            info = universe.get(code, {"name": code, "market": "UNKNOWN"})
            seen.add(code)
            if spec["market"] != "all" and info["market"] not in (spec["market"], "UNKNOWN"):
                continue
            counts["universe"] += 1
            if base_result is not None:
                if code in base_excluded:
                    excluded.append(base_excluded[code])
                    continue
                if code not in base_items:
                    counts["failed"] += 1
                    continue
            cap = rows[-1]["mktcap"]
            reason = None
            if spec["market"] != "all" and info["market"] == "UNKNOWN":
                reason = "unknown_market"
            elif rows[-1]["date"] != as_of:
                reason = "missing_as_of"
            elif spec["min_market_cap"] > 0:
                if cap is None or not math.isfinite(cap) or cap < 0:
                    reason = "missing_market_cap"
                elif cap < spec["min_market_cap"]:
                    counts["failed"] += 1
                    continue
            detail = {"code": code, "name": info["name"], "first_date": rows[0]["date"],
                      "last_date": rows[-1]["date"]}
            if reason:
                excluded.append({**detail, "reason": reason})
                continue
            days = [row["date"] for row in rows]
            day_set = set(days)
            # Rows arrive sorted by date and cut at as_of, so the per-condition window
            # checks reduce to index arithmetic: the last invalid row and the count of
            # observed sessions from the window start (days ⊆ calendar once duplicates
            # are excluded, so "a calendar day is missing" ⇔ the counts differ).
            last_invalid = max((i for i, row in enumerate(rows) if not _valid_price(row)), default=-1)
            checks = dict(base_items.get(code, {}).get("checks", {}))
            unavailable = []
            for condition in conditions:
                key = condition["strategy_id"]
                definition, requirement = definitions[key], requirements[key]
                start = requirement["required_start"]
                first = bisect.bisect_left(days, start)
                reason = None
                if definition["timeframe"] != "1d":
                    reason = "missing_intraday"
                elif len(days) != len(day_set):
                    reason = "duplicate_dates"
                elif len(rows) < requirement["sessions"]:
                    reason = "insufficient_history"
                elif requirement.get("start_date") and days[0] > requirement["start_date"]:
                    reason = "insufficient_history"
                elif last_invalid >= first:
                    reason = "invalid_ohlcv"
                elif len(days) - first != len(calendar) - bisect.bisect_left(calendar, start):
                    reason = "missing_observed_sessions"
                check = ({"status": "unavailable", "reason": reason, "value": None, "date": None}
                         if reason else evaluate_strategy(rows, condition))
                checks[key] = {**check, "label": definition["label"], "parameters": condition["params"],
                               "within_days": condition["within_days"], "required_start": start}
                if check["status"] == "unavailable":
                    unavailable.append({"strategy_id": key, "label": definition["label"],
                                        "reason": check.get("reason") or "insufficient_history"})
            if unavailable:
                excluded.append({**detail, "reason": unavailable[0]["reason"], "conditions": unavailable,
                                 "required_start": min(r["required_start"] for r in requirements.values())})
                continue
            if any(checks[c["strategy_id"]]["status"] == "fail" for c in conditions):
                counts["failed"] += 1
                continue
            candidates.append({**base_items.get(code, {}), "code": code, **info,
                               "market_cap": cap if cap is not None and math.isfinite(cap) else None,
                               "as_of_close": rows[-1]["close"],
                               "ma_value": base_items.get(code, {}).get("ma_value"),
                               "breakout_date": base_items.get(code, {}).get("breakout_date"),
                               "high52_date": base_items.get(code, {}).get("high52_date"),
                               "pattern": base_items.get(code, {}).get("pattern"),
                               "checks": checks, "status": "verified" if adjusted and official else "provisional"})
    for code in sorted((scope if scope is not None else set(universe)) - seen):
        info = universe.get(code, {"name": code, "market": "UNKNOWN"})
        if spec["market"] != "all" and info["market"] not in (spec["market"], "UNKNOWN"):
            continue
        counts["universe"] += 1
        excluded.append({"code": code, "name": info["name"], "reason": "missing_as_of"})

    # Every ranking sees the same eligible population; checkbox order cannot
    # change the intersection. Equal values use ascending stock code as tie-break.
    for condition in ranks:
        key = condition["strategy_id"]
        ordered = sorted(candidates, key=lambda row: (-row["checks"][key]["value"], row["code"]))
        for rank, row in enumerate(ordered, 1):
            row["checks"][key].update(rank=rank, population=len(candidates),
                                      top_n=condition["params"]["top_n"],
                                      status="pass" if rank <= condition["params"]["top_n"] else "fail")
    items = [row for row in candidates if all(row["checks"][c["strategy_id"]]["status"] == "pass" for c in ranks)]
    counts["failed"] += len(candidates) - len(items)
    if ranks:
        items.sort(key=lambda row: (row["checks"][ranks[0]["strategy_id"]]["rank"], row["code"]))
        warnings.append("순위는 일반 조건을 통과하고 선택한 지표를 모두 계산할 수 있는 종목 사이에서 매깁니다. 동률은 종목코드 순입니다.")
    counts["matched"] = len(items)
    counts["excluded"] = counts["unevaluated"] = len(excluded)
    counts["evaluated"] = counts["failed"] + counts["matched"]
    if any(definitions[c["strategy_id"]]["timeframe"] == "10m" for c in conditions):
        warnings.append("현재 스냅샷에는 10분봉이 없어 해당 조건을 평가할 수 없습니다.")
    if any(c["strategy_id"] == "rank_trading_value" for c in conditions):
        warnings.append("실제 거래대금 데이터가 없습니다. 종가×거래량을 거래대금으로 대체하지 않습니다.")
    incomplete = bool(excluded or not adjusted or not official or
                      manifest.get("excluded", {}).get("invalid_code_or_date_rows"))
    return {"status": "partial" if incomplete else "completed", "as_of": as_of, "spec": spec,
            "snapshot_id": manifest["snapshot_id"], "skill_version": SKILL_VERSION,
            "catalog_version": CATALOG_VERSION, "counts": counts, "items": items,
            "excluded": excluded, "warnings": list(dict.fromkeys(warnings)),
            "strategy_definitions": [definitions[c["strategy_id"]] for c in conditions],
            **({"pattern_definition": base_result["pattern_definition"]} if base_result else {})}
