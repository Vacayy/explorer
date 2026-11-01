import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { TradeFlagBadge } from "@/components/follow/tradeFormat"
import { useActions } from "@/hooks/useActions"
import { useTradeByStock } from "@/hooks/useTrade"
import { cn } from "@/lib/utils"
import { formatPercent } from "@/utils/format"

const mmdd = (d: string) => `${d.slice(4, 6)}-${d.slice(6, 8)}`

/**
 * 종목 도시에 개요의 '최근 활동' 두 줄 — 최근 30일 기업활동(stock_brief와 같은 corporate_actions 30일 창)과
 * 이 종목을 관련 종목으로 지목한 수출입 품목. 둘 다 없으면 그리지 않는다(대부분 종목이 해당 없음).
 */
export function StockActivityStrip({ stockCode }: { stockCode: string }) {
  const actions = useActions({ stockCode, days: 30 })
  const trade = useTradeByStock(stockCode)
  if (actions.isLoading || trade.isLoading) return <Skeleton className="h-12 w-full rounded-xl" />
  const acts = actions.data?.items ?? []
  const items = trade.data ?? []
  if (!acts.length && !items.length && !actions.isError && !trade.isError) return null
  const corrections = acts.filter((a) => a.is_correction).length
  return (
    <Card className="py-0">
      <CardContent className="space-y-1.5 px-4 py-3 text-sm">
        <Row label="최근 30일 기업활동" more={<Link to="/actions" className="text-primary hover:underline">기업활동 →</Link>}>
          {actions.isError ? <span className="text-muted-foreground">불러오지 못했어요</span>
            : !acts.length ? <span className="text-muted-foreground">공시 없음</span>
            : <>
              {acts.filter((a) => !a.is_correction).slice(0, 3).map((a) => (
                <a key={a.id} href={a.dart_url} target="_blank" rel="noreferrer" title={a.summary ?? a.report_nm ?? undefined}
                  className="inline-flex items-center gap-1 hover:underline">
                  <Badge variant="secondary" className={cn("h-4 px-1 text-[10px]", a.action_type === "유상증자" && "bg-down/10 text-down", a.action_type === "무상증자" && "bg-up/10 text-up")}>{a.action_type}</Badge>
                  <span className="tabular-nums text-muted-foreground">{mmdd(a.rcept_dt)}</span>
                </a>
              ))}
              {corrections > 0 && <span className="text-xs text-muted-foreground">정정 {corrections}건</span>}
            </>}
        </Row>
        {(items.length > 0 || trade.isError) && (
          <Row label="수출 지표" more={<Link to="/follow/trade" className="text-primary hover:underline">수출입 →</Link>}>
            {trade.isError ? <span className="text-muted-foreground">불러오지 못했어요</span>
              : items.slice(0, 4).map((t) => (
                <Link key={t.hs_code} to={`/follow/trade?hs=${encodeURIComponent(t.hs_code)}`} className="inline-flex items-center gap-1 hover:underline">
                  <span>{t.item_name}</span>
                  <span className={cn("tabular-nums text-xs", (t.yoy_pct ?? 0) >= 0 ? "text-up" : "text-down")}>{formatPercent(t.yoy_pct)}</span>
                  <TradeFlagBadge flag={t.flag} reason={t.reason} />
                  {t.rel && <span className="text-[10px] text-muted-foreground">{t.rel}</span>}
                </Link>
              ))}
            {items[0]?.period && <span className="text-xs text-muted-foreground tabular-nums">{items[0].period} 통계</span>}
          </Row>
        )}
      </CardContent>
    </Card>
  )
}

function Row({ label, more, children }: { label: string; more: ReactNode; children: ReactNode }) {
  return (
    // 모바일: 라벨·링크 한 줄, 내용은 아래 전폭 / md+: 라벨(고정폭)·내용·링크 한 줄
    <div className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 md:flex md:flex-wrap">
      <span className="text-xs font-medium text-muted-foreground md:w-28 md:shrink-0">{label}</span>
      <div className="order-last col-span-2 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 md:order-none md:flex-1">{children}</div>
      <span className="shrink-0 text-xs">{more}</span>
    </div>
  )
}
