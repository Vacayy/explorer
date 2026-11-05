import { useMemo, useRef, useState, type ReactNode } from "react"
import { Link, useNavigate } from "react-router-dom"
import { BookOpen, Check, ChevronRight, Copy, Quote, RotateCcw } from "lucide-react"
import { toast } from "sonner"
import { Markdown } from "@/components/shared/Markdown"
import SaveButton from "@/components/shared/SaveButton"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { useProjects } from "@/components/study/useProjects"
import type { ChatMessage, ChatRoute } from "@/types"
import { formatKstSlashDate, formatNumber } from "@/utils/format"
import { MOBILE_QUERY, useMediaQuery } from "@/hooks/useMediaQuery"
import { useChatStudy } from "@/hooks/useChatStudy"
import { cn } from "@/lib/utils"
import { type Draft } from "@/hooks/useChat"
import { citationComponents, citationHref, GAP_LABEL, KIND_LABEL, linkifyCitations } from "./citations"
import { evidenceSummary, fmtSec, RoutePanel, routeTotalMs } from "./RoutePanel"
import { PriceChartCard, priceTargets } from "./PriceChartCard"
import { FollowUps } from "./FollowUps"
import { CITE_CHIP, quoteFromSelection, type Quote as QuoteRef } from "./useQuoteSelection"
import { SelectionPalette } from "@/components/shared/SelectionPalette"
import { useCopy } from "./UserMessage"

const BODY = "text-[15px] leading-7 [&_p]:my-3 [&_li]:my-1.5 [&_h2]:mt-6 [&_h3]:mt-5 [&_table]:my-3 [&_table]:text-sm"

const AI_BADGE = "h-[22px] rounded-md border-0 bg-[color-mix(in_srgb,var(--hypothesis)_12%,transparent)] px-2 text-xs font-medium text-hypothesis"

/** 'claude-code/sonnet' → 'sonnet' */
const modelName = (model?: string | null) => model?.split("/").pop() ?? null

/**
 * 답변 머리 한 줄 (시안 Chat) — 'AI 답변' · 근거 수집 요약(누르면 답변 경로 펼침) · 모델 · 시각.
 * LLM 산출 표시는 말풍선 틴트 대신 이 배지로 한다(chat-page.md §4).
 */
function MetaRow({ model, createdAt, route }: { model?: string | null; createdAt?: string; route?: ChatRoute | null }) {
  const [open, setOpen] = useState(false)
  const name = modelName(model ?? route?.model)
  const tail = [name, createdAt ? formatKstSlashDate(createdAt) : null].filter(Boolean).join(" · ")
  const summary = route ? evidenceSummary(route) : []
  const total = route ? routeTotalMs(route) : undefined
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <Badge variant="secondary" className={AI_BADGE}>AI 답변</Badge>
        <span className="basis-full md:hidden max-md:order-2" aria-hidden />
        {route && (
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" data-route-toggle className="-mx-1.5 h-auto min-h-7 max-w-full min-w-0 shrink gap-1 px-1.5 py-0.5 text-left text-xs font-normal whitespace-normal text-muted-foreground hover:text-foreground max-md:order-3 max-md:min-h-10">
              <span className="min-w-0">근거 수집{summary.length ? ` · ${summary.join(" · ")}` : ` · ${formatNumber(route.evidence_n)}건`}{total != null && ` · ${fmtSec(total)}`}</span>
              <ChevronRight className={cn("size-3.5 shrink-0 transition-transform", open && "rotate-90")} aria-hidden />
            </Button>
          </CollapsibleTrigger>
        )}
        {tail && <span className="tabular-nums max-md:order-1">{route && <span className="max-md:hidden">· </span>}{tail}</span>}
      </div>
      {route && <CollapsibleContent className="pt-2"><RoutePanel route={route} /></CollapsibleContent>}
    </Collapsible>
  )
}

