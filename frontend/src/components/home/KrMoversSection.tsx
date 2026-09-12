import { useState } from "react"
import { DetailLink as Link } from "@/components/shared/DetailNavigation"
import { AlertTriangle, ChevronDown, Coins } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { FreshnessStamp } from "@/components/shared/FreshnessStamp"
import { RefreshButton } from "@/components/shared/RefreshButton"
import { formatKrw, formatPercent } from "@/utils/format"
import { useKrMovers } from "@/hooks/useKrMovers"
import type { KrMoverItem } from "@/types"

/**
 * 홈 — 전일 국장 거래대금 상위 (D-108). 미국장 브리핑의 국장 대응물.
 * 차이: LLM 종합(분위기 산문) 없음 — 표 + 섹터 쏠림 + 개별 이슈까지 전부 결정적 계산.
 * 5-state: Loading / Error(status=error·쿼리실패) / Partial(stale) / Empty / Ideal.
 */
export function KrMoversSection() {
  const { data, isLoading, isError, refetch, refresh, refreshing } = useKrMovers()
  const [open, setOpen] = useState(false)

  if (isLoading) return <Skeleton className="h-64 w-full rounded-xl" />
  if (isError || !data || data.status === "error")
    return <ErrorState message={data?.error ?? "국장 거래대금을 불러올 수 없습니다."} onRetry={() => refetch()} />

  const header = (
    <CardHeader className="pb-2 flex flex-wrap items-center gap-2">
      <CardTitle className="text-sm flex items-center gap-1.5">
        <Coins className="h-4 w-4 text-primary" /> 전일 국장 거래대금
      </CardTitle>
      <span className="text-caption text-muted-foreground">상위 20 · 자금 집중과 관련 이슈</span>
      <div className="ml-auto flex items-center gap-1.5">
        {data.trade_date && <span className="text-caption text-muted-foreground">{data.trade_date} 스냅샷</span>}
        {data.fetched_at && <FreshnessStamp asOf={data.fetched_at} />}
        <RefreshButton onClick={refresh} pending={refreshing} title="지금 업데이트 (전일 거래대금 재수집)" />
      </div>
    </CardHeader>
  )

  if (data.items.length === 0)
    return (
      <Card>
        {header}
        <CardContent>
          <EmptyState message={refreshing ? "전일 거래대금을 불러오는 중…" : "‘지금 업데이트’를 눌러 전일 거래대금 상위를 수집하세요."} />
        </CardContent>
      </Card>
    )

  const { clusters, idiosyncratic, items } = data
  const top = clusters[0]

  return (
    <Card data-home-section="kr-movers">
      {header}
      <CardContent className="space-y-3">
        {data.status === "stale" && (
          <div className="flex items-start gap-1.5 rounded-md bg-chart-warning/10 px-2 py-1.5 text-caption text-chart-warning">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
            <span>실시간 갱신 실패 — 마지막 성공 데이터를 표시합니다.{data.error ? ` (${data.error})` : ""}</span>
          </div>
        )}

        <div className="rounded-xl bg-muted/40 px-4 py-3 text-sm leading-relaxed">
          상위 {items.length}종목 거래대금 합계는 <strong>{formatKrw(items.reduce((sum, m) => sum + (m.value_traded ?? 0), 0))}</strong>입니다.
          {top && <> 이 중 <strong>{top.label}</strong>에 {top.share_pct}%가 집중됐습니다.</>}
          {items[0] && <> 거래대금 1위는 <Link to={`/analyze/${items[0].stock_code}/summary`} className="font-medium underline underline-offset-4">{items[0].name}</Link>이며, 등락률은 {formatPercent(items[0].change_pct)}입니다.</>}
          <span className="block mt-1 text-caption text-muted-foreground">비중은 시장 전체가 아닌 상위 {items.length}종목 기준입니다. 날짜는 저장 스냅샷 기준입니다.</span>
        </div>
        <div className="grid grid-cols-1 @[1000px]/market:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] gap-6">
        <div className="space-y-4 min-w-0">
        {/* 섹터 쏠림 */}
        <div>
          <div className="mb-1 text-caption font-medium text-muted-foreground">
            섹터 쏠림 {top && <span className="text-foreground">· {top.label} {top.share_pct}%</span>}
          </div>
          <div className="space-y-1">
            {clusters.map((c) => (
              <div key={c.label} className="flex items-center gap-2 text-xs">
                <span className="w-28 shrink-0 truncate">{c.label}</span>
                <div className="relative h-3 flex-1 rounded bg-muted overflow-hidden">
                  <div className="absolute inset-y-0 left-0 bg-primary/70 rounded" style={{ width: `${c.share_pct}%` }} />
                </div>
                <span className="w-12 shrink-0 text-right tabular-nums">{c.share_pct}%</span>
                <span className={`w-14 shrink-0 text-right tabular-nums ${chg(c.median_change)}`}>{formatPercent(c.median_change)}</span>
                {c.has_new && <Badge variant="outline" className="text-caption shrink-0 text-up border-up/40">신규</Badge>}
                <span className="hidden sm:block text-caption text-muted-foreground truncate min-w-0 flex-1">{c.names.join(" · ")}</span>
              </div>
            ))}
          </div>
        </div>

        {/* 개별 이슈 */}
        {idiosyncratic.length > 0 && (
          <div>
            <div className="mb-1 text-caption font-medium text-muted-foreground">개별 이슈 — 그룹으로 안 풀리는 움직임</div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
              {idiosyncratic.map((m) => <MoverRow key={m.stock_code} m={m} />)}
            </div>
          </div>
        )}

        </div>
        <section className="min-w-0" aria-label="거래대금 상위 이유 브리핑">
          <h3 className="text-sm font-semibold">거래대금 상위 이유 브리핑</h3>
          <p className="text-caption text-muted-foreground mt-1 mb-3">상위 5종목 · 스냅샷 당일까지 3일간의 관련 자료. 저장 요약은 이슈 배경이며 거래 원인을 확정하지 않습니다.</p>
          <div className="divide-y">
            {(data.briefing ?? []).map(b => <div key={b.stock_code} className="py-3 first:pt-0">
              <div className="flex items-center gap-2"><span className="text-caption text-muted-foreground">{b.rank}</span><Link to={`/analyze/${b.stock_code}/summary`} className="text-sm font-medium hover:underline">{b.name}</Link>{b.parent_company_context && <span className="text-caption text-muted-foreground">본주 관련 자료 포함</span>}</div>
              {b.documents.length ? b.documents.map((d, i) => <div key={d.doc_id} className="mt-2">
                {i === 0 && d.excerpt && <p className="text-sm leading-relaxed line-clamp-3 mb-1">{d.excerpt}</p>}
                <Link to={`/doc/${d.doc_id}`} className="text-caption text-primary hover:underline">{d.title || '관련 자료 원문'} ↗</Link>
                <span className="ml-2 text-caption text-muted-foreground">{d.source_type} · {d.published_at?.slice(0, 10)}{i === 0 && d.excerpt ? (d.excerpt_kind === 'summary' ? ' · 저장 AI 요약 발췌' : ' · 원문 발췌') : ''}</span>
              </div>) : <p className="mt-1 text-caption text-muted-foreground">해당 기간에 연결된 자료가 없습니다. 거래대금 상위 이유는 추가 확인이 필요합니다.</p>}
            </div>)}
            {!data.briefing?.length && <p className="text-sm text-muted-foreground">관련 자료를 아직 확인하지 못했습니다.</p>}
          </div>
        </section>
        </div>
        {/* 상위 20 전체 */}
        <Collapsible open={open} onOpenChange={setOpen}>
          <CollapsibleTrigger className="flex items-center gap-1 text-caption text-muted-foreground hover:text-foreground">
            <ChevronDown className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
            거래대금 상위 20 전체
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-0.5">
            {items.map((m) => (
              <div key={m.stock_code} className="flex items-center gap-2 py-0.5 text-sm min-w-0">
                <span className="w-5 text-right text-xs text-muted-foreground tabular-nums shrink-0">{m.rank}</span>
                <Link to={`/analyze/${m.stock_code}/summary`} className="font-medium text-primary hover:underline truncate min-w-0 flex-1">{m.name}</Link>
                {m.market === "KOSDAQ" && <Badge variant="outline" className="text-caption shrink-0">코스닥</Badge>}
                <span className={`w-14 text-right text-xs tabular-nums shrink-0 ${chg(m.change_pct)}`}>
                  {m.change_pct != null ? formatPercent(m.change_pct) : "-"}
                </span>
                <span className="w-16 text-right shrink-0 font-medium tabular-nums text-xs">{formatKrw(m.value_traded)}</span>
              </div>
            ))}
          </CollapsibleContent>
        </Collapsible>
      </CardContent>
    </Card>
  )
}

/** 등락률 색 — 한국 컨벤션(상승=빨강 text-up, 하락=파랑 text-down). */
function chg(v: number | null): string {
  if (v == null || v === 0) return "text-muted-foreground"
  return v > 0 ? "text-up" : "text-down"
}

function MoverRow({ m }: { m: KrMoverItem }) {
  return (
    <div className="flex items-center gap-2 py-1 text-sm min-w-0">
      <Link to={`/analyze/${m.stock_code}/summary`} className="font-medium text-primary hover:underline shrink-0 truncate max-w-[40%]">{m.name}</Link>
      <span className={`text-xs tabular-nums shrink-0 ${chg(m.change_pct)}`}>
        {m.change_pct != null ? formatPercent(m.change_pct) : ""}
      </span>
      <div className="flex items-center gap-1 min-w-0 flex-1 truncate">
        {m.flags.map((f) => (
          <Badge key={f} variant="outline" className={`text-caption shrink-0 ${f === "신규 진입" ? "text-up border-up/40" : ""}`}>{f}</Badge>
        ))}
      </div>
      {m.sector && <span className="ml-auto shrink-0 text-caption text-muted-foreground truncate max-w-[35%]">{m.sector}</span>}
    </div>
  )
}
