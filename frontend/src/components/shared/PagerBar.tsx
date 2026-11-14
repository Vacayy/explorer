import type { MouseEvent } from "react"
import { ChevronLeft, ChevronRight } from "lucide-react"
import { Pagination, PaginationContent, PaginationEllipsis, PaginationItem, PaginationLink } from "@/components/ui/pagination"
import { cn } from "@/lib/utils"
import { formatNumber } from "@/utils/format"

/** 페이지 나눔 — 지금 페이지 행과 바닥 줄에 넘길 값 */
export function paged<T>(rows: T[], page: number, per: number) {
  const pages = Math.max(1, Math.ceil(rows.length / per))
  const p = Math.min(Math.max(0, page), pages - 1)
  return { rows: rows.slice(p * per, p * per + per), page: p, pages, from: rows.length ? p * per + 1 : 0, to: Math.min(rows.length, p * per + per), total: rows.length }
}

/** 보일 페이지 번호 — 7개 이하는 모두, 넘으면 처음·끝·지금 주변만(사이는 …) */
function numbers(page: number, pages: number): (number | null)[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i)
  const keep = new Set([0, pages - 1, page - 1, page, page + 1].filter(i => i >= 0 && i < pages))
  const out: (number | null)[] = []
  ;[...keep].sort((a, b) => a - b).forEach((i, k, arr) => { if (k && i - arr[k - 1] > 1) out.push(null); out.push(i) })
  return out
}

const BTN = "size-7 min-w-7 rounded-lg font-mono text-xs font-medium text-ink-2"

/**
 * 고정 높이 칸 바닥의 페이지 줄(시안 Home-KR·US) — 왼쪽 'n–m / 전체', 오른쪽 ‹ 번호 ›. 공식 ui/pagination 위 조합.
 * 번호를 눌러도 칸 높이는 그대로(목록은 칸 안 스크롤 영역).
 */
export function PagerBar({ page, pages, from, to, total, onPage, label = "페이지", className }: ReturnType<typeof paged> & {
  onPage: (page: number) => void; label?: string; className?: string
}) {
  const go = (p: number) => (e: MouseEvent) => { e.preventDefault(); if (p >= 0 && p < pages && p !== page) onPage(p) }
  return <div data-pager className={cn("flex shrink-0 items-center justify-between gap-2 border-t pt-2", className)}>
    <span className="font-mono text-[11.5px] text-ink-3 tabular-nums">{from}–{to} / {formatNumber(total)}</span>
    {pages > 1 && <Pagination aria-label={label} className="mx-0 w-auto justify-end">
      <PaginationContent className="gap-0.5">
        <PaginationItem><PaginationLink href="#" aria-label="이전 페이지" aria-disabled={page === 0} className={cn(BTN, page === 0 && "pointer-events-none opacity-40")} onClick={go(page - 1)}><ChevronLeft className="size-3.5" /></PaginationLink></PaginationItem>
        {numbers(page, pages).map((i, k) => <PaginationItem key={i ?? `gap-${k}`}>
          {i == null ? <PaginationEllipsis className="size-7" />
            : <PaginationLink href="#" isActive={i === page} aria-label={`${i + 1}페이지`} onClick={go(i)}
              className={cn(BTN, i === page && "border-0 bg-action text-action-ink hover:bg-action hover:text-action-ink")}>{i + 1}</PaginationLink>}
        </PaginationItem>)}
        <PaginationItem><PaginationLink href="#" aria-label="다음 페이지" aria-disabled={page >= pages - 1} className={cn(BTN, page >= pages - 1 && "pointer-events-none opacity-40")} onClick={go(page + 1)}><ChevronRight className="size-3.5" /></PaginationLink></PaginationItem>
      </PaginationContent>
    </Pagination>}
  </div>
}
