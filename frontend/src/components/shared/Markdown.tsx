import ReactMarkdown, { type Components } from "react-markdown"
import remarkBreaks from "remark-breaks"
import { cn } from "@/lib/utils"

/**
 * 공통 마크다운 렌더 — AI 산출물(브리프·세계관·정리본·다이제스트) 전반의
 * 가독성 표준. 문단 간격·소제목 크기·불릿 마커를 일관되게 준다.
 * (기존엔 컴포넌트마다 인라인 [&_h3]:… 를 제각각 달아 문단이 뭉쳐 보였다.)
 */
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
      className,
    )}>
      <ReactMarkdown remarkPlugins={[remarkBreaks]} components={components}>{children}</ReactMarkdown>
    </div>
  )
}
