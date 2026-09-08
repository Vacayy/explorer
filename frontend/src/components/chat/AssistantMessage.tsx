import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { AlertTriangle, Check, ChevronRight, Copy } from "lucide-react"
import { Markdown } from "@/components/shared/Markdown"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { TooltipProvider } from "@/components/ui/tooltip"
import type { ChatMessage, ChatRoute } from "@/types"
import { formatRelativeTime } from "@/utils/format"
import { cn } from "@/lib/utils"
import { utcMs, type Draft } from "@/hooks/useChat"
import { citationComponents, citationHref, GAP_LABEL, KIND_LABEL, linkifyCitations } from "./citations"
import { fmtSec, RoutePanel, routeTotalMs } from "./RoutePanel"
import { useCopy } from "./UserMessage"

const BODY = "text-[15px] leading-7 [&_p]:my-3 [&_li]:my-1.5 [&_h2]:mt-6 [&_h3]:mt-5 [&_table]:my-3 [&_table]:text-sm"

/** 메타 행 — hypothesis 색 점 + 라벨. LLM 산출 마커를 말풍선 틴트 대신 라벨로 (spec §4, D-135) */
function MetaRow({ model, createdAt, live }: { model?: string | null; createdAt?: string; live?: boolean }) {
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <span className={cn("size-2 rounded-full bg-hypothesis", live && "animate-pulse")} aria-hidden />
      <span className="font-medium text-hypothesis">AI 종합</span>
      {model && <span>· {model}</span>}
      {createdAt && <span>· {formatRelativeTime(new Date(utcMs(createdAt)).toISOString())}</span>}
    </div>
  )
}

/** 과정 행 — 답 위에 접힌 한 줄("Thought for Ns" 패턴). 펼치면 RoutePanel */
function RouteRow({ route }: { route: ChatRoute }) {
  const [open, setOpen] = useState(false)
  const total = routeTotalMs(route)
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <Button variant="ghost" size="sm" className="-ml-2 h-7 gap-1 px-2 text-xs font-normal text-muted-foreground hover:text-foreground">
          <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} />
          답변 경로
          <span className="tabular-nums">· 도구 {route.tools?.length ?? 0} · 근거 {route.evidence_n}{total != null && ` · ${fmtSec(total)}`}</span>
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-1 pb-2">
        <RoutePanel route={route} />
      </CollapsibleContent>
    </Collapsible>
  )
}

const SOURCES_PREVIEW = 6

function Sources({ citations }: { citations: NonNullable<ChatMessage["citations"]> }) {
  const [all, setAll] = useState(false)
  const shown = all ? citations : citations.slice(0, SOURCES_PREVIEW)
  const rest = citations.length - shown.length
  return (
    <div className="space-y-1.5">
      <p className="text-xs font-medium text-muted-foreground">근거 {citations.length}건</p>
      <div className="flex flex-wrap gap-1.5">
        {shown.map((c) => {
          const to = citationHref(c)
          const inner = (
            <>
              <span className="shrink-0 tabular-nums text-muted-foreground">{c.n}</span>
              <span className="shrink-0 whitespace-nowrap text-muted-foreground">{KIND_LABEL[c.kind ?? ""] ?? c.kind ?? "근거"}</span>
              <span className="min-w-0 truncate">{c.title}</span>
            </>
          )
          const cls = "inline-flex max-w-[280px] items-center gap-1.5 rounded-lg border bg-card px-2.5 py-1.5 text-xs transition-colors"
          return to ? (
            <Link key={c.n} to={to} className={cn(cls, "hover:bg-muted hover:text-foreground")}>{inner}</Link>
          ) : (
            <span key={c.n} className={cls}>{inner}</span>
          )
        })}
        {rest > 0 && (
          <Button variant="ghost" size="sm" className="h-auto rounded-lg px-2.5 py-1.5 text-xs font-normal text-muted-foreground" onClick={() => setAll(true)}>
            +{rest}
          </Button>
        )}
      </div>
    </div>
  )
}

/** 완료된 어시스턴트 메시지 — 메타 · 과정 · 본문(인라인 인용) · 갭 · 근거 · 액션 */
export function AssistantMessage({ m }: { m: ChatMessage }) {
  const { copied, copy } = useCopy()
  const body = useMemo(() => linkifyCitations(m.content, m.citations), [m.content, m.citations])
  const components = useMemo(() => citationComponents(m.citations), [m.citations])
  return (
    <article className="group/msg space-y-2">
      <MetaRow model={m.model} createdAt={m.created_at} />
      {m.route && <RouteRow route={m.route} />}
      <TooltipProvider delayDuration={150}>
        <Markdown className={BODY} components={components}>{body}</Markdown>
      </TooltipProvider>

      {m.gaps && m.gaps.length > 0 && (
        <div className="rounded-xl bg-[color-mix(in_srgb,var(--hypothesis)_8%,var(--card))] px-4 py-3 space-y-1.5">
          {m.gaps.map((g, i) => (
            <div key={i} className="flex items-start gap-2 text-[13px] leading-relaxed">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-hypothesis" />
              <Badge variant="secondary" className="shrink-0 text-[10px]">{GAP_LABEL[g.type] ?? g.type}</Badge>
              <span>{g.note}</span>
            </div>
          ))}
        </div>
      )}

      {m.citations && m.citations.length > 0 && <Sources citations={m.citations} />}

      <div className="flex gap-0.5 opacity-0 transition-opacity group-hover/msg:opacity-100 focus-within:opacity-100 max-md:opacity-100">
        <Button variant="ghost" size="icon-xs" aria-label="답변 복사" onClick={() => copy(m.content)}>
          {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
        </Button>
      </div>
    </article>
  )
}

/** 생성 중 — 같은 골격에서 과정 행 자리에 라이브 status, 본문은 초안+캐럿 또는 스켈레톤 (D-130) */
export function StreamingMessage({ draft }: { draft: Draft | null }) {
  return (
    <article className="space-y-2" aria-live="polite" aria-atomic="false">
      <MetaRow live />
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Spinner className="size-3.5" />
        <span>{draft?.status || "질문 분석 중…"}</span>
        <span className="hidden sm:inline">· 다른 화면에 다녀와도 계속됩니다</span>
      </div>
      {draft?.text ? (
        <div className="relative">
          <Markdown className={BODY}>{draft.text}</Markdown>
          <span className="ml-0.5 inline-block h-[1.1em] w-[2px] translate-y-[3px] animate-pulse bg-foreground/70" aria-hidden />
        </div>
      ) : (
        <div className="space-y-2.5 pt-1">
          <Skeleton className="h-4 w-11/12" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      )}
    </article>
  )
}
