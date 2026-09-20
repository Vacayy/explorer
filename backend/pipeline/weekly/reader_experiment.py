"""Resumable same-evidence writing experiment, isolated from the live publishing path."""
import fcntl
import hashlib
import json
import time
from pathlib import Path

from pydantic import ValidationError

from models.weekly_reader import ComparisonRequest, FactualReview, InvestorReview, Judgment, ReaderBrief, ReaderCitationRepairs
from . import reader_prompts as prompts
from .reader_render import write_brief, write_support
from .reader_review import check, plain, publishable
from .store import atomic_write, digest, dumps, now
from .worker import Cancelled, isolated


def model_packet(packet):
    """No target report, previous draft, raw price history or execution diary."""
    result = {key: packet[key] for key in ("period", "cutoff", "sources", "metrics", "charts", "coverage", "gaps")}
    if packet.get("workflow") == "research":
        from .research import writing_sources
        result["sources"] = writing_sources(packet)
    return result


def run(directory, *, model_call=None):
    directory = Path(directory).resolve()
    with (directory / ".run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("이 비교 실행이 이미 진행 중입니다") from exc
        return _run(directory, model_call=model_call)


def _run(directory, *, model_call=None):
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("status") not in {"prepared", "running", "partial", "cancelled", "completed"}:
        raise ValueError("입력 준비가 완료된 비교만 실행할 수 있습니다")
    request = ComparisonRequest.model_validate(manifest["request"])
    packet = json.loads((directory / "packet.json").read_text())
    if digest(packet) != manifest.get("packet_sha256"):
        raise ValueError("동결된 입력 자료가 변경되었습니다. 새 request_key로 준비하세요")
    for name, expected in manifest.get("research_inputs", {}).items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
            raise ValueError("동결된 연구 입력이 변경되었습니다: " + name)
    paths = sorted((directory / "evidence").glob("*.json")) + sorted((directory / "charts").glob("*.svg"))
    files = {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    if manifest.get("evidence_files") is not None and manifest["evidence_files"] != files:
        raise ValueError("보관 원문 또는 차트가 변경되었습니다")
    manifest["evidence_files"] = files
    if manifest.get("status") == "completed":
        return manifest
    code_files = [Path(__file__), Path(prompts.__file__), Path(__file__).with_name("reader_review.py")]
    if request.workflow == "research":
        from .research import ResearchDesk
        from . import research_prompts
        from models import weekly_research, weekly_reader
        code_files += [Path(__file__).with_name("research.py"), Path(research_prompts.__file__),
                       Path(weekly_research.__file__), Path(weekly_reader.__file__)]
    if request.completion_engine == "codex-exec":
        code_files += [Path(__file__).with_name("codex_completion.py"), Path(__file__).with_name("worker.py")]
    contract = digest({p.name: p.read_text() for p in code_files})
    # Host validation fixes may resume the same evidence experiment. Cached model
    # inputs must still match byte-for-byte; changed prompts/schema cannot silently reuse results.
    prior_contract = manifest.get("execution_contract")
    if prior_contract and prior_contract != contract:
        manifest.setdefault("contract_changes", []).append({"previous": prior_contract, "current": contract,
                                                            "at": now(), "stage": manifest.get("active_stage")})
        for path in directory.glob("*.html"):
            atomic_write(directory / "previous-exports" / prior_contract[:12] / path.name, path.read_text())
        for path in [*directory.glob("*-checks.json"), *[directory / name for name in ("single.json", "judged.json", "reviewed.json", "judgment.json") if (directory / name).exists()]]:
            atomic_write(directory / "previous-exports" / prior_contract[:12] / path.name, path.read_text())
    for path in code_files:
        atomic_write(directory / "implementation" / contract / path.name, path.read_text())
    manifest["execution_contract"] = contract
    if (directory / "cancel.requested").exists():
        raise Cancelled("취소된 실행입니다. 명시적으로 resume 하세요")
    started = time.monotonic()
    manifest.update(status="running", resumed_at=now(), active_stage=None)
    manifest.setdefault("calls", {})
    manifest["attempts"] = manifest.get("attempts", 0) + 1
    manifest.setdefault("attempt_history", []).append({"started_at": now(), "contract": contract,
                                                       "max_seconds": request.max_seconds})

    def save():
        atomic_write(directory / "manifest.json", dumps(manifest))
        write_support(directory, packet, manifest)

    save()
    fetch = model_call or (lambda payload, timeout, cancelled: isolated("model", payload, timeout=timeout, cancelled=cancelled))
    cancelled = lambda: (directory / "cancel.requested").exists()
    context = dumps(model_packet(packet))

    def call(stage, system, content, schema, *, effort=None):
        # Re-synthesis already has independently researched memos and review
        # findings. Bound its deliberation; keep source/factual review at the
        # requested effort. Each effective setting remains in the call record.
        if effort is None and request.workflow == "research" and (
            stage.startswith("research-revised-decision") or stage in {"reviewed", "reviewed-structure-repair"}
        ):
            effort = "medium" if request.effort == "high" else request.effort
        payload = {"system": system, "prompt": content, "model": request.model, "effort": effort or request.effort,
                   "timeout": request.call_timeout, "job": "weekly-reader-" + stage, "json_schema": schema.model_json_schema()}
        if stage.startswith("reviewed") and request.completion_engine == "codex-exec":
            payload.update(engine="codex-exec", model=request.completion_model)
        key = digest(payload)
        cache = directory / "calls" / f"{stage}.json"
        if cancelled():
            raise Cancelled("취소 요청")
        if cache.exists():
            prior = json.loads(cache.read_text())
            if prior["input_sha256"] != key and prior.get("parsed") is None:
                # A cancelled/failed call has no reusable result. Preserve its
                # attempt before a revised stage input; completed calls still
                # require exact identity. Contract changes are recorded above.
                atomic_write(directory / "calls" / "history" / f"{stage}-{digest(prior)[:16]}.json", dumps(prior))
                cache.unlink()
        if cache.exists():
            prior = json.loads(cache.read_text())
            if prior["input_sha256"] != key:
                raise ValueError("저장된 호출과 입력이 다릅니다: " + stage)
            if digest(prior["payload"]) != key:
                raise ValueError("보관된 호출 입력이 변경되었습니다: " + stage)
            # Failed or interrupted calls do not become valid cached outputs.
            if prior.get("parsed") is not None:
                original = schema.model_validate_json(prior["result"]["text"]).model_dump(mode="json")
                if original != prior["parsed"]:
                    raise ValueError("보관된 모델 출력이 변경되었습니다: " + stage)
                recorded_hash = manifest["calls"].get(stage, {}).get("output_sha256")
                if recorded_hash and digest(original) != recorded_hash:
                    raise ValueError("보관된 모델 출력 hash 불일치: " + stage)
                return schema.model_validate(prior["parsed"])
            atomic_write(directory / "calls" / "history" / f"{stage}-{digest(prior)[:16]}.json", dumps(prior))
        remaining = request.max_seconds - (time.monotonic() - started)
        if remaining < request.call_timeout + 5:
            raise TimeoutError("비교 실행의 남은 시간 예산이 다음 호출 상한보다 작습니다. 저장된 결과에서 재개할 수 있습니다")
        manifest["active_stage"] = stage
        save()
        record = {"input_sha256": key, "started_at": now(), "payload": payload}
        atomic_write(cache, dumps(record))
        try:
            result = fetch(payload, request.call_timeout + 5, cancelled)
        except (Cancelled, TimeoutError, RuntimeError) as exc:
            record.update(finished_at=now(), error=str(exc))
            atomic_write(cache, dumps(record))
            manifest.setdefault("incomplete_calls", []).append({"stage": stage, "input_sha256": key,
                                                                 "started_at": record["started_at"], "finished_at": record["finished_at"],
                                                                 "error": str(exc), "cost_usd": None})
            raise
        record.update(result=result, finished_at=now())
        atomic_write(cache, dumps(record))
        manifest["calls"][stage] = {k: result.get(k) for k in ("usage", "cost_usd", "duration_ms", "model", "engine", "structured_output_enforced")}
        manifest["calls"][stage]["input_sha256"] = key
        save()
        try:
            parsed = schema.model_validate_json(result["text"])
        except (ValueError, ValidationError, KeyError) as exc:
            # A failed native schema stays a visible failure; never manufacture a passing result.
            record["parse_error"] = type(exc).__name__
            atomic_write(cache, dumps(record))
            raise ValueError("구조화된 모델 결과를 검증하지 못했습니다: " + stage) from exc
        record["parsed"] = parsed.model_dump(mode="json")
        atomic_write(cache, dumps(record))
        manifest["calls"][stage]["output_sha256"] = digest(record["parsed"])
        atomic_write(directory / "manifest.json", dumps(manifest))
        return parsed

    def write_variant(name, system, content):
        brief = call(name, system, content, ReaderBrief)
        mechanical = check(brief, packet)
        source_unresolved = []
        if mechanical["blocking"]:
            citation_only = request.workflow == "research" and all(
                issue["reason"].startswith(("의견을 지지하는 근거 연결 없음", "제공 원문에 없는 인용:", "본문에 없는 인용 위치"))
                for issue in mechanical["issues"])
            if citation_only:
                targets = {issue["location"] for issue in mechanical["issues"]}
                repairs = call(name + "-source-repair", prompts.SOURCE_REPAIR,
                               dumps({"paragraphs": [p.model_dump() for p in brief.paragraphs() if p.id in targets],
                                      "sources": model_packet(packet)["sources"], "issues": mechanical["issues"]}),
                               ReaderCitationRepairs, effort="medium")
                if sorted(p.paragraph_id for p in repairs.paragraphs) != sorted(targets):
                    raise ValueError("요청한 문단의 인용만 한 번씩 수정해야 합니다")
                replacements = {p.paragraph_id: p.sources for p in repairs.paragraphs}
                source_unresolved = repairs.unresolved
                for paragraph in brief.paragraphs():
                    if paragraph.id in replacements:
                        paragraph.sources = replacements[paragraph.id]
                atomic_write(directory / f"{name}-source-repair.json", dumps(repairs.model_dump(mode="json")))
            else:
                brief = call(name + "-structure-repair", prompts.WRITING,
                             content + "\n기존 초안: " + brief.model_dump_json() +
                             "\n형식·출처 연결 검사: " + dumps(mechanical) +
                             "\n시장 의견을 재평가하는 단계가 아닙니다. 지적된 형식·출처 연결 오류를 실제 근거에 맞게 고치세요.", ReaderBrief)
            mechanical = check(brief, packet)
            # These are model opinions, not deterministic format failures.
            # The factual reviewer gets metrics and originals to adjudicate them.
            if source_unresolved:
                mechanical["source_review_notes"] = source_unresolved
        atomic_write(directory / f"{name}-checks.json", dumps({"mechanical": mechanical}))
        write_brief(directory, name, brief, packet)
        save()
        archive_variant(name)
        return brief, mechanical

    def archive_variant(name):
        if request.workflow == "research":
            # The next research round may replace selected spans. Keep every
            # inspectable draft linked to the evidence it actually received.
            atomic_write(directory / f"{name}-packet.json", dumps(packet))
            atomic_write(directory / f"{name}-evidence.html", (directory / "evidence.html").read_text())
            html = directory / f"{name}.html"
            atomic_write(html, html.read_text().replace('href="evidence.html', f'href="{name}-evidence.html'))

    try:
        if request.workflow == "comparison":
            single, _ = write_variant("single", prompts.WRITING, "동일 동결 자료:\n" + context)
        desk = None
        editorial = ""
        if request.workflow == "research":
            desk = ResearchDesk(directory, packet, call, cancelled=cancelled)
            packet, decision = desk.start()
            context = dumps(model_packet(packet))
            judgment = decision.judgment
            editorial = "\n집필 판단 계약:\n" + dumps(desk.writing_contract(decision))
            manifest.update(research_packet_sha256=digest(packet),
                            document_count=sum(s["kind"] == "document" for s in packet["sources"].values()),
                            unresolved_material=decision.unresolved_material)
        else:
            judgment = call("judgment", prompts.JUDGING, "동일 동결 자료:\n" + context, Judgment)
        atomic_write(directory / "judgment.json", dumps(judgment.model_dump(mode="json")))
        judged, mechanical = write_variant("judged", prompts.WRITING,
                                           "동일 동결 자료:\n" + context + "\n현재 판단 요약:\n" + judgment.model_dump_json() + editorial)

        def reviews(brief, prefix):
            text = plain(brief, packet)
            repair_file = directory / f"{prefix}-source-repair.json"
            notes = json.loads(repair_file.read_text()).get("unresolved", []) if repair_file.exists() else []
            factual = call(prefix + "-facts", prompts.FACT_CHECK,
                           "동결 근거:\n" + context + "\n브리핑:\n" + text + "\n인용 연결:\n" + brief.model_dump_json() + editorial +
                           ("\n각주 보완자의 미해결 의견(판정 아님; 원문·metrics와 대조):\n" + dumps(notes) if notes else ""), FactualReview)
            # Deliberately receives neither the packet nor the writer's intended judgment.
            investor = call(prefix + "-investor", prompts.INVESTOR_CHECK, text, InvestorReview)
            return factual.model_dump(mode="json"), investor.model_dump(mode="json")

        factual, investor = reviews(judged, "judged")
        checks = {"mechanical": mechanical, "factual": factual, "investor": investor}
        atomic_write(directory / "judged-checks.json", dumps(checks))
        needs_revision = mechanical["blocking"] or factual["issues"] or investor["issues"] or investor["verdict"] == "rewrite"
        if needs_revision:
            if desk:
                packet, decision = desk.reopen({"checks": checks, "draft": judged.model_dump(mode="json"),
                                               "previous_decision": decision.model_dump(mode="json")})
                context = dumps(model_packet(packet))
                revised_judgment = decision.judgment
                editorial = "\n집필 판단 계약:\n" + dumps(desk.writing_contract(decision))
                manifest.update(research_packet_sha256=digest(packet),
                                document_count=sum(s["kind"] == "document" for s in packet["sources"].values()),
                                unresolved_material=decision.unresolved_material)
            else:
                revised_judgment = call("reviewed-judgment", prompts.REJUDGING,
                                    "동일 동결 자료:\n" + context + "\n현재 판단 요약:\n" + judgment.model_dump_json() +
                                    "\n검사 결과:\n" + dumps(checks), Judgment)
            atomic_write(directory / "reviewed-judgment.json", dumps(revised_judgment.model_dump(mode="json")))
            reviewed, mechanical = write_variant("reviewed", prompts.WRITING,
                                                  "동일 동결 자료:\n" + context + "\n현재 판단 요약:\n" + revised_judgment.model_dump_json() + editorial)
            if not mechanical["blocking"]:
                factual, investor = reviews(reviewed, "reviewed")
            else:
                factual, investor = None, None
        else:
            reviewed = judged
        approved = publishable(mechanical, factual, investor) and not manifest.get("unresolved_material")
        checks = {"mechanical": mechanical, "factual": factual, "investor": investor,
                  "automatic_checks_passed": approved, "expert_quality": "not_evaluated",
                  "unresolved_material": manifest.get("unresolved_material", [])}
        atomic_write(directory / "reviewed-checks.json", dumps(checks))
        write_brief(directory, "reviewed", reviewed, packet, approved=approved)
        manifest.update(status="completed", active_stage=None, completed_at=now(), automatic_checks_passed=approved,
                        revision_used=bool(needs_revision), winner=None, expert_quality="not_evaluated")
        save()
        archive_variant("reviewed")
        return manifest
    except (Cancelled, TimeoutError, ValueError, RuntimeError) as exc:
        manifest.update(status="cancelled" if isinstance(exc, Cancelled) else "partial", last_error=str(exc), stopped_at=now())
        save()
        raise
