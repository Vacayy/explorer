import { useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { ArrowLeft } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useSpineSignals } from "@/hooks/useSpineSignals"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { FreshnessStamp } from "@/components/shared/FreshnessStamp"
import { SignalCard } from "@/components/shared/SignalCard"
import { PageContainer } from '@/components/shared/PageContainer'

const TYPE_LABEL: Record<string, string> = {
  theme_surge: "주목 주제", mention_surge: "언급 급증", neglect: "소외",
  high_52w: "52주 신고가", volume_spike: "거래량 급증",
  quadrant_gap: "가격-관측 괴리", consensus_extreme: "컨센서스 극단",
}
const ALL_TYPES = ["mention_surge", "theme_surge", "neglect", "high_52w", "volume_spike", "quadrant_gap", "consensus_extreme"]
const PAGE_SIZE = 12

/**
 * /explore — 신호 상세 목록 (탐색 해체, D-057).
 * L1 pill 없는 도시에 — 신호 요약은 Home 대시보드로 이관, 여기는 유형별 개별 카드만.
 * ?list=<type> = 목록 모드, 없으면 유형 인덱스.
 */
export default function ExplorePage() {
  const [searchParams] = useSearchParams()
  const list = searchParams.get("list")
  if (list) return <SignalListView type={list} />
  return <SignalIndexView />
}

/* ---------- 유형 인덱스 (bare /explore) — 요약은 Home, 여기선 상세 진입만 ---------- */

function SignalIndexView() {
  const navigate = useNavigate()
  return (
    <PageContainer gap="sm">
      <div>
        <h2 className="text-xl font-bold">신호</h2>
        <p className="text-xs text-muted-foreground mt-1">
          유형별 상세 목록입니다. 언급 모멘텀·주목 주제·인과 활동 요약은 Home에서 봅니다.
        </p>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {ALL_TYPES.map((t) => (
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
