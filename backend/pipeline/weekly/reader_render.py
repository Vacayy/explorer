"""Readable prose and a separate, inspectable audit trail. No web dependencies."""
import html
import json
import random
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .reader_review import TOKEN, resolve
from .store import atomic_write, digest, dumps

STYLE = """
:root{color-scheme:light;--ink:#203330;--muted:#667671;--line:#dce2da;--paper:#f9faf6;--accent:#226956}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:system-ui,-apple-system,'Apple SD Gothic Neo','Noto Sans KR',sans-serif}
main{max-width:850px;margin:auto;padding:48px 28px 96px}a{color:var(--accent);text-underline-offset:4px;overflow-wrap:anywhere}
nav,.meta,figcaption{font-size:13px;color:var(--muted);line-height:1.7}nav{display:flex;gap:18px;flex-wrap:wrap;margin-bottom:45px}
h1{font-size:clamp(28px,4.3vw,42px);line-height:1.4;letter-spacing:-.04em;margin:20px 0;word-break:keep-all;overflow-wrap:anywhere;text-wrap:balance}h2{font-size:24px;line-height:1.5;margin:54px 0 22px;word-break:keep-all}
p{font-size:17px;line-height:1.95;word-break:keep-all;overflow-wrap:anywhere;margin:22px 0}.opening{font-size:20px;font-weight:550;line-height:1.85;border-left:3px solid var(--accent);padding-left:22px;margin:35px 0 46px}
sup{font-size:11px;white-space:nowrap;margin-left:4px}figure{margin:32px 0 40px}img{width:100%;height:auto;border:1px solid var(--line);border-radius:8px}figcaption{margin-top:8px}
footer{border-top:1px solid var(--line);margin-top:56px;padding-top:20px;font-size:13px;color:var(--muted)}.note{background:#edf0e8;padding:16px 20px;border-radius:8px;font-size:14px;line-height:1.8}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.card{border:1px solid var(--line);padding:20px;border-radius:10px;background:white}.card h2{margin:0 0 12px;font-size:21px}.card p{font-size:14px}
pre{font-size:13px;line-height:1.65;white-space:pre-wrap;overflow-wrap:anywhere;background:#eef1e9;padding:18px;border-radius:8px}details{margin:20px 0}summary{cursor:pointer;line-height:1.7}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:12px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}li{line-height:1.8;margin:10px 0}
@media(max-width:650px){main{padding:28px 20px 60px}.cards{grid-template-columns:1fr}nav{margin-bottom:25px}p{font-size:16px}.opening{font-size:18px;padding-left:16px}}
@media print{nav{display:none}body{background:white}main{max-width:none;padding:0}h2,figure{break-inside:avoid}p{orphans:3;widows:3}}
"""
e = html.escape


def page(title, body):
    return f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title><style>{STYLE}</style></head><body><main>{body}</main></body></html>'


def safe_link(url):
    return url if urlsplit(url or "").scheme in {"http", "https"} else ""


