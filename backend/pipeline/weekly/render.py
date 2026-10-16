"""Standalone readable briefing, with escaped model prose and frozen evidence."""
import html
import json
import re
from urllib.parse import urlsplit

from .calculations import resolve_figure
from .evidence import Evidence
from .store import atomic_write, dumps

STYLE = """
:root{color-scheme:light;--paper:#f7f5ef;--ink:#242723;--muted:#667166;--line:#d8ded4;--accent:#27675d}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:17px/1.9 system-ui,-apple-system,sans-serif;word-break:keep-all;overflow-wrap:anywhere}
main{max-width:960px;margin:auto;padding:64px 24px}header{border-bottom:2px solid var(--ink);padding-bottom:30px;margin-bottom:40px}
h1{font-size:clamp(32px,5vw,52px);line-height:1.3;letter-spacing:-.04em}h2{margin-top:56px;font-size:26px;line-height:1.4}h3{font-size:19px}
.meta,small{color:var(--muted);font-size:13px}.standfirst{font-size:21px;font-weight:500}.tag{font-size:11px;color:var(--accent);margin-right:8px}
a{color:var(--accent);text-underline-offset:3px}p{margin:18px 0}sup{font-size:11px;margin-left:5px}pre{white-space:pre-wrap;word-break:break-word;font-size:12px;line-height:1.7;background:#fff;padding:18px;border:1px solid var(--line)}
details{border-top:1px solid var(--line);padding:16px 0}summary{cursor:pointer;font-weight:600}.notice{padding:16px 20px;border-left:3px solid var(--accent);background:#edf1e8}.blocking{border-left-color:#ab624b}
figure{margin:30px 0}figure img{width:100%;height:auto}section,details{scroll-margin-top:25px}.condition{padding:20px;background:#fff;margin:16px 0;border:1px solid var(--line)}
@media print{body{background:white;font-size:11pt}main{padding:0;max-width:none}h2{break-after:avoid}figure,.condition{break-inside:avoid}details>summary{list-style:none}a{color:inherit}header{margin-bottom:20px}}
"""


def safe_link(url):
    return url if url and urlsplit(url).scheme in {"https", "http"} else None


def archive_attempt(directory, attempt):
    """Preserve the exact delivered report before a resumed run replaces the current view."""
    if attempt < 1:
        return
    mapping = {name: f"{name.rsplit('.', 1)[0]}-attempt-{attempt}.{name.rsplit('.', 1)[1]}"
               for name in ("briefing.html", "briefing.json", "run.json", "events.json", "evidence-index.json")}
    for name, archived in mapping.items():
        source, target = directory / name, directory / archived
        if not source.exists() or target.exists():
            continue
        content = source.read_text()
        if name.endswith(".html"):
            for old, new in mapping.items():
                content = content.replace(f'href="{old}"', f'href="{new}"')
        atomic_write(target, content)


def citation_labels(report):
    ids = list(dict.fromkeys(eid for c in report.claims() for eid in
                             [*(s.evidence_id for s in c.supports), *(f.evidence_id for f in c.figures)]))
    return {eid: str(i + 1) for i, eid in enumerate(ids)}


def rendered_claim(claim, evidence, labels=None):
    prose = claim.text
    for figure in claim.figures:
        try:
            value, unit = resolve_figure(figure, evidence)
            number = f"{value:,.{figure.decimals}f}"
            unit_label = {"percent": "%", "percentage points": "%p", "index points": "포인트", "observations": "개 관측치", "shares": "주", "USD / share": "달러"}.get(unit, unit)
            text = number + ("" if unit_label in {"%", "%p"} else " ") + unit_label
        except (KeyError, ValueError, IndexError, TypeError):
            text = "[수치 연결 오류]"
        prose = prose.replace("{{" + figure.id + "}}", text)
    refs = list(dict.fromkeys([s.evidence_id for s in claim.supports] + [f.evidence_id for f in claim.figures]))
    kinds = {"fact": "관측·원문", "interpretation": "해석", "hypothesis": "가설·조건"}
    return f'<p id="{html.escape(claim.id)}"><span class="tag">{kinds[claim.kind]}</span>{html.escape(prose)}' + "".join(
        f'<sup><a href="#e-{html.escape(eid)}">[{html.escape((labels or {}).get(eid, eid))}]</a></sup>' for eid in refs) + "</p>"


