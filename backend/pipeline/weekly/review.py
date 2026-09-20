"""Mechanical claim checks plus a separate-context argument review contract."""
import re

from .calculations import resolve_figure
from .store import dumps


def issue(claim_id, code, reason, severity="blocking"):
    return {"claim_id": claim_id, "severity": severity, "code": code, "reason": reason}


def structural_numbers(item):
    """Dates, instrument labels and sampling parameters are not calculated claim values."""
    label = item["meta"].get("title", "") + " " + (item["meta"].get("unit") or "")
    permitted = set(re.findall(r"\d+", label))
    dates = set()

    def visit(value, key=""):
        if isinstance(value, dict):
            for k, v in value.items():
                visit(v, k)
        elif isinstance(value, list):
            for v in value:
                visit(v, key)
        elif isinstance(value, str):
            dates.update(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", value))
        elif key in {"start_shift", "annualization", "observations", "horizon_observations"}:
            permitted.add(str(value).lstrip("+-"))

    if item["kind"] != "document":
        visit(item["data"])
    visit(item["meta"].get("published_at", ""))
    return permitted, dates


def check(report, evidence, checkpoint):
    issues, seen = [], set()
    read_ids = set(checkpoint.get("read_ids", []))
    for claim in report.claims():
        if claim.id in seen:
            issues.append(issue(claim.id, "duplicate_claim", "주장 ID가 중복됩니다"))
        seen.add(claim.id)
        tokens = re.findall(r"\{\{(n\d+)\}\}", claim.text)
        if set(tokens) != {f.id for f in claim.figures} or len({f.id for f in claim.figures}) != len(claim.figures):
            issues.append(issue(claim.id, "figure_binding", "본문 수치 placeholder와 figures 정의가 일치하지 않습니다"))
        if claim.kind != "hypothesis" and not claim.supports and not claim.figures:
            issues.append(issue(claim.id, "unsupported_claim", "사실·해석에는 읽은 근거가 필요합니다"))
        supporting_text, structural, dates = [], set(), set()
        for support in claim.supports:
            try:
                item = evidence.get(support.evidence_id)
                labels, known_dates = structural_numbers(item)
                structural.update(labels)
                dates.update(known_dates)
                if support.evidence_id not in read_ids:
                    issues.append(issue(claim.id, "unread_source", f"읽지 않은 근거: {support.evidence_id}"))
                text = item["text"] or dumps(item["data"])
                if support.quote:
                    positions = [m.start() for m in re.finditer(re.escape(support.quote), text)]
                    ranges = checkpoint.get("read_ranges", {}).get(item["id"], [])
                    if not any(a <= pos and pos + len(support.quote) <= b for pos in positions for a, b in ranges):
                        issues.append(issue(claim.id, "quote_not_read", f"인용이 실제 읽은 원문 구간과 일치하지 않음: {item['id']}"))
                    else:
                        supporting_text.append(support.quote)
                elif claim.kind == "fact" and item["kind"] == "document":
                    issues.append(issue(claim.id, "missing_quote", "문서 기반 사실 주장에는 정확한 원문 구절이 필요합니다"))
                if item["meta"].get("content_kind") in {"derived_summary", "stored_markdown_unverified"} and claim.kind == "fact":
                    issues.append(issue(claim.id, "derived_as_fact", "생성 요약/원문 미검증 저장본을 직접 사실 근거로 사용했습니다"))
                if item["meta"].get("temporal_status") == "historical_version_unverified":
                    issues.append(issue(claim.id, "unverified_historical_version", f"cutoff 당시 원문/관측 버전을 확인할 수 없습니다: {item['id']}"))
            except (KeyError, ValueError, TypeError) as exc:
                issues.append(issue(claim.id, "invalid_evidence", str(exc)))
        for figure in claim.figures:
            try:
                if figure.evidence_id not in read_ids:
                    raise ValueError("읽지 않은 수치 근거")
                resolve_figure(figure, evidence)
                item = evidence.get(figure.evidence_id)
                labels, known_dates = structural_numbers(item)
                structural.update(labels)
                dates.update(known_dates)
                if item["meta"].get("temporal_status") == "historical_version_unverified":
                    issues.append(issue(claim.id, "unverified_historical_figure", figure.evidence_id))
            except (KeyError, IndexError, ValueError, TypeError) as exc:
                issues.append(issue(claim.id, "invalid_figure", str(exc)))
        # Numeric literals in factual prose must occur in the exact cited passage.
        # Calculation numbers are rendered from pointers instead. Unit/meaning is reviewed separately.
        if claim.kind == "fact":
            prose = re.sub(r"\{\{n\d+\}\}", "", claim.text)
            for day in dates:
                year, month, date_of_month = day.split("-")
                forms = [day, f"{int(month)}/{int(date_of_month)}", f"{month}-{date_of_month}",
                         f"{int(month)}월 {int(date_of_month)}일", f"{year}년 {int(month)}월 {int(date_of_month)}일"]
                for form in sorted(forms, key=len, reverse=True):
                    prose = re.sub(r"(?<!\d)" + re.escape(form) + r"(?!\d)", "", prose)
            numbers = re.findall(r"(?<![A-Za-z0-9])[-+]?\d[\d,]*(?:\.\d+)?%?", prose)
            quoted = " ".join(supporting_text).replace(",", "")
            unmatched = [n for n in numbers if n.replace(",", "").lstrip("+") not in quoted and n.strip(",+-") not in structural]
            if unmatched:
                issues.append(issue(claim.id, "unbound_number", "원문 인용에 없는 숫자입니다. 계산은 figures로 연결하세요: " + ", ".join(unmatched[:8])))
    if not checkpoint.get("overview_seen"):
        issues.append(issue("report", "missing_overview", "질문 선정 전 시장 범위 점검이 없습니다"))
    if not checkpoint.get("calculation_seen"):
        issues.append(issue("report", "missing_calculation", "시장 진단을 뒷받침하는 기간 정의·계산이 없습니다"))
    if not any(evidence.get(eid)["kind"] == "document" for eid in read_ids):
        issues.append(issue("report", "missing_original_read", "원문을 읽은 기록이 없습니다"))
    if not checkpoint.get("decisions"):
        issues.append(issue("report", "missing_decision", "질문·대안·판단 변경 조건 기록이 없습니다"))
    for hypothesis in report.hypotheses:
        for eid in hypothesis.evidence_ids:
            if eid not in read_ids:
                issues.append(issue(hypothesis.id, "unread_hypothesis_support", eid))
    return issues


def reviewer_packet(report, evidence, checkpoint):
    ids = {s.evidence_id for c in report.claims() for s in c.supports}
    ids.update(f.evidence_id for c in report.claims() for f in c.figures)
    ids.update(eid for h in report.hypotheses for eid in h.evidence_ids)
    sources = []
    for eid in sorted(ids):
        try:
            item = evidence.get(eid)
        except (KeyError, ValueError):
            sources.append({"id": eid, "missing": True})
            continue
        text = item["text"] or dumps(item["data"])
        ranges = checkpoint.get("read_ranges", {}).get(eid, [])
        passages = [{"start": a, "end": min(b, a + 12000), "text": text[a:min(b, a + 12000)]} for a, b in ranges[-3:]]
        # Always include every cited passage and adjacent context, even in long documents.
        for claim in report.claims():
            for support in claim.supports:
                if support.evidence_id == eid and support.quote and support.quote in text:
                    at = text.index(support.quote)
                    passages.append({"start": max(0, at - 600), "text": text[max(0, at - 600):at + len(support.quote) + 600]})
        figures = []
        for claim in report.claims():
            for f in claim.figures:
                if f.evidence_id == eid:
                    try:
                        value, unit = resolve_figure(f, evidence)
                        figures.append({"claim_id": claim.id, **f.model_dump(), "value": value, "unit": unit})
                    except (ValueError, KeyError, IndexError, TypeError):
                        pass
        sources.append({"id": eid, "kind": item["kind"], "meta": item["meta"], "passages": passages,
                        "figures": figures, "total_length": len(text), "full_document_included": len(text) <= 12000 and any(a == 0 and b >= len(text) for a, b in ranges)})
    return {"report": report.model_dump(), "evidence": sources,
            "coverage": evidence.coverage(), "mechanical_issues": check(report, evidence, checkpoint)}