def write_brief(directory, variant, brief, packet, *, approved=False):
    source_numbers = {sid: i + 1 for i, sid in enumerate(packet["sources"])}

    def paragraph(p, opening=False):
        # Invalid drafts remain inspectable, but unresolved values cannot look verified.
        try:
            text = resolve(p.text, packet)
        except ValueError:
            text = p.text
        refs = list(dict.fromkeys([c.source_id for c in p.sources] +
                                 [packet["metrics"][mid]["source_id"] for mid in TOKEN.findall(p.text) if mid in packet["metrics"]]))
        refs = "".join(f'<sup><a href="evidence.html#{e(sid)}" aria-label="근거 {source_numbers[sid]}">[{source_numbers[sid]}]</a></sup>' for sid in refs if sid in source_numbers)
        out = f'<p id="{e(p.id)}" class="{"opening" if opening else "body"}">{e(text)}{refs}</p>'
        for cid in p.charts:
            if cid in packet["charts"]:
                chart = packet["charts"][cid]
                out += f'<figure><img src="{e(chart["file"])}" alt="{e(chart["title"])} {e(chart["start"])}부터 {e(chart["end"])}까지 가격 추이"><figcaption>{e(chart["title"])} · {e(chart["start"])} ~ {e(chart["end"])}</figcaption></figure>'
        return out

    period = packet["period"]
    report_only = packet.get("workflow") in {"briefing", "research"}
    state = "자동 검토 완료 · 전문가 평가는 대기 중" if approved else "비교용 연구 초안 · 검증 상태는 검토 기록 참조"
    checks_path = Path(directory) / f"{variant}-checks.json"
    if checks_path.exists():
        checks = json.loads(checks_path.read_text())
        if any((checks.get(kind) or {}).get("issues") for kind in ("mechanical", "factual", "investor")):
            state = "검토 의견 남음 · 비교용 연구 초안"
    title = resolve(brief.title, packet) if all(mid in packet["metrics"] for mid in TOKEN.findall(brief.title)) else brief.title
    if report_only:
        state = state.replace("비교용 연구 초안", "연구 초안")
    home_label = "리포트 안내" if report_only else "세 브리핑 비교"
    body = f'<nav><a href="index.html">{home_label}</a><a href="evidence.html">근거 자료</a><a href="audit.html">검토 기록</a></nav><div class="meta">WEEKLY · {e(state)}</div><h1>{e(title)}</h1>'
    cutoff = datetime.fromisoformat(packet["cutoff"]).astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y.%m.%d %H:%M KST")
    body += f'<div class="meta">지난주 {e(period["week_start"])} ~ {e(period["week_end"])}<br>대응 주간 {e(period["outlook_start"])} ~ {e(period["outlook_end"])}<br>정보 기준 {e(cutoff)}</div>'
    body += paragraph(brief.opening, True)
    for section in brief.sections:
        try:
            heading = resolve(section.heading, packet)
        except ValueError:
            heading = section.heading
        body += f'<h2>{e(heading)}</h2>' + "".join(paragraph(p) for p in section.paragraphs)
    body += '<footer>각 문단의 근거 번호에서 사용한 원문과 가격 자료를 확인할 수 있습니다.</footer>'
    atomic_write(Path(directory) / f"{variant}.json", dumps(brief.model_dump(mode="json")))
    atomic_write(Path(directory) / f"{variant}.html", page(title, body))


