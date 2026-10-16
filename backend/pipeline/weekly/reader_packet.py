"""Build a frozen, broad input packet for the writing experiment, without a target answer."""
import json
import hashlib
from datetime import date, timedelta
from pathlib import Path

from models.weekly_reader import ComparisonRequest
from .calculations import chart_svg, metrics
from .evidence import Evidence
from .store import Store, atomic_write, digest, dumps, now
from .worker import isolated

BASE_SERIES = ("s-index_sp500", "s-index_nasdaq", "s-index_dow", "s-macro_us2y",
               "s-macro_us10y", "s-macro_oil", "s-vix", "s-fear_greed", "s-macro_hyg",
               "s-macro_gold", "s-macro_dxy")


def add_series(packet, item, directory, request, area="prices"):
    sid = item["id"]
    # Every comparison discloses actual observation dates. Never forward fill.
    points = sorted(item["data"]["points"], key=lambda x: x["date"])
    end = request.week_end.isoformat()
    baseline = (request.week_start - timedelta(days=1)).isoformat()
    prior = [p for p in points if p["date"] <= baseline]
    weekly = [p for p in points if request.week_start.isoformat() <= p["date"] <= end]
    if not prior or not weekly:
        packet["gaps"].append({"area": area, "source_id": sid, "reason": "회고 주간 관측 부족"})
        return
    if (request.week_start - date.fromisoformat(prior[-1]["date"])).days > 7:
        packet["gaps"].append({"area": area, "source_id": sid, "reason": "직전 주 기준값이 없어 주간 비교에서 제외"})
        return
    window = [prior[-1], *weekly]
    kind = item["meta"]["metric_kind"]
    value = metrics(window, metric_kind=kind)
    unit = item["meta"]["unit"]
    suffix = {"percent": "%", "index points": "포인트", "USD / share": "달러", "USD / barrel": "달러", "index": "포인트", "score (0–100)": "점"}.get(unit, unit)
    defs = [("last", value["last"], suffix, "주간 마지막 관측값")]
    defs += [("return_pct", value["return_pct"], "%", "직전 주 마지막 관측부터 주간 가격 변화율")] if kind == "price" else [
        ("change", value["change"], "%p" if kind == "yield" else suffix, "직전 주 마지막 관측부터 변화")]
    if kind == "price":
        defs.append(("drawdown_pct", value["drawdown_pct"], "%", "종가 관측 구간 최대낙폭(장중 낙폭 아님)"))
    observed_before = [p for p in points if p["date"] <= end]
    context = observed_before[-41:]
    if kind == "price" and len(context) > 20:
        twenty = metrics(context[-21:], metric_kind=kind)
        defs.append(("twenty_return", twenty["return_pct"], "%", "최근 20개 관측 간격 가격 변화율"))
    entries = []
    for key, number, label, meaning in defs:
        mid = f"m{len(packet['metrics']) + 1:04d}"
        formatted = f"{number:,.2f}" + label
        start = context[-21]["date"] if key == "twenty_return" else window[0]["date"]
        entry = {"id": mid, "source_id": sid, "name": item["meta"]["title"] + " · " + meaning,
                 "value": number, "unit": label, "formatted": formatted,
                 "start": start, "end": window[-1]["date"], "observations": 21 if key == "twenty_return" else len(window),
                 "definition": key, "complete_week": window[-1]["date"] == end}
        packet["metrics"][mid] = entry
        entries.append(entry)
    if window[-1]["date"] != end:
        packet["gaps"].append({"area": "prices", "source_id": sid, "reason": "종료 관측일이 주간 종료일과 다름: " + window[-1]["date"]})
    packet["sources"][sid] = {"id": sid, "kind": "series", "meta": item["meta"],
                              "text": dumps({"calculation": entries, "week_points": window}),
                              "sha256": digest(item), "areas": [area], "raw_file": f"evidence/{sid}.json"}
    packet["coverage"].setdefault(area, []).append(sid)
    atomic_write(directory / "evidence" / f"{sid}.json", dumps(item))
    if len(context) >= 2:
        cid = "chart-" + sid
        packet["charts"][cid] = {"source_id": sid, "title": item["meta"]["title"],
                                 "start": context[0]["date"], "end": context[-1]["date"], "file": f"charts/{cid}.svg"}
        atomic_write(directory / "charts" / f"{cid}.svg", chart_svg(item, context[0]["date"], context[-1]["date"]))


