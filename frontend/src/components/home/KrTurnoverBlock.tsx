import { DetailLink as Link } from "@/components/shared/DetailNavigation"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { RefreshButton } from "@/components/shared/RefreshButton"
import { HomeBlock } from "@/components/home/HomeSection"
import { BlockError, RowsSkeleton, tone } from "@/components/home/blockState"
import { useKrMovers } from "@/hooks/useKrMovers"
import { cn } from "@/lib/utils"
import { formatKrw, formatPercent, formatRatio } from "@/utils/format"
import type { KrMovers } from "@/types"

/**
 * 홈 › 한국 시장 — 국장 거래대금 상위 (시안 Home-KR, ia-redesign §4.2). 원천 /api/spine/kr/movers(D-108, LLM 없음).
 * 한 줄 요약 → 섹터 쏠림 막대 → 상위 10 표(신규 진입·급등락 배지). 시안대로 '상위 20 전체'·'상위 5종목 관련 자료' 접힘 줄은 두지 않는다.
 */
export function KrTurnoverBlock({ className }: { className?: string }) {
  const q = useKrMovers()
  const d = q.data
  return (
    <HomeBlock section label="kr.turnover" title="국장 거래대금 상위" className={className}
      info="전일 거래대금 상위 20종목입니다. 비중은 시장 전체가 아니라 상위 20종목 합계 기준이고, 날짜는 저장 스냅샷 기준입니다. 평일 16:20에 받습니다."
      sub={d?.trade_date ? `${d.trade_date} 스냅샷 · 상위 ${d.items.length}` : null}
      asOf={d && d.status !== "ok" ? "갱신 실패" : null} stale={!!d && d.status !== "ok"}
      actions={<RefreshButton label="갱신" onClick={q.refresh} pending={q.refreshing} title="지금 업데이트 (전일 거래대금 재수집)" />}
>
      {!d ? (q.isError ? <BlockError message="국장 거래대금을 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} /> : <RowsSkeleton rows={8} />)
        : d.status === "error" ? <BlockError message={d.error ?? "국장 거래대금을 불러오지 못했습니다"} onRetry={() => void q.refetch()} />
        : !d.items.length ? <p role="status" className="text-sm text-muted-foreground">{q.refreshing ? "전일 거래대금을 불러오는 중입니다." : "전일 거래대금 스냅샷이 아직 없습니다. 평일 16:20에 받습니다."}</p>
        : <Body d={d} />}
    </HomeBlock>
  )
}

function Body({ d }: { d: KrMovers }) {
  const top = d.clusters[0]
  const fresh = d.clusters.find(c => c.has_new && c !== top)
  return (
    <div className="space-y-3">
      {d.status === "stale" && <p className="text-xs text-chart-warning">갱신에 실패해 마지막으로 받은 값을 보여 드립니다.</p>}
      {top && <p className="text-sm leading-relaxed">
        상위 {d.items.length}종목 거래대금 중 {top.label}에 {formatRatio(top.share_pct)}가 몰렸고 대표 등락은 {formatPercent(top.median_change)}였습니다.
        {fresh && <> {fresh.label}({formatPercent(fresh.median_change)})이 새로 들어왔습니다.</>}
      </p>}

      <ul aria-label="섹터 쏠림" className="space-y-2.5 text-[13px]">
        {d.clusters.slice(0, 5).map(c => (
          <li key={c.label} className="grid grid-cols-[minmax(0,8.5rem)_minmax(0,1fr)_3.5rem_3.5rem] items-center gap-2.5">
            <span className="flex min-w-0 items-center gap-1">
              <Link to={`/map?group=${encodeURIComponent(c.label)}`} className="truncate hover:underline" title={c.names.join(" · ")}>{c.label}</Link>
              {c.has_new && <Badge className="shrink-0">신규</Badge>}
            </span>
            <span className="h-1.5 overflow-hidden rounded-full bg-chip" aria-hidden="true"><span className="block h-full rounded-full bg-ink" style={{ width: `${Math.min(100, c.share_pct)}%` }} /></span>
            <span className="text-right font-mono text-xs tabular-nums">{formatRatio(c.share_pct)}</span>
            <span className={cn("text-right font-mono text-xs tabular-nums", tone(c.median_change))}>{formatPercent(c.median_change)}</span>
          </li>
        ))}
      </ul>

      <Table className="text-sm">
        <TableHeader><TableRow>
          <TableHead className="h-9 w-10 px-2.5 text-xs">#</TableHead><TableHead className="h-9 px-2.5 text-xs">종목</TableHead>
          <TableHead className="h-9 px-2.5 text-right text-xs">등락</TableHead><TableHead className="h-9 px-2.5 text-right text-xs">거래대금</TableHead>
        </TableRow></TableHeader>
        <TableBody>{d.items.slice(0, 10).map(m => (
          <TableRow key={m.stock_code}>
            <TableCell className="px-2.5 py-2 font-mono text-xs text-ink-3 tabular-nums">{m.rank}</TableCell>
            <TableCell className="px-2.5 py-2">
              <span className="flex min-w-0 flex-wrap items-center gap-1.5">
                <Link to={`/analyze/${m.stock_code}/summary`} className="truncate hover:underline">{m.name}</Link>
                {m.flags.map(f => <Badge key={f} variant={f.startsWith("급등") ? "up" : f.startsWith("급락") ? "down" : "neutral"}>{f}</Badge>)}
              </span>
            </TableCell>
            <TableCell className={cn("px-2.5 py-2 text-right font-mono tabular-nums", tone(m.change_pct))}>{formatPercent(m.change_pct)}</TableCell>
            <TableCell className="px-2.5 py-2 text-right font-mono tabular-nums">{formatKrw(m.value_traded)}</TableCell>
          </TableRow>
        ))}</TableBody>
      </Table>
    </div>
  )
}