def write_support(directory, packet, manifest):
    directory = Path(directory)
    report_only = packet.get("workflow") in {"briefing", "research"}
    home_label = "리포트 안내" if report_only else "세 브리핑 비교"
    nav = f'<nav><a href="index.html">{home_label}</a><a href="evidence.html">근거 자료</a><a href="audit.html">검토 기록</a></nav>'
    if packet.get("workflow") == "research":
        nav = nav.replace('</nav>', '<a href="research.html">쟁점·원문 조사·채택 이유</a></nav>')
    note = "이 리포트는 아래의 동결 자료를 사용합니다." if report_only else "세 작성 방식은 아래의 동일한 동결 자료를 사용합니다."
    body = nav + '<h1>브리핑의 근거</h1><p class="note">' + note + ' 외부 요약·전망은 해당 저자의 주장입니다. 전체 보관 원문과 모델에 전달한 범위를 구분해 표시합니다.</p>'
    for i, (sid, source) in enumerate(packet["sources"].items(), 1):
        meta = source["meta"]
        url = safe_link(meta.get("url"))
        body += f'<section id="{e(sid)}"><h2>[{i}] {e(meta.get("title", sid))}</h2><div class="meta">{e(sid)} · {e(str(meta.get("source_type", "")))} · 발행 {e(str(meta.get("published_at", "미상")))}<br>확보 {e(str(meta.get("fetched_at", "")))}</div>'
        if url:
            body += f'<p><a href="{e(url, quote=True)}" rel="noopener noreferrer">출처 페이지</a> · <a href="{e(source["raw_file"])}">확보한 원문 JSON</a></p>'
        else:
            body += f'<p><a href="{e(source["raw_file"])}">확보한 원문 JSON</a></p>'
        if source.get("range"):
            body += f'<div class="meta">전달 범위: {source["range"][0]}~{source["range"][1]}자 / 보관 원문 {source["full_length"]}자</div>'
        body += f'<details><summary>작성에 전달된 내용 보기</summary><pre>{e(source["text"])}</pre></details></section>'
    atomic_write(directory / "evidence.html", page("브리핑의 근거", body))
    records = []
    for filename in sorted(directory.glob("*-checks.json")):
        records.append(f'<h2>{e(filename.stem)}</h2><pre>{e(filename.read_text())}</pre>')
    judgment = directory / "judgment.json"
    body = nav + '<h1>판단과 검토 기록</h1><p class="note">여기는 내부 검토용입니다. 모델 검토와 기계 검사는 인간 전문가의 품질 평가를 대신하지 않습니다.</p>'
    if judgment.exists():
        body += f'<details><summary>작성에 사용한 판단 요약</summary><pre>{e(judgment.read_text())}</pre></details>'
    if (directory / "reviewed-judgment.json").exists():
        body += f'<details><summary>검토 후 다시 정리한 현재 판단</summary><pre>{e((directory / "reviewed-judgment.json").read_text())}</pre></details>'
    body += "".join(records) + f'<details><summary>실행·비용·입력 식별 기록</summary><pre>{e(dumps(manifest))}</pre></details>'
    atomic_write(directory / "audit.html", page("판단과 검토 기록", body))
    if report_only:
        body = nav + '<div class="meta">WEEKLY</div><h1>이번 주 시장과 대응</h1><p>시장 판단을 정리하고 작성한 뒤 사실·논증과 독자 이해를 검토했습니다. 검토에서 문제가 나오면 판단을 다시 정리해 한 차례 재작성합니다.</p>'
        if (directory / "reviewed.html").exists():
            body += '<p><a href="reviewed.html">새 Weekly 읽기 →</a></p>'
        elif (directory / "judged.html").exists():
            body += '<p><a href="judged.html">검토 중인 초안 읽기 →</a></p>'
        body += f'<p class="note">실행 상태: {e(manifest["status"])} · 문서 {manifest.get("document_count", 0)}개 / 전체 근거 {len(packet["sources"])}개<br>원문 Weekly와 이전 생성물은 작성 입력에서 제외했습니다. 인간 전문가 품질 판정은 아직 없습니다.</p>'
        if (directory / "source-selection.html").exists():
            body += '<p><a href="source-selection.html">소스·인물로 찾은 자료와 선정 이유</a></p>'
        calls = list(manifest.get("calls", {}).values())
        if calls:
            duration = f'{sum(c["duration_ms"] for c in calls) / 60000:.1f}분' if all(c.get("duration_ms") is not None for c in calls) else "미집계"
            cost = f'${sum(c["cost_usd"] for c in calls):.2f}' if all(c.get("cost_usd") is not None for c in calls) else "미집계"
            body += f'<p class="meta">완료한 모델 호출 {len(calls)}회 · 모델 시간 합계 {duration} · 공급자 추정 비용 {cost}</p>'
        body += '<details><summary>확보하지 못한 자료</summary><ul>' + ''.join(f'<li>{e(str(g.get("area", "")))}: {e(g["reason"])}</li>' for g in packet["gaps"]) + '</ul></details>'
        atomic_write(directory / "index.html", page("Weekly 리포트", body))
        return
    write_blind_review(directory, packet, manifest)
    cards = []
    for variant, label, description in (("single", "A · 바로 작성", "근거를 읽고 한 번에 글을 구성"), ("judged", "B · 판단 후 작성", "시장 판단과 대응을 먼저 정리한 뒤 새 문맥에서 작성"), ("reviewed", "C · 검토 후 작성", "B를 검토하고 판단을 다시 정리한 뒤 새 문맥에서 한 차례 재작성")):
        link = f'<a href="{variant}.html">브리핑 읽기 →</a>' if (directory / f"{variant}.html").exists() else "아직 생성되지 않음"
        cards.append(f'<article class="card"><h2>{label}</h2><p>{description}</p>{link}</article>')
    body = '<nav><a href="review.html">조건명을 가리고 평가</a><a href="evidence.html">근거 자료</a><a href="audit.html">검토 기록</a><a href="manifest.json">실행 상태</a></nav><div class="meta">WEEKLY WRITING EXPERIMENT</div><h1>같은 자료, 세 가지 브리핑</h1>'
    body += '<p>지난주 무엇이 중요했고, 지금 어떤 시장이며, 이번 주 어떻게 대응할지 읽히는가를 비교합니다.</p><div class="cards">' + "".join(cards) + '</div>'
    body += f'<p class="note">실행 상태: {e(manifest["status"])} · 문서 {manifest.get("document_count", 0)}개 / 전체 근거 {len(packet["sources"])}개<br>개발용으로 선정한 자료입니다. 원문 Weekly와 기존 생성물은 작성 입력에서 제외했습니다. 인간 전문가 품질 판정은 아직 없습니다.</p>'
    body += '<h2>작성 방식별 실행 기록</h2><table><thead><tr><th>방식</th><th>호출</th><th>모델 시간</th><th>추정 비용</th></tr></thead><tbody>'
    calls = manifest.get("calls", {})
    base = ["judgment", "judged", "judged-structure-repair"]
    groups = [("A", ["single", "single-structure-repair"]), ("B", base),
              ("C", base + ["judged-facts", "judged-investor", "reviewed-judgment", "reviewed", "reviewed-structure-repair", "reviewed-facts", "reviewed-investor"])]
    for label, stages in groups:
        records = [calls[s] for s in stages if s in calls]
        duration = f'{sum(r["duration_ms"] for r in records) / 60000:.1f}분' if records and all(r.get("duration_ms") is not None for r in records) else "—"
        cost = f'${sum(r["cost_usd"] for r in records):.2f}' if records and all(r.get("cost_usd") is not None for r in records) else "—"
        body += f'<tr><td>{label}</td><td>{len(records)}회</td><td>{duration}</td><td>{cost}</td></tr>'
    body += '</tbody></table><p class="meta">완료한 호출의 기록값입니다. B와 C는 판단·초안을 공유하므로 행을 더하면 중복됩니다. 재사용한 호출도 해당 방식의 실행량에 포함합니다. 시간은 모델 호출 시간의 합계이며, 비용은 공급자 추정치로 실제 청구액을 뜻하지 않습니다.</p>'
    body += '<h2>동일한 질문으로 읽기</h2><ol><li>지난주 시장의 핵심 변화와 그 이유를 이해했는가?</li><li>지금 시장에 대한 저자의 우선 의견이 무엇인가?</li><li>기존 보유와 신규 진입에 각각 어떻게 대응하라는가?</li><li>무엇이 달라지면 그 의견과 행동을 바꾸는가?</li><li>그 판단을 근거가 실제로 지지하는가?</li></ol>'
    body += '<h2>자료의 공백</h2><ul>' + "".join(f'<li>{e(str(g.get("area", "")))}: {e(g["reason"])}</li>' for g in packet["gaps"]) + '</ul>'
    body += '<details><summary>조사 범위와 확보 근거</summary><pre>' + e(dumps(packet["coverage"])) + '</pre></details>'
    if (directory / "implementation-review.html").exists():
        body += '<p><a href="implementation-review.html">구현자가 직접 읽고 남긴 비교·남은 문제</a></p>'
    atomic_write(directory / "index.html", page("Weekly 작성 비교", body))


