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
  const { pathname } = useLocation()
  const target = link === undefined ? (def.detailPathOf?.(params) ?? def.detailPath) : link?.to
  const to = target && target.split("#")[0] !== pathname ? target : undefined   // 지금 화면으로 가는 링크는 숨긴다
  const label = link?.label ?? "전체 보기"
  const name = title ?? def.titleOf?.(params) ?? def.title
  return (
    <header className="flex h-10 shrink-0 items-center gap-1.5 border-b px-3">
      <h2 className="min-w-0 truncate text-sm font-semibold">{name}</h2>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="icon-xs" aria-label={`${name} 설명`} className="shrink-0 text-muted-foreground/70"><Info className="size-3.5" /></Button>
        </TooltipTrigger>
        <TooltipContent className="max-w-[280px] text-xs leading-relaxed">{def.description}</TooltipContent>
      </Tooltip>
      {meta.asOf && <span className={cn("ml-auto shrink-0 font-mono text-[11px] tabular-nums max-sm:hidden", meta.stale ? "text-chart-warning" : "text-muted-foreground")}>{meta.asOf}</span>}
      {to && <Link to={to} className={cn("shrink-0 text-xs text-muted-foreground hover:text-foreground", !meta.asOf && "ml-auto", "max-sm:ml-auto")}>{label} ›</Link>}
    </header>
  )
}
