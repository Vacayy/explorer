"""Deterministic expression search with explicit unknowns and immutable scope."""
from __future__ import annotations

import math

if __package__:
    from .analytics import _input, _connection, _series, SKILL_VERSION
    from .expression import EXPRESSION_VERSION, evaluate_expression, expression_conditions, flatten_checks, compact_expression_evidence
    from .strategies import catalog, CATALOG_VERSION
else:
    from analytics import _input, _connection, _series, SKILL_VERSION
    from expression import EXPRESSION_VERSION, evaluate_expression, expression_conditions, flatten_checks, compact_expression_evidence
    from strategies import catalog, CATALOG_VERSION


def screen_expression(data_dir, spec, *, base_result=None):
    folder, manifest = _input(data_dir)
    requested = spec["as_of"] or manifest["as_of"]
    calendar = [day for day in manifest["calendar"]["dates"] if day <= requested]
    if not calendar:
        raise ValueError("no snapshot prices at the requested date")
    as_of = calendar[-1]
    definitions = {entry["id"]: entry for entry in catalog()}
    adjusted = manifest.get("price_adjustment", {}).get("status") == "adjusted"
    official = manifest.get("calendar", {}).get("status") == "verified"
    warnings = list((base_result or manifest).get("warnings", []))
    if not adjusted:
        warnings.append("수정주가 여부가 확인되지 않아 가격 조건의 일치 결과는 잠정 결과입니다.")
    if not official:
        warnings.append("거래일은 관측일 기준이며 거래정지·휴장·원천 누락을 완전히 구분하지 못합니다.")
    if requested != as_of:
        warnings.append(f"요청 기준일 {requested} 대신 마지막 관측일 {as_of}까지 계산했습니다.")
    warnings.append("조건식은 자료 부족을 별도 값으로 계산합니다. OR의 다른 조건이 통과하면 일부 조건이 미평가여도 통과할 수 있습니다.")
    counts = {"universe": 0, "evaluated": 0, "matched": 0, "excluded": 0, "failed": 0, "unevaluated": 0}
    base_items = {item["code"]: item for item in (base_result or {}).get("items", [])}
    base_excluded = {item["code"]: item for item in (base_result or {}).get("excluded", [])}
    selected = set(spec["universe_codes"]) if spec.get("universe_codes") is not None else None
    items, excluded, seen = [], [], set()
    with _connection() as connection:
        universe = {code: {"name": name, "market": market} for code, name, market in connection.execute(
            "SELECT code,name,market FROM read_parquet(?)", [str(folder / "universe.parquet")]).fetchall()}
        for code, rows in _series(connection, folder, as_of):
            if selected is not None and code not in selected:
                continue
            seen.add(code)
            info = universe.get(code, {"name": code, "market": "UNKNOWN"})
            if spec["market"] != "all" and info["market"] not in (spec["market"], "UNKNOWN"):
                continue
            counts["universe"] += 1
            detail = {"code": code, "name": info["name"], "first_date": rows[0]["date"], "last_date": rows[-1]["date"]}
            if base_result is not None:
                if code in base_excluded:
                    excluded.append(base_excluded[code]); continue
                if code not in base_items:
                    counts["failed"] += 1; continue
            cap = rows[-1]["mktcap"]
            cap = cap if cap is not None and math.isfinite(cap) and cap >= 0 else None
            reason = None
            if spec["market"] != "all" and info["market"] == "UNKNOWN":
                reason = "unknown_market"
            elif rows[-1]["date"] != as_of:
                reason = "missing_as_of"
            elif spec["min_market_cap"] > 0 and cap is None:
                reason = "missing_market_cap"
            elif spec["min_market_cap"] > 0 and cap < spec["min_market_cap"]:
                counts["failed"] += 1; continue
            if reason:
                excluded.append({**detail, "reason": reason}); continue
            expression = evaluate_expression(rows, calendar, spec["expression"])
            if expression["status"] == "unavailable":
                excluded.append({**detail, "reason": "expression_unavailable", "expression": expression}); continue
            if expression["status"] == "fail":
                counts["failed"] += 1; continue
            checks = dict(base_items.get(code, {}).get("checks", {}))
            for key, check in flatten_checks(expression).items():
                checks[key] = {**check, "label": definitions[check["strategy_id"]]["label"]}
            checks["expression"] = {**compact_expression_evidence(expression), "label": "복합 조건식", "date": as_of}
            items.append({**base_items.get(code, {}), "code": code, **info, "market_cap": cap,
                          "as_of_close": rows[-1]["close"], "ma_value": base_items.get(code, {}).get("ma_value"),
                          "breakout_date": base_items.get(code, {}).get("breakout_date"),
                          "high52_date": base_items.get(code, {}).get("high52_date"),
                          "pattern": base_items.get(code, {}).get("pattern"), "checks": checks,
                          "status": "verified" if adjusted and official else "provisional"})
    for code in sorted((selected if selected is not None else set(universe)) - seen):
        info = universe.get(code, {"name": code, "market": "UNKNOWN"})
        if spec["market"] != "all" and info["market"] not in (spec["market"], "UNKNOWN"):
            continue
        counts["universe"] += 1
        excluded.append({"code": code, "name": info["name"], "reason": "missing_as_of"})
    counts["matched"] = len(items)
    counts["excluded"] = counts["unevaluated"] = len(excluded)
    counts["evaluated"] = counts["matched"] + counts["failed"]
    incomplete = bool(excluded or not adjusted or not official or manifest.get("excluded", {}).get("invalid_code_or_date_rows"))
    ids = list(dict.fromkeys(c["strategy_id"] for c in expression_conditions(spec["expression"])))
    return {"status": "partial" if incomplete else "completed", "as_of": as_of, "spec": spec,
            "snapshot_id": manifest["snapshot_id"], "skill_version": SKILL_VERSION,
            "catalog_version": CATALOG_VERSION, "expression_version": EXPRESSION_VERSION,
            "counts": counts, "items": items, "excluded": excluded, "warnings": list(dict.fromkeys(warnings)),
            "strategy_definitions": [definitions[key] for key in ids],
            **({"pattern_definition": base_result["pattern_definition"]} if base_result else {})}
