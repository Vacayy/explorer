"""Bounded, three-valued search expressions; standalone read-only sandbox skill.

Unknown is never converted to a negative signal. Temporal operators evaluate
prefixes ending at each event date, using the snapshot's observed sessions.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right

if __package__:
    from .strategies import normalize_condition, history_requirement, evaluate_strategy
else:
    from strategies import normalize_condition, history_requirement, evaluate_strategy

EXPRESSION_VERSION = "market-expression-v1"


def normalize_expression(expression: dict) -> dict:
    nodes, leaves, work = 0, 0, 0

    def visit(node, depth=0, multiplier=1):
        nonlocal nodes, leaves, work
        nodes += 1
        if not isinstance(node, dict) or depth > 5 or nodes > 48:
            raise ValueError("조건식은 최대 깊이 5, 노드 48개입니다.")
        op = node.get("op")
        allowed = {"condition": {"op", "condition"}, "and": {"op", "children"},
                   "or": {"op", "children"}, "not": {"op", "child"},
                   "sequence": {"op", "children", "within_days", "max_gap_days", "allow_same_day"},
                   "consecutive": {"op", "child", "days"}}
        if op not in allowed or set(node) - allowed[op]:
            raise ValueError("지원하지 않는 조건식 연산 또는 필드입니다.")
        if op == "condition":
            condition = normalize_condition(node.get("condition"))
            if condition["strategy_id"].startswith("rank_"):
                raise ValueError("순위 조건은 strategy_conditions의 AND 조합으로 지정해 주세요. 조건식 안의 순위는 미지원입니다.")
            leaves += 1
            work += multiplier * condition["within_days"]
            if leaves > 12 or work > 500:
                raise ValueError("조건식은 조건 12개, 종목별 사건 평가 500회까지 지원합니다.")
            return {"op": op, "condition": condition}
        if op in {"and", "or"}:
            children = node.get("children")
            if not isinstance(children, list) or not 2 <= len(children) <= 12:
                raise ValueError("AND/OR는 2~12개 자식 조건이 필요합니다.")
            return {"op": op, "children": [visit(child, depth + 1, multiplier) for child in children]}
        if op == "not":
            return {"op": op, "child": visit(node.get("child"), depth + 1, multiplier)}
        key, maximum = ("days", 60) if op == "consecutive" else ("within_days", 90)
        count = node.get(key)
        if type(count) is not int or not 1 <= count <= maximum:
            raise ValueError(f"{key}는 1~{maximum} 정수입니다.")
        children = [node.get("child")] if op == "consecutive" else node.get("children")
        if not isinstance(children, list) or not 1 <= len(children) <= 4 or (op == "sequence" and len(children) < 2):
            raise ValueError("사건 순서는 2~4개 단일 조건이 필요합니다.")
        normalized = []
        for child in children:
            if not isinstance(child, dict) or child.get("op") != "condition":
                raise ValueError("사건 순서와 연속 유지는 단일 전략 조건을 사용합니다.")
            value = visit(child, depth + 1, count)
            if value["condition"]["within_days"] != 1:
                raise ValueError("시간 연산 안의 조건은 within_days=1이어야 합니다.")
            normalized.append(value)
        if op == "consecutive":
            return {"op": op, "child": normalized[0], "days": count}
        gap = node.get("max_gap_days", count)
        same = node.get("allow_same_day", False)
        if type(gap) is not int or not 1 <= gap <= 90 or type(same) is not bool:
            raise ValueError("사건 간격과 같은 날 허용 여부를 확인해 주세요.")
        return {"op": op, "children": normalized, "within_days": count,
                "max_gap_days": gap, "allow_same_day": same}

    return visit(expression)


def expression_conditions(node):
    if node["op"] == "condition":
        return [node["condition"]]
    children = node.get("children", [node.get("child")])
    return [condition for child in children for condition in expression_conditions(child)]


def combine_status(op, statuses):
    """Strong Kleene logic: false AND unknown=false, true OR unknown=true."""
    if op == "not":
        return {"pass": "fail", "fail": "pass", "unavailable": "unavailable"}[statuses[0]]
    decisive, other = ("fail", "pass") if op == "and" else ("pass", "fail")
    return decisive if decisive in statuses else ("unavailable" if "unavailable" in statuses else other)


def evaluate_expression(rows, calendar, expression):
    # Imported lazily because analytics dispatches back to this standalone skill.
    if __package__:
        from .analytics import _valid_price
    else:
        from analytics import _valid_price
    by_date = [row["date"] for row in rows]
    present = set(by_date)
    invalid_prefix, duplicate_prefix, missing_prefix = [0], [0], [0]
    for index, row in enumerate(rows):
        invalid_prefix.append(invalid_prefix[-1] + (not _valid_price(row)))
        duplicate_prefix.append(duplicate_prefix[-1] + (index > 0 and by_date[index - 1] == row["date"]))
    for day in calendar:
        missing_prefix.append(missing_prefix[-1] + (day not in present))
    cache = {}

    def leaf(condition, end):
        key = (repr(condition), end)
        if key in cache:
            return cache[key]
        stop = bisect_right(by_date, end)
        session_stop = bisect_right(calendar, end)
        requirement = history_requirement(condition, end)
        earliest = calendar[max(0, session_stop - condition["within_days"])]
        exact = history_requirement({**condition, "within_days": 1}, earliest)
        start = calendar[max(0, session_stop - requirement["sessions"])]
        if exact["start_date"]:
            start = min(start, exact["start_date"])
        first_relevant = bisect_left(by_date, start, 0, stop)
        reason = None
        if not stop or rows[stop - 1]["date"] != end:
            reason = "missing_as_of"
        elif duplicate_prefix[stop]:
            reason = "duplicate_dates"
        elif stop < requirement["sessions"] or (exact["start_date"] and rows[0]["date"] > exact["start_date"]):
            reason = "insufficient_history"
        elif invalid_prefix[stop] - invalid_prefix[first_relevant]:
            reason = "invalid_ohlcv"
        elif missing_prefix[session_stop] - missing_prefix[bisect_left(calendar, start, 0, session_stop)]:
            reason = "missing_observed_sessions"
        # The catalog itself uses a fixed trailing seed span. Supply that span,
        # retaining the calendar-boundary witness for 52-week/year extrema.
        # This avoids validating hundreds of irrelevant dates for every event.
        begin = (max(0, bisect_right(by_date, exact["start_date"], 0, stop) - 1)
                 if exact["start_date"] else max(0, stop - requirement["sessions"]))
        result = ({"status": "unavailable", "reason": reason, "value": None, "date": end}
                  if reason else evaluate_strategy(rows[begin:stop], condition))
        result = {**result, "strategy_id": condition["strategy_id"], "parameters": condition["params"],
                  "within_days": condition["within_days"], "required_start": start}
        cache[key] = result
        return result

    def visit(node, path="expression"):
        op = node["op"]
        if op == "condition":
            return {**leaf(node["condition"], calendar[-1]), "op": op, "path": path}
        if op in {"and", "or", "not"}:
            children = node.get("children", [node.get("child")])
            checks = [visit(child, f"{path}.{index}") for index, child in enumerate(children)]
            return {"op": op, "path": path, "status": combine_status(op, [c["status"] for c in checks]), "children": checks}
        if op == "consecutive":
            days = calendar[-node["days"]:]
            checks = [{**leaf(node["child"]["condition"], day), "evaluated_at": day} for day in days]
            statuses = [check["status"] for check in checks]
            if len(days) < node["days"]:
                statuses.append("unavailable")
            # Keep evidence bounded across a full market; all session outcomes
            # still determine the result and are independently recomputed.
            sample = [checks[0], *[c for c in checks[1:-1] if c["status"] != "pass"][:6]]
            if len(checks) > 1:
                sample.append(checks[-1])
            return {"op": op, "path": path, "status": combine_status("and", statuses), "days": node["days"],
                    "start_date": days[0], "end_date": days[-1], "evaluated_days": len(checks),
                    "passed_days": statuses.count("pass"), "failed_days": statuses.count("fail"),
                    "unknown_days": statuses.count("unavailable"),
                    "observations": [{key: value for key, value in check.items()
                                      if key in {"evaluated_at", "status", "value", "reference", "reason"}} for check in sample],
                    "observations_sampled": len(sample) < len(checks)}
        days = calendar[-node["within_days"]:]
        checks = [[leaf(child["condition"], day) for day in days] for child in node["children"]]

        def chain(allow_unknown):
            previous = {}
            for step, observations in enumerate(checks):
                current = {}
                for index, check in enumerate(observations):
                    if check["status"] != "pass" and not (allow_unknown and check["status"] == "unavailable"):
                        continue
                    if step == 0:
                        current[index] = [index]
                        continue
                    for before, selected in previous.items():
                        delta = index - before
                        if (delta >= 0 if node["allow_same_day"] else delta > 0) and delta <= node["max_gap_days"]:
                            current[index] = selected + [index]
                            break
                previous = current
            return next(iter(previous.values()), None)

        found = chain(False)
        possible = found or chain(True)
        incomplete_window = len(days) < node["within_days"]
        status = "pass" if found is not None else ("unavailable" if possible is not None or incomplete_window else "fail")
        return {"op": op, "path": path, "status": status, "window_start": days[0],
                "within_days": node["within_days"], "max_gap_days": node["max_gap_days"],
                "allow_same_day": node["allow_same_day"],
                "events": [{**checks[step][index], "known_at": days[index]} for step, index in enumerate(found or [])],
                "unknown_observations": sum(c["status"] == "unavailable" for lane in checks for c in lane),
                "unavailable_conditions": [{"strategy_id": identifier, "reason": reason} for identifier, reason in sorted({
                    (c["strategy_id"], c.get("reason") or "insufficient_history")
                    for lane in checks for c in lane if c["status"] == "unavailable"})]}

    return visit(expression)


def flatten_checks(result):
    output = {}

    def visit(check):
        if check["op"] == "condition":
            output[check["path"]] = check
        for index, event in enumerate(check.get("events", [])):
            output[f"{check['path']}.event.{index}"] = event
        for child in check.get("children", []):
            visit(child)
    visit(result)
    return output


def compact_expression_evidence(check):
    """Store each detailed leaf once in checks; tree leaves reference that key."""
    if check["op"] == "condition":
        return {key: check[key] for key in ("op", "path", "status")}
    result = dict(check)
    if "children" in result:
        result["children"] = [compact_expression_evidence(child) for child in result["children"]]
    if "events" in result:
        result["events"] = [{key: value for key, value in event.items()
                              if key in {"strategy_id", "date", "known_at", "status"}}
                            for event in result["events"]]
    return result
