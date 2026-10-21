import { PageLayout, PageHeader } from '@/components/shared/PageLayout'
import { IndexStrip } from "@/components/home/IndexStrip"
import { AiActivityFeed } from "@/components/home/AiActivityFeed"
import { RiskMonitoring } from '@/components/home/RiskMonitoring'
import { RetailHeatCard } from '@/components/home/RetailHeatCard'
import { MarketRegime } from "@/components/home/MarketRegime"
import { MacroLiquidity } from "@/components/home/MacroLiquidity"
import { UsBriefingSection } from "@/components/home/UsBriefingSection"
import { KrMoversSection } from "@/components/home/KrMoversSection"
import { ChannelReader } from "@/components/feed/ChannelReader"
import { useState } from "react"
import { Navigate, useParams } from "react-router-dom"
import { Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState } from "@/components/shared/ErrorState"
import Dashboard from "@/components/home/Dashboard"
import { NewBoardDialog } from "@/components/home/NewBoardDialog"
import { useHomeBoards } from "@/hooks/useDashboard"
import { useHomeMode } from "@/hooks/useHomeMode"

/** 홈 › 내 메뉴(위젯 보드) 또는 캔버스 › 피드(소스 디렉터리 + 리더). 보기는 URL home_view만 따른다. */
export default function HomePage() {
  const mode = useHomeMode()
  if (mode === 'feed') return (
    <PageLayout mode="reader" header={<PageHeader title="피드" />} overview={<AiActivityFeed />}>
      <ChannelReader />
    </PageLayout>
  )
  return <PageLayout mode="document" header={<PageHeader title="홈" />}><HomeMenu /></PageLayout>
}

/** /home/b/:boardId = 그 메뉴, /home = 첫 메뉴. 없는 id면 첫 메뉴로 (home-widgets.md §5) */
function HomeMenu() {
  const { boardId } = useParams()
  const boards = useHomeBoards()
  const [creating, setCreating] = useState(false)
  if (boards.isPending) return <div className="grid grid-cols-12 gap-3">{[12, 6, 6, 3, 3, 3, 3].map((w, n) => <Skeleton key={n} className="h-36 rounded-[var(--radius-card)]" style={{ gridColumn: `span ${w}` }} />)}</div>
  if (boards.isError) return <ErrorState message="홈 메뉴를 불러오지 못했습니다." onRetry={() => void boards.refetch()} />
  if (!boards.data.length) return <>
    <div className="rounded-[var(--radius-card)] border border-dashed p-8 text-center text-sm text-muted-foreground">
      <p>아직 메뉴가 없어요. 빈 메뉴나 시스템 프리셋에서 시작해 위젯을 골라 놓으세요.</p>
      <Button className="mt-3" size="sm" onClick={() => setCreating(true)}><Plus className="size-3.5" />새 메뉴</Button>
    </div>
    <NewBoardDialog open={creating} onOpenChange={setCreating} />
  </>
  const menu = boardId ? boards.data.find(b => String(b.id) === boardId) : boards.data[0]
  if (!menu) return <Navigate to="/home" replace />
  return <Dashboard key={menu.id} menu={menu} />
}

/** 홈 › 시장 브리핑 — 미국장·국장 전체 보기 (위젯 '전체 보기' 대상) */
export function HomeBriefingPage() {
  return <PageLayout mode="document" header={<PageHeader title="시장 브리핑" />} overview={<IndexStrip />}>
    <div className="@container/market space-y-5"><UsBriefingSection /><KrMoversSection /></div>
  </PageLayout>
}

/** 홈 › 국면·리스크 — 시장 국면·Risk 추이·개인 투자 열기 전체 보기 */
export function HomeRiskPage() {
  return <PageLayout mode="document" header={<PageHeader title="국면·리스크" />}>
    <div className="@container/market space-y-5"><MarketRegime /><RiskMonitoring /><RetailHeatCard /></div>
  </PageLayout>
}

/** 홈 › 매크로 — 매크로·유동성 지표와 신호등 전체 보기 (시장 요약 띠의 '상세'와 같은 카드) */
export function HomeMacroPage() {
  return <PageLayout mode="document" header={<PageHeader title="매크로" />}>
    <div className="@container/market space-y-5"><MacroLiquidity /></div>
  </PageLayout>
}
