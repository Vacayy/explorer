"""Question-led, original-source research over an immutable local corpus.

The host owns reads, citation validation, budgets and provenance. Models propose
bounded actions; neither channel profiles nor search snippets become evidence.
"""
import copy
import hashlib
import json
import re
import shutil
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from models.weekly_reader import ComparisonRequest
from models.weekly_research import CitationRepairs, ChallengeSet, DecisionBrief, DecisionSelectionRepair, ResearchAgenda, ResearchStep, SearchRequest
from . import research_prompts as prompts
from .evidence import Evidence, instant, readonly
from .reader_render import e, page
from .store import Store, atomic_write, digest, dumps, now
from .worker import Cancelled


def exact_whitespace_quote(text, quote):
    """Recover raw characters for a unique whitespace-only match, never words."""
    if quote in text:
        return quote
    parts = list(re.finditer(r"\s+|\S", text))
    normalized = "".join(" " if m.group().isspace() else m.group() for m in parts)
    needle = re.sub(r"\s+", " ", quote).strip()
    start = normalized.find(needle)
    if not needle or start < 0 or normalized.find(needle, start + 1) >= 0:
        return None
    return text[parts[start].start():parts[start + len(needle) - 1].end()]


def writing_sources(packet):
    """Omit duplicate metric JSON from model context; retain the raw evidence."""
    sources = copy.deepcopy(packet["sources"])
    for source in sources.values():
        if source["kind"] == "series":
            content = json.loads(source["text"])
            content.pop("calculation", None)  # Identical records live in packet.metrics.
            source["text"] = dumps(content)
    return sources


def channel_key(meta):
    source = str(meta.get("source_id") or "")
    if meta.get("source_type") == "blog":
        url = urlsplit(meta.get("url") or source)
        if "naver.com" in url.netloc:
            return parse_qs(url.query).get("blogId", [url.path.strip("/").split("/")[0]])[0]
        return url.netloc
    return source.split("/")[0]


def routing_snapshot(database):
    """Routing metadata has its own capture time; never evidence for the past."""
    with readonly(database) as conn:
        conn.execute("BEGIN")
        profiles = [dict(r) for r in conn.execute("SELECT kind,key,digest,insights,created_at FROM source_digests ORDER BY kind,key")]
        people = [dict(r) for r in conn.execute("SELECT id,name,aliases FROM entities WHERE type='person' ORDER BY id")]
        links = [list(r) for r in conn.execute("SELECT l.doc_id,l.entity_id FROM entity_links l JOIN entities e ON e.id=l.entity_id WHERE e.type='person' ORDER BY l.doc_id,l.entity_id")]
    return {"captured_at": now(), "usage": "retrieval_only; current profiles/tags, not historical evidence",
            "profiles": profiles, "people": people, "links": links}


def prepare_research(base_directory, request_key, *, database=None, max_seconds=7200):
    """Keep the comparison's period, cutoff and numeric inputs; reopen its corpus."""
    base = Path(base_directory).resolve()
    prior = json.loads((base / "manifest.json").read_text())
    config = {**prior["request"], "request_key": request_key, "workflow": "research", "max_seconds": max_seconds}
    request = ComparisonRequest.model_validate(config)
    directory = base.parent / request.request_key
    if directory.exists():
        raise ValueError("새 request_key가 필요합니다. 기존 실행을 덮어쓰지 않습니다")
    packet = json.loads((base / "packet.json").read_text())
    if digest(packet) != prior["packet_sha256"]:
        raise ValueError("원본 packet hash 불일치")
    for name, expected in prior["evidence_files"].items():
        if hashlib.sha256((base / name).read_bytes()).hexdigest() != expected:
            raise ValueError("원본 evidence hash 불일치: " + name)
    corpus = Evidence(Store().directory(request.source_run_id))
    if corpus.file_hash() != prior["source_corpus_sha256"]:
        raise ValueError("원본 corpus hash 불일치")
    directory.mkdir(parents=True)
    manifest = {"request": request.model_dump(mode="json"), "status": "preparing", "created_at": now(),
                "base_request": base.name, "source_corpus_sha256": corpus.file_hash(),
                "expert_quality": "not_evaluated", "research_version": 1}
    atomic_write(directory / "manifest.json", dumps(manifest))
    shutil.copyfile(corpus.path, directory / "corpus.sqlite")
    for folder in ("evidence", "charts"):
        if (base / folder).exists():
            shutil.copytree(base / folder, directory / folder)
    # Preserve already acquired official documents as discoverable sources, not a
    # hand-picked narrative. All local documents remain searchable in the corpus.
    extras = {sid: s for sid, s in packet["sources"].items() if s["kind"] == "document" and not re.fullmatch(r"d\d+", sid)}
    atomic_write(directory / "external-catalog.json", dumps(extras))
    routing = routing_snapshot(database or Path(__file__).resolve().parents[2] / "db/stock_explorer.db")
    atomic_write(directory / "routing.json", dumps(routing))
    packet["sources"] = {sid: s for sid, s in packet["sources"].items() if s["kind"] == "series"}
    packet["coverage"] = {"baseline_series": list(packet["sources"])}
    packet.update(workflow="research", method="question_led_frozen_corpus; no reference or previous generated prose supplied")
    atomic_write(directory / "packet.json", dumps(packet))
    manifest.update(status="prepared", packet_sha256=digest(packet), document_count=0,
                    research_inputs={name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                                     for name in ("corpus.sqlite", "routing.json", "external-catalog.json")},
                    evidence_files=prior["evidence_files"])
    atomic_write(directory / "manifest.json", dumps(manifest))
    return directory