def write_blind_review(directory, packet, manifest):
    """A reviewer can first read without method labels; the audit key is kept separately."""
    variants = ["single", "judged", "reviewed"]
    random.Random(manifest["packet_sha256"]).shuffle(variants)
    mapping = {str(i): variant for i, variant in enumerate(variants, 1)}
    atomic_write(directory / "blind-key.json", dumps(mapping))
    report_hashes = {name: digest(json.loads((directory / f"{name}.json").read_text()))
                     if (directory / f"{name}.json").exists() else None for name in variants}
    review_set = digest({"packet_sha256": manifest["packet_sha256"], "reports": report_hashes})
    fields = [("market", "지난주의 핵심 변화와 현재 시장 상태"), ("opinion", "저자가 무게를 둔 의견"),
              ("response", "기존 보유와 신규 진입에 대한 대응"), ("change", "의견과 대응을 바꿀 조건"),
              ("evidence_errors", "근거 대조 후 발견한 중대한 오류·누락")]
    template = {"packet_sha256": manifest["packet_sha256"], "review_set_sha256": review_set, "reviewer": None, "winner": None,
                "readers": {n: {**{key: None for key, _ in fields}, "rewrite_burden": None} for n in mapping}}
    evaluation_path = directory / "expert-review.json"
    previous = json.loads(evaluation_path.read_text()) if evaluation_path.exists() else None
    filled = previous and (previous.get("reviewer") or previous.get("winner") or
                           any(value for reader in previous.get("readers", {}).values() for value in reader.values()))
    if not filled:
        atomic_write(evaluation_path, dumps(template))
    elif previous.get("review_set_sha256") != review_set:
        atomic_write(directory / f"expert-review-{review_set[:12]}.json", dumps(template))
    nav = '<nav><a href="review.html">평가 목록</a><a href="evidence.html">근거 자료</a></nav>'
    body = '<div class="meta">WEEKLY · 독자 평가</div><h1>어느 글의 의견과 대응이 읽히나요?</h1><p class="note">먼저 각 글을 읽고 이해한 내용을 적습니다. 이후 근거를 대조해 오류와 재작성 부담을 평가합니다. 작성 방식과 자동 검사 결과는 이 보기에서 가렸습니다.</p>'
    body += '<style>label{display:block;margin:18px 0 8px;font-size:14px}textarea,input,select,button{font:inherit;max-width:100%;padding:10px;border:1px solid #b9c6be;border-radius:6px;background:white;color:inherit}textarea{width:100%;resize:vertical}button{cursor:pointer;margin-top:22px}fieldset{border:1px solid var(--line);padding:20px;margin:24px 0;border-radius:10px}legend{padding:0 8px;font-weight:650}</style>'
    body += '<form id="evaluation"><label for="reviewer">평가자</label><input id="reviewer" name="reviewer" autocomplete="name">'
    for n, variant in mapping.items():
        source = directory / f"{variant}.html"
        if source.exists():
            text = source.read_text()
            start, stop = text.index("<nav>"), text.index("</nav>") + len("</nav>")
            text = text[:start] + nav + text[stop:]
            for state in ("자동 검토 완료 · 전문가 평가는 대기 중", "비교용 연구 초안 · 검증 상태는 검토 기록 참조", "검토 의견 남음 · 비교용 연구 초안"):
                text = text.replace(state, "동일 자료의 비교용 연구 초안")
            atomic_write(directory / f"reader-{n}.html", text)
            link = f'<a href="reader-{n}.html" target="_blank" rel="noopener">브리핑 {n} 읽기 ↗</a>'
        else:
            link = "아직 생성되지 않음"
        body += f'<fieldset><legend>브리핑 {n}</legend>{link}'
        for key, label in fields:
            body += f'<label for="r{n}-{key}">{label}</label><textarea id="r{n}-{key}" name="{n}.{key}" rows="2"></textarea>'
        body += f'<label for="r{n}-rewrite">핵심 판단을 얼마나 다시 써야 하나요?</label><select id="r{n}-rewrite" name="{n}.rewrite_burden"><option value="">미평가</option><option value="none">핵심 재작성 불필요</option><option value="light">국소 수정 필요</option><option value="major">판단·대응 재작성 필요</option></select></fieldset>'
    body += '<label for="winner">선호하는 글</label><select id="winner" name="winner"><option value="">미평가</option><option value="1">브리핑 1</option><option value="2">브리핑 2</option><option value="3">브리핑 3</option><option value="tie">차이 없음</option><option value="none">모두 재작성 필요</option></select><br><button type="submit">평가 JSON 내려받기</button><p id="save-status" class="meta" role="status">평가 내용은 이 브라우저에 임시 보관합니다. 내려받기로 파일을 보존할 수 있습니다.</p></form>'
    body += '<footer><a href="evidence.html">근거 대조하기</a> · <a href="index.html">작성 방식과 실행 결과 공개</a></footer>'
    key = json.dumps("weekly-reader-review-" + review_set)
    packet_key = json.dumps(manifest["packet_sha256"])
    body += f'<script>const packetSha={packet_key};const storageKey={key};const form=document.querySelector("form");try{{const saved=JSON.parse(localStorage.getItem(storageKey)||"{{}}");for(const [k,v] of Object.entries(saved)){{if(form.elements.namedItem(k))form.elements.namedItem(k).value=v;}}}}catch(e){{}}form.addEventListener("input",()=>{{try{{localStorage.setItem(storageKey,JSON.stringify(Object.fromEntries(new FormData(form))));}}catch(e){{document.querySelector("#save-status").textContent="임시 저장을 사용할 수 없습니다. 평가 JSON을 내려받아 보존하세요.";}}}});form.addEventListener("submit",event=>{{event.preventDefault();const result={{packet_sha256:packetSha,review_set_sha256:storageKey.replace("weekly-reader-review-",""),recorded_at:new Date().toISOString(),reviewer:null,winner:null,readers:{{}}}};for(const [key,value] of new FormData(form)){{if(key.includes(".")){{const [reader,field]=key.split(".");result.readers[reader]??={{}};result.readers[reader][field]=value||null;}}else{{result[key]=value||null;}}}}const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{{type:"application/json"}}));const a=document.createElement("a");a.href=url;a.download="weekly-expert-review.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}});</script>'
    atomic_write(directory / "review.html", page("Weekly 독자 평가", body))
