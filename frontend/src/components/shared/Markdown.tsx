import ReactMarkdown, { type Components } from "react-markdown"
import remarkBreaks from "remark-breaks"
import remarkGfm from "remark-gfm"
import { cn } from "@/lib/utils"

/**
 * 공통 마크다운 렌더 — AI 산출물(브리프·세계관·정리본·다이제스트) 전반의
 * 가독성 표준. 문단 간격·소제목 크기·불릿 마커를 일관되게 준다.
 * (기존엔 컴포넌트마다 인라인 [&_h3]:… 를 제각각 달아 문단이 뭉쳐 보였다.)
 */
/** 표 셸 — 넓은 표는 자기 안에서만 가로 스크롤(페이지 가로 스크롤 금지, DESIGN_SYSTEM §1) */
function TableShell({ children }: React.ComponentProps<"table">) {
  return (
    <div className="my-3 overflow-x-auto rounded-lg ring-1 ring-border">
      <table>{children}</table>
    </div>
  )
}

/** 표 셀 — `+1.3%`·`-4.7%`처럼 부호 있는 등락 셀은 한국 주식 컨벤션 색(상승 빨강·하락 파랑, number-formatting 정책) */
const SIGNED_PCT = /^\s*([+-])\d[\d,]*(?:\.\d+)?\s*%/
function textOf(node: React.ReactNode): string {
  if (node == null || typeof node === "boolean") return ""
  if (typeof node === "string" || typeof node === "number") return String(node)
  if (Array.isArray(node)) return node.map(textOf).join("")
  if (typeof node === "object" && "props" in node) return textOf((node as React.ReactElement<{ children?: React.ReactNode }>).props.children)
  return ""
}
function Td({ children, className, ...props }: React.ComponentProps<"td">) {
  const m = SIGNED_PCT.exec(textOf(children))
  const tone = m ? (m[1] === "+" ? "text-up" : "text-down") : undefined
  return <td className={cn(tone, className)} {...props}>{children}</td>
}

/** components: 특정 요소 렌더 교체 (예: 대화 인용 칩 — chat/citations.tsx). 기본은 ReactMarkdown 그대로. */
export function Markdown({ children, className, components }: { children: string; className?: string; components?: Components }) {
  return (
    <div className={cn(
      "text-sm leading-relaxed break-words [&>*:first-child]:mt-0 [&>*:last-child]:mb-0",
      "[&_h1]:text-lg [&_h1]:font-bold [&_h1]:mt-5 [&_h1]:mb-2",
      "[&_h2]:text-[15px] [&_h2]:font-semibold [&_h2]:mt-5 [&_h2]:mb-2",
      "[&_h3]:text-[13px] [&_h3]:font-semibold [&_h3]:mt-4 [&_h3]:mb-1.5",
      "[&_p]:my-2.5 [&_p]:leading-relaxed",
      "[&_ul]:my-2 [&_ul]:pl-5 [&_ul]:list-disc [&_ol]:my-2 [&_ol]:pl-5 [&_ol]:list-decimal",
      "[&_li]:my-1 [&_li]:leading-relaxed [&_li]:marker:text-muted-foreground",
      "[&_strong]:font-semibold [&_a]:text-primary [&_a]:underline",
      "[&_hr]:my-4 [&_hr]:border-border [&_em]:text-muted-foreground",
      "[&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground",
      // GFM 표 — 셸(overflow-x 래퍼)은 components.table, 셀 스타일은 여기
      "[&_table]:w-full [&_table]:border-collapse [&_table]:text-[13px] [&_table]:leading-snug",
      "[&_th]:border-b [&_th]:border-border [&_th]:bg-muted/50 [&_th]:px-2.5 [&_th]:py-1.5 [&_th]:text-left [&_th]:font-medium [&_th]:text-muted-foreground [&_th]:whitespace-nowrap",
      "[&_td]:border-b [&_td]:border-border/60 [&_td]:px-2.5 [&_td]:py-1.5 [&_td]:tabular-nums [&_td]:align-top [&_tr:last-child>td]:border-b-0",
      className,
    )}>
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]} components={{ table: TableShell, td: Td, ...components }}>{children}</ReactMarkdown>
    </div>
  )
}
