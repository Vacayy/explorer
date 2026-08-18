import { useState } from "react"
import { Link } from "react-router-dom"
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
    <CardHeader className="pb-2 flex-row items-center gap-2">
      <CardTitle className="text-sm flex items-center gap-1.5">
        <Coins className="h-4 w-4 text-primary" /> 전일 국장 거래대금
      </CardTitle>
      <span className="text-[11px] text-muted-foreground">상위 20 · 자금이 어디로 쏠렸나</span>
      <div className="ml-auto flex items-center gap-1.5">
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
    <Card>
      {header}
      <CardContent className="space-y-3">
        {data.status === "stale" && (
          <div className="flex items-start gap-1.5 rounded-md bg-chart-warning/10 px-2 py-1.5 text-[11px] text-chart-warning">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
            <span>실시간 갱신 실패 — 마지막 성공 데이터를 표시합니다.{data.error ? ` (${data.error})` : ""}</span>
          </div>
        )}

        {/* 섹터 쏠림 */}
        <div>
          <div className="mb-1 text-[11px] font-medium text-muted-foreground">
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
                {c.has_new && <Badge variant="outline" className="text-[9px] shrink-0 text-up border-up/40">신규</Badge>}
                <span className="hidden sm:block text-[10px] text-muted-foreground truncate min-w-0 flex-1">{c.names.join(" · ")}</span>
              </div>
            ))}
          </div>
        </div>

        {/* 개별 이슈 */}
        {idiosyncratic.length > 0 && (
          <div>
            <div className="mb-1 text-[11px] font-medium text-muted-foreground">개별 이슈 — 그룹으로 안 풀리는 움직임</div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
              {idiosyncratic.map((m) => <MoverRow key={m.stock_code} m={m} />)}
            </div>
          </div>
        )}

        {/* 상위 20 전체 */}
        <Collapsible open={open} onOpenChange={setOpen}>
          <CollapsibleTrigger className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground">
            <ChevronDown className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
            거래대금 상위 20 전체
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-0.5">
            {items.map((m) => (
              <div key={m.stock_code} className="flex items-center gap-2 py-0.5 text-sm min-w-0">
                <span className="w-5 text-right text-xs text-muted-foreground tabular-nums shrink-0">{m.rank}</span>
                <Link to={`/analyze/${m.stock_code}/summary`} className="font-medium text-primary hover:underline truncate min-w-0 flex-1">{m.name}</Link>
                {m.market === "KOSDAQ" && <Badge variant="outline" className="text-[9px] shrink-0">코스닥</Badge>}
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
          <Badge key={f} variant="outline" className={`text-[9px] shrink-0 ${f === "신규 진입" ? "text-up border-up/40" : ""}`}>{f}</Badge>
        ))}
      </div>
      {m.sector && <span className="ml-auto shrink-0 text-[10px] text-muted-foreground truncate max-w-[35%]">{m.sector}</span>}
    </div>
  )
}
