"""마크다운 → 텔레그램 HTML 변환 + 태그 안전 분할 (D-109).

왜 필요한가: 내러티브·유튜브 정리본·다이제스트는 전부 마크다운(`## 핵심 요약`, `**굵게**`,
`- 불릿`)인데 v2까지는 parse_mode 없이 평문으로 보내 마크업이 날것으로 노출됐다.

텔레그램 HTML은 **인라인 태그만** 지원한다 — `b i u s a code pre blockquote tg-spoiler`.
제목·리스트·표 태그가 없으므로 의미를 보존하는 자리로 옮긴다:
  `## 제목` → <b>제목</b> · `- 항목` → `• 항목` · `---` → 구분선 문자 · 표 → <pre> 고정폭

MarkdownV2가 아니라 HTML을 쓰는 이유: MarkdownV2는 `_ * [ ] ( ) ~ > # + - = | { } . !` 를
전부 이스케이프해야 하는데, 본문이 한국어 산문 + 종목코드 + URL 혼합이라 누락 시 400이 난다.
HTML은 이스케이프 대상이 `& < >` 셋뿐이라 실패 표면이 훨씬 좁다.
"""
import html
import re

# 텔레그램 메시지 상한은 4,096자. 태그를 포함한 원문 문자열 기준으로 보수적으로 잡는다
# (태그는 보이는 길이에 안 잡히지만, 요청 크기와 분할 여유를 함께 확보).
LIMIT = 3500

_FENCE = re.compile(r"```(\w*)\n(.*?)```", re.S)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_HEADING = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.M)
_BULLET = re.compile(r"^([ \t]*)[-*+][ \t]+", re.M)
_HR = re.compile(r"^[ \t]{0,3}([-*_])\1{2,}[ \t]*$", re.M)
_QUOTE = re.compile(r"^[ \t]{0,3}>[ \t]?(.*)$", re.M)
_LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_BOLD_ALT = re.compile(r"__(.+?)__", re.S)
_STRIKE = re.compile(r"~~(.+?)~~", re.S)
# 이탤릭은 `*x*` 만 지원한다. `_x_` 는 share_delta_pp·source_id 같은 식별자를 오탐하므로 제외.
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?!\*)")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TAG = re.compile(r"</?([a-zA-Z][\w-]*)(?:\s[^>]*)?>")
_VOID_OR_SELF = {"br", "hr"}
_HR_LINE = "──────────"


def to_html(md: str) -> str:
    """마크다운 본문을 텔레그램 HTML로. 입력이 이미 평문이어도 안전(무해 통과)."""
    if not md:
        return ""
    slots: list[str] = []

    def _stash(payload: str) -> str:
        slots.append(payload)
        return f"\x00{len(slots) - 1}\x00"

    # ① 코드부터 격리 — 이후 이스케이프·인라인 변환이 코드 내용을 건드리지 않게
    def _fence(m: re.Match) -> str:
        lang, body = m.group(1), m.group(2)
        attr = f' class="language-{html.escape(lang)}"' if lang else ""
        return _stash(f"<pre><code{attr}>{html.escape(body.rstrip())}</code></pre>")

    text = _FENCE.sub(_fence, md)
    text = _INLINE_CODE.sub(lambda m: _stash(f"<code>{html.escape(m.group(1))}</code>"), text)

    # ② 표를 고정폭 블록으로 (텔레그램에 표 태그가 없다 — 정렬만이라도 살린다)
    text = _tables_to_pre(text, _stash)

    # ③ 이스케이프 — 우리가 넣을 태그보다 반드시 먼저
    text = html.escape(text, quote=False)

    # ④ 블록 수준
    text = _HR.sub(_HR_LINE, text)
    text = _HEADING.sub(lambda m: f"<b>{m.group(2)}</b>", text)
    text = _BULLET.sub(r"\1• ", text)
    text = _QUOTE.sub(r"▍ \1", text)

    # ⑤ 인라인 — 링크를 먼저 걷어야 URL 속 `*`·`_`가 강조로 오인되지 않는다
    text = _LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', text)
    text = _BOLD.sub(r"<b>\1</b>", text)
    text = _BOLD_ALT.sub(r"<b>\1</b>", text)
    text = _STRIKE.sub(r"<s>\1</s>", text)
    text = _ITALIC.sub(r"<i>\1</i>", text)

    # ⑥ 코드 복원
    for i, payload in enumerate(slots):
        text = text.replace(f"\x00{i}\x00", payload)

    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _tables_to_pre(text: str, stash) -> str:
    """연속된 `| a | b |` 행 묶음을 <pre>로. 구분행(|---|)은 버린다."""
    out, block = [], []

    def _flush():
        if not block:
            return
        rows = [r for r in block if not re.fullmatch(r"\s*\|[\s:|-]+\|\s*", r)]
        out.append(stash(f"<pre>{html.escape(chr(10).join(r.strip() for r in rows))}</pre>")
                   if len(rows) >= 1 else "")
        block.clear()

    for line in text.split("\n"):
        if _TABLE_ROW.match(line):
            block.append(line)
        else:
            _flush()
            out.append(line)
    _flush()
    return "\n".join(out)


