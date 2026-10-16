import { useState } from "react"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { ArrowLeft, ChevronRight } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useSignalsSummary, useSpineSignals } from "@/hooks/useSpineSignals"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { FreshnessStamp } from "@/components/shared/FreshnessStamp"
import { SIGNAL_LABEL, SignalCard, signalEntityPath } from "@/components/shared/SignalCard"
import { PageContainer } from '@/components/shared/PageContainer'
import { formatNumber } from "@/utils/format"
import { cn } from "@/lib/utils"

/** 신호 유형 — 인덱스 카드 순서. call_momentum(실적 발언 모멘텀)은 미국 기업 실적 시즌 신호 */
const SIGNAL_TYPES = ["mention_surge", "theme_surge", "neglect", "high_52w", "volume_spike", "quadrant_gap", "consensus_extreme", "call_momentum"]
const TYPE_DESC: Record<string, string> = {
  mention_surge: "직전 7일보다 언급이 크게 늘어난 종목",
  theme_surge: "여러 소스가 지금 몰리는 주제",
  neglect: "저평가·흑자인데 30일 언급이 없는 종목",
  high_52w: "52주 전고점을 넘긴 종목",
  volume_spike: "60일 평균의 몇 배 거래가 터진 날",
  quadrant_gap: "주가와 관측 감성이 엇갈리는 종목",
  consensus_extreme: "감성이 한쪽으로 쏠린 종목",
  call_momentum: "실적 발표에서 새로 생기거나 빨라진 성장 동인",
}
/** 목록 기간 — 매일 도는 신호는 30일, 실적 시즌 신호는 한 시즌(90일) */
const LIST_DAYS: Record<string, number> = { theme_surge: 14, call_momentum: 90 }
const PAGE_SIZE = 12

/**
 * /explore — 탐색 › 신호 (docs/specs/discover-signals.md).
 * 인덱스 = 유형별 최신일 건수·상위 3 · ?list=<type> = 유형별 개별 카드 목록.
 */
export default function ExplorePage() {
  const [searchParams] = useSearchParams()
  const list = searchParams.get("list")
  if (list) return <SignalListView type={list} />
  return <SignalIndexView />
}

/* ---------- 유형 인덱스 — 유형별 최신일 건수·상위 3 (GET /signals/summary) ---------- */

function SignalIndexView() {
  const { data, isLoading, isError, refetch } = useSignalsSummary(7)
  const byType = new Map((data?.types ?? []).map((t) => [t.type, t]))
  return (
    <PageContainer gap="sm">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-xl font-bold">신호</h2>
        <p className="text-xs text-muted-foreground">
          매일 계산되는 관찰 신호입니다. 조건을 직접 쌓아 찾으려면 <Link to="/discover" className="text-primary hover:underline">종목 발견</Link>으로.
        </p>
        {data?.as_of && <span className="ml-auto text-xs text-muted-foreground tabular-nums">{data.as_of} 기준</span>}
      </div>
      {isLoading ? (
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
          {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-36 rounded-xl" />)}
        </div>
      ) : isError || !data ? (
        <ErrorState onRetry={() => refetch()} />
      ) : data.types.length === 0 ? (
        <EmptyState message="아직 계산된 신호가 없습니다. 수집이 쌓이면 나타납니다." />
      ) : (
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
          {SIGNAL_TYPES.map((type) => {
            const t = byType.get(type)
            // 유형마다 최신일이 다르다(가격 신호=전 거래일). 2일 넘게 뒤처지면 멈춘 것으로 보고 주의 색
            const stale = !!t && !!data.as_of && daysBetween(t.latest_date, data.as_of) > 2
            return (
              <Card key={type} className="gap-0 py-0 shadow-none">
                <CardContent className="flex h-full flex-col gap-2 p-3">
                  <div className="flex items-center gap-1">
                    <Link to={`/explore?list=${type}`} className="text-sm font-semibold hover:underline">{SIGNAL_LABEL[type] ?? type}</Link>
                    {t && <span className={cn("ml-auto text-[11px] tabular-nums", stale ? "text-chart-warning" : "text-muted-foreground")}>{t.latest_date}</span>}
                  </div>
                  <p className="text-xs text-muted-foreground line-clamp-1">{TYPE_DESC[type]}</p>
                  {t ? (
                    <>
                      <div className="flex items-baseline gap-2">
                        <span className="text-2xl font-semibold tabular-nums">{formatNumber(t.count_latest)}</span>
                        <span className="text-xs text-muted-foreground">건 · 7일 {formatNumber(t.count_window)}</span>
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {t.top.map((x) => (
                          <Badge key={x.entity_id} variant="outline" className="font-normal" asChild>
                            <Link to={signalEntityPath(x)}>{x.name}</Link>
                          </Badge>
                        ))}
                      </div>
                    </>
                  ) : <p className="text-xs text-muted-foreground">아직 신호가 없습니다</p>}
                  <Button variant="ghost" size="xs" className="mt-auto self-start" asChild>
                    <Link to={`/explore?list=${type}`}>목록 <ChevronRight /></Link>
                  </Button>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
    </PageContainer>
  )
}

function daysBetween(a: string, b: string): number {
  return Math.round((new Date(b + "T00:00:00").getTime() - new Date(a + "T00:00:00").getTime()) / 86_400_000)
}

/* ---------- 목록 모드 — 유형별 개별 카드 + 페이지네이션 ---------- */

function SignalListView({ type }: { type: string }) {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const days = LIST_DAYS[type] ?? 30
  const { data, isLoading, isError, refetch } = useSpineSignals(type, days)
  if (isLoading) return <ExploreSkeleton />
  if (isError || !data) return <ErrorState onRetry={() => refetch()} />

  const items = data.items
  const shown = items.slice(0, page * PAGE_SIZE)
  return (
    <PageContainer gap="sm">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={() => navigate("/explore")}>
          <ArrowLeft className="h-4 w-4" /> 신호
        </Button>
        <h2 className="text-lg font-bold">{SIGNAL_LABEL[type] ?? type}</h2>
        <span className="text-xs text-muted-foreground">{items.length}건</span>
        <span className="ml-auto"><FreshnessStamp asOf={data.as_of} /></span>
      </div>
      {items.length === 0 ? (
        <EmptyState message="해당 신호가 아직 없습니다. 수집이 쌓이면 나타납니다." />
      ) : (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {shown.map((s) => (
              <SignalCard key={s.id} signal={s}
                onKeywordClick={(k) => navigate(`/feed?topic=${encodeURIComponent(k)}`)} />
            ))}
          </div>
          {shown.length < items.length && (
            <div className="flex justify-center pt-1">
              <Button variant="outline" size="sm" onClick={() => setPage((p) => p + 1)}>
                {items.length - shown.length}건 더 보기
              </Button>
            </div>
          )}
        </>
      )}
    </PageContainer>
  )
}

function ExploreSkeleton() {
  return (
    <PageContainer gap="sm">
      <Skeleton className="h-6 w-24" />
      <Skeleton className="h-5 w-64" />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="border rounded-xl p-4 space-y-2">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-5 w-28" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-3/4" />
          </div>
        ))}
      </div>
    </PageContainer>
  )
}
