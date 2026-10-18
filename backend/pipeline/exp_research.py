"""리서치 하우스 공개 전망(시장 기대치) 수집 — TrendForce 보도자료 · WSTS 반도체 시장 전망 (LLM 0, 키 없음).

사실(실적)이 아니라 '예측'만 expectation_claims에 쌓는다. 파싱은 전부 결정론 정규식이다.

TrendForce: presscenter/news 목록(쪽당 5건, ?page=N) → 기사 <p>·<h1>·요점 <li>를 문장·절로 쪼개
  "<대상> … <방향 동사> <값|범위>% <QoQ|YoY> … <기간>"을 뽑는다.
  - 예측 판정: 절(없으면 문장)에 미래 단서(expected·forecast·projected·will …)가 있어야 한다.
    'have/had + 과거분사', 미래 단서 없는 과거형('rose 12% in 2Q26'), 기사 날짜 전에 끝난 기간은 사실로 보고 건너뛴다.
  - 'rise to 6.2%'(수준·점유율)·'from 28% to 31%'(개정 — 뒤 값만)·CAGR은 성장률로 보지 않는다.
  - 기간: 절(숫자 뒤 우선) → 문장(숫자 앞 우선) → 연도 없는 표현('second half of the year' → 기사 연도) → 바로 앞 문장
    → 기사 제목의 유일한 기간(메모리 가격 보도는 분기를 제목에만 적는다). 그래도 없으면 버린다.
  - 대상: 아래 SUBJECT_NODES 사전으로 칸을 정한다. 사전에 없으면 'forecasts X to …'의 X를 대상으로 두고 node_key=NULL.
  - 값은 부호 있는 %다: 'decline 15–20%' → low=-20, high=-15, direction='down'.
  한계: 품목별(PC·모바일 DRAM 등) 분기 가격표는 이미지라 못 읽는다 — 본문 문장에 적힌 수치만 잡힌다.
WSTS: 'Recent News Release'의 춘계·추계 전망 보도. pdftotext가 있으면 PDF 요약표(세부 품목 내년치까지), 없으면 본문 산문.
  어느 경로였는지 결과 sources.wsts.method로 드러낸다. Logic은 파운드리·IC 설계 수요의 대리라 node_key='foundry'.
UNIQUE 키 = (source, url, node_key, subject, metric, target_period) — 같은 기사의 DRAM·NAND가 따로 남는다. 빈 칸·기간은 ''로 저장.
"""
from __future__ import annotations

import html as _html
import re
import shutil
import subprocess
import tempfile
import time
from datetime import date, datetime, timedelta

import requests

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
TF_BASE = "https://www.trendforce.com"
TF_LIST = TF_BASE + "/presscenter/news?page={}"
WSTS_URL = "https://www.wsts.org/76/Recent-News-Release"
DELAY = 1.5                                  # 요청 간 최소 간격(초)
DAILY_PAGES, BACKFILL_DAYS = 2, 365
MAX_REQ = {False: 15, True: 320}             # 1회 실행 요청 상한(일간 / 백필)

# 대상 → 밸류체인 칸. 위에서부터 우선(같은 위치면 앞 패턴이 이긴다: 'PC DRAM'은 memory, 'smartphone panel'은 display)
SUBJECT_NODES: list[tuple[str, str | None]] = [
    (r"DDR[234]|legacy DRAM|consumer DRAM|specialty DRAM|NOR Flash|SLC NAND|MLC NAND", "tw_memory"),
    (r"DRAM modules?", "mem_module"),
    (r"HBM\d?e?|(?:server|mobile|PC|graphics|conventional|traditional|overall) DRAM|LPDRAM|LPDDR\w*|GDDR\w*|RDIMMs?|DRAM"
     r"|(?:overall )?NAND Flash|NAND|enterprise SSDs?|SSDs?|memory", "memory"),
    (r"CoWoS(?:-[LSR])?|CoPoS|advanced packaging", "osat"),
    (r"ABF(?: substrates?)?|IC substrates?", "abf"),
    (r"silicon wafers?", "wafer"),
    (r"(?:wafer )?foundr(?:y|ies)|mature[- ]node", "foundry"),
    (r"semiconductor equipment|wafer fab equipment|WFE", "dep_etch"),
    (r"(?:TV|monitor|notebook|smartphone|LCD|OLED|large-generation) panels?|panels?|AMOLED|OLED|LCD|display", "display"),
    (r"(?:CSP )?CapEx", "ai"),
    (r"AI servers?|GPU racks?|NVL72(?: racks?)?|(?:general[- ]purpose )?servers?", "ai_odm"),
    (r"GPUs?|AI chips?|AI accelerators?|ASICs?", "ai_accel"),
    (r"notebooks?|laptops?|PCs?", "nb_odm"),
    (r"smartphones?|iPhones?|handsets?", "mobile_asm"),
    (r"MLCCs?|passive components?|X5R|X6S|X7R", "mlcc"),
    (r"fabless|IC design", "ic_design"),
    (r"wafers?", "wafer"),
]
_SUBJ_RE = re.compile("|".join(f"(?P<g{i}>\\b(?:{p})\\b)" for i, (p, _) in enumerate(SUBJECT_NODES)), re.I)