def link(label: str, url: str) -> str:
    """본문에 심는 인라인 링크 — 라벨만 이스케이프(URL은 호출부가 만든 것)."""
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(label, quote=False)}</a>'


def esc(s: str) -> str:
    """이미 HTML을 조립하는 자리에서 쓰는 평문 이스케이프."""
    return html.escape(s or "", quote=False)


def split_html(text: str, limit: int = LIMIT) -> list[str]:
    """HTML을 태그 경계를 지키며 분할.

    태그 중간이나 열린 태그 안에서 자르면 텔레그램이 400(can't parse entities)을 뱉고
    메시지가 통째로 유실된다. 문단 단위로 모으되, 한 문단이 상한을 넘으면 강제 절단 후
    열린 태그를 닫고 다음 조각에서 다시 연다.
    """
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    cur = ""
    for block in _atomic_blocks(text):
        if len(block) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.extend(_hard_split(block, limit))
            continue
        candidate = f"{cur}\n\n{block}" if cur else block
        if len(candidate) > limit:
            chunks.append(cur)
            cur = block
        else:
            cur = candidate
    if cur:
        chunks.append(cur)
    return _rebalance(chunks)


def _atomic_blocks(text: str) -> list[str]:
    """문단 분할하되 <pre>…</pre>는 내부 빈 줄이 있어도 쪼개지 않는다."""
    blocks, buf, in_pre = [], [], False
    for para in text.split("\n\n"):
        opens, closes = para.count("<pre"), para.count("</pre>")
        if in_pre:
            buf.append(para)
            if closes > opens:
                blocks.append("\n\n".join(buf))
                buf, in_pre = [], False
        elif opens > closes:
            buf, in_pre = [para], True
        else:
            blocks.append(para)
    if buf:
        blocks.append("\n\n".join(buf))
    return blocks


def _hard_split(block: str, limit: int) -> list[str]:
    """상한을 넘는 단일 블록 — 줄 경계 우선, 없으면 문자 단위로 자른다(태그 내부는 피한다)."""
    out, rest = [], block
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit)
        if cut <= 0:
            cut = rest.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        # 태그 한복판(`<b` … `>`)에서 자르지 않도록 뒤로 물린다
        lt, gt = rest.rfind("<", 0, cut), rest.rfind(">", 0, cut)
        if lt > gt:
            cut = lt
        out.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    if rest:
        out.append(rest)
    return out


def _rebalance(chunks: list[str]) -> list[str]:
    """조각마다 열린 채 끝난 태그를 닫고, 다음 조각 앞에서 다시 연다."""
    out: list[str] = []
    carry: list[str] = []
    for chunk in chunks:
        body = "".join(f"<{t}>" for t in carry) + chunk
        stack: list[str] = []
        for m in _TAG.finditer(body):
            name = m.group(1).lower()
            if name in _VOID_OR_SELF:
                continue
            if m.group(0).startswith("</"):
                if stack and stack[-1] == name:
                    stack.pop()
            else:
                stack.append(name)
        body += "".join(f"</{t}>" for t in reversed(stack))
        # 재개용 여는 태그는 속성 없는 형태로 — <a href>는 잘려도 링크 없이 이어 읽히게
        carry = [t for t in stack if t != "a"]
        out.append(body)
    return out
