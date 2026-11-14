import type { ReactNode } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Link, useLocation } from "react-router-dom"
import { Info } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { BoundedArea, type BoundSize } from "@/components/shared/Bounded"
import { ErrorBoundary } from "@/components/shared/ErrorBoundary"
import { WIDGET_BY_ID } from "@/components/widgets/registry"
import { cn } from "@/lib/utils"

interface HomeSectionProps {
  /** 위젯 레지스트리 id — 본문·기준 시각·전체 보기 경로를 그대로 빌려 쓴다 */
  widget: string
  params?: Record<string, unknown>
  /** 본문 밀도(위젯 격자 칸) — 클수록 자세히 */
  w?: number
  h?: number
  title?: string
  /** 머리 오른쪽 링크. 생략하면 위젯의 전체 보기 경로, null이면 없음 */
  link?: { to: string; label: string } | null
  /** 띠형 — 머리 없이 본문만 */
  flat?: boolean
  /** 기상도 아래 큰 칸(Market Overnight·Today) — Geist 24 제목 · 유리 알약 링크 · 안쪽 여백 22 (시안 Home) */
  display?: boolean
  /** 시장 탭 블록(시안 Home-KR·US) — 머리 구분선 없이 15/600 제목 · 안쪽 여백 16 */
  section?: boolean
  /** 본문 높이 상한(눈금, shared/Bounded) — 넘치면 본문 안에서 스크롤. 머리는 고정 */
  bounded?: BoundSize
  className?: string
  bodyClassName?: string
}

/** 본문을 상한 안 스크롤 영역으로 — bounded가 없으면 그대로 */
const boundBody = (body: ReactNode, bounded?: BoundSize) => bounded ? <BoundedArea size={bounded}>{body}</BoundedArea> : body

/**
 * 홈 고정 화면의 섹션 (docs/specs/home-widgets.md §0) — 위젯 본문을 위젯 틀(손잡이·빼기 메뉴) 없이 그대로 쓴다.
 * 본문만 오류 경계로 감싸 한 블록이 깨져도 머리와 다른 블록은 남는다(블록 단위 실패, 상태 시트 §4.28).
 */
export function HomeSection({ widget, params, w = 12, h = 6, title, link, flat, display, section, bounded, className, bodyClassName }: HomeSectionProps) {
  const def = WIDGET_BY_ID[widget]
  const client = useQueryClient()
  if (!def) return null
  const body = (
    <ErrorBoundary onReset={() => { void client.refetchQueries({ type: "active", predicate: q => q.state.status === "error" }) }}>
      <def.Body w={w} h={h} params={params} />
    </ErrorBoundary>
  )
  return (
    <Card data-home-section={widget} className={cn("flex min-h-0 min-w-0 flex-col gap-0 overflow-hidden rounded-[var(--radius-card)] py-0 shadow-none", display && "gap-3.5 p-[22px] max-sm:p-4", section && SECTION_CARD, className)}>
      {flat ? <div className={cn("min-h-0 flex-1 px-1 py-2", bodyClassName)}>{body}</div> : <>
        <SectionHead widget={widget} params={params} title={title} link={link} display={display} section={section} />
        <div className={cn("min-h-0 flex-1", !display && !section && "p-3", bodyClassName)}>{boundBody(body, bounded)}</div>
      </>}
    </Card>
  )
}

const SECTION_CARD = "gap-3 p-4"

function SectionHead({ widget, params, title, link, display, section }: Pick<HomeSectionProps, "widget" | "params" | "title" | "link" | "display" | "section">) {
  const def = WIDGET_BY_ID[widget]
  const meta = def.useMeta(params)
  const target = link === undefined ? def.detailPath : link?.to
  return <BlockHead title={title ?? def.title} info={def.description} asOf={meta.asOf} stale={meta.stale} sub={meta.sub}
    link={target ? { to: target, label: link?.label ?? "전체 보기" } : null} display={display} section={section} />
}

interface BlockHeadProps {
  title: ReactNode
  /** 제목 옆 ⓘ 툴팁 — 화면에 부연설명을 쓰지 않고 여기에만 둔다 */
  info?: ReactNode
  /** 제목 아래 회색 한 줄(큰 칸 머리) */
  sub?: ReactNode
  asOf?: string | null
  stale?: boolean
  link?: { to: string; label: string } | null
  /** 머리 오른쪽 끝(링크 앞)에 두는 동작 — 갱신 버튼 등 */
  actions?: ReactNode
  /** 큰 칸 머리 — Geist 24 제목 · 유리 알약 링크 (HomeSection display) */
  display?: boolean
  /** 시장 탭 블록 머리 — 구분선 없음 · 15/600 · 링크 13 (HomeSection section) */
  section?: boolean
}

