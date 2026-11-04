import { useState } from "react"
import { ChevronDown } from "lucide-react"
import { DetailLink as Link } from "@/components/shared/DetailNavigation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
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
 * 한 줄 요약 → 섹터 쏠림 막대 → 상위 20 표(신규 진입·급등락 배지). 상위 5종목 관련 자료는 접어 둔다.
 */
export function KrTurnoverBlock({ className }: { className?: string }) {
  const q = useKrMovers()
  const d = q.data
  return (
    <HomeBlock label="kr.turnover" title="국장 거래대금 상위" className={className}
      info="전일 거래대금 상위 20종목입니다. 비중은 시장 전체가 아니라 상위 20종목 합계 기준이고, 날짜는 저장 스냅샷 기준입니다. 평일 16:20에 받습니다."
      asOf={d?.trade_date ? `${d.trade_date} 스냅샷` : null} stale={!!d && d.status !== "ok"}
      actions={<RefreshButton onClick={q.refresh} pending={q.refreshing} title="지금 업데이트 (전일 거래대금 재수집)" />}
>
      {!d ? (q.isError ? <BlockError message="국장 거래대금을 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} /> : <RowsSkeleton rows={8} />)
        : d.status === "error" ? <BlockError message={d.error ?? "국장 거래대금을 불러오지 못했습니다"} onRetry={() => void q.refetch()} />
        : !d.items.length ? <p role="status" className="text-sm text-muted-foreground">{q.refreshing ? "전일 거래대금을 불러오는 중입니다." : "전일 거래대금 스냅샷이 아직 없습니다. 평일 16:20에 받습니다."}</p>
        : <Body d={d} />}
    </HomeBlock>
  )
}

function Body({ d }: { d: KrMovers }) {
  const [open, setOpen] = useState(false)
  const [all, setAll] = useState(false)
  const top = d.clusters[0]
  const fresh = d.clusters.find(c => c.has_new && c !== top)
  return (
    <div className="space-y-3">
      {d.status === "stale" && <p className="text-xs text-chart-warning">갱신에 실패해 마지막으로 받은 값을 보여 드립니다.</p>}
      {top && <p className="text-sm leading-relaxed">
        상위 {d.items.length}종목 거래대금 중 {top.label}에 {formatRatio(top.share_pct)}가 몰렸고 대표 등락은 {formatPercent(top.median_change)}였습니다.
        {fresh && <> {fresh.label}({formatPercent(fresh.median_change)})이 새로 들어왔습니다.</>}
      </p>}

      <ul aria-label="섹터 쏠림" className="space-y-1.5 text-xs">
        {d.clusters.slice(0, 5).map(c => (
          <li key={c.label} className="grid grid-cols-[minmax(0,8.5rem)_minmax(0,1fr)_3rem_3.5rem] items-center gap-2">
            <span className="flex min-w-0 items-center gap-1">
              <Link to={`/map?group=${encodeURIComponent(c.label)}`} className="truncate hover:underline" title={c.names.join(" · ")}>{c.label}</Link>
              {c.has_new && <Badge variant="secondary" className="h-4 shrink-0 px-1 text-[10px] font-normal">신규</Badge>}
            </span>
            <span className="h-1.5 overflow-hidden bg-muted" aria-hidden="true"><span className="block h-full bg-foreground/80" style={{ width: `${Math.min(100, c.share_pct)}%` }} /></span>
            <span className="text-right tabular-nums">{formatRatio(c.share_pct)}</span>
            <span className={cn("text-right font-mono tabular-nums", tone(c.median_change))}>{formatPercent(c.median_change)}</span>
          </li>
        ))}
      </ul>

      <Table className="text-[13px]">
        <TableHeader><TableRow>
          <TableHead className="h-8 w-8 px-1 text-[11px]">#</TableHead><TableHead className="h-8 px-1 text-[11px]">종목</TableHead>
          <TableHead className="h-8 px-1 text-right text-[11px]">등락</TableHead><TableHead className="h-8 px-1 text-right text-[11px]">거래대금</TableHead>
        </TableRow></TableHeader>
        <TableBody>{d.items.slice(0, all ? undefined : 10).map(m => (
          <TableRow key={m.stock_code}>
            <TableCell className="px-1 py-1.5 text-muted-foreground tabular-nums">{m.rank}</TableCell>
            <TableCell className="px-1 py-1.5">
              <span className="flex min-w-0 flex-wrap items-center gap-1">
                <Link to={`/analyze/${m.stock_code}/summary`} className="truncate font-medium hover:underline">{m.name}</Link>
                {m.flags.map(f => <Badge key={f} variant="secondary" className={cn("h-4 px-1 text-[10px] font-normal", f.startsWith("급등") && "text-up", f.startsWith("급락") && "text-down")}>{f}</Badge>)}
              </span>
            </TableCell>
            <TableCell className={cn("px-1 py-1.5 text-right font-mono tabular-nums", tone(m.change_pct))}>{formatPercent(m.change_pct)}</TableCell>
            <TableCell className="px-1 py-1.5 text-right tabular-nums">{formatKrw(m.value_traded)}</TableCell>
          </TableRow>
        ))}</TableBody>
      </Table>
      {d.items.length > 10 && <Button variant="ghost" size="sm" className="h-7 px-1 text-xs text-muted-foreground" onClick={() => setAll(v => !v)} aria-expanded={all}>
        <ChevronDown className={cn("size-3.5 transition-transform", all && "rotate-180")} />{all ? "상위 10만 보기" : `상위 ${d.items.length} 전체`}
      </Button>}

      {!!d.briefing?.length && <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} />상위 5종목 관련 자료
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-2 divide-y">
          {d.briefing.map(b => <div key={b.stock_code} className="py-2 first:pt-0">
            <p className="text-sm font-medium"><span className="mr-1.5 text-xs text-muted-foreground">{b.rank}</span>{b.name}</p>
            {b.documents.length ? b.documents.map((doc, i) => <div key={doc.doc_id} className="mt-1">
              {i === 0 && doc.excerpt && <p className="mb-0.5 line-clamp-3 text-[13px] leading-relaxed">{doc.excerpt}</p>}
              <Link to={`/doc/${doc.doc_id}`} className="text-xs text-primary hover:underline">{doc.title || "관련 자료 원문"}</Link>
              <span className="ml-2 text-xs text-muted-foreground">{doc.source_type} · {doc.published_at?.slice(0, 10)}</span>
            </div>) : <p className="mt-0.5 text-xs text-muted-foreground">연결된 자료가 없습니다.</p>}
          </div>)}
        </CollapsibleContent>
      </Collapsible>}
    </div>
  )
}