/**
 * 폰(<768)에서 답변 본문의 `## ` 절을 제목만 보이게 접는다(ia-redesign §4.32). 첫 절 앞(결론)은 펼친 채로 둔다.
 * 코드 블록 안의 `## `는 절로 보지 않는다. 절이 둘 미만이면 나누지 않는다.
 */
export function splitSections(md: string): { lead: string; sections: { title: string; body: string }[] } | null {
  const lines = md.split("\n")
  const sections: { title: string; body: string[] }[] = []
  const lead: string[] = []
  let fence = false
  for (const line of lines) {
    if (/^\s*(```|~~~)/.test(line)) fence = !fence
    const h = !fence && /^## (.+)$/.exec(line)
    if (h) sections.push({ title: h[1].replace(/\*\*/g, "").trim(), body: [] })
    else if (sections.length) sections[sections.length - 1].body.push(line)
    else lead.push(line)
  }
  if (sections.length < 2) return null
  return { lead: lead.join("\n").trim(), sections: sections.map(x => ({ title: x.title, body: x.body.join("\n").trim() })) }
}

function FoldRow({ title, children }: { title: ReactNode; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="border-b">
      <CollapsibleTrigger asChild>
        <Button variant="ghost" className="h-auto min-h-11 w-full justify-between whitespace-normal px-0 py-2 text-left text-[15px] font-normal">
          <span className="min-w-0">{title}</span>
          <ChevronRight className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} aria-hidden />
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent className="pb-3">{children}</CollapsibleContent>
    </Collapsible>
  )
}

/** 출처 목록 (시안 Chat) — 번호 · 종류 · 제목(원문 링크) · 날짜. 시세는 답변 시각, 수집 자료는 게시일 */
function SourceList({ citations, answeredAt }: { citations: NonNullable<ChatMessage["citations"]>; answeredAt?: string }) {
  return (
    <ol className="text-[12.5px] leading-5">
      {citations.map((c) => {
        const to = citationHref(c)
        const when = c.published_at ?? (c.kind === "quote" ? answeredAt : null)
        return (
          <li key={c.n} data-source={c.n} className="grid grid-cols-[2.25rem_3.5rem_minmax(0,1fr)_auto] items-baseline gap-2 border-t py-1.5 first:border-t-0">
            <span className="font-mono tabular-nums text-muted-foreground">[{c.n}]</span>
            <span className="truncate text-muted-foreground">{KIND_LABEL[c.kind ?? ""] ?? c.kind ?? "근거"}</span>
            {to
              ? <Link to={to} className="truncate hover:underline" title={c.title}>{c.title}</Link>
              : <span className="truncate" title={c.title}>{c.title}</span>}
            <span className="font-mono tabular-nums text-muted-foreground">{when ? formatKstSlashDate(when, false) : ""}</span>
          </li>
        )
      })}
    </ol>
  )
}

const GAP_TONE: Record<string, string> = {
  contradiction: "bg-[color-mix(in_srgb,var(--hypothesis)_14%,transparent)] text-hypothesis",
  unsupported: "bg-accent text-accent-foreground",
  assumption: "bg-accent text-accent-foreground",
}

/** 답에서 확인하지 못한 것 (시안 Chat) — 종류 배지 · 한 줄 */
function GapList({ gaps }: { gaps: NonNullable<ChatMessage["gaps"]> }) {
  return (
    <ul className="text-[12.5px] leading-5">
      {gaps.map((g, i) => (
        <li key={i} data-gap={g.type} className="grid grid-cols-[7.5rem_minmax(0,1fr)] items-start gap-2.5 border-t py-1.5 first:border-t-0">
          <Badge variant="secondary" className={cn("h-[22px] w-fit max-w-full justify-start rounded-md border-0 px-2 text-xs font-medium", GAP_TONE[g.type])}>{GAP_LABEL[g.type] ?? g.type}</Badge>
          <span className="pt-0.5">{g.note}</span>
        </li>
      ))}
    </ul>
  )
}

/** 답변 아래 묶음 상자 — 폰에서는 접힌 줄(4i) */
function AnswerBox({ title, phone, children }: { title: string; phone: boolean; children: ReactNode }) {
  if (phone) return <FoldRow title={title}>{children}</FoldRow>
  return (
    <section className="rounded-xl border bg-card px-4 py-3">
      <h3 className="pb-1 text-[13px] font-semibold">{title}</h3>
      {children}
    </section>
  )
}

/** '스터디로 보내기' — 답변을 고른 스터디 프로젝트에 자료로 넣는다. 프로젝트 목록은 메뉴를 열 때만 읽는다 */
function SendToStudy({ m, threadTitle }: { m: ChatMessage; threadTitle: string }) {
  const [open, setOpen] = useState(false)
  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="max-md:h-10"><BookOpen className="size-3.5" aria-hidden />스터디로 보내기</Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64">
        {open && <StudyMenuItems m={m} threadTitle={threadTitle} />}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function StudyMenuItems({ m, threadTitle }: { m: ChatMessage; threadTitle: string }) {
  const projects = useProjects()
  const { sendAnswer } = useChatStudy()
  const navigate = useNavigate()
  const send = (projectId: number, projectTitle?: string) => sendAnswer.mutate({ projectId, projectTitle, threadTitle, message: m }, {
    onSuccess: r => toast.success(`‘${r.title}’에 답변을 넣었습니다.`, { action: { label: "열기", onClick: () => navigate(`/study/projects/${r.id}`) } }),
    onError: () => toast.error("스터디에 넣지 못했습니다. 다시 시도해 주세요."),
  })
  return <>
    <DropdownMenuItem onSelect={() => send(0)}>새 프로젝트 ‘{threadTitle.length > 24 ? threadTitle.slice(0, 24) + "…" : threadTitle}’</DropdownMenuItem>
    <DropdownMenuSeparator />
    <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">기존 프로젝트</DropdownMenuLabel>
    {projects.isLoading && <div className="px-2 py-1.5"><Skeleton className="h-4 w-3/4" /></div>}
    {projects.isError && <p className="px-2 py-1.5 text-xs text-destructive">목록을 불러오지 못했습니다.</p>}
    {projects.data?.length === 0 && <p className="px-2 py-1.5 text-xs text-muted-foreground">프로젝트가 없습니다.</p>}
    {projects.data?.slice(0, 8).map(p => <DropdownMenuItem key={p.id} onSelect={() => send(p.id, p.title)}><span className="truncate">{p.title}</span></DropdownMenuItem>)}
  </>
}

/** 완료된 어시스턴트 메시지 (시안 Chat) — 머리 · 본문(인라인 인용) · 행동 · 확인하지 못한 것 · 출처 · 이어 물을 질문 */
export function AssistantMessage({ m, isLast, carried, onQuote, onPick, conversationId, threadTitle, onRegenerate }: {
  m: ChatMessage
  /** 마지막 답변에만 후속 질문을 보인다 — 스레드에 낡은 제안이 쌓이지 않게 */
  isLast?: boolean
  /** 앞 답에서 남은 후속 질문 (carriedFollowUps) — 마지막 답변에만 */
  carried?: { kind: string; question: string }[]
  /** 드래그한 대목을 컴포저에 인용으로 붙이기 (문단·근거 동반) */
  onQuote?: (q: QuoteRef) => void
  /** 후속 질문을 컴포저에 채우기 */
  onPick?: (q: string) => void
  /** 저장(북마크) 목적지 — 없으면 저장 버튼을 숨긴다 */
  conversationId?: number | null
  /** 스터디 자료 제목 — 없으면 '스터디로 보내기'를 숨긴다 */
  threadTitle?: string | null
  /** 같은 질문을 다시 보내 새 답을 받는다 — 마지막 답변·생성 중 아님일 때만 넘긴다 */
  onRegenerate?: () => void
}) {
  const { copied, copy } = useCopy()
  const body = useMemo(() => linkifyCitations(m.content, m.citations), [m.content, m.citations])
  const components = useMemo(() => citationComponents(m.citations), [m.citations])
  const prices = useMemo(() => priceTargets(m.citations), [m.citations])
  const bodyRef = useRef<HTMLDivElement>(null)
  const followUps = (isLast && m.route?.follow_ups) || []
  const leftover = (isLast && carried) || []
  const phone = useMediaQuery(MOBILE_QUERY)
  const parts = useMemo(() => phone ? splitSections(body) : null, [phone, body])
  const firstLine = m.content.replace(/[#*>`_[\]]/g, "").split("\n").map(x => x.trim()).find(Boolean)?.slice(0, 120) ?? null
  return (
    <article className="group/msg space-y-3" data-answer={m.id}>
      <MetaRow model={m.model} createdAt={m.created_at} route={m.route} />
      <div ref={bodyRef} className="relative">
        <TooltipProvider delayDuration={150}>
          {parts ? <>
            {parts.lead && <Markdown className={BODY} components={components}>{parts.lead}</Markdown>}
            <div className="mt-2 border-t">
              {parts.sections.map((x, i) => <FoldRow key={i} title={x.title}><Markdown className={BODY} components={components}>{x.body}</Markdown></FoldRow>)}
            </div>
          </> : <Markdown className={BODY} components={components}>{body}</Markdown>}
        </TooltipProvider>
        {/* 드래그 인용 — 공통 선택 팔레트 (D-144·D-146, canvas.md §2) */}
        {onQuote && <SelectionPalette containerRef={bodyRef} ignore={CITE_CHIP}
          actions={[{ key: "quote", label: "인용해서 질문", Icon: Quote, primary: true, onSelect: sel => onQuote(quoteFromSelection(sel, m.id, m.citations)) }]} />}
      </div>

      {/* 시세 근거를 인용한 답변 — 같은 스냅샷을 차트로 (종목 1=종가, 2+=등락률 비교) */}
      {prices && <PriceChartCard targets={prices.targets} days={prices.days} />}

      {/* 답변 아래 행동 — 복사 · 저장 · 스터디로 보내기 · 다시 답변 */}
      <div className="-ml-2 flex flex-wrap items-center gap-0.5" data-answer-actions>
        <Button variant="ghost" size="sm" className="max-md:h-10" onClick={() => copy(m.content)}>
          {copied ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}{copied ? "복사됨" : "복사"}
        </Button>
        {conversationId && <SaveButton kind="chat" refId={String(m.id)} url={`/chat?id=${conversationId}`} title={threadTitle || "AI 답변"} subtitle={firstLine} showLabel className="max-md:h-10" />}
        {threadTitle && <SendToStudy m={m} threadTitle={threadTitle} />}
        {onRegenerate && <Button variant="ghost" size="sm" className="max-md:h-10" onClick={onRegenerate}><RotateCcw className="size-3.5" aria-hidden />다시 답변</Button>}
      </div>

      {m.gaps && m.gaps.length > 0 && <AnswerBox phone={phone} title={phone ? `이 답에서 확인하지 못한 것 ${formatNumber(m.gaps.length)}` : "이 답에서 확인하지 못한 것"}><GapList gaps={m.gaps} /></AnswerBox>}

      {m.citations && m.citations.length > 0 && <AnswerBox phone={phone} title={`출처 ${formatNumber(m.citations.length)}${phone ? "건" : ""}`}><SourceList citations={m.citations} answeredAt={m.created_at} /></AnswerBox>}

      {onPick && (followUps.length > 0 || leftover.length > 0) && <FollowUps items={followUps} carried={leftover} onPick={onPick} />}
    </article>
  )
}

/** 생성 중 — 같은 골격에서 근거 수집 자리에 라이브 status, 본문은 초안+캐럿 또는 스켈레톤 (D-130) */
export function StreamingMessage({ draft }: { draft: Draft | null }) {
  return (
    <article className="space-y-2" aria-live="polite" aria-atomic="false">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Badge variant="secondary" className={cn(AI_BADGE, "animate-pulse")}>AI 답변</Badge>
        <Spinner className="size-3.5" />
        <span>{draft?.status || "질문 분석 중…"}</span>
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
