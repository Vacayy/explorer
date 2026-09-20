"""Small deterministic gates; semantic entailment is reviewed separately."""
import math
import re

from models.weekly_reader import ReaderBrief

TOKEN = re.compile(r"\{\{(m[0-9]+)\}\}")
EXTRA_UNIT = re.compile(r"\{\{m[0-9]+\}\}\s*(?:%|퍼센트|달러|포인트|USD|bp\b)", re.I)
INTERNAL = re.compile(r"지난 회차|이전 초안|내부 검토|사건 창|베이스라인|패킷|Claim\s*ID|앞서 유지하던|앞선 판단|내 전제.{0,8}(?:무너뜨렸다|무너졌다)")


def resolve(text, packet):
    def replace(match):
        metric = packet["metrics"].get(match[1])
        if not metric or not math.isfinite(metric["value"]):
            raise ValueError("알 수 없거나 유한하지 않은 수치: " + match[1])
        return metric["formatted"]
    return TOKEN.sub(replace, text)


def check(brief: ReaderBrief, packet):
    issues = []

    def flag(location, reason, change):
        issues.append({"severity": "blocking", "location": location, "reason": reason, "requested_change": change})

    seen = set()
    for paragraph in brief.paragraphs():
        if paragraph.id in seen:
            flag(paragraph.id, "중복 문단 ID", "모든 문단에 고유 ID를 부여하세요")
        seen.add(paragraph.id)
        ids = TOKEN.findall(paragraph.text)
        if not paragraph.sources and not ids:
            flag(paragraph.id, "의견을 지지하는 근거 연결 없음", "대응의 이유가 되는 출처를 연결하세요")
        for citation in paragraph.sources:
            source = packet["sources"].get(citation.source_id)
            if not source or citation.quote not in source["text"]:
                flag(paragraph.id, "제공 원문에 없는 인용: " + citation.source_id, "실제 원문에 존재하는 정확한 구절을 연결하세요")
            if citation.anchor not in paragraph.text:
                flag(paragraph.id, "본문에 없는 인용 위치", "anchor를 본문의 실제 문구로 지정하세요")
        for cid in paragraph.charts:
            if cid not in packet["charts"]:
                flag(paragraph.id, "존재하지 않는 차트: " + cid, "제공된 차트 ID만 사용하세요")
    texts = [("title", brief.title), *[(f"heading:{i}", s.heading) for i, s in enumerate(brief.sections)],
             *[(p.id, p.text) for p in brief.paragraphs()]]
    for location, text in texts:
        if EXTRA_UNIT.search(text):
            flag(location, "계산 토큰 뒤 단위 중복", "토큰이 이미 단위를 포함하므로 덧붙인 단위를 제거하세요")
        if INTERNAL.search(text):
            flag(location, "내부 작업 기록 또는 제공되지 않은 과거 자기 의견이 독자 본문에 노출됨",
                 "이전 공개 의견은 제공되지 않았습니다. 자신의 과거 해석을 접거나 정정한다는 문장을 현재 시장 사실과 현재 의견으로 다시 쓰세요. 단어만 바꾸어 가상의 과거 의견을 유지하지 마세요.")
        if "{{" in TOKEN.sub("", text) or "}}" in TOKEN.sub("", text):
            flag(location, "정의되지 않은 수치 토큰 형식", "제공한 {{m0001}} 형식만 사용하세요")
        try:
            resolved = resolve(text, packet)
            if re.search(r"%%|%p%p|달러달러|포인트포인트", resolved):
                flag(location, "렌더링 후 단위 중복", "숫자와 단위를 한 번씩만 표시하세요")
        except (ValueError, TypeError) as exc:
            flag(location, str(exc), "제공된 유효한 수치 토큰을 사용하세요")
    return {"issues": issues, "blocking": len(issues),
            "limits": "인용 실재·수치 연결·단위·형식 검사. 인용의 의미와 의견의 타당성은 별도 검토가 필요합니다."}


def plain(brief, packet):
    """The investor reviewer sees precisely this reader text, never the judgment memo."""
    period = packet["period"]
    lines = [resolve(brief.title, packet),
             f"회고 {period['week_start']}~{period['week_end']} / 대응 {period['outlook_start']}~{period['outlook_end']} / 정보 {packet['cutoff']}",
             resolve(brief.opening.text, packet)]
    for section in brief.sections:
        lines.append(resolve(section.heading, packet))
        lines.extend(resolve(p.text, packet) for p in section.paragraphs)
    return "\n\n".join(lines)


def publishable(mechanical, factual, investor):
    return (not mechanical["blocking"] and factual is not None and investor is not None
            and not any(x["severity"] == "blocking" for x in factual["issues"] + investor["issues"])
            and investor["verdict"] == "readable")