NUM = r"(?<![\d.,])-?\d+(?:\.\d+)?"
PCT = r"\s?(?:%|percent\b)"
QUAL = r"(?:approximately|about|around|nearly|roughly|almost|more than|over|at least|up to|just|some|a cumulative|an? (?:average|further)|another)\s+"
# 개정('from 28% to 31%') → 범위 → 단일 값 순으로 시도
_VAL_RE = re.compile(rf"(?P<rev>\bfrom\s+(?:{QUAL})?(?P<r0>{NUM}){PCT}\s+to\s+(?:{QUAL})?(?P<r1>{NUM}){PCT})"
                     rf"|(?P<lo>(?!(?:19|20)\d\d\b){NUM})(?:{PCT})?\s*(?:–|—|-|~|to)\s*(?P<hi>{NUM}){PCT}"
                     rf"|(?P<one>{NUM}){PCT}", re.I)
UP = r"ris(?:e|es|ing)|risen|rose|rais(?:e|es|ing)|hik\w*|upward|increas\w*|grow(?:s|ing|n|th)?|grew|climb\w*|surg\w*|jump\w*|soar\w*|gain\w*|expand\w*|rebound\w*|up|higher|accelerat\w*"
DOWN = (r"fall(?:s|ing|en)?|fell|declin\w*|drop\w*|decreas\w*|contract(?:s|ed|ing|ion)?(?!\s+(?:price|manufactur|chip))"
        r"|shrink\w*|shrank|slid(?:e|es|ing)?|dip\w*|down|lower|plung\w*|slump\w*")
_DIR_BACK = re.compile(rf"\b(?:(?P<up>{UP})|(?P<down>{DOWN}))\b(?!.*\b(?:{UP}|{DOWN})\b)", re.I | re.S)
_DIR_FWD = re.compile(rf"^\s*(?:QoQ|YoY|HoH|year-over-year|quarter-over-quarter|annual|\w+)?\s*"
                      rf"(?:(?P<up>increase|growth|rise|jump|gain|surge|hike)|(?P<down>decline|drop|decrease|fall|contraction))\b", re.I)
_PAST_VERB = re.compile(r"\b(?:rose|fell|grew|surged|increased|declined|jumped|climbed|dropped|soared|decreased|shrank|slid|posted|recorded|reached|saw|was|were)\b", re.I)
_PERFECT = re.compile(r"\b(?:have|has|had)\s+(?:already\s+)?(?:been\s+)?(?:risen|grown|fallen|shrunk|\w+ed)\b", re.I)
_FUTURE = re.compile(r"\b(?:expect\w*|forecast\w*|project(?:ed|s|ions?)?|predict\w*|estimat\w*|will|would|could|may|might|likely|poised"
                     r"|set to|anticipat\w*|outlook|possible|potential(?:ly)?|to (?:rise|grow|increase|decline|fall|drop|surge|climb|jump|expand|contract"
                     r"|soar|double|drive|push|lift|keep|remain|reach|exceed|hit|approach|raise))\b", re.I)
_FUTURE_STRONG = re.compile(r"\b(?:expect\w*|forecast\w*|projected|predict\w*|will|would|could|likely|poised|set to|anticipat\w*)\b", re.I)
_CLAUSE_SPLIT = re.compile(r";|\s[—–]\s|—(?!\d)|(?<!\d)—|,\s+(?=(?:while|whereas|but|although|though|with|representing|marking|following|after)\b)", re.I)
_SENT_SPLIT = re.compile(r"(?<=[.!?])(?<!\.[A-Z]\.)\s+(?=[A-Z“\"(])")
_FALLBACK_SUBJ = re.compile(r"\b(?:forecasts?|estimates?|expects?|predicts?|projects?)\s+(?:that\s+)?(?:the\s+)?"
                            r"([A-Za-z][\w\-’' ]{2,60}?)\s+(?:will|to|are|is|could|would|may)\b", re.I)