def prepare(request: ComparisonRequest, selection: dict, *, store=None, root=None, source_call=None):
    store = store or Store()
    run = store.get(request.source_run_id)
    ev = Evidence(store.directory(request.source_run_id))
    if ev.file_hash() != run["checkpoint"].get("corpus_sha256"):
        raise ValueError("원본 corpus hash 불일치")
    root = Path(root) if root else store.runs_dir.parent / "comparisons"
    directory = root / request.request_key
    config = request.model_dump(mode="json")
    identity = digest({"request": config, "selection": selection})
    if directory.exists():
        manifest = json.loads((directory / "manifest.json").read_text())
        if manifest["identity"] != identity:
            raise ValueError("같은 request_key를 다른 설정/선택에 사용할 수 없습니다")
        if manifest.get("status") == "preparing":
            raise ValueError("준비가 끝나지 않은 디렉터리입니다. 원본은 보존하고 새 request_key로 준비하세요")
        return directory
    directory.mkdir(parents=True)
    manifest = {"identity": identity, "request": config, "created_at": now(), "status": "preparing",
                "source_corpus_sha256": ev.file_hash(), "expert_quality": "not_evaluated"}
    atomic_write(directory / "manifest.json", dumps(manifest))
    atomic_write(directory / "selection.json", dumps(selection))
    packet = {"version": 2, "workflow": request.workflow, "period": {k: config[k] for k in ("week_start", "week_end", "outlook_start", "outlook_end")},
              "origin_snapshot_cutoff": run["config"]["cutoff"], "cutoff": now(),
              "sources": {}, "metrics": {}, "charts": {}, "coverage": {}, "gaps": list(selection.get("gaps", [])),
              "method": "development_curated_broad_packet; no reference Weekly or prior generated report supplied"}
    ids = {}
    for area, source_ids in selection["areas"].items():
        packet["coverage"][area] = []
        for sid in source_ids:
            ids.setdefault(sid, []).append(area)
    seen = set()
    for sid, areas in ids.items():
        item = ev.get(sid)
        meta = item["meta"]
        if item["kind"] != "document" or meta.get("temporal_status") == "historical_version_unverified" or meta.get("content_kind") == "derived_summary":
            raise ValueError(f"원문/시점 자격 미충족: {sid}")
        if "3da9e403cb628080a1fed604f8542436" in (meta.get("url") or ""):
            raise ValueError("평가 대상 Weekly 원문은 작성 입력에 포함할 수 없습니다")
        group = meta.get("duplicate_group", item["sha256"])
        if group in seen:
            continue
        seen.add(group)
        if len(item["text"]) > 16000:
            raise ValueError(f"긴 원문 {sid}: 선택을 명시적으로 좁히거나 전용 문서 읽기를 사용하세요")
        packet["sources"][sid] = {"id": sid, "kind": "document", "meta": meta, "text": item["text"],
                                  "sha256": item["sha256"], "areas": areas, "raw_file": f"evidence/{sid}.json"}
        for area in areas:
            packet["coverage"][area].append(sid)
        atomic_write(directory / "evidence" / f"{sid}.json", dumps(item))
    for sid in selection.get("series", BASE_SERIES):
        add_series(packet, ev.get(sid), directory, request)
    fetch = source_call or (lambda p: isolated("source", p, timeout=65))
    for index, acquisition in enumerate(selection.get("acquisitions", [])):
        try:
            result = fetch({"provider": acquisition["provider"], "args": acquisition["args"], "cutoff": now(), "mode": "live"})
            sid = f"provider-{index + 1:02d}"
            result["id"] = sid
            result["meta"]["availability_basis"] = "captured_during_packet_preparation; not historical replay"
            if result["kind"] == "series":
                add_series(packet, result, directory, request, acquisition.get("area", "prices"))
            else:
                full = result["text"]
                atomic_write(directory / "evidence" / f"{sid}.json", dumps(result))
                # Explicit excerpt boundary, full raw version still preserved. No silent context trim.
                start = full.find(acquisition["start_marker"]) if acquisition.get("start_marker") else 0
                if start < 0:
                    raise ValueError("원문 발췌 시작 문구를 찾지 못했습니다")
                stop = min(len(full), start + acquisition.get("max_chars", 12000))
                area = acquisition.get("area", "primary")
                packet["sources"][sid] = {"id": sid, "kind": "document", "meta": result["meta"],
                                          "text": full[start:stop], "range": [start, stop], "full_length": len(full),
                                          "sha256": digest(result), "areas": [area], "raw_file": f"evidence/{sid}.json"}
                packet["coverage"].setdefault(area, []).append(sid)
                atomic_write(directory / "evidence" / f"{sid}.json", dumps(result))
        except (RuntimeError, ValueError, TimeoutError) as exc:
            packet["gaps"].append({"area": acquisition.get("area", "prices"), "provider": acquisition["provider"],
                                   "requested": acquisition["args"], "reason": str(exc)})
    packet["cutoff"] = now()
    if date.fromisoformat(packet["cutoff"][:10]) < request.week_end:
        raise ValueError("회고 주간이 아직 끝나지 않았습니다")
    if sum(len(s["text"]) for s in packet["sources"].values()) > 130000:
        raise ValueError("입력 본문 130,000자 상한 초과: 선택을 명시적으로 조정하세요")
    atomic_write(directory / "packet.json", dumps(packet))
    archived = sorted((directory / "evidence").glob("*.json")) + sorted((directory / "charts").glob("*.svg"))
    manifest.update(status="prepared", packet_sha256=digest(packet), source_count=len(packet["sources"]),
                    document_count=sum(s["kind"] == "document" for s in packet["sources"].values()), prepared_at=now(),
                    evidence_files={str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest() for p in archived})
    atomic_write(directory / "manifest.json", dumps(manifest))
    return directory