/** 홈 블록 머리 — 제목 · ⓘ · 기준 시각 · 동작 · 링크. 지금 화면으로 가는 링크는 숨긴다 */
export function BlockHead({ title, info, sub, asOf, stale, link, actions, display, section }: BlockHeadProps) {
  const { pathname } = useLocation()
  const to = link && link.to.split("#")[0] !== pathname ? link.to : undefined
  const name = typeof title === "string" ? title : undefined
  const heading = <h2 className={cn("min-w-0 truncate", display ? "font-display text-2xl leading-tight font-normal tracking-[-0.02em]" : section ? "text-[15px] leading-[1.4] font-semibold" : "text-[13.5px] font-semibold")}>{title}</h2>
  const tip = info && <Tooltip>
    <TooltipTrigger asChild>
      <Button variant="ghost" size="icon-xs" aria-label={`${name ?? "블록"} 설명`} className="shrink-0 text-muted-foreground/70"><Info className="size-3.5" /></Button>
    </TooltipTrigger>
    <TooltipContent className="max-w-[280px] text-xs leading-relaxed">{info}</TooltipContent>
  </Tooltip>
  return (
    <header className={cn("flex shrink-0 items-center gap-2", display ? "min-h-[38px] flex-wrap items-end gap-x-2.5 border-b pb-3" : section ? "min-h-7 flex-wrap gap-x-2.5" : "min-h-[38px] border-b px-3 py-1.5")}>
      {sub && !display ? <>{heading}{tip}<span className="shrink-0 pt-px text-xs text-ink-3">{sub}</span></>
      // 큰 칸 머리는 회색 줄 자리를 늘 둔다 — 불러오는 중·빈 상태에도 머리 높이가 같게(높이 상한과 넘침)
      : display ? <div className="flex min-w-0 flex-col gap-0.5">
        <div className="flex min-w-0 items-center gap-2">{heading}{tip}</div>
        <span className="truncate text-[12.5px] text-ink-2">{sub ?? "\u00a0"}</span>
      </div> : <>{heading}{tip}</>}
      <span className="ml-auto" />
      {asOf && <span className={cn("inline-flex shrink-0 items-center whitespace-nowrap max-sm:hidden", display ? "gap-1.5 self-center text-xs" : "gap-[5px] text-[11.5px]", stale ? "text-warn" : "text-ink-3")}>
        <span aria-hidden className={cn("rounded-full", display ? "size-1.5" : "size-[5px]", stale ? "bg-warn" : "bg-fact")} />{asOf}
      </span>}
      {actions}
      {to && (display
        ? <Link to={to} className="glass inline-flex h-7 shrink-0 items-center gap-1 self-center rounded-full px-3 text-[12.5px] font-medium whitespace-nowrap text-ink">{link!.label} ›</Link>
        : <Link to={to} className={cn("shrink-0 whitespace-nowrap text-ink-2 hover:text-ink", section ? "text-[13px]" : "text-xs")}>{link!.label} ›</Link>)}
    </header>
  )
}

/** 홈 고정 화면의 직접 만든 블록 — HomeSection과 같은 틀(머리 + 본문 오류 경계)을 위젯 레지스트리 없이 쓴다 */
export function HomeBlock({ children, className, bodyClassName, label, bounded, ...head }: BlockHeadProps & { children: ReactNode; className?: string; bodyClassName?: string; label?: string; bounded?: BoundSize }) {
  const client = useQueryClient()
  return (
    <Card data-home-section={label} className={cn("flex min-h-0 min-w-0 flex-col gap-0 overflow-hidden rounded-[var(--radius-card)] py-0 shadow-none", head.section && SECTION_CARD, className)}>
      <BlockHead {...head} />
      <div className={cn("min-h-0 flex-1", !head.section && "p-3", bodyClassName)}>
        {boundBody(<ErrorBoundary onReset={() => { void client.refetchQueries({ type: "active", predicate: q => q.state.status === "error" }) }}>{children}</ErrorBoundary>, bounded)}
      </div>
    </Card>
  )
}