_MODS = {"foldable", "conventional", "overall", "traditional", "consumer", "enterprise", "high-end", "mainstream", "legacy", "specialty",
         "gaming", "ai", "lcd", "oled", "large-size", "mid-range", "low-end", "entry-level", "flagship", "premium", "commercial", "tv",
         "monitor", "automotive", "industrial", "high-capacity", "low-capacity", "qlc", "tlc", "mature", "advanced"}

ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_PERIOD_RE = re.compile(r"\b(?P<q>[1-4])Q(?P<qy>\d{2})\b|\bQ(?P<q2>[1-4])\s?(?P<qy2>20\d\d)\b|\b(?P<h>[12])H(?P<hy>\d{2})\b"
                        r"|\b(?P<qo>first|second|third|fourth) quarter of (?P<qoy>20\d\d)\b|\b(?P<ho>first|second) half of (?P<hoy>20\d\d)\b"
                        r"|\b(?P<y>20[2-3]\d)\b", re.I)


def norm_period(token: str) -> str | None:
    """'4Q26'·'Q4 2026'·'fourth quarter of 2026' → '2026Q4', '2H26'·'second half of 2026' → '2026H2', '2026' → '2026'"""
    m = _PERIOD_RE.search(token)
    return _period_of(m) if m else None


def _period_of(m: re.Match) -> str:
    g = m.groupdict()
    if g["q"]:
        return f"20{g['qy']}Q{g['q']}"
    if g["q2"]:
        return f"{g['qy2']}Q{g['q2']}"
    if g["h"]:
        return f"20{g['hy']}H{g['h']}"
    if g["qo"]:
        return f"{g['qoy']}Q{ORD[g['qo'].lower()]}"
    if g["ho"]:
        return f"{g['hoy']}H{ORD[g['ho'].lower()]}"
    return g["y"]


def period_end(p: str) -> date:
    y = int(p[:4])
    if "Q" in p:
        m = int(p[-1]) * 3
    elif "H" in p:
        m = int(p[-1]) * 6
    else:
        m = 12
    return (date(y + (m == 12), m % 12 + 1, 1)) - timedelta(days=1)


def subject_node(text: str) -> tuple[str, str | None] | None:
    """대상 문구 → (원문 대상, node_key). 사전에 없으면 None"""
    m = _SUBJ_RE.search(text)
    return (m.group(0), SUBJECT_NODES[int(m.lastgroup[1:])][1]) if m else None


_METRIC_WORDS = [(r"\bprices?\b|\basps?\b|quotation", "price"), (r"capex", "capex"), (r"revenue|output value|\bsales\b", "revenue"),
                 (r"shipments?|installations", "shipments"), (r"production|\boutput\b", "production"), (r"\bsupply\b", "supply"),
                 (r"\bdemand\b", "demand"), (r"\bcosts?\b", "cost"), (r"\bmarket\b", "revenue")]


def _metric_base(windows: list[tuple[str, bool]], node: str | None) -> str:
    """우선순위 창마다 측정 단어를 찾는다. (창, last)에서 last면 숫자에 가장 가까운(마지막) 단어, 아니면 첫 단어"""
    for w, last in windows:
        hits = [(m.start(), base) for pat, base in _METRIC_WORDS for m in re.finditer(pat, w, re.I)]
        if hits:
            return (max(hits) if last else min(hits))[1]
    return "capex" if node == "ai" else "growth"


def _suffix(clause: str, period: str) -> str:
    c = clause.lower()
    if re.search(r"\bqoq\b|quarter-over-quarter|quarter on quarter", c):
        return "qoq"
    if re.search(r"\byoy\b|year-over-year|year on year|year over year|annual", c):
        return "yoy"
    if re.search(r"\bhoh\b|compared (?:to|with) the first half|half-over-half", c):
        return "hoh"
    if "cumulative" in c:
        return "cum"
    return "qoq" if "Q" in period else "hoh" if "H" in period else "yoy"


def _nearest_period(text: str, pos: int | None = None, after_first: bool = True) -> str | None:
    """after_first면 pos 뒤 첫 기간 우선(절 안: '… 10–15% in 4Q26'), 아니면 pos 앞 가장 가까운 기간 우선(절 밖). pos=None이면 마지막 기간"""
    ms = list(_PERIOD_RE.finditer(text))
    if not ms:
        return None
    if pos is None:
        return _period_of(ms[-1])
    after = [m for m in ms if m.start() >= pos]
    before = [m for m in ms if m.start() < pos]
    pick = (after[:1] or before[-1:]) if after_first else (before[-1:] or after[:1])
    return _period_of(pick[0])


