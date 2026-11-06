import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { X } from "lucide-react"
import { Bar, Cell, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { Button } from "@/components/ui/button"
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { Pagination, PaginationContent, PaginationEllipsis, PaginationItem, PaginationLink } from "@/components/ui/pagination"
import { Skeleton } from "@/components/ui/skeleton"
import { tone } from "@/components/home/blockState"
import { cn } from "@/lib/utils"
import { formatPercent } from "@/utils/format"

/**
 * 산업 › 수출입 · 대만 공급망 모니터링형 카드 벽(D-325, 시안 Industry-Trade · Industry-TW).
 * 칸 168px · 데스크톱 6열 × 4행(24개씩) · 태블릿 4열 · 폰 2열 × 6행(12개씩). 카드를 누르면 가운데 대화상자(MonitorDialog).
 */

export const CARD_H = 168
/** 쪽당 카드 수 — 폰(<768)은 12, 그 위는 24 */
export const wallPageSize = (mobile: boolean) => (mobile ? 12 : 24)
/** 벽 높이 — 마지막 쪽이 덜 차도 아래 쪽 넘김이 움직이지 않게 행 수만큼 자리를 둔다(폰·태블릿 6행, 넓은 화면 4행) */
const WALL_GRID = "grid grid-cols-2 content-start pr-px pb-px md:grid-cols-4 xl:grid-cols-6 min-h-[1008px] xl:min-h-[672px]"

export interface MonitorCardData {
  key: string
  name: string
  group: string
  value: string
  yoy: number | null
  /** 급등 배지 + 마지막 막대 강조색 */
  surge: boolean
  badge?: string
  bars: (number | null)[]
  ma: (number | null)[]
}

/** 작은 차트 — 월별 막대(회색) · 마지막 달(급등이면 분홍, 아니면 글자색) · 12개월 평균 선. 칸마다 세로축이 다르다 */
export function MiniBars({ bars, ma, surge, label }: { bars: (number | null)[]; ma: (number | null)[]; surge: boolean; label: string }) {
  const W = 240, H = 64
  const max = Math.max(0, ...bars.map(v => v ?? 0)) || 1
  const step = W / Math.max(bars.length, 1)
  const y = (v: number) => H - Math.max(1, (v / max) * (H - 4))
  const line = ma.map((v, i) => v == null ? null : `${(i * step + step / 2).toFixed(1)},${(H - (v / max) * (H - 4)).toFixed(1)}`).filter(Boolean).join(" ")
  return <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={label} className="mt-auto block !h-[72px] !w-full">
    {bars.map((v, i) => v == null ? null : <rect key={i} x={i * step + 0.8} y={y(v)} width={Math.max(0.6, step - 1.6)} height={H - y(v)}
      fill={i === bars.length - 1 ? (surge ? "var(--up)" : "var(--ink)") : "var(--series)"} />)}
    {line && <polyline points={line} fill="none" stroke="var(--ink-2)" strokeWidth={1.2} vectorEffect="non-scaling-stroke" />}
  </svg>
}

export function MonitorCard({ d, onOpen }: { d: MonitorCardData; onOpen: (key: string) => void }) {
  return <Button variant="ghost" onClick={() => onOpen(d.key)} aria-label={`${d.name} 상세 열기`} data-monitor-card
    className="-mr-px -mb-px flex h-[168px] min-w-0 flex-col items-stretch justify-start gap-1 rounded-none border border-line bg-card px-3 pt-3 pb-2.5 text-left font-normal whitespace-normal hover:bg-surface-2">
    <span className="flex min-w-0 items-baseline gap-1.5">
      <span className="min-w-0 truncate text-[13px] font-semibold">{d.name}</span>
      {d.surge && <span className="inline-flex h-[18px] shrink-0 items-center rounded-[6px] bg-up-tint px-1.5 text-[11px] text-up-ink">급등</span>}
      {d.badge && <span className="inline-flex h-[18px] shrink-0 items-center rounded-[6px] bg-chip px-1.5 text-[11px] text-ink-2">{d.badge}</span>}
      <span className="ml-auto shrink-0 truncate text-[11px] text-ink-3 max-sm:hidden">{d.group}</span>
    </span>
    <span className="flex min-w-0 items-baseline gap-2">
      <span className="truncate font-display text-lg tabular-nums">{d.value}</span>
      <span className={cn("shrink-0 font-mono text-xs tabular-nums", tone(d.yoy))}>{formatPercent(d.yoy)}</span>
    </span>
    <MiniBars bars={d.bars} ma={d.ma} surge={d.surge} label={`${d.name} 월별 추이`} />
  </Button>
}

/** 카드 벽 — 불러오는 중에는 같은 높이 뼈대 */
export function MonitorWall({ cards, loading, onOpen, empty }: { cards: MonitorCardData[]; loading?: boolean; onOpen: (key: string) => void; empty?: ReactNode }) {
  if (loading) return <div role="status" aria-label="카드 불러오는 중" className={WALL_GRID}>
    {Array.from({ length: 24 }, (_, i) => <div key={i} className={cn("-mr-px -mb-px flex h-[168px] flex-col gap-2 border bg-card p-3", i >= 12 && "max-md:hidden")}>
      <Skeleton className="h-3.5 w-2/3" /><Skeleton className="h-5 w-1/2" /><Skeleton className="mt-auto h-[64px] w-full" />
    </div>)}
  </div>
  if (!cards.length) return <div className={cn(WALL_GRID, "place-items-center")}><div className="col-span-full self-center text-sm text-ink-2">{empty}</div></div>
  return <div className={WALL_GRID}>{cards.map(c => <MonitorCard key={c.key} d={c} onOpen={onOpen} />)}</div>
}

/** 쪽 번호 — 1 … 이웃 … 끝 */
function pageNumbers(page: number, pages: number): (number | "gap")[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1)
  const out: (number | "gap")[] = [1]
  const lo = Math.max(2, page - 1), hi = Math.min(pages - 1, page + 1)
  if (lo > 2) out.push("gap")
  for (let p = lo; p <= hi; p++) out.push(p)
  if (hi < pages - 1) out.push("gap")
  out.push(pages)
  return out
}

