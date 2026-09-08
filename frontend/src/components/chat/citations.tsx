import type { Components } from "react-markdown"
import { Link } from "react-router-dom"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import type { ChatMessage } from "@/types"

export type Citation = NonNullable<ChatMessage["citations"]>[number]

/** 근거 종류 → 한국어 라벨 (chat_tools 근거 항목 kind) */
export const KIND_LABEL: Record<string, string> = {
  doc: "문서", narrative: "내러티브", edges: "인과", knowledge: "지식", question: "질문",
  lens: "렌즈", quote: "시세", prices: "시세 추이", regime: "국면", briefing: "브리핑",
  digest: "다이제스트", youtube: "유튜브", signal: "신호", action: "기업활동",
}

export const GAP_LABEL: Record<string, string> = {
  unsupported: "근거 부족",
  contradiction: "모순",
  stale: "오래된 정보",
  missing: "빠진 정보",
}

export function citationHref(c: Citation): string | null {
  return c.href ?? (c.doc_id ? `/doc/${c.doc_id}` : null)
}

const CITE_RE = /\[(\d{1,2}(?:\s*[,·]\s*\d{1,2})*)\](?!\()/g

/**
 * 본문의 `[3]`·`[1, 4]`를 `[3](#cite-3)` 링크로 바꿔 Markdown이 인용 칩으로 렌더하게 한다.
 * citations에 없는 번호는 그대로 둔다(모델이 근거 밖 번호를 썼다면 텍스트로 남아 보인다).
 * 뒤에 `(`가 오는 것은 이미 마크다운 링크라 건드리지 않는다.
 */
export function linkifyCitations(content: string, citations: Citation[] | null): string {
  if (!citations || citations.length === 0) return content
  const valid = new Set(citations.map((c) => c.n))
  return content.replace(CITE_RE, (whole, inner: string) => {
    const nums = inner.split(/\s*[,·]\s*/).map(Number)
    if (!nums.every((n) => valid.has(n))) return whole
    return nums.map((n) => `[${n}](#cite-${n})`).join("")
  })
}

/** Markdown `a` 교체 — `#cite-n`만 칩으로, 나머지 링크는 기본 렌더 */
export function citationComponents(citations: Citation[] | null): Components {
  const byN = new Map((citations ?? []).map((c) => [c.n, c]))
  return {
    a: ({ href, children, ...rest }) => {
      const m = href?.match(/^#cite-(\d+)$/)
      if (!m) return <a href={href} {...rest}>{children}</a>
      const c = byN.get(Number(m[1]))
      if (!c) return <>{children}</>
      return <CitationChip c={c} />
    },
  }
}

// Markdown 래퍼의 `[&_a]:text-primary [&_a]:underline`(복합 선택자)보다 우선해야 하므로 색·밑줄은 important
const CHIP =
  "inline-flex items-center justify-center h-[17px] min-w-[17px] px-1 ml-px rounded-md bg-muted text-[10.5px] " +
  "font-medium tabular-nums leading-none text-muted-foreground! no-underline! align-[2px] " +
  "hover:bg-accent hover:text-accent-foreground! transition-colors"

function CitationChip({ c }: { c: Citation }) {
  const to = citationHref(c)
  const label = `${KIND_LABEL[c.kind ?? ""] ?? c.kind ?? "근거"} · ${c.title}`
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        {to ? (
          <Link to={to} className={CHIP} aria-label={label}>{c.n}</Link>
        ) : (
          <span className={CHIP} aria-label={label}>{c.n}</span>
        )}
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-xs">
        <span className="text-muted-foreground">{KIND_LABEL[c.kind ?? ""] ?? c.kind}</span> {c.title}
      </TooltipContent>
    </Tooltip>
  )
}