_REL_PERIOD = re.compile(r"\b(?:the )?(?:(?P<h>first|second) half|(?P<q>first|second|third|fourth) quarter)(?: of (?:the|this) year)?(?! of 20)\b"
                         r"|\b(?P<next>next year)\b", re.I)


def _relative_period(text: str, published: date) -> str | None:
    """연도 없는 기간('the second half of the year'·'the fourth quarter'·'next year') → 기사 연도 기준"""
    m = _REL_PERIOD.search(text)
    if not m:
        return None
    if m.group("next"):
        return str(published.year + 1)
    return f"{published.year}{'H' if m.group('h') else 'Q'}{ORD[(m.group('h') or m.group('q')).lower()]}"


def extract_claims(sentence: str, published: date, context: list[str] | None = None, stats: dict | None = None,
                   default_period: str | None = None) -> list[dict]:
    """한 문장 → 전망 주장 목록. context = 같은 문단의 앞 문장들(바로 앞 문장만 기간 보충에 쓴다).
    default_period = 기사 제목의 유일한 기간(메모리 가격 보도는 분기를 제목·첫 문장에만 적는다). stats에 건너뛴 사유를 센다"""
    st = stats if stats is not None else {}
    bump = lambda k: st.__setitem__(k, st.get(k, 0) + 1)  # noqa: E731
    out: list[dict] = []
    sentence = re.sub(r"\s+", " ", sentence).strip()
    clauses, start = [], 0
    for m in _CLAUSE_SPLIT.finditer(sentence):
        clauses.append((start, sentence[start:m.start()]))
        start = m.end()
    clauses.append((start, sentence[start:]))

    if re.match(r"\s*If\b", sentence):
        bump("conditional")
        return out
    for c0, clause in clauses:
        if re.search(r"\bCAGR\b|market share|penetration|utilization|share of", clause, re.I):
            continue
        for v in _VAL_RE.finditer(clause):
            pre = clause[:v.start()]
            if v.group("rev") and re.search(r"\brang\w*\s+$", pre, re.I):   # 'range from 10% to 20%'는 범위
                lo, hi = float(v.group("r0")), float(v.group("r1"))
            elif v.group("rev"):
                lo = hi = float(v.group("r1"))
            elif v.group("lo"):
                if re.search(rf"\bfrom\s+(?:{QUAL})?$", pre, re.I):
                    continue                              # 'rise from 33–38% to 55–60%' — 앞 범위는 이전 전망
                lo, hi = float(v.group("lo")), float(v.group("hi"))
            else:
                lo = hi = float(v.group("one"))
                if re.search(rf"\b(?:to|reach(?:es|ing)?|exceed\w*|surpass\w*|from|at|of|above|below)\s+(?:{QUAL})?$", pre, re.I) and \
                        not re.search(rf"\b(?:increases?|growth|declines?|rises?|jump|drop|gains?)\s+of\s+(?:{QUAL})?$", pre, re.I):
                    continue                              # 수준·기준점('rise to 6.2%', 'from 40%')이지 변화율이 아니다
            post = clause[v.end():v.end() + 40]
            if re.search(r"(?:account(?:s|ed|ing)? for|making up)\s+(?:\w+\s+){0,3}$", pre, re.I) or \
                    re.match(r"\s*(?:of (?:total|all|global|the)|share)\b", post, re.I):
                continue                                  # 비중('accounting for 33%', '41% of total')이지 변화율이 아니다
            if re.match(r"\s*(?:YoY\s+|QoQ\s+)?(?:recorded|seen|posted|registered|achieved|reported)\b", post, re.I):
                bump("historical")                        # 'than the 17% YoY recorded in 2026'
                continue
            # 방향: 숫자 앞 60자 안의 마지막 방향 동사, 없으면 숫자 뒤 명사형('a 60% YoY increase')
            back = _DIR_BACK.search(pre[-60:])
            fwd = _DIR_FWD.search(post)
            d = back or fwd
            if not d:
                bump("no_direction")
                continue
            direction = "up" if d.group("up") else "down"
            # 예측 판정
            if _PERFECT.search(clause) or (back and _PAST_VERB.fullmatch(back.group(0)) and not _FUTURE_STRONG.search(clause)):
                bump("historical")
                continue
            if not (_FUTURE.search(clause) or _FUTURE.search(sentence[:c0 + v.start()])):
                bump("historical" if _PAST_VERB.search(clause) else "not_forecast")
                continue
            # 기간
            period = (_nearest_period(clause, v.end()) or _nearest_period(sentence, c0 + v.start(), after_first=False)
                      or _relative_period(sentence, published) or (_nearest_period(context[-1]) if context else None)
                      or default_period)
            if not period:
                bump("no_period")
                continue
            if re.search(r"full[- ]year", clause, re.I):
                period = period[:4]
            if period_end(period) < published:
                bump("historical")
                continue
            # 대상: 명사형 뒤 'in/of X'('90% surge in CSP CapEx') → 절 안 숫자 앞 가장 가까운 것 → 문장 앞부분 → 절 안 숫자 뒤
            #       → 'forecasts X to …' 명사구
            subj = None
            if not back and fwd:
                m = re.match(r"\s*(?:in|of|for)\s+(?:[A-Za-z\-]+\s+){0,2}?(?=\S)", clause[v.end() + fwd.end():])
                m = m and _SUBJ_RE.match(clause, v.end() + fwd.end() + m.end())
                if m:
                    subj = (m.group(0), SUBJECT_NODES[int(m.lastgroup[1:])][1], c0 + m.start())
            for scope, base in ((pre, c0), (sentence[:c0], 0)):
                if subj:
                    break
                ms = list(_SUBJ_RE.finditer(scope))
                if ms:
                    subj = (ms[-1].group(0), SUBJECT_NODES[int(ms[-1].lastgroup[1:])][1], base + ms[-1].start())
                    break
            if subj and subj[2] < c0 + v.start():      # 'DRAM prices …, TrendForce forecasts that overall BOM costs will grow' → BOM costs
                m = _FALLBACK_SUBJ.search(sentence, subj[2] + len(subj[0]), c0 + v.start())
                if m and " " in m.group(1).strip() and not _SUBJ_RE.search(m.group(1)) and not re.search(r"\b(?:this|that|these|those|it|its|they|their|which)\b", m.group(1), re.I):
                    subj = (m.group(1).strip(), None, m.start(1))
            if subj is None:
                m = _SUBJ_RE.search(clause, v.end())
                if m:
                    subj = (m.group(0), SUBJECT_NODES[int(m.lastgroup[1:])][1], c0 + m.start())
            if subj is None:
                m = _FALLBACK_SUBJ.search(sentence[:c0 + v.start()])
                if m and not re.search(r"\b(?:this|that|these|those|it|its|they|their|which)\b", m.group(1), re.I):
                    subj = (m.group(1).strip(), None, m.start(1))
            if subj is None:
                bump("no_subject")
                continue
            name, node, spos = subj
            if node is not None:                          # 앞 수식어(허용 목록)를 붙인다('foldable smartphone', 'overall SLC NAND')
                mods = re.search(r"((?:[A-Za-z][\w\-]*\s+){1,2})$", sentence[:spos])
                words = (mods.group(1).split() if mods else [])[-2:]
                while words and words[0].lower() not in _MODS:
                    words.pop(0)
                if words and all(w.lower() in _MODS for w in words):
                    name = " ".join(words + [name])
            vpos, send = c0 + v.start(), spos + len(subj[0])
            # 대상 → 숫자 사이에서 숫자에 가장 가까운 단어('Memory Prices to Drive Notebook Shipments Down 14.8%' → shipments),
            # 대상이 숫자 뒤면('24.8% Growth in Foundry Revenue') 대상부터 첫 단어
            windows = ([(sentence[spos:vpos], True)] if spos < vpos else [(sentence[spos:send + 40], False)]) + \
                      [(post[:25], False), (sentence[max(0, spos - 30):spos], True)]
            metric = f"{_metric_base(windows, node)}_{_suffix(clause, period)}"
            if direction == "down":
                lo, hi = -abs(hi), -abs(lo)
            lo, hi = min(lo, hi), max(lo, hi)
            out.append({"subject": name, "node_key": node, "metric": metric, "target_period": period,
                        "value_low": lo, "value_high": hi, "unit": "%", "direction": direction, "quote": sentence})
    return out


