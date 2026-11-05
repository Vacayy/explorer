import { Link } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { HomeBlock } from "@/components/home/HomeSection"
import { BlockError, RowsSkeleton, tone } from "@/components/home/blockState"
import { localToday } from "@/lib/seasonPhase"
import { useTradeHighlights } from "@/hooks/useTrade"
import { cn } from "@/lib/utils"
import { formatNumber, formatPercent, formatRatio, formatUsd } from "@/utils/format"
import type { TradeHighlights } from "@/types"

/** 통계월이 지난달보다 오래됐나 — 관세청 품목별 통계는 매월 중순에 나와서, 그 전에는 지지난달 값을 보인다(§4.28 부분) */
export function tradeIsLagging(period: string | null, today: string = localToday()): boolean {
  if (!period) return false
  const y = +today.slice(0, 4), m = +today.slice(5, 7)
  const prev = m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, "0")}`
  return period < prev
}

const pct = (v: number | null | undefined) => formatPercent(v == null ? null : v * 100)

/**
 * 홈 › 한국 시장 — 수출입 (시안 Home-KR, ia-redesign §4.2). 원천 /api/spine/trade/highlights(D-140, 서버 판정).
 * 수출 총액 · 기여 1위 → 산업별 수출 규모 상위 8 | 평소보다 크게 늘어난 품목 8(수출액·전년 대비·전월 대비·증가분 기여).
 */
export function TradeBlock() {
  const q = useTradeHighlights(100)   // 급등 수를 세려고 넉넉히(산업 › 수출입과 같은 캐시) — 표는 상위 8만
  const d = q.data
  return (
    <HomeBlock label="kr.trade" title="수출입" link={{ to: "/follow/trade", label: "산업 › 수출입" }}
      info="관세청 품목별 수출 통계입니다. '평소보다 크게 늘어난 품목'은 품목별 과거 변동 폭에 비해 전년 대비 증가가 이례적인 것을 증가분 기여 순으로 고릅니다."
      asOf={d?.period ?? null}>
      {!d ? (q.isError ? <BlockError message="수출입 통계를 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} /> : <RowsSkeleton rows={6} />)
        : !d.period ? <p role="status" className="text-sm text-muted-foreground">수출입 통계가 아직 없습니다. 매일 09:20에 새 통계월을 확인합니다.</p>
        : <Body d={d} />}
    </HomeBlock>
  )
}

function Body({ d }: { d: TradeHighlights }) {
  const top = d.surge[0]
  const groups = d.groups.slice(0, 8)
  const maxGroup = Math.max(...groups.map(g => g.value), 1)
  const month = d.period ? `${+d.period.slice(5, 7)}월` : ""
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-x-8 gap-y-3">
        <div>
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">수출 총액 · {month}
            {tradeIsLagging(d.period) && <Badge variant="outline" className="h-4 border-chart-warning/50 px-1 text-[10px] font-normal text-chart-warning">{month} 기준</Badge>}
          </p>
          <p className="font-mono text-2xl font-semibold tabular-nums">{formatUsd(d.total_usd)}</p>
        </div>
        {top && <div className="min-w-0">
          <p className="text-xs text-muted-foreground">기여 1위</p>
          <p className="text-sm font-semibold">
            <Link to={`/follow/trade?hs=${encodeURIComponent(top.hs_code)}`} className="hover:underline">{top.item_name}</Link>
            {' · '}전년 대비 <span className={tone(top.yoy)}>{pct(top.yoy)}</span>
            {top.contribution != null && <> · 증가분의 {formatRatio(top.contribution * 100)}</>}
          </p>
        </div>}
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <section aria-label="산업별 수출 규모" className="min-w-0">
          <h3 className="mb-2 text-xs font-semibold">산업별 수출 규모</h3>
          <ul className="space-y-1.5 text-xs">{groups.map(g => (
            <li key={g.group_label} className="grid grid-cols-[minmax(0,5.5rem)_minmax(0,1fr)_3.5rem_4.5rem] items-center gap-2">
              <span className="truncate">{g.group_label}</span>
              <span className="h-1.5 overflow-hidden bg-muted" aria-hidden="true"><span className="block h-full bg-foreground/70" style={{ width: `${g.value / maxGroup * 100}%` }} /></span>
              <span className="text-right font-mono tabular-nums">{formatUsd(g.value)}</span>
              <span className="whitespace-nowrap text-right">{!g.surge && !g.plunge ? <span className="text-muted-foreground">-</span> : <>
                {!!g.surge && <span className="text-up">급등 {g.surge}</span>}{!!g.surge && !!g.plunge && " "}{!!g.plunge && <span className="text-down">급감 {g.plunge}</span>}
              </>}</span>
            </li>
          ))}</ul>
        </section>

        <section aria-label="평소보다 크게 늘어난 품목" className="min-w-0">
          <h3 className="mb-1 text-xs font-semibold">평소보다 크게 늘어난 품목 {formatNumber(d.surge.length)}</h3>
          {!d.surge.length ? <p className="text-sm text-muted-foreground">{month}에는 평소보다 크게 늘어난 품목이 없습니다.</p> :
          <div className="overflow-x-auto"><Table className="text-[13px]">
            <TableHeader><TableRow>
              <TableHead className="h-8 px-1 text-[11px]">품목</TableHead>
              <TableHead className="h-8 px-1 text-right text-[11px]">수출액</TableHead>
              <TableHead className="h-8 px-1 text-right text-[11px]">전년 대비</TableHead>
              <TableHead className="h-8 px-1 text-right text-[11px] max-sm:hidden">전월 대비</TableHead>
              <TableHead className="h-8 px-1 text-right text-[11px]">증가분 기여</TableHead>
            </TableRow></TableHeader>
            <TableBody>{d.surge.slice(0, 8).map(r => (
              <TableRow key={r.hs_code}>
                <TableCell className="max-w-48 px-1 py-1.5 whitespace-normal">
                  <Link to={`/follow/trade?hs=${encodeURIComponent(r.hs_code)}`} className="hover:underline">{r.item_name}</Link>
                  <span className="block text-[11px] text-muted-foreground">{r.group_label ?? "미분류"} · HS {r.hs_code}</span>
                </TableCell>
                <TableCell className="px-1 py-1.5 text-right font-mono tabular-nums">{r.value == null ? "-" : formatUsd(r.value)}</TableCell>
                <TableCell className={cn("px-1 py-1.5 text-right font-mono tabular-nums", tone(r.yoy))}>{pct(r.yoy)}</TableCell>
                <TableCell className={cn("px-1 py-1.5 text-right font-mono tabular-nums max-sm:hidden", tone(r.mom))}>{pct(r.mom)}</TableCell>
                <TableCell className="px-1 py-1.5">
                  <span className="flex items-center justify-end gap-2">
                    <span className="h-1.5 w-16 overflow-hidden bg-muted max-sm:hidden" aria-hidden="true"><span className="block h-full bg-up" style={{ width: `${Math.max(0, Math.min(1, r.contribution ?? 0)) * 100}%` }} /></span>
                    <span className="w-12 text-right tabular-nums">{formatRatio(r.contribution == null ? null : r.contribution * 100)}</span>
                  </span>
                </TableCell>
              </TableRow>
            ))}</TableBody>
          </Table></div>}
        </section>
      </div>
    </div>
  )
}