class ResearchDesk:
    def __init__(self, directory, packet, call, *, cancelled=lambda: False):
        self.directory, self.packet, self.call = Path(directory), copy.deepcopy(packet), call
        self.cancelled = cancelled
        self.ev = Evidence(directory)
        self.routing = json.loads((self.directory / "routing.json").read_text())
        self.extra = json.loads((self.directory / "external-catalog.json").read_text())
        self.people = {p["id"]: p for p in self.routing["people"]}
        self.tags = {}
        for doc, person in self.routing["links"]:
            self.tags.setdefault(f"d{doc}", []).append(person)
        self.profiles = {}
        for p in self.routing["profiles"]:
            key = channel_key({"source_type": p["kind"], "source_id": p["key"]})
            previous = self.profiles.get((p["kind"], key))
            if not previous or p["created_at"] > previous["created_at"]:
                self.profiles[(p["kind"], key)] = {**p, "channel": key}
        self.documents = {}
        cutoff = instant(packet.get("origin_snapshot_cutoff", packet["cutoff"]))
        with readonly(self.ev.path) as conn:
            for row in conn.execute("SELECT id,meta,text FROM items WHERE kind='document' ORDER BY id"):
                meta = json.loads(row["meta"])
                bound = instant(meta.get("available_at_bound"))
                if not bound or bound > cutoff or meta.get("temporal_status") == "historical_version_unverified":
                    continue
                if meta.get("content_kind") in {"derived_summary", "stored_markdown_unverified"}:
                    continue
                if "3da9e403cb628080a1fed604f8542436" in (meta.get("url") or ""):
                    continue
                self.documents[row["id"]] = {"meta": meta, "text": row["text"]}
        for sid, source in self.extra.items():
            item = json.loads((self.directory / source["raw_file"]).read_text())
            self.documents[sid] = {"meta": source["meta"], "text": item["text"]}
        self.events, self.memos, self.challenges = [], {}, []
        self.memo_history = []
        self.read_by_question = {}
        self.baseline = copy.deepcopy({k: self.packet[k] for k in ("period", "cutoff", "sources", "metrics", "charts", "gaps")})
        # Metrics already contain every value/definition/date. Avoid repeating
        # their full JSON inside each series source and every research call.
        self.baseline["sources"] = {sid: {"title": s["meta"]["title"], "kind": "series",
                                         "week_points": json.loads(s["text"]).get("week_points", []),
                                         "warnings": s["meta"].get("warnings", [])}
                                    for sid, s in self.baseline["sources"].items()}
        self.agenda = None

    def record(self, kind, **data):
        event = {"sequence": len(self.events) + 1, "kind": kind, **data}
        self.events.append(event)
        atomic_write(self.directory / "research" / "events.json", dumps(self.events))

    def candidate(self, sid, *, query="", excerpt_chars=400):
        source = self.documents[sid]
        terms = query.casefold().split()
        positions = [source["text"].casefold().find(t) for t in terms]
        start = max(0, next((p for p in positions if p >= 0), 0) - 100)
        meta = source["meta"]
        return {"source_id": sid, "title": meta.get("title"), "published_at": meta.get("published_at"),
                "channel": channel_key(meta), "source_type": meta.get("source_type"),
                "people": [self.people[p]["name"] for p in self.tags.get(sid, []) if p in self.people][:6],
                "length": len(source["text"]), "excerpt_start": start, "excerpt": source["text"][start:start + excerpt_chars],
                "status": "discovered; not read"}

    def discover(self):
        since = (date.fromisoformat(self.packet["period"]["week_start"]) - timedelta(days=14)).isoformat()
        counts, entries = Counter(), []
        for sid, source in sorted(self.documents.items(), key=lambda p: p[1]["meta"].get("published_at") or "", reverse=True):
            if (source["meta"].get("published_at") or "") < since:
                continue
            key = (source["meta"].get("source_type"), channel_key(source["meta"]))
            if counts[key] >= 3:
                continue
            counts[key] += 1
            entries.append(self.candidate(sid, excerpt_chars=160))
        profiles = [{"kind": p["kind"], "channel": p["channel"], "profile_excerpt": (p.get("digest") or "")[:600],
                     "captured_at": p["created_at"], "usage": "routing only"}
                    for p in self.profiles.values() if (p["kind"], p["channel"]) in counts]
        return {"recent_candidates": entries[:150], "channel_profiles": profiles,
                "eligible_documents": len(self.documents), "routing_capture": self.routing["captured_at"],
                "note": "채널별 최근 최대3개/전체150개 탐색 표본. 검색은 전체 동결 원문을 대상으로 한다."}

    def search(self, request):
        terms = re.findall(r"[\w가-힣]+", request.query.casefold())
        ranked = []
        for sid, source in self.documents.items():
            meta, text = source["meta"], source["text"]
            channel = channel_key(meta)
            if request.channel and request.channel.casefold() not in channel.casefold():
                continue
            day = (meta.get("published_at") or "")[:10]
            if request.since and day < request.since or request.until and day > request.until:
                continue
            people = " ".join(self.people[p]["name"] + " " + (self.people[p]["aliases"] or "")
                              for p in self.tags.get(sid, []) if p in self.people).casefold()
            haystack = (meta.get("title", "") + " " + text).casefold()
            if request.person and request.person.casefold() not in people and request.person.casefold() not in haystack:
                continue
            matches = sum(t in haystack for t in terms)
            tagged = sum(t in people for t in terms)
            if not matches and not tagged:
                continue
            profile = self.profiles.get((meta.get("source_type"), channel), {})
            boost = sum(t in ((profile.get("digest") or "") + (profile.get("insights") or "")).casefold() for t in terms)
            score = matches * 10 + min(tagged, 2) * 2 + min(boost, 2)
            ranked.append((score, day, sid))
        ranked.sort(reverse=True)
        seen, counts, ids = set(), Counter(), []
        for _, _, sid in ranked:
            meta = self.documents[sid]["meta"]
            group = meta.get("duplicate_group", sid)
            key = channel_key(meta)
            if group in seen or (not request.channel and counts[key] >= 5):
                continue
            seen.add(group)
            counts[key] += 1
            ids.append(sid)
        selected = ids[request.offset:request.offset + 10]
        return {"candidates": [self.candidate(sid, query=request.query) for sid in selected],
                "total_diversified": len(ids), "next_offset": request.offset + 10 if len(ids) > request.offset + 10 else None,
                "note": "본문 일치 우선; 프로필/인물은 탐색 보조. 채널당 최대5개, 채널 지정 시 제한 없음. 검색 발췌는 인용 불가."}

    def read(self, request, question_id):
        if request.source_id not in self.documents:
            return {"error": "자격 있는 동결 원문 ID가 아닙니다"}
        source = self.documents[request.source_id]
        start, stop = request.start, min(len(source["text"]), request.start + request.length)
        if start >= stop:
            return {"error": "원문 범위 밖입니다", "full_length": len(source["text"])}
        sid = f"{request.source_id}-r{start}-{stop}"
        raw_file = f"research/evidence/{request.source_id}.json"
        if request.source_id in self.extra:
            raw = json.loads((self.directory / self.extra[request.source_id]["raw_file"]).read_text())
        else:
            raw = self.ev.get(request.source_id)
        atomic_write(self.directory / raw_file, dumps(raw))
        item = {"id": sid, "kind": "document", "meta": source["meta"], "text": source["text"][start:stop],
                "range": [start, stop], "full_length": len(source["text"]), "original_source_id": request.source_id,
                "sha256": digest(raw), "areas": [question_id], "raw_file": raw_file}
        self.packet["sources"][sid] = item
        self.read_by_question.setdefault(question_id, set()).add(sid)
        self.packet["coverage"].setdefault(question_id, [])
        if sid not in self.packet["coverage"][question_id]:
            self.packet["coverage"][question_id].append(sid)
        return {**item, "status": "read", "next_start": stop if stop < len(source["text"]) else None}

    def validate_memo(self, memo, question_id):
        if memo.question_id != question_id:
            raise ValueError("연구 메모 담당 쟁점 불일치")
        ids = set()
        for claim in memo.claims:
            if not claim.id.startswith(question_id + "-") or claim.id in ids:
                raise ValueError("연구 claim ID 불일치/중복")
            ids.add(claim.id)
        problems = self.citation_problems(memo, question_id)
        if problems:
            raise ValueError(dumps(problems))

    def citation_problems(self, memo, question_id):
        problems = []
        for claim in memo.claims:
            for cite in claim.citations:
                if cite.source_id not in self.read_by_question.get(question_id, set()):
                    # Models sometimes return the requested document ID instead
                    # of the returned span ID. Resolve only a unique, actually
                    # delivered span containing the exact quote; never search
                    # the corpus or extend the read boundary during validation.
                    matches = [sid for sid in self.read_by_question.get(question_id, set())
                               if self.packet["sources"][sid].get("original_source_id") == cite.source_id
                               and exact_whitespace_quote(self.packet["sources"][sid]["text"], cite.quote) is not None]
                    if len(matches) == 1:
                        self.record("citation_resolved", question_id=question_id, claim_id=claim.id,
                                    requested_document_id=cite.source_id, read_span_id=matches[0])
                        cite.source_id = matches[0]
                if cite.source_id in self.read_by_question.get(question_id, set()):
                    raw_quote = exact_whitespace_quote(self.packet["sources"][cite.source_id]["text"], cite.quote)
                    if raw_quote is not None and raw_quote != cite.quote:
                        self.record("citation_whitespace_resolved", question_id=question_id, claim_id=claim.id,
                                    source_id=cite.source_id, requested_quote=cite.quote, exact_quote=raw_quote)
                        cite.quote = raw_quote
                if cite.source_id not in self.read_by_question.get(question_id, set()):
                    reason = "연구원이 읽지 않은 원문 인용"
                elif cite.quote not in self.packet["sources"][cite.source_id]["text"]:
                    reason = "원문에 없는 연구 인용"
                else:
                    continue
                problems.append({"claim_id": claim.id, "source_id": cite.source_id, "quote": cite.quote, "reason": reason})
        return problems

    def investigate(self, question, stage, request=None, rounds=4):
        context = {"baseline": self.baseline, "question": question.model_dump(mode="json"), "followup": request,
                   "previous_memo": self.memos.get(question.id), "tool_results": []}
        # Initial retrieval is driven by the lead's question, then the researcher
        # changes search/reading actions based on the returned original sources.
        queries = [request["query"]] if request and request.get("query") else question.search_terms[:3]
        for query in queries:
            try:
                req = SearchRequest(query=query)
                search = req.model_dump()
                result = self.search(req)
            except ValueError:
                # A reviewer may put reading instructions in its query field.
                # Preserve that request for the researcher, reject the invalid
                # tool argument, and let it issue a short query or direct read.
                search = {"query": query}
                result = {"candidates": [], "error": "검색 query는 1~160자여야 합니다. 짧은 검색어를 선택하거나 요청의 원문 ID를 직접 읽으세요."}
            self.record("search", stage=stage, question_id=question.id, request=search, result=result)
            context["tool_results"].append({"search": search, "result": result})
        for iteration in range(rounds + 1):
            if self.cancelled():
                raise Cancelled("취소 요청")
            context["remaining_action_rounds"] = rounds - iteration
            context["remaining_context_chars"] = max(0, 155000 - len(dumps(context)))
            if iteration == rounds:
                context["instruction"] = "도구 예산 종료. 확보한 근거로 memo를 제출하고 미확인 사항을 unresolved에 남겨라."
            step = self.call(f"research-{stage}-{iteration}", prompts.RESEARCH, dumps(context), ResearchStep)
            self.record("model_decision", stage=stage, question_id=question.id, iteration=iteration, decision=step.model_dump(mode="json"))
            if step.memo:
                try:
                    self.validate_memo(step.memo, question.id)
                except ValueError as exc:
                    problems = self.citation_problems(step.memo, question.id)
                    if not problems:
                        raise
                    bad = {p["claim_id"] for p in problems}
                    relevant = {c.source_id for claim in step.memo.claims if claim.id in bad for c in claim.citations}
                    allowed = {sid: s for sid, s in self.packet["sources"].items()
                               if sid in self.read_by_question.get(question.id, set())
                               and (sid in relevant or s.get("original_source_id") in relevant)}
                    if not allowed:
                        raise ValueError("수정할 인용의 적격 읽기 구간이 없습니다") from exc
                    repair_context = {"errors": problems, "claims": [c.model_dump() for c in step.memo.claims if c.id in bad],
                                      "allowed_sources": allowed}
                    repairs = self.call(f"research-{stage}-{iteration}-citations-v2-{digest(repair_context)[:8]}",
                                        prompts.CITATION_REPAIR, dumps(repair_context), CitationRepairs)
                    if sorted(r.claim_id for r in repairs.repairs) != sorted(bad):
                        raise ValueError("오류가 있는 모든 claim의 인용만 한 번씩 수정해야 합니다")
                    by_id = {c.id: c for c in step.memo.claims}
                    for repair in repairs.repairs:
                        by_id[repair.claim_id].citations = repair.citations
                    self.validate_memo(step.memo, question.id)
                self.memos[question.id] = step.memo.model_dump(mode="json")
                self.memo_history.append({"stage": stage, "memo": copy.deepcopy(self.memos[question.id])})
                atomic_write(self.directory / "research" / f"memo-{stage}.json", dumps(self.memos[question.id]))
                return
            if iteration == rounds:
                raise ValueError("연구 도구 예산 종료 후 메모를 제출하지 않았습니다")
            for req in step.searches:
                result = self.search(req)
                if len(dumps(context)) + len(dumps(result)) > 155000:
                    result = {"candidates": [], "error": "context 예산 부족. 기존 원문으로 결론/공백을 정리하세요."}
                self.record("search", stage=stage, question_id=question.id, request=req.model_dump(), result=result)
                context["tool_results"].append({"search": req.model_dump(), "result": result})
            for req in step.reads:
                remaining = 155000 - len(dumps(context))
                # Reject before recording a read. A rejected tool action must not
                # grant citation eligibility or strand a cached run on resume.
                if req.length + 5000 > remaining:
                    result = {"error": "context 예산 부족. 읽기 length를 줄이거나 memo를 제출하세요.", "remaining_context_chars": remaining}
                else:
                    result = self.read(req, question.id)
                self.record("read", stage=stage, question_id=question.id, request=req.model_dump(),
                            source_id=result.get("id"), range=result.get("range"), sha256=result.get("sha256"), error=result.get("error"))
                context["tool_results"].append({"read": req.model_dump(), "result": result})

    def review(self, stage, feedback=None):
        # Quotes are exact-checked by the host; reviewers also see surrounding text.
        cited = {c["source_id"] for m in self.memos.values() for claim in m["claims"] for c in claim["citations"]}
        context = {"baseline": self.baseline, "agenda": self.agenda.model_dump(mode="json"), "memos": self.memos,
                   "sources": {sid: self.packet["sources"][sid] for sid in sorted(cited)}, "feedback": feedback,
                   "available_primary_catalog": [self.candidate(sid) for sid in sorted(self.extra)]}
        if feedback:
            context["research_history"] = self.decision_memos()
            draft = feedback.get("draft", {})
            paragraphs = [draft.get("opening", {}), *[p for s in draft.get("sections", []) for p in s.get("paragraphs", [])]]
            used = {c["source_id"] for p in paragraphs for c in p.get("sources", [])}
            context["sources"].update({sid: self.packet["sources"][sid] for sid in sorted(used) if sid in self.packet["sources"]})
        challenge = self.call("research-" + stage, prompts.CHALLENGE, dumps(context), ChallengeSet)
        valid_ids = {q.id for q in self.agenda.questions}
        if any(r.question_id not in valid_ids for r in challenge.requests):
            raise ValueError("알 수 없는 쟁점에 재조사를 배정했습니다")
        self.challenges.append(challenge.model_dump(mode="json"))
        atomic_write(self.directory / "research" / f"{stage}.json", dumps(challenge.model_dump(mode="json")))
        for i, req in enumerate(challenge.requests):
            self.record("research_request", stage=stage, request=req.model_dump(mode="json"))
            if req.route == "source":
                question = next(q for q in self.agenda.questions if q.id == req.question_id)
                self.investigate(question, f"{stage}-{i}-{req.question_id}", req.model_dump(mode="json"), rounds=2)
        return challenge

    def decide(self, stage, feedback=None):
        memos = self.decision_memos()
        context = {"baseline": self.baseline, "agenda": self.agenda.model_dump(mode="json"),
                   "memos": memos, "challenges": self.challenges, "feedback": feedback,
                   "source_lengths": {sid: len(s["text"]) for sid, s in self.packet["sources"].items()},
                   "writing_context_limit_chars": 150000}
        claims = {c["id"]: c for m in memos.values() for c in m["claims"]}
        cited = {c["source_id"] for claim in claims.values() for c in claim["citations"]}
        for attempt in range(2):
            if attempt and feedback:
                repair_context = {**context, "source_costs": {
                    "fixed_series_chars": sum(len(s["text"]) for s in writing_sources(self.packet).values() if s["kind"] == "series"),
                    "documents": {sid: {"chars": len(self.packet["sources"][sid]["text"]),
                                        "claims": [cid for cid, c in claims.items() if any(x["source_id"] == sid for x in c["citations"])]}
                                  for sid in sorted(cited)}}}
                repair = self.call("research-" + stage + "-selection-repair-v1", prompts.SELECTION_REPAIR,
                                   dumps(repair_context), DecisionSelectionRepair)
                updates = [d.claim_id for d in repair.disposition_updates]
                if len(set(updates)) != len(updates) or not set(updates) <= set(claims):
                    raise ValueError("자료 선택 수정은 기존 연구 claim만 한 번씩 지정해야 합니다")
                dispositions = {d.claim_id: d for d in decision.dispositions if d.claim_id in claims}
                dispositions.update({d.claim_id: d for d in repair.disposition_updates})
                decision = decision.model_copy(update={"dispositions": list(dispositions.values()),
                    "writing_source_ids": repair.writing_source_ids, "judgment": repair.judgment or decision.judgment,
                    "unresolved_material": decision.unresolved_material + repair.additional_material_gaps})
            else:
                decision = self.call("research-" + stage + ("-contract-repair" if attempt else ""),
                                     prompts.REDECIDE if feedback else prompts.DECIDE, dumps(context), DecisionBrief)
            try:
                if sorted(d.claim_id for d in decision.dispositions) != sorted(claims):
                    raise ValueError("연구 claim 전체의 채택/기각 결정을 한 번씩 기록해야 합니다. 필요한 ID: " + dumps(sorted(claims)))
                if not set(decision.writing_source_ids) <= cited:
                    raise ValueError("읽고 인용한 원문만 집필 근거로 선택할 수 있습니다")
                needed = {c["source_id"] for d in decision.dispositions if d.status == "adopted" for c in claims[d.claim_id]["citations"]}
                selected = set(decision.writing_source_ids) | needed
                packet = copy.deepcopy(self.packet)
                packet["sources"] = {sid: s for sid, s in packet["sources"].items() if s["kind"] == "series" or sid in selected}
                packet["coverage"] = {k: [sid for sid in ids if sid in packet["sources"]] for k, ids in packet["coverage"].items()}
                if sum(len(s["text"]) for s in writing_sources(packet).values()) > 150000:
                    raise ValueError("집필 context 예산 150000자 초과. 핵심 채택 주장과 필요한 원문을 좁혀라. 제외 이유를 기록하고 결론도 그에 맞춰 한정하라.")
                break
            except ValueError as exc:
                if attempt:
                    raise
                context.update(validation_error=str(exc), previous_decision=decision.model_dump(mode="json"))
        atomic_write(self.directory / "research" / f"{stage}.json", dumps(decision.model_dump(mode="json")))
        atomic_write(self.directory / "research-packet.json", dumps(packet))
        self.record("decision", stage=stage, packet_sha256=digest(packet), decision=decision.model_dump(mode="json"))
        self.render(decision, packet)
        return packet, decision

    def start(self):
        discovery = self.discover()
        atomic_write(self.directory / "research" / "discovery.json", dumps(discovery))
        self.agenda = self.call("research-agenda", prompts.AGENDA,
                               dumps({"baseline": self.baseline, "discovery": discovery}), ResearchAgenda)
        atomic_write(self.directory / "research" / "agenda.json", dumps(self.agenda.model_dump(mode="json")))
        for question in self.agenda.questions:
            self.investigate(question, question.id)
        self.review("challenge")
        return self.decide("decision")

    def reopen(self, feedback):
        self.review("postwrite-challenge", feedback)
        return self.decide("revised-decision", feedback)

    def writing_contract(self, decision):
        dispositions = {d.claim_id: d.model_dump() for d in decision.dispositions}
        memos = self.decision_memos()
        selected = set(decision.writing_source_ids)
        selected |= {c["source_id"] for memo in memos.values() for claim in memo["claims"]
                     if dispositions[claim["id"]]["status"] == "adopted" for c in claim["citations"]}
        return {"instruction": "채택한 주장을 하우스 의견으로 설명한다. rejected/unconfirmed는 반대 논거 또는 한계로만 다룬다.",
                "claims": [{**claim, "citations": [c for c in claim["citations"] if c["source_id"] in selected],
                            "disposition": dispositions[claim["id"]]}
                           for memo in memos.values() for claim in memo["claims"]]}

    def decision_memos(self):
        """A follow-up on buybacks must not erase the earlier policy research."""
        result = {}
        for sequence, version in enumerate(self.memo_history, 1):
            memo = copy.deepcopy(version["memo"])
            memo["research_sequence"] = sequence
            for claim in memo["claims"]:
                claim["id"] = version["stage"] + "/" + claim["id"]
            result[version["stage"]] = memo
        return result

    def render(self, decision, packet):
        unique_reads = {ev["request"]["source_id"] for ev in self.events if ev["kind"] == "read" and not ev.get("error")}
        searched = {c["source_id"] for ev in self.events if ev["kind"] == "search" for c in ev["result"]["candidates"]}
        body = '<nav><a href="reviewed.html">Weekly</a><a href="evidence.html">집필 근거</a><a href="audit.html">검토 기록</a></nav><h1>쟁점에서 최종 판단까지</h1>'
        body += f'<p class="note">검색 후보 {len(searched)}개 · 원문 읽기 {len(unique_reads)}개 · 최종 집필 원문 {sum(s["kind"] == "document" for s in packet["sources"].values())}개(분할 구간 포함). 프로필·인물 태그는 검색 안내에만 사용했습니다. 자동개선·릴리스는 실행하지 않습니다.</p>'
        sections = [("쟁점 선정과 제외 이유", self.agenda.model_dump(mode="json")), ("쟁점별 연구와 재조사 이력", self.decision_memos()),
                    ("반론과 재조사 요청", self.challenges), ("최종 의견과 채택·기각 이유", decision.model_dump(mode="json"))]
        for title, content in sections:
            body += f'<h2>{e(title)}</h2><pre>{e(json.dumps(content, ensure_ascii=False, indent=2))}</pre>'
        body += '<h2>원문 읽기 기록</h2><ul>'
        for ev in self.events:
            if ev["kind"] == "read":
                body += f'<li>{e(ev["question_id"])} · {e(ev["request"]["source_id"])} · {e(str(ev.get("range")))} · {e(ev.get("error") or "실제 원문 전달")}</li>'
        body += '</ul><p><a href="research/events.json">전체 검색·읽기·판단 기록 JSON</a></p>'
        atomic_write(self.directory / "research.html", page("Weekly 조사와 판단", body))