# ── TrendForce ────────────────────────────────────────────────────────────────

class _Fetcher:
    """요청 간격·상한을 지키는 세션"""

    def __init__(self, cap: int):
        self.s, self.cap, self.n, self.last = requests.Session(), cap, 0, 0.0
        self.s.headers.update(UA)

    def get(self, url: str) -> requests.Response:
        if self.n >= self.cap:
            raise RuntimeError(f"요청 상한({self.cap}) 도달")
        wait = DELAY - (time.monotonic() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.n += 1
        try:
            res = self.s.get(url, timeout=30)
        finally:
            self.last = time.monotonic()
        res.raise_for_status()
        return res


def _clean(fragment: str) -> str:
    return _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse_listing(page_html: str) -> list[tuple[str, str]]:
    """목록 쪽 → [(기사 URL, YYYY-MM-DD)]. 기사 주소의 YYYYMMDD가 날짜다"""
    out = []
    for path in dict.fromkeys(re.findall(r'href="(/presscenter/news/(\d{8})-\d+\.html)"', page_html)):
        p, d = path
        out.append((TF_BASE + p, f"{d[:4]}-{d[4:6]}-{d[6:]}"))
    return out


def parse_article(page_html: str) -> tuple[str | None, list[list[str]], str]:
    """기사 → (게시일 YYYY-MM-DD, 문단별 문장 목록, 제목). 본문 <p> 먼저, 제목 <h1>·요점 <li>는 뒤(같은 키면 본문 문장이 이긴다)"""
    m = re.search(r'"datePublished":\s*"(\d{4}-\d{2}-\d{2})', page_html)
    i = page_html.find("<article")
    if i < 0:
        raise ValueError("TrendForce 기사 본문(<article>)을 찾지 못함 — 레이아웃 변경 확인 필요")
    j = page_html.find("For more information", i)
    seg = page_html[i:j if j > 0 else page_html.find("</article>", i)]
    body, heads, title = [], [], ""
    for tag, frag in re.findall(r"<(h1|li|p)\b[^>]*>(.*?)</\1>", seg, re.S | re.I):
        text = _clean(frag)
        if not text:
            continue
        title = title or (text if tag.lower() == "h1" else "")
        sents = [s for s in _SENT_SPLIT.split(text) if s]
        (body if tag.lower() == "p" else heads).append(sents)
    return (m.group(1) if m else None), body + heads, title


def claims_from_article(page_html: str, url: str, published: str | None = None, stats: dict | None = None) -> tuple[str, list[dict]]:
    pub, paras, title = parse_article(page_html)
    pub = pub or published
    if not pub:
        raise ValueError(f"TrendForce 게시일을 찾지 못함: {url}")
    pd = date.fromisoformat(pub)
    tps = {_period_of(m) for m in _PERIOD_RE.finditer(title)}
    default = tps.pop() if len(tps) == 1 else None
    seen, out = set(), []
    for sents in paras:
        for k, s in enumerate(sents):
            for c in extract_claims(s, pd, sents[:k], stats, default):
                key = (c["subject"].lower(), c["metric"], c["target_period"])
                if key in seen:
                    continue
                seen.add(key)
                out.append(c)
    return pub, out


def _store(conn, source: str, org: str, url: str, published: str | None, claims: list[dict]) -> int:
    for c in claims:
        conn.execute(
            "INSERT INTO expectation_claims (source, source_org, published_at, node_key, subject, metric, target_period, value_low, value_high,"
            " unit, direction, quote, url, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))"
            " ON CONFLICT(source, url, node_key, subject, metric, target_period) DO UPDATE SET source_org=excluded.source_org,"
            " published_at=excluded.published_at, value_low=excluded.value_low, value_high=excluded.value_high,"
            " unit=excluded.unit, direction=excluded.direction, quote=excluded.quote, fetched_at=excluded.fetched_at",
            (source, org, published, c["node_key"] or "", c["subject"] or "", c["metric"], c["target_period"] or "", c["value_low"], c["value_high"],
             c["unit"], c["direction"], c["quote"], url))
    return len(claims)


def collect_trendforce(conn, backfill: bool = False) -> dict:
    f = _Fetcher(MAX_REQ[backfill])
    cutoff = (date.today() - timedelta(days=BACKFILL_DAYS)).isoformat()
    stats: dict = {}
    stored = articles = with_claims = failed = 0
    note = None
    page = 1
    try:
        while True:
            items = parse_listing(f.get(TF_LIST.format(page)).text)
            if not items:
                raise ValueError(f"TrendForce 목록 {page}쪽에서 기사 링크를 찾지 못함 — 레이아웃 변경 확인 필요")
            for url, d in items:
                if backfill and d < cutoff:
                    continue
                articles += 1
                try:
                    pub, claims = claims_from_article(f.get(url).text, url, d, stats)
                except (requests.RequestException, ValueError):
                    failed += 1
                    continue
                if claims:
                    with_claims += 1
                    stored += _store(conn, "trendforce", "TrendForce", url, pub, claims)
            conn.commit()
            page += 1
            if (not backfill and page > DAILY_PAGES) or (backfill and min(d for _, d in items) < cutoff):
                break
    except RuntimeError as e:                       # 요청 상한 — 여기까지 저장한 것은 유효
        note = str(e)
    conn.commit()
    out = {"stored": stored, "articles": articles, "articles_with_claims": with_claims, "pages": page - 1 if note is None else page,
           "requests": f.n, "skipped": stats}
    if failed:
        out["failed_articles"] = failed
    if note:
        out["note"] = note
    if articles and failed == articles:
        raise ValueError(f"TrendForce 기사 {articles}건 전부 파싱 실패 — 레이아웃 변경 확인 필요")
    return out


# ── WSTS ──────────────────────────────────────────────────────────────────────

WSTS_SEGMENTS = {  # 표 행 이름 → (대상, node_key)
    "Total World": ("World semiconductor market", None), "Memory": ("Memory", "memory"), "Logic": ("Logic", "foundry"),
    "Micro": ("Micro", None), "Analog": ("Analog", None), "Discrete Semiconductors": ("Discrete", None),
    "Optoelectronics": ("Optoelectronics", None), "Sensors": ("Sensors", None),
}
_WSTS_PROSE = [  # 산문 별칭 → 표 행 이름
    (r"global semiconductor market|semiconductor market|world semiconductor market", "Total World"), (r"Memory", "Memory"),
    (r"Logic", "Logic"), (r"Microprocessors|Micro\b", "Micro"), (r"Analog", "Analog"), (r"Discrete(?: Semiconductors)?", "Discrete Semiconductors"),
    (r"Optoelectronics", "Optoelectronics"), (r"Sensors", "Sensors"),
]


def parse_wsts_table(text: str) -> dict[tuple[str, str], tuple[float, str]]:
    """pdftotext -layout 출력 → {(행, 연도): (전년 대비 %, 근거)}. 머리행 '2025 2026 2027 2025 2026 2027' 뒤 3열이 성장률"""
    hdr = re.search(r"^\s*(20\d\d)\s+(20\d\d)\s+(20\d\d)\s+\1\s+\2\s+\3\s*$", text, re.M)
    if not hdr:
        raise ValueError("WSTS 요약표 머리행(연도 3개 ×2)을 찾지 못함")
    years = hdr.groups()
    out = {}
    for row in WSTS_SEGMENTS:
        m = re.search(rf"^\s*{re.escape(row)}[^\n]*?((?:\s+-?[\d,.]+){{6}})\s*$", text[hdr.end():], re.M)
        if m:
            line = re.sub(r"\s+", " ", m.group(0)).strip()
            for y, g in zip(years, m.group(1).split()[3:]):
                out[(row, y)] = (float(g), f"WSTS Forecast Summary 표 ({'/'.join(years)} 금액·성장률): {line}")
    if "Total World" not in {r for r, _ in out}:
        raise ValueError("WSTS 요약표에서 'Total World' 행을 찾지 못함")
    return out


def parse_wsts_prose(text: str) -> dict[tuple[str, str], tuple[float, str]]:
    """보도 본문 → {(행, 연도): (%, 문장)}. 'Logic … growing 37 percent in 2026', 'Microprocessors 20 percent' 나열,
    'For 2027, … grow a further 27 percent'. 연도는 문장의 'For YYYY' 또는 마지막 연도, 없으면 앞 문장 연도를 잇는다"""
    out: dict[tuple[str, str], tuple[float, str]] = {}
    year = None
    for s in (x for para in text.split("\n") for x in _SENT_SPLIT.split(para.strip()) if x):
        lead = re.match(r"\s*For (20\d\d)", s)
        ys = re.findall(r"\b(20\d\d)\b", s)
        year = lead.group(1) if lead else (ys[-1] if ys else year)
        if not year or not re.search(r"\d\s?percent", s):
            continue
        for alias, row in _WSTS_PROSE:
            for m in re.finditer(rf"\b(?:{alias})\b[^.%]{{0,120}}?(-?\d+(?:\.\d+)?)\s?percent", s, re.I):
                out.setdefault((row, year), (float(m.group(1)), s.strip()))
    if "Total World" not in {r for r, _ in out}:
        raise ValueError("WSTS 본문에서 세계 시장 성장률을 찾지 못함")
    return out


def collect_wsts(conn) -> dict:
    res = requests.get(WSTS_URL, headers=UA, timeout=30)
    res.raise_for_status()
    page = res.text
    text = _clean(re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", page))
    if not re.search(r"market forecast", text, re.I):
        raise ValueError("WSTS 'Recent News Release'가 시장 전망 보도가 아님 — 페이지 확인 필요")
    season = re.search(r"\b(Spring|Fall|Autumn) (20\d\d)\b", text)
    pdf = re.search(r'href="([^"]+?(\d{4})-([A-Za-z]{3})[^"]*\.pdf)"', page)
    published = None
    if pdf:
        published = datetime.strptime(f"{pdf.group(2)}-{pdf.group(3)}", "%Y-%b").strftime("%Y-%m")
    elif season:
        published = f"{season.group(2)}-{'05' if season.group(1).lower() == 'spring' else '11'}"
    out: dict = {"method": "prose", "published": published, "pdf": pdf.group(1) if pdf else None}
    values = None
    if pdf and shutil.which("pdftotext"):          # 표가 있으면 세부 품목 내년치·소수점까지 — 실패 사유는 결과에 남긴다
        try:
            blob = requests.get(requests.compat.urljoin(WSTS_URL, pdf.group(1)), headers=UA, timeout=60).content
            with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
                tmp.write(blob)
                tmp.flush()
                values = parse_wsts_table(subprocess.run(["pdftotext", "-layout", tmp.name, "-"], capture_output=True,
                                                         text=True, timeout=60, check=True).stdout)
            out["method"] = "pdf_table"
        except (requests.RequestException, subprocess.SubprocessError, ValueError) as e:
            out["pdf_error"] = str(e)
    elif pdf:
        out["pdf_error"] = "pdftotext 없음 — 본문 산문만 파싱(세부 품목 내년치 없음)"
    if values is None:                              # 본문 = <div class="article"> 안 <p> 문단(줄 단위)
        art = page[page.find('class="article"'):]
        paras = [_clean(p) for p in re.findall(r"<p\b[^>]*>(.*?)</p>", art[:art.find("About WSTS")], re.S | re.I)]
        values = parse_wsts_prose("\n".join(p for p in paras if p))
    pub_year = int((published or str(date.today().year))[:4])
    claims = []
    for (row, y), (g, quote) in sorted(values.items()):
        if int(y) < pub_year:                       # 지난해 실적 열은 예측이 아니다
            continue
        subj, node = WSTS_SEGMENTS[row]
        claims.append({"subject": subj, "node_key": node, "metric": "market_yoy", "target_period": y, "value_low": g, "value_high": g,
                       "unit": "%", "direction": "up" if g > 0 else "down" if g < 0 else "flat", "quote": quote})
    out["stored"] = _store(conn, "wsts", "WSTS", WSTS_URL, published, claims)
    conn.commit()
    return out


def collect(backfill: bool = False) -> dict:
    """TrendForce + WSTS 전망 수집. 원천 하나라도 실패하면 partial, 전부 실패면 error"""
    from database import get_connection
    conn = get_connection()
    sources, errors, stored = {}, [], 0
    try:
        for name, fn in (("trendforce", lambda: collect_trendforce(conn, backfill)), ("wsts", lambda: collect_wsts(conn))):
            try:
                r = fn()
                sources[name] = r
                stored += r["stored"]
                # 일간 실행에서 새 기사에 전망이 없는 날은 정상 — 목록·기사를 읽었는데 0건이면 ok(거짓 경보 방지).
                # 기사를 하나도 못 읽었거나, 백필인데 0건이면 파싱 규칙이 깨진 것
                if r["stored"] == 0 and (backfill or not r.get("articles", 1)):
                    errors.append(f"{name}: 저장된 전망 0건 — 파싱 규칙 확인 필요")
            except Exception as e:  # noqa: BLE001 — 수집 실패는 status로 드러낸다
                sources[name] = {"stored": 0, "error": str(e)}
                errors.append(f"{name}: {e}")
    finally:
        conn.close()
    failed = sum(1 for n in sources if sources[n].get("error") or any(e.startswith(f"{n}:") for e in errors))
    status = "ok" if not failed else ("error" if failed == len(sources) else "partial")
    return {"stored": stored, "sources": sources, "status": status, **({"error": " / ".join(errors)} if errors else {})}