/** 벽 아래 쪽 넘김 — 왼쪽 범위('1-24 / 142'), 오른쪽 공식 shadcn Pagination. 쪽은 URL이 들고 있다 */
export function WallPager({ from, to, total, page, pages, hrefOf, onPage }: { from: number; to: number; total: number; page: number; pages: number; hrefOf: (p: number) => string; onPage: (p: number) => void }) {
  const go = (p: number) => (e: React.MouseEvent) => { e.preventDefault(); if (p >= 1 && p <= pages && p !== page) onPage(p) }
  const cell = "size-7 rounded-lg text-[12.5px] font-medium text-ink-2 data-[active=true]:border-action data-[active=true]:bg-action data-[active=true]:text-action-ink"
  return <div className="flex items-center justify-between gap-2 border-t pt-2">
    <span className="font-mono text-[11.5px] text-ink-3 tabular-nums">{from}-{to} / {total}</span>
    <Pagination aria-label="쪽" className="mx-0 w-auto justify-end">
      <PaginationContent className="gap-0.5">
        <PaginationItem><PaginationLink href={hrefOf(page - 1)} onClick={go(page - 1)} aria-label="이전 쪽" aria-disabled={page <= 1} className={cn(cell, page <= 1 && "pointer-events-none opacity-40")}>‹</PaginationLink></PaginationItem>
        {pageNumbers(page, pages).map((p, i) => p === "gap"
          ? <PaginationItem key={`gap${i}`}><PaginationEllipsis className="size-7" /></PaginationItem>
          : <PaginationItem key={p}><PaginationLink href={hrefOf(p)} onClick={go(p)} isActive={p === page} aria-label={`${p}쪽`} className={cell}>{p}</PaginationLink></PaginationItem>)}
        <PaginationItem><PaginationLink href={hrefOf(page + 1)} onClick={go(page + 1)} aria-label="다음 쪽" aria-disabled={page >= pages} className={cn(cell, page >= pages && "pointer-events-none opacity-40")}>›</PaginationLink></PaginationItem>
      </PaginationContent>
    </Pagination>
  </div>
}

/** 벽 칸(머리 · 도구줄 · 벽 · 쪽 넘김)을 담는 틀 — 시안 section: 16/18 여백, 칸 사이 12 */
export function MonitorSection({ children, className, label }: { children: ReactNode; className?: string; label: string }) {
  return <section data-home-section={label} className={cn("-mt-px flex min-w-0 flex-col gap-3 border bg-card px-[18px] py-4 max-sm:px-3", className)}>{children}</section>
}

export interface Stat { label: string; value: string; tone?: number | null }

/** 대화상자·상세 페이지 통계 4칸 */
export function StatGrid({ stats, large }: { stats: Stat[]; large?: boolean }) {
  return <div className="grid grid-cols-2 pr-px pb-px sm:grid-cols-4">
    {stats.map(s => <div key={s.label} className={cn("-mr-px -mb-px flex min-w-0 flex-col gap-0.5 border", large ? "px-4 py-3" : "px-3 py-2.5")}>
      <span className="truncate text-[11.5px] text-ink-3">{s.label}</span>
      <span className={cn("truncate font-mono tabular-nums", large ? "text-lg" : "text-[15px]", s.tone === undefined ? "text-ink" : tone(s.tone))}>{s.value}</span>
    </div>)}
  </div>
}

/** 눈금 'YY.MM' — 막대 왼쪽에 붙여 왼쪽 정렬(첫 눈금이 잘리지 않게) */
function MonthTick({ x, y, payload }: { x?: number | string; y?: number | string; payload?: { value: string } }) {
  return <text x={Math.max(0, Number(x) - 6)} y={Number(y) + 10} textAnchor="start" fontSize={10.5} fill="var(--ink-3)" fontFamily="var(--font-mono)">{payload?.value.slice(2).replace("-", ".")}</text>
}

