import { useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { ArrowLeft } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import api from "@/api/client"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useSpineSignals } from "@/hooks/useSpineSignals"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { FreshnessStamp } from "@/components/shared/FreshnessStamp"
import { SignalCard } from "@/components/shared/SignalCard"
import { SignalSummaryCard, type SummaryRow } from "@/components/explore/SignalSummaryCard"
import { PageContainer } from '@/components/shared/PageContainer'

const TYPE_LABEL: Record<string, string> = {
  theme_surge: "주목 주제", mention_surge: "언급 급증", neglect: "소외",
  high_52w: "52주 신고가", volume_spike: "거래량 급증",
  quadrant_gap: "가격-관측 괴리", consensus_extreme: "컨센서스 극단",
}
const PAGE_SIZE = 12


/**
 * /explore — 탐색 (product-v2.md v2.1)
 * P0: 신호 카드 피드. 스캔(신고가)·섹터 렌즈는 P1.
 * URL 쿼리(type/days)가 필터 상태의 단일 소스.
 */
export default function ExplorePage() {
  const [searchParams] = useSearchParams()
  const list = searchParams.get("list")   // 있으면 목록(디테일) 모드
  // 목록 모드: 특정 신호 유형의 개별 카드 나열 + 페이지네이션
  if (list) return <SignalListView type={list} />
  return <SignalSummaryView />
}

/* ---------- 요약 모드 (기본 착륙) — Signal Summary Card들 ---------- */

function SignalSummaryView() {
  const navigate = useNavigate()
  const stock = useSpineSignals(undefined, 30)
  if (stock.isLoading) return <ExploreSkeleton />

  return (
    <PageContainer gap="sm">
      <div className="flex items-baseline justify-between">
        <h2 className="text-xl font-bold">신호</h2>
        {stock.data && <FreshnessStamp asOf={stock.data.as_of} />}
      </div>

      <MomentumSection onOpen={() => navigate("/explore?list=mention_surge")} />
      <ThemeSurgeSummary onOpen={() => navigate("/explore?list=theme_surge")} />
      <BacktestSection />

      {/* 나머지 신호 유형 진입 — 각 유형 목록으로 */}
      <div className="flex flex-wrap gap-1.5">
        <span className="text-[11px] text-muted-foreground self-center mr-1">더 보기</span>
        {["neglect", "high_52w", "volume_spike", "quadrant_gap", "consensus_extreme"].map((t) => (
          <Badge key={t} variant="outline" className="cursor-pointer text-xs"
            onClick={() => navigate(`/explore?list=${t}`)}>{TYPE_LABEL[t]}</Badge>
        ))}
      </div>
    </PageContainer>
  )
}

/* ---------- 목록 모드 — 유형별 개별 카드 + 페이지네이션 ---------- */

function SignalListView({ type }: { type: string }) {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const days = type === "theme_surge" ? 14 : 30
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
        <h2 className="text-lg font-bold">{TYPE_LABEL[type] ?? type}</h2>
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

/* ---------- 주제 모멘텀 요약 카드 (theme_surge) ---------- */

function ThemeSurgeSummary({ onOpen }: { onOpen: () => void }) {
  const { data } = useSpineSignals("theme_surge", 14)
  const rows: SummaryRow[] = (data?.items ?? []).map((s, i) => ({
    key: String(s.id),
    rank: i + 1,
    name: s.entity_name,
    link: `/feed?topic=${encodeURIComponent(s.entity_name)}`,
    metric: `비중 ${s.payload.share_pct ?? "-"}%`,
    sub: `${s.payload.recent ?? 0}건`,
    badge: s.payload.is_new ? "신규" : (s.payload.share_delta_pp ? `+${s.payload.share_delta_pp}%p` : undefined),
  }))
  return (
    <SignalSummaryCard
      title="주목 주제 — 지금 소스들이 몰리는 화두"
      subtitle="전체 문서 중 비중 상승"
      rows={rows}
      onOpen={onOpen}
    />
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


/* ---------- 언급 모멘텀 랭킹 — 이번 주 부상 종목 (새 탭 없이 /explore 착륙) ---------- */

interface MomentumRow {
  rank: number
  entity_id: number
  name: string
  stock_code: string | null
  count_7d: number
  prior_7d: number
  score: number
  daily: number[]
}

function MomentumSection({ onOpen }: { onOpen: () => void }) {
  const { data } = useQuery({
    queryKey: ["spine", "momentum"],
    queryFn: async () => (await api.get("/api/spine/signals/momentum")).data as { items: MomentumRow[] },
    staleTime: 5 * 60_000,
  })
  const rows: SummaryRow[] = (data?.items ?? []).map((m) => ({
    key: String(m.entity_id),
    rank: m.rank,
    name: m.name,
    link: m.stock_code ? `/analyze/${m.stock_code}/mentions` : undefined,
    spark: m.daily,
    metric: `7일 ${m.count_7d}회`,
    sub: `직전 ${m.prior_7d}`,
    badge: m.score >= 2 ? `×${m.score}` : undefined,
  }))
  return (
    <SignalSummaryCard
      title="언급 모멘텀 — 이번 주 부상 종목"
      rows={rows}
      onOpen={onOpen}
    />
  )
}


/* ---------- 신호 성적표 — 언급 급증 후 5거래일 수익률 (자기 검증) ---------- */

function BacktestSection() {
  const { data } = useQuery({
    queryKey: ["spine", "backtest"],
    queryFn: async () => (await api.get("/api/spine/signals/backtest")).data as {
      items: { date: string; name: string; stock_code: string | null; ret_5d: number | null }[]
      avg_ret: number | null
      hit_rate: number | null
      n: number
    },
    staleTime: 30 * 60_000,
  })
  if (!data || data.n === 0) return null
  return (
    <Card>
      <CardHeader className="pb-2 flex-row items-baseline gap-3">
        <CardTitle className="text-sm">신호 성적표 — 언급 급증 후 5거래일</CardTitle>
        <span className="text-xs tabular-nums">
          평균 <b className={data.avg_ret! > 0 ? "text-up" : "text-down"}>{data.avg_ret}%</b>
          <span className="text-muted-foreground"> · 적중 {data.hit_rate}% · {data.n}건</span>
        </span>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs tabular-nums">
          {data.items.filter((i) => i.ret_5d != null).slice(0, 12).map((i, idx) => (
            <span key={idx}>
              <span className="text-muted-foreground">{i.date.slice(5)}</span>{" "}
              {i.name}{" "}
              <b className={i.ret_5d! > 0 ? "text-up" : "text-down"}>
                {i.ret_5d! > 0 ? "+" : ""}{i.ret_5d}%
              </b>
            </span>
          ))}
        </div>
        <p className="text-[10px] text-muted-foreground mt-2">
          과거 신호의 사후 수익률 — 신호의 유효성 자체를 검증하기 위한 것 (투자 추천 아님)
        </p>
      </CardContent>
    </Card>
  )
}
