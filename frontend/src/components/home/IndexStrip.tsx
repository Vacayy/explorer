// Home 최상단 주요 지수 스트립 — 한국·홍콩·일본 종가·전일대비·1Y 추이 (D-110)
// 아침에 여는 첫 화면이므로 '판이 어디에 서 있나'를 한 줄로. LLM 0, yfinance(무키).
import { useQuery } from "@tanstack/react-query"
import { AlertTriangle } from "lucide-react"
import { apiQuery, STALE } from "@/api/query"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { HorizontalCarousel } from "@/components/shared/HorizontalCarousel"
import { SparkLine } from "@/components/shared/Spark"
import { formatKstTime, formatNumber, formatPercent } from "@/utils/format"

interface IndexRow {
  key: string
  label: string
  region: string
  market: string
  is_open: boolean
  hours_kst: string
  price: number | null
  change_pct: number | null
  spark: number[]
  as_of: string | null
  fetched_at: string | null   // UTC — 표시는 KST
  lagging: boolean            // 다른 지수는 갱신됐는데 이것만 옛 값 = 이 지수만 수집 실패
}

interface IndicesResponse {
  as_of: string | null
  items: IndexRow[]
  degraded: string[]
  any_open: boolean
  holiday_aware: boolean
}

/** 개장 중이면 10분, 전 시장 휴장이면 30분 — 휴장 중에도 개장 전환을 알아채려면 폴링을 아예 끊지 않는다 */
const POLL_OPEN = 10 * 60_000
const POLL_CLOSED = 30 * 60_000

export function IndexStrip() {
  const { data, isLoading, isError, refetch } = useQuery({
    ...apiQuery<IndicesResponse>({
      key: ["spine", "indices"],
      url: "/api/spine/indices",
      staleTime: STALE.medium,
    }),
    // 백엔드 캐시 TTL도 개장 중 10분이라 폴링 주기와 맞물린다(TTL이 길면 폴링해도 같은 값)
    refetchInterval: (q) => (q.state.data?.any_open ? POLL_OPEN : POLL_CLOSED),
    refetchIntervalInBackground: false,   // 안 보는 탭에서는 폴링 안 함
  })

  if (isLoading) {
    return (
      <Card className="gap-0 py-0">
        <CardContent className="flex gap-4 overflow-x-auto py-3">
          {Array.from({ length: 7 }, (_, i) => (
            <div key={i} className="min-w-32 flex-1 space-y-1.5">
              <Skeleton className="h-3 w-16" />
              <Skeleton className="h-4 w-20" />
              <Skeleton className="h-6 w-full" />
            </div>
          ))}
        </CardContent>
      </Card>
    )
  }
  if (isError) return <ErrorState message="지수를 불러올 수 없습니다." onRetry={() => refetch()} />

  const order = ['sp500', 'nasdaq', 'kospi', 'kosdaq', 'hsi', 'nikkei', 'twii']
  const items = order.flatMap(key => (data?.items ?? []).filter(it => it.key === key))
  const degraded = (data?.degraded ?? []).filter(label => items.some(it => it.label === label))
  const live = items.filter((it) => it.price !== null)
  if (live.length === 0) {
    return <EmptyState message="지수 데이터를 아직 받지 못했습니다. 잠시 후 다시 열어주세요." />
  }

  return (
    <Card className="gap-0 py-0">
      <CardContent className="space-y-1 px-4 py-3">
        <HorizontalCarousel label="시장 지수" footer={
        <div className="flex flex-wrap items-center gap-x-2 text-caption text-muted-foreground">
          <span>전일대비 · 추이 1Y · 시간 KST</span>
          {data?.as_of && <span>· 데이터 {data.as_of}</span>}
          <span>· 표시 시장 {items.some(it => it.is_open) ? "개장 중" : "휴장"} · {data?.any_open ? "10" : "30"}분 주기 갱신</span>
          {data?.holiday_aware === false && <span>· 공휴일 미반영</span>}
          {degraded.length > 0 && (
            <span className="flex items-center gap-1 text-hypothesis">
              <AlertTriangle className="h-3 w-3" /> 수집 실패: {degraded.join(", ")}
            </span>
          )}
        </div>
        }>
          {items.map((it) => (
            <div key={it.key} className="min-w-32 flex-1 snap-start">
              <div className="flex items-baseline gap-1">
                <span
                  className={`mb-px h-1.5 w-1.5 shrink-0 rounded-full ${
                    it.is_open ? "bg-[var(--color-chart-profit)]" : "bg-muted-foreground/30"
                  }`}
                  title={it.is_open ? "정규장 개장 중 (공휴일 미반영)" : "정규장 휴장"}
                  aria-label={it.is_open ? "개장 중" : "휴장"}
                />
                <span className="truncate text-xs font-medium">{it.label}</span>
                <span className="shrink-0 text-caption text-muted-foreground">{it.region}</span>
              </div>
              {it.price === null ? (
                // 조용한 fallback 금지 — 못 받은 지수는 자리를 비우되 이유를 표시
                <div className="mt-0.5 text-xs text-muted-foreground">수집 실패</div>
              ) : (
                <>
                  <div className="mt-0.5 flex items-baseline gap-1.5">
                    <span className="text-base font-semibold tabular-nums">{formatNumber(it.price)}</span>
                    <span
                      className={`text-xs tabular-nums ${
                        (it.change_pct ?? 0) > 0
                          ? "text-up"
                          : (it.change_pct ?? 0) < 0
                            ? "text-down"
                            : "text-muted-foreground"
                      }`}
                    >
                      {formatPercent(it.change_pct)}
                    </span>
                  </div>
                  <div className="mt-1">
                    <SparkLine data={it.spark} height={20} />
                  </div>
                  {/* 개장 시간(KST) + 이 지수를 마지막으로 받은 시각 — 한 지수만 실패하면 여기가 뒤처진다 */}
                  <div className="mt-0.5 space-y-px text-caption leading-tight text-muted-foreground">
                    <div
                      className={`tabular-nums ${it.lagging ? "text-hypothesis" : ""}`}
                      title={
                        it.lagging
                          ? "다른 지수보다 오래된 값 — 이 지수 수집이 실패했습니다"
                          : `정규장 ${it.hours_kst} KST · 수집 시각 KST · 데이터 일자 ${it.as_of ?? "-"}`
                      }
                    >
                      {formatKstTime(it.fetched_at)} 수집{it.lagging && " ⚠"}
                    </div>
                  </div>
                </>
              )}
            </div>
          ))}
        </HorizontalCarousel>

      </CardContent>
    </Card>
  )
}
