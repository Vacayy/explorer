"""Deterministic, unit-aware observations. Statistical analogues are exploratory."""
import html
import math
import statistics
from datetime import date

METRIC_UNITS = {
    "observations": "observations", "return_pct": "%", "drawdown_pct": "%",
    "volatility_ann_pct": "%", "slope_pct_per_observation": "% / observation",
    "distance_to_ma20_pct": "%", "average_volume": "shares",
}


def metrics(points, *, metric_kind="price", annualization=252):
    if len(points) < 2:
        raise ValueError("계산에는 최소 두 개의 관측치가 필요합니다")
    values = [float(p["value"]) for p in points]
    if not all(math.isfinite(v) for v in values):
        raise ValueError("계산 입력에 NaN/Infinity가 있습니다")
    out = {"observations": len(points), "first": values[0], "last": values[-1], "change": values[-1] - values[0]}
    if metric_kind != "price":
        # A yield change is a percentage-point change, not an asset return.
        return out
    if min(values) <= 0:
        raise ValueError("가격 수익률 계산은 양수 가격이 필요합니다")
    returns = [b / a - 1 for a, b in zip(values, values[1:])]
    peak, drawdown = values[0], 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1)
    slope = statistics.linear_regression(range(len(values)), [math.log(v) for v in values]).slope
    out.update(return_pct=(values[-1] / values[0] - 1) * 100,
               drawdown_pct=drawdown * 100,
               volatility_ann_pct=statistics.stdev(returns) * math.sqrt(annualization) * 100 if len(returns) > 1 else None,
               slope_pct_per_observation=math.expm1(slope) * 100,
               distance_to_ma20_pct=(values[-1] / statistics.mean(values[-20:]) - 1) * 100 if len(values) >= 20 else None)
    volumes = [p.get("volume") for p in points]
    out["average_volume"] = statistics.mean(volumes) if all(v is not None for v in volumes) else None
    return out


def compare(item, windows, start_shifts):
    points = item["data"]["points"]
    kind = item["meta"].get("metric_kind", "level")
    annualization = 365 if item["meta"].get("series") == "macro_btc" else 252
    result = []
    for window in windows:
        start, end = str(window["start"]), str(window["end"])
        if start > end:
            raise ValueError("시작일은 종료일보다 늦을 수 없습니다")
        selected = [i for i, p in enumerate(points) if start <= p["date"] <= end]
        if len(selected) < 2:
            raise ValueError(f"{start} ~ {end}: 관측치가 부족합니다")
        first, last = selected[0], selected[-1]
        variants = []
        for shift in sorted(set([0, *start_shifts])):
            idx = first + shift
            if idx < 0 or idx >= last:
                variants.append({"start_shift": shift, "unavailable": "관측 범위 밖"})
                continue
            sample = points[idx:last + 1]
            variants.append({"start_shift": shift, "actual_start": sample[0]["date"], "actual_end": sample[-1]["date"],
                             "metrics": metrics(sample, metric_kind=kind, annualization=annualization)})
        result.append({"requested_start": start, "requested_end": end, "rationale": window["rationale"],
                       "actual_start": points[first]["date"], "actual_end": points[last]["date"],
                       "metrics": metrics(points[first:last + 1], metric_kind=kind, annualization=annualization),
                       "sensitivity": variants})
    return {"source_id": item["id"], "windows": result, "annualization": annualization,
            "method": "simple close return; sample stdev of simple observation returns; log-price OLS slope; running-peak drawdown; MA20 only with 20 observations",
            "limitations": ["시간 간격이 균등한 일별 가격에 대한 연율화입니다. 변동성은 변동의 원인이나 추세 부재를 증명하지 않습니다.",
                            "가격 조정 정의와 결측일은 원본 시계열 메타데이터를 함께 확인하세요."]}


