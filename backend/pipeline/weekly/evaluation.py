"""Reproducible same-evidence baseline and an unscored expert evaluation packet."""
import html
import json
import random
import uuid
from pathlib import Path

from models.weekly import Report
from pipeline.llm import extract_json
from .evidence import Evidence
from .render import STYLE, citation_labels, rendered_claim
from .review import check
from .runner import WRITER_SYSTEM
from .store import atomic_write, digest, dumps, now
from .worker import isolated

AXES = [
    ("grounding", "사실·계산·출처", "핵심 수치·기간·단위·인용이 맞고 출처가 실제 주장을 지지하는가"),
    ("question_selection", "문제 선택·중요 누락", "그 주의 진단을 바꿀 질문을 골랐고 핵심 쟁점을 놓치지 않았는가"),
    ("alternatives", "경쟁 설명·메커니즘", "가장 강한 대안을 조사하고 두 설명을 구분하는 근거를 제시했는가"),
    ("comparisons", "기간·역사 비교", "기간 선택이 타당하고 시작점 민감도·사례 선정 편향을 다뤘는가"),
    ("updating", "판단 갱신·유용성", "무엇을 보면 판단을 바꿀지 구체적이며 다음 관찰에 유용한가"),
    ("rewrite_burden", "핵심 재작성 부담", "전문가가 질문·논증을 다시 작성할 필요가 없는가"),
]


