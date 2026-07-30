import { Link, useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { usDossierQuery } from "@/api/spine"
import { PageContainer } from "@/components/shared/PageContainer"
import { ErrorState } from "@/components/shared/ErrorState"
import { Skeleton } from "@/components/ui/skeleton"
import { Card, CardContent } from "@/components/ui/card"
import { LensView } from "@/components/lens/LensPage"

function usd(v?: number | null) {
  if (v == null) return "-"
  const a = Math.abs(v)
  if (a >= 1e9) return `$${(v / 1e9).toFixed(1)}B`
  if (a >= 1e6) return `$${(v / 1e6).toFixed(0)}M`
  return `$${v.toLocaleString()}`
}
function num(v?: number | null, d = 1) {
  return v == null ? "-" : v.toFixed(d)
}

/**
 * 미국 종목 도시에 (docs/specs/us-dossier.md) — 경량 통합 뷰.
 * 헤더(yfinance 시세·밸류) + 투자 렌즈(가치/추세, market='us') + 컨콜·언급 링크.
 */
export default function UsDossierPage() {
  const { ticker = "" } = useParams<{ ticker: string }>()
  const q = useQuery(usDossierQuery(ticker))

  if (q.isLoading)
    return (
      <PageContainer>
        <Skeleton className="h-24 w-full rounded-xl" />
      </PageContainer>
    )
  if (q.isError || !q.data)
    return (
      <PageContainer>
        <ErrorState onRetry={() => q.refetch()} />
      </PageContainer>
    )

  const d = q.data
  const f = d.fundamentals
  const pt = (f?.estimates?.price_targets ?? null) as { mean?: number } | null
  const up = pt?.mean && f?.price ? ((pt.mean - f.price) / f.price) * 100 : null

  return (
    <PageContainer gap="sm">
      <Card>
        <CardContent className="py-4">
          <div className="flex items-baseline gap-2">
            <span className="text-lg font-semibold">{d.name}</span>
            <span className="text-sm text-muted-foreground">{d.ticker}</span>
          </div>
          {f ? (
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
              <span>
                현재가 <b>${num(f.price, 2)}</b>
              </span>
              <span className="text-muted-foreground">시총 {usd(f.market_cap)}</span>
              <span className="text-muted-foreground">Fwd PER {num(f.fwd_pe)}배</span>
              <span className="text-muted-foreground">trailing {num(f.trailing_pe)}배</span>
              {up != null && (
                <span className={up >= 0 ? "text-up" : "text-down"}>
                  목표가 대비 {up >= 0 ? "+" : ""}
                  {up.toFixed(0)}%
                </span>
              )}
            </div>
          ) : (
            <p className="mt-2 text-sm text-muted-foreground">시세 데이터를 불러오지 못했습니다.</p>
          )}
          <div className="mt-2 flex gap-3 text-xs">
            {d.latest_transcript && (
              <Link to="/follow/transcripts" className="text-primary hover:underline">
                최근 컨콜 {d.latest_transcript.fiscal_year} {d.latest_transcript.fiscal_period} →
              </Link>
            )}
            <Link to={`/feed?q=${encodeURIComponent(d.name)}`} className="text-primary hover:underline">
              이 종목 언급 →
            </Link>
          </div>
        </CardContent>
      </Card>

      <LensView code={d.ticker} market="us" />
    </PageContainer>
  )
}