def write_bundle(store, run_id, report, checkpoint, status, reason=None):
    directory = store.directory(run_id)
    evidence = Evidence(directory)
    run = store.get(run_id)
    archive_attempt(directory, checkpoint.get("resume_count", 0))
    e = html.escape
    labels = {"complete": "실행 검증 통과 · 전문가 품질 미평가", "partial": "부분 완료 · 확인할 근거/검증 항목 있음", "failed": "실행 실패", "cancelled": "실행 취소"}
    body = [f'<header><div class="meta">EXPLORER / WEEKLY · {e(run["config"]["cutoff"])} · {e(run["config"]["mode"])}</div>',
            f'<h1>{e(report.title if report else "Weekly 실행 기록")}</h1>',
            f'<div class="notice {"blocking" if status != "complete" else ""}">{labels.get(status, status)}</div>',
            '<p class="meta">근거·검토·판단 변경 기록은 부록에서 확인할 수 있습니다. 전문가 품질 평가: 미실시.</p></header>']
    if reason:
        message = "모델 응답이 시간 제한을 넘었습니다. 보존한 근거와 검토 지적으로 재개할 수 있으며, 아래 본문은 중단 당시 저장한 초안입니다." if "Timeout" in reason else reason
        body.append(f'<p class="notice">{e(message)}</p>')
    final_review = checkpoint.get("final_review", {})
    blockers = [i for i in [*final_review.get("mechanical", []), *final_review.get("argument", {}).get("issues", [])] if i["severity"] == "blocking"]
    if blockers:
        claim_ids = {c.id for c in report.claims()} if report else set()
        entries = []
        for i in blockers:
            label = f'<a href="#{e(i["claim_id"])}">{e(i["claim_id"])}</a>' if i["claim_id"] in claim_ids else e(i["claim_id"])
            entries.append(f'<li>{label} · {e(i["reason"])}</li>')
        body.append('<details open class="notice blocking"><summary>해결되지 않은 검토 · 본문은 검증을 통과하지 못했습니다</summary><ul>' + ''.join(entries) + '</ul></details>')
    if report:
        labels_map = citation_labels(report)
        body.append('<div class="standfirst">' + rendered_claim(report.standfirst, evidence, labels_map) + '</div>')
        for section in report.sections:
            body.append(f'<section><h2>{e(section.heading)}</h2>')
            body.extend(rendered_claim(claim, evidence, labels_map) for claim in section.claims)
            body.append('</section>')
        if checkpoint.get("charts"):
            body.append('<h2>관측 차트</h2>')
            for chart in checkpoint["charts"]:
                body.append(f'<figure><img src="{e(chart["file"])}" alt="{e(chart["source_id"])} 관측 차트"><figcaption class="meta">고정 근거 {e(chart["source_id"])}</figcaption></figure>')
        body.append('<h2>다음 판단을 바꿀 조건</h2>')
        for h in report.hypotheses:
            body.append(f'<div class="condition"><h3>{e(h.question)}</h3><p>{e(h.judgment)}</p><p><strong>경쟁 설명</strong> · {e(h.alternative)}</p><p><strong>변경 조건</strong> · {e(h.change_condition)}</p></div>')
        if report.gaps:
            body.append('<h2>남은 공백</h2><ul>' + ''.join(f'<li>{e(g)}</li>' for g in report.gaps) + '</ul>')
    if checkpoint.get("gaps"):
        body.append('<details><summary>추가 확보 요청</summary><pre>' + e(json.dumps(checkpoint['gaps'], ensure_ascii=False, indent=2)) + '</pre></details>')
    archived = sorted(directory.glob("briefing-attempt-*.html"))
    if archived:
        body.append('<details><summary>이전 실행 시도의 보고서</summary><ul>' + ''.join(f'<li><a href="{e(p.name)}">{e(p.name)}</a></li>' for p in archived) + '</ul></details>')
    body.append('<h2>검증과 결정 기록</h2>')
    for name, value in [("최종 검증", checkpoint.get("final_review", {})), ("조사·판단의 근거와 대안", checkpoint.get("decisions", [])), ("자료 범위와 시점 제약", evidence.coverage() if evidence.path.exists() else {})]:
        body.append(f'<details><summary>{e(name)}</summary><pre>{e(json.dumps(value, ensure_ascii=False, indent=2))}</pre></details>')
    body.append('<h2>고정 근거</h2><p class="meta">아래 원문은 이 실행에 보존한 버전입니다. 출처의 주장과 시장의 확인된 사실은 구분해서 읽어야 합니다.</p>')
    ids = set(checkpoint.get("read_ids", []))
    if report:
        ids.update(s.evidence_id for c in report.claims() for s in c.supports)
        ids.update(f.evidence_id for c in report.claims() for f in c.figures)
    # Include source series behind every calculation so a reviewer can reproduce it.
    todo = list(ids)
    frozen = {}
    while todo:
        eid = todo.pop()
        if eid in frozen:
            continue
        try:
            item = evidence.get(eid)
        except (KeyError, ValueError):
            continue
        frozen[eid] = item
        todo.extend(item["meta"].get("source_ids", []))
    for eid, item in sorted(frozen.items()):
        atomic_write(directory / "evidence" / f"{eid}.json", dumps(item))
        meta = item["meta"]
        link = safe_link(meta.get("url"))
        source_link = f'<a href="{e(link, quote=True)}" rel="noopener noreferrer">현재 출처 페이지</a> · ' if link else ''
        text = item["text"] or json.dumps(item["data"], ensure_ascii=False, indent=2)
        reference = citation_labels(report).get(eid, eid) if report else eid
        body.append(f'<details id="e-{e(eid)}"><summary>[{e(reference)}] {e(meta["title"])}</summary><p class="meta">{source_link}<a href="evidence/{e(eid)}.json">고정 원문·메타데이터 JSON</a></p><pre>{e(json.dumps(meta, ensure_ascii=False, indent=2))}</pre><pre>{e(text)}</pre></details>')
    body.append(f'<footer class="meta">Run {e(run_id)} · {e(run["config"]["model"])} / review {e(run["config"]["reviewer_model"])} · <a href="run.json">실행 기록</a> · <a href="events.json">도구·결정 로그</a></footer>')
    document = '<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\' data:; style-src \'unsafe-inline\'"><title>' + e(report.title if report else "Weekly") + '</title><style>' + STYLE + '</style></head><body><main>' + ''.join(body) + '</main></body></html>'
    atomic_write(directory / "briefing.html", document)
    if report:
        atomic_write(directory / "briefing.json", report.model_dump_json(indent=2))
    atomic_write(directory / "events.json", dumps(store.events(run_id)))
    atomic_write(directory / "run.json", dumps({**run, "status": status, "checkpoint": checkpoint}))
    atomic_write(directory / "evidence-index.json", dumps([{k: item[k] for k in ("id", "kind", "sha256", "meta")} for item in frozen.values()]))
    return str(directory / "briefing.html")