def select_analogues(item, target_start, target_end, window, stride, min_separation, limit, rationale):
    if item["meta"].get("metric_kind") != "price":
        raise ValueError("초기 analogue 도구는 양수 가격 시계열만 지원합니다")
    points = item["data"]["points"]
    target = [p for p in points if target_start <= p["date"] <= target_end]
    if len(target) < 5:
        raise ValueError("비교 대상 관측치가 부족합니다")
    if len(target) != window:
        raise ValueError(f"대상은 {len(target)}개 관측치입니다. 비교 window도 같게 지정하세요")
    target_metrics = metrics(target)
    dimensions = ["return_pct", "drawdown_pct", "volatility_ann_pct"]
    candidates = []
    for end in range(window - 1, len(points), stride):
        if points[end]["date"] >= target_start:
            break
        sample = points[end - window + 1:end + 1]
        m = metrics(sample)
        candidates.append({"id": f"a{end}", "start": sample[0]["date"], "end": sample[-1]["date"],
                           "end_index": end, "metrics": {k: m[k] for k in dimensions}})
    if not candidates:
        raise ValueError("대상 이전에 비교할 가격 구간이 없습니다")
    scales = {k: statistics.pstdev(c["metrics"][k] for c in candidates) or 1 for k in dimensions}
    for candidate in candidates:
        candidate["distance"] = math.sqrt(sum(((candidate["metrics"][k] - target_metrics[k]) / scales[k]) ** 2 for k in dimensions))
    selected = []
    for candidate in sorted(candidates, key=lambda c: (c["distance"], c["end"])):
        if any(abs(candidate["end_index"] - other["end_index"]) < min_separation for other in selected):
            candidate["exclusion"] = "too_close_to_selected_window"
        elif len(selected) < limit:
            candidate["selected"] = True
            selected.append(candidate)
        else:
            candidate["exclusion"] = "rank_limit"
    return {"source_id": item["id"], "target": {"start": target_start, "end": target_end, "metrics": target_metrics},
            "criteria": {"dimensions": dimensions, "scales": scales, "window": window, "stride": stride,
                         "min_separation": min_separation, "limit": limit, "rationale": rationale},
            "candidates": candidates, "selected_ids": [c["id"] for c in selected],
            "limitations": ["정량적 형태 비교이며 사건·정책·경로 순서의 메커니즘 일치를 판정하지 않습니다.",
                            "후속 결과를 열기 전에 후보/제외 목록을 고정했습니다. 작은 표본·중첩·선정 편향이 남습니다."]}


def outcomes(selection, item, horizon):
    points = item["data"]["points"]
    results = []
    for c in selection["data"]["candidates"]:
        if c["id"] not in selection["data"]["selected_ids"]:
            continue
        end = c["end_index"]
        if end + horizon >= len(points):
            results.append({"candidate_id": c["id"], "unavailable": "cutoff 이전 후속 기간 부족"})
            continue
        sample = points[end:end + horizon + 1]
        results.append({"candidate_id": c["id"], "start": sample[0]["date"], "end": sample[-1]["date"], "metrics": metrics(sample)})
    return {"selection_id": selection["id"], "source_id": item["id"], "horizon_observations": horizon, "outcomes": results,
            "limitations": ["비독립적 탐색 표본입니다. 상승 확률이나 인과 효과의 추정으로 사용하지 마세요."]}


def chart_svg(item, start, end):
    points = [p for p in item["data"]["points"] if start <= p["date"] <= end]
    if len(points) < 2:
        raise ValueError("차트 관측치 부족")
    values = [p["value"] for p in points]
    low, high = min(values), max(values)
    span = high - low or 1
    coords = " ".join(f"{60 + i * 820 / (len(points) - 1):.2f},{280 - (v - low) * 210 / span:.2f}" for i, v in enumerate(values))
    e = html.escape
    title = f"{item['meta']['title']} · {points[0]['date']} — {points[-1]['date']}"
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 940 370" role="img" aria-labelledby="title desc">
<title id="title">{e(title)}</title><desc id="desc">{e(item['meta']['unit'])}. {len(points)} observations. {e(item['id'])}</desc>
<rect width="940" height="370" fill="#faf9f5"/><g font-family="sans-serif" fill="#222">
<text x="30" y="30" font-size="19">{e(title)}</text><text x="30" y="55" font-size="13">{e(item['meta']['unit'])} · source {e(item['id'])}</text>
<text x="15" y="78" font-size="11">{high:.2f}</text><text x="15" y="280" font-size="11">{low:.2f}</text>
<polyline fill="none" stroke="#27675d" stroke-width="2.3" points="{coords}"/>
<text x="60" y="308" font-size="12">{points[0]['date']}</text><text x="790" y="308" font-size="12">{points[-1]['date']}</text>
<text x="30" y="346" font-size="12">Actual dated observations; source definition and adjustment: see evidence appendix.</text></g></svg>'''


def resolve_figure(figure, evidence):
    item = evidence.get(figure.evidence_id)
    value = item["data"]
    keys = figure.path.split("/")[1:]
    if not figure.path.startswith("/") or not keys:
        raise ValueError("수치 경로는 JSON pointer여야 합니다")
    for key in keys:
        key = key.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("유한 숫자만 본문 수치로 연결할 수 있습니다")
    unit = METRIC_UNITS.get(keys[-1])
    if keys[-1] in {"first", "last", "change", "value"}:
        unit = item["meta"].get("unit")
        if keys[-1] == "change" and item["meta"].get("metric_kind") == "yield":
            unit = "percentage points"
    if not unit:
        raise ValueError("단위가 정의되지 않은 수치 경로입니다")
    return value, unit