def build_packet(store, run_id, *, baseline=False, model=None, model_call=None, reference_manifest=None):
    run = store.get(run_id)
    cp, cfg = run["checkpoint"], run["config"]
    if not cp.get("draft"):
        raise ValueError("보고서가 있는 실행만 평가할 수 있습니다")
    if run["status"] not in {"complete", "partial"}:
        raise ValueError("실행이 끝난 뒤 평가 자료를 고정하세요")
    ev = Evidence(store.directory(run_id))
    directory = store.directory(run_id) / "evaluation"
    if directory.exists():
        directory = store.directory(run_id) / ("evaluation-" + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=False)
    reference = None
    if reference_manifest:
        raw_reference = json.loads(Path(reference_manifest).read_text())
        reference = {k: raw_reference.get(k) for k in ("url", "title", "captured_at", "text_sha256", "purpose")}
        reference["image_count"] = len(raw_reference.get("images", []))
        reference["source_manifest_sha256"] = digest(raw_reference)
        reference["comparison_status"] = "reference_attached_unscored"
        atomic_write(directory / "reference.json", dumps(reference))
    # Same *read* evidence, not the analyst's conclusions or later benchmark answers.
    inputs = []
    for eid in dict.fromkeys(cp["read_ids"]):
        item = ev.get(eid)
        text = item["text"] or dumps(item["data"])
        passages = [{"start": a, "end": b, "text": text[a:b]} for a, b in cp.get("read_ranges", {}).get(eid, [])]
        inputs.append({"id": eid, "sha256": item["sha256"], "kind": item["kind"], "meta": item["meta"], "read_passages": passages})
    fixed = {"cutoff": cfg["cutoff"], "mode": cfg["mode"], "scope": cfg["scope"], "evidence": inputs,
             "response_schema": Report.model_json_schema()}
    atomic_write(directory / "fixed-inputs.json", dumps(fixed))
    final = Report.model_validate(cp["draft"])
    variants = {"harness": final}
    # The first saved draft is an observational ablation, not an independent randomized trial.
    writes = sorted((store.directory(run_id) / "calls").glob("*-write-output.json"))
    for path in writes:
        try:
            draft = Report.model_validate(extract_json(json.loads(path.read_text())["text"]))
            variants["before_review"] = draft
            break
        except (ValueError, KeyError):
            continue
    if baseline:
        output_path = directory / "baseline-output.json"
        baseline_model = model or cfg["model"]
        request = {"prompt": dumps(fixed), "system": WRITER_SYSTEM,
                   "model": baseline_model, "effort": cfg["effort"], "timeout": 450, "job": "weekly.evaluation_baseline",
                   "json_schema": Report.model_json_schema()}
        atomic_write(directory / "baseline-input.json", dumps(request))
        result = model_call(request) if model_call else isolated("model", request, timeout=455)
        atomic_write(output_path, dumps(result))
        variants["single_pass"] = Report.model_validate(extract_json(result.get("text", "")))
    seed = int(digest(run_id)[:8], 16)
    order = list(variants)
    random.Random(seed).shuffle(order)
    mapping, scores = {}, {}
    e = html.escape
    for index, name in enumerate(order):
        label = chr(65 + index)
        report = variants[name]
        mapping[label] = name
        citations = citation_labels(report)
        content = f'<h1>브리핑 {label}</h1><h2>{e(report.title)}</h2>' + rendered_claim(report.standfirst, ev, citations)
        for section in report.sections:
            content += f'<h2>{e(section.heading)}</h2>' + ''.join(rendered_claim(c, ev, citations) for c in section.claims)
        content += '<h2>판단 변경 조건</h2>' + ''.join(f'<p>{e(h.question)} · {e(h.change_condition)}</p>' for h in report.hypotheses)
        content += '<h2>공백</h2>' + ''.join(f'<p>{e(g)}</p>' for g in report.gaps)
        content += '<p><a href="../briefing.html">공통 고정 근거 부록</a> · <a href="fixed-inputs.json">동일 입력 자료</a></p>'
        # Citation anchors point to the common frozen evidence, without runtime/model labels.
        content = content.replace('href="#e-', 'href="../briefing.html#e-')
        atomic_write(directory / f"briefing-{label}.html", f'<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>브리핑 {label}</title><style>{STYLE}</style><main>{content}</main></html>')
        scores[label] = {"axes": {key: {"score": None, "evidence": ""} for key, _, _ in AXES},
                         "material_errors": [], "core_rewrite_required": None, "expert_pass": None}
    atomic_write(directory / "sealed-variant-map.json", dumps(mapping))
    atomic_write(directory / "expert-scorecard.json", dumps({"run_id": run_id, "reference_weekly_path": str(reference_manifest) if reference else None, "reviewer": None, "reviewed_at": None, "reports": scores}))
    manifest = {"run_id": run_id, "created_at": now(), "fixed_inputs_sha256": digest(fixed), "variants": list(variants),
                "expert_quality": "not_evaluated", "benchmark_source": reference or "not_attached",
                "mechanical_checks": {name: check(report, ev, cp) for name, report in variants.items()},
                "limitations": ["후보 원문/차트가 아직 첨부되지 않으면 원문급 비교는 수행되지 않은 것입니다.",
                                "같은 자료의 분석 능력 비교입니다. 조사 능력 비교와 미래 주차 평가는 별도입니다.",
                                "before_review는 동일 실행의 첫 초안입니다. 완전히 독립된 reviewer 제거 실험은 아닙니다.",
                                "번호를 가렸지만 스타일·내용으로 조건을 추정할 수 있어 완전한 블라인드가 아닙니다."]}
    atomic_write(directory / "manifest.json", dumps(manifest))
    rubric = '<h1>Weekly 전문가 평가</h1><p>보고서 번호만 보고 먼저 독립 평가한 뒤 sealed-variant-map.json으로 조건을 확인합니다. 점수와 판정은 비워 두었습니다.</p>'
    if reference:
        from .render import safe_link
        url = safe_link(reference.get("url"))
        link = f'<a href="{e(url, quote=True)}">{e(reference.get("title") or "기준 Weekly")}</a>' if url else e(reference.get("title") or "기준 Weekly")
        rubric += f'<p>비교 원문: {link} · 보존 이미지 {reference["image_count"]}개. 원문의 보고 기간·추가 작성 시각과 생성 보고서 cutoff를 따로 확인하세요. 원문의 결론도 사실 검증이 필요한 참고 판단이며 정답으로 취급하지 않습니다. 기준선 작성 입력에는 원문을 넣지 않았습니다.</p>'
    rubric += '<p>0: 근본적 실패 · 1: 핵심 재작성 필요 · 2: 부분 수정 필요 · 3: 작은 수정만 필요 · 4: 충분히 충족. 합산 점수로 중대한 사실 오류를 상쇄하지 않습니다.</p>'
    rubric += '<ul>' + ''.join(f'<li><a href="briefing-{label}.html">브리핑 {label}</a></li>' for label in mapping) + '</ul>'
    rubric += '<table><thead><tr><th>축</th><th>평가 질문</th></tr></thead><tbody>' + ''.join(f'<tr><td>{e(title)}</td><td>{e(question)}</td></tr>' for _, title, question in AXES) + '</tbody></table>'
    rubric += '<p>핵심 사실·시간·계산 오류 0건, 핵심 질문과 논증 재작성 불필요가 통과의 전제입니다. 기준 원문과 12개 차트로 보고된 자료의 실제 확보·검증 여부도 기록하세요.</p>'
    rubric += '<p><a href="expert-scorecard.json">점수 기록 JSON</a> · <a href="manifest.json">실험 범위·기계 검증</a></p>'
    atomic_write(directory / "index.html", f'<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Weekly 평가</title><style>{STYLE}</style><main>{rubric}</main></html>')
    return str(directory / "index.html")
