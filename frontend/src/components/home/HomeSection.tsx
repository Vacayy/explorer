import type { ReactNode } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Link, useLocation } from "react-router-dom"
import { Info } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
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
  className?: string
  bodyClassName?: string
}

/**
 * 홈 고정 화면의 섹션 (docs/specs/home-widgets.md §0) — 위젯 본문을 위젯 틀(손잡이·빼기 메뉴) 없이 그대로 쓴다.
 * 본문만 오류 경계로 감싸 한 블록이 깨져도 머리와 다른 블록은 남는다(블록 단위 실패, 상태 시트 §4.28).
 */
export function HomeSection({ widget, params, w = 12, h = 6, title, link, flat, className, bodyClassName }: HomeSectionProps) {
  const def = WIDGET_BY_ID[widget]
  const client = useQueryClient()
  if (!def) return null
  const body = (
    <ErrorBoundary onReset={() => { void client.refetchQueries({ type: "active", predicate: q => q.state.status === "error" }) }}>
      <def.Body w={w} h={h} params={params} />
    </ErrorBoundary>
  )
  return (
    <Card data-home-section={widget} className={cn("flex min-h-0 min-w-0 flex-col gap-0 overflow-hidden rounded-[var(--radius-card)] py-0 shadow-none", className)}>
      {flat ? <div className={cn("min-h-0 flex-1 px-1 py-2", bodyClassName)}>{body}</div> : <>
        <SectionHead widget={widget} params={params} title={title} link={link} />
        <div className={cn("min-h-0 flex-1 p-3", bodyClassName)}>{body}</div>
      </>}
    </Card>
  )
}

function SectionHead({ widget, params, title, link }: Pick<HomeSectionProps, "widget" | "params" | "title" | "link">) {
  const def = WIDGET_BY_ID[widget]
  const meta = def.useMeta(params)
  const target = link === undefined ? def.detailPath : link?.to
  return <BlockHead title={title ?? def.title} info={def.description} asOf={meta.asOf} stale={meta.stale}
    link={target ? { to: target, label: link?.label ?? "전체 보기" } : null} />
}

interface BlockHeadProps {
  title: ReactNode
  /** 제목 옆 ⓘ 툴팁 — 화면에 부연설명을 쓰지 않고 여기에만 둔다 */
  info?: ReactNode
  asOf?: string | null
  stale?: boolean
  link?: { to: string; label: string } | null
  /** 머리 오른쪽 끝(링크 앞)에 두는 동작 — 갱신 버튼 등 */
  actions?: ReactNode
}

/** 홈 블록 머리 — 제목 · ⓘ · 기준 시각 · 동작 · 링크. 지금 화면으로 가는 링크는 숨긴다 */
export function BlockHead({ title, info, asOf, stale, link, actions }: BlockHeadProps) {
  const { pathname } = useLocation()
  const to = link && link.to.split("#")[0] !== pathname ? link.to : undefined
  const name = typeof title === "string" ? title : undefined
  return (
    <header className="flex min-h-[38px] shrink-0 items-center gap-2 border-b px-3 py-1.5">
      <h2 className="min-w-0 truncate text-[13.5px] font-semibold">{title}</h2>
      {info && <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="icon-xs" aria-label={`${name ?? "블록"} 설명`} className="shrink-0 text-muted-foreground/70"><Info className="size-3.5" /></Button>
        </TooltipTrigger>
        <TooltipContent className="max-w-[280px] text-xs leading-relaxed">{info}</TooltipContent>
      </Tooltip>}
      <span className="ml-auto" />
      {asOf && <span className={cn("inline-flex shrink-0 items-center gap-[5px] text-[11.5px] whitespace-nowrap max-sm:hidden", stale ? "text-warn" : "text-ink-3")}>
        <span aria-hidden className={cn("size-[5px] rounded-full", stale ? "bg-warn" : "bg-fact")} />{asOf}
      </span>}
      {actions}
      {to && <Link to={to} className="shrink-0 text-xs whitespace-nowrap text-ink-2 hover:text-ink">{link!.label} ›</Link>}
    </header>
  )
}

/** 홈 고정 화면의 직접 만든 블록 — HomeSection과 같은 틀(머리 + 본문 오류 경계)을 위젯 레지스트리 없이 쓴다 */
export function HomeBlock({ children, className, bodyClassName, label, ...head }: BlockHeadProps & { children: ReactNode; className?: string; bodyClassName?: string; label?: string }) {
  const client = useQueryClient()
  return (
    <Card data-home-section={label} className={cn("flex min-h-0 min-w-0 flex-col gap-0 overflow-hidden rounded-[var(--radius-card)] py-0 shadow-none", className)}>
      <BlockHead {...head} />
      <div className={cn("min-h-0 flex-1 p-3", bodyClassName)}>
        <ErrorBoundary onReset={() => { void client.refetchQueries({ type: "active", predicate: q => q.state.status === "error" }) }}>{children}</ErrorBoundary>
      </div>
    </Card>
  )
}