export interface BigPoint { period: string; v: number | null; yoy: number | null }

/** 큰 차트 — 월별 막대(마지막 달 글자색) + 전년 대비 선(보라, 0선 점선). 세로축 숫자는 감춘다 — 값은 머리·툴팁에서 */
export function BigChart({ data, height = 240, barLabel, fmt }: { data: BigPoint[]; height?: number; barLabel: string; fmt: (v: number) => string }) {
  return <div className="flex flex-col gap-2">
    <div className="flex gap-3.5 text-xs text-ink-3">
      <span className="inline-flex items-center gap-1"><span className="inline-block size-2.5 bg-series" />{barLabel}</span>
      <span className="inline-flex items-center gap-1"><span className="inline-block h-0.5 w-3.5 bg-hyp" />전년 대비(선)</span>
    </div>
    <div style={{ height }} role="img" aria-label={`${barLabel}과 전년 대비 추이`}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 0, bottom: 0, left: 0 }} barCategoryGap="12%">
          <XAxis dataKey="period" tickLine={false} axisLine={false} interval={11} tick={MonthTick} />
          <YAxis yAxisId="v" hide domain={[0, "dataMax"]} />
          <YAxis yAxisId="yoy" hide orientation="right" domain={["dataMin", "dataMax"]} />
          <Tooltip cursor={{ fill: "var(--chip)" }} contentStyle={{ fontSize: 12, background: "var(--bg)", border: "1px solid var(--line-2)", borderRadius: 8 }}
            formatter={(v, name) => [name === "yoy" ? formatPercent(Number(v)) : fmt(Number(v)), name === "yoy" ? "전년 대비" : barLabel]} />
          <Bar yAxisId="v" dataKey="v" isAnimationActive={false}>
            {data.map((_, i) => <Cell key={i} fill={i === data.length - 1 ? "var(--ink)" : "var(--series)"} />)}
          </Bar>
          <ReferenceLine yAxisId="yoy" y={0} stroke="var(--hyp)" strokeDasharray="3 4" strokeOpacity={0.6} />
          <Line yAxisId="yoy" dataKey="yoy" stroke="var(--hyp)" strokeWidth={1.6} dot={false} connectNulls isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  </div>
}

/** 가운데 상세 대화상자(오른쪽 drawer 대신, D-325) — 폰은 화면 높이 전체. 머리: 분류 · 이름 · 값 · 전년 대비 · '상세 페이지 ›' · 닫기 */
export function MonitorDialog({ open, onClose, sub, name, value, yoy, detailTo, children }: {
  open: boolean; onClose: () => void; sub: string; name: string; value: string; yoy: number | null; detailTo: string; children: ReactNode
}) {
  return <Dialog open={open} onOpenChange={v => { if (!v) onClose() }}>
    <DialogContent showCloseButton={false}
      className="flex max-h-[min(680px,calc(100dvh-2rem))] flex-col gap-0 overflow-hidden p-0 sm:max-w-[920px] max-sm:top-0 max-sm:left-0 max-sm:h-[100dvh] max-sm:max-h-none max-sm:max-w-none max-sm:translate-x-0 max-sm:translate-y-0 max-sm:rounded-none">
      <header className="flex shrink-0 items-start gap-3 border-b px-5 pt-[18px] pb-3 max-sm:px-4 max-sm:pt-[max(14px,env(safe-area-inset-top))]">
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="truncate text-xs text-ink-3">{sub}</span>
          <DialogTitle className="truncate text-xl font-semibold">{name}</DialogTitle>
          <DialogDescription asChild>
            <div className="flex flex-wrap items-baseline gap-x-2.5 text-ink">
              <span className="font-display text-[28px] leading-tight tabular-nums max-sm:text-2xl">{value}</span>
              <span className={cn("font-mono text-sm tabular-nums", tone(yoy))}>전년 대비 {formatPercent(yoy)}</span>
            </div>
          </DialogDescription>
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-1.5">
          <Button asChild variant="outline" size="sm" className="h-8 rounded-full px-3 text-[13px] max-sm:hidden"><Link to={detailTo}>상세 페이지 ›</Link></Button>
          <DialogClose asChild><Button variant="secondary" size="icon-sm" aria-label="닫기"><X /></Button></DialogClose>
        </div>
      </header>
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto overscroll-contain px-5 pt-4 pb-5 max-sm:px-4">
        {children}
        <Button asChild variant="outline" size="sm" className="h-9 rounded-full sm:hidden"><Link to={detailTo}>상세 페이지 ›</Link></Button>
      </div>
    </DialogContent>
  </Dialog>
}

/** 대화상자 아래 줄 — 관련 종목 · 역할 */
export function DialogRow({ label, children }: { label: string; children: ReactNode }) {
  return <div className="flex flex-col gap-1.5"><span className="text-xs text-ink-3">{label}</span><div className="text-[13.5px]">{children}</div></div>
}
