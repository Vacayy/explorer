import { useQuery } from "@tanstack/react-query"
import { Loader2 } from "lucide-react"
import { apiQuery, STALE } from "@/api/query"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { MetricHint } from "@/components/shared/MetricHint"

/**
 * Peer 그룹 — 본 종목 + 경쟁사(국내·해외) 지표 비교.
 * 목록은 haiku 큐레이션 1회 캐시, 지표는 KR=자체 / 해외=yfinance (24h 캐시).
 * 첫 열람은 큐레이션+지표 수집으로 수십 초 — 이후 즉답.
 */

interface PeerRow {
  name: string
  ticker: string
  market: string
  is_self: boolean
  market_cap: number | null
  currency: string | null
  per_fwd: number | null
  op_margin: number | null
}

function fmtCap(cap: number | null, currency: string | null): string {
  if (!cap) return "-"
  if (currency === "KRW") {
    return cap >= 1e12 ? `${(cap / 1e12).toFixed(0)}조` : `${(cap / 1e8).toFixed(0)}억`
  }
  const sym = currency === "USD" ? "$" : `${currency ?? ""} `
  return cap >= 1e12 ? `${sym}${(cap / 1e12).toFixed(1)}T` : `${sym}${(cap / 1e9).toFixed(0)}B`
}

export default function PeerSection({ stockCode }: { stockCode: string }) {
  const { data, isLoading, isError } = useQuery(
    apiQuery<PeerRow[]>({
      key: ["spine", "peers", stockCode],
      url: `/api/spine/stock/${stockCode}/peers`,
      staleTime: STALE.long,
    }),
  )

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Peer 그룹</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Peer 큐레이션·지표 수집 중… (첫 열람은 수십 초)
          </div>
        )}
        {isError && <p className="text-xs text-muted-foreground py-1">Peer 정보를 불러오지 못했습니다.</p>}
        {data && data.length <= 1 && !isLoading && (
          <p className="text-xs text-muted-foreground py-1">Peer 큐레이션 결과가 없습니다.</p>
        )}
        {data && data.length > 1 && (
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b text-muted-foreground">
                <th className="py-1 text-left font-medium">기업</th>
                <th className="py-1 text-right font-medium">
                  <MetricHint hint="국내: 거래소 최신 거래일 / 해외: Yahoo Finance (현지통화)">시총</MetricHint>
                </th>
                <th className="py-1 text-right font-medium">
                  <MetricHint hint="국내: 네이버 컨센서스 최신 회계연도 추정 / 해외: Yahoo Finance forwardPE">PER(fwd)</MetricHint>
                </th>
                <th className="py-1 text-right font-medium">
                  <MetricHint hint="국내: DART 최근 연간 영업이익÷매출액 / 해외: Yahoo operatingMargins(TTM) — 회계기준 차이 유의">영업이익률</MetricHint>
                </th>
              </tr>
            </thead>
            <tbody>
              {data.map((p) => (
                <tr key={p.ticker} className={cn("border-b border-border/50", p.is_self && "bg-accent/50 font-semibold")}>
                  <td className="py-1.5">
                    <span className="inline-flex items-center gap-1">
                      {p.name}
                      {p.market !== "KR" && (
                        <Badge variant="outline" className="text-[9px] px-1 py-0">{p.market}</Badge>
                      )}
                    </span>
                  </td>
                  <td className="py-1.5 text-right tabular-nums">{fmtCap(p.market_cap, p.currency)}</td>
                  <td className="py-1.5 text-right tabular-nums">{p.per_fwd != null ? `${p.per_fwd.toFixed(1)}배` : "-"}</td>
                  <td className="py-1.5 text-right tabular-nums">{p.op_margin != null ? `${p.op_margin.toFixed(1)}%` : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {data && data.some((p) => p.market !== "KR") && (
          <p className="pt-1.5 text-[10px] text-muted-foreground">해외 지표: Yahoo Finance (일 1회 갱신) · 회계기준 차이 유의</p>
        )}
      </CardContent>
    </Card>
  )
}
