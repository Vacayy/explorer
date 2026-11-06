import { useEffect } from "react"
import { Navigate, useLocation } from "react-router-dom"
import { ActionsList } from "@/components/actions/ActionsPage"
import { PageLayout } from '@/components/shared/PageLayout'
import { UsSeasonBlock } from "@/components/home/UsSeasonBlock"
import { Band } from "@/components/home/MarketFrame"
import { MarketHero } from "@/components/home/MarketHero"
import { KrFlowCard, KrSeasonCard, KrTurnoverCard, MarketTodayCard, RetailCard, TradeCard, TrendCard } from "@/components/home/MarketKr"
import { CallsCard, MomentumCard, OvernightCard, UsFlowCard, UsTurnoverCard } from "@/components/home/MarketUs"
import HomeDashboard from "@/components/home/HomeDashboard"
import { getHomeMode } from "@/hooks/useHomeMode"

/**
 * 홈 L2 = 시스템 고정 탭 다섯 개 (docs/specs/home-widgets.md §0): 대시보드 · 한국 시장 · 미국 시장 · 매크로 · 내 종목.
 * 한국·미국 시장은 시안대로(3b), 매크로는 home/HomeMacroPage(3c), 내 종목은 home/HomeStocksPage(3d).
 * 옛 /home?home_view=feed는 피드 대메뉴(/feed)로 보낸다 — 나머지 쿼리(channel·channel_type·reader_topic …)는 그대로(ia-redesign §10.6).
 */
export default function HomePage() {
  const { search } = useLocation()
  if (getHomeMode(search) === 'feed') {
    const rest = new URLSearchParams(search)
    rest.delete('home_view')
    return <Navigate to={`/feed${rest.size ? `?${rest}` : ''}`} replace />
  }
  return <HomeDashboard />
}

/**
 * 홈 › 한국 시장 (시안 Home-KR, ia-redesign §4.2 공통 틀, D-325). 띠마다 높이 고정, 넘치면 칸 안 스크롤·페이지.
 * ① 지수 차트 | 요약 지표 → ② 오늘 시장 이야기 | 거래대금 쏠림 → ③ 거래대금 상위 종목 | 가파른 추세 →
 * ④ 국내 실적 시즌 | 기업활동(`#actions`, D-300) → ⑤ 개인 투자 열기(`#retail`) | 수출입.
 */
export function HomeKrPage() {
  useHashScroll()
  // 시안 Home-KR: 하위 메뉴 칩이 제목을 대신한다 — 제목은 화면 읽기용으로만
  return <PageLayout mode="document">
    <h1 className="sr-only">한국 시장</h1>
    <div className="flex flex-col gap-4">
      <MarketHero market="kr" />
      <Band label="시장 정리" cells={[[7, <MarketTodayCard />], [5, <KrFlowCard />]]} />
      <Band label="종목" cells={[[7, <KrTurnoverCard />], [5, <TrendCard />]]} />
      <Band label="실적·이벤트" cells={[[7, <KrSeasonCard />], [5, <ActionsList variant="block" />]]} />
      <Band label="개인 투자·수출입" cells={[[6, <RetailCard />], [6, <TradeCard />]]} />
    </div>
  </PageLayout>
}

/**
 * 홈 › 미국 시장 (시안 Home-US, ia-redesign §4.3 공통 틀, D-325). 한국 시장과 같은 띠 순서·높이.
 * ① 지수 차트 | 요약 지표 → ② 어젯밤 미국장(핵심 | 전문) | 거래대금 쏠림 → ③ 거래대금 상위 종목(실적 열) | 새 모멘텀 후보 →
 * ④ 실적 시즌(맨 위에서 내려옴, 시즌 사이엔 다음 시즌까지 D-n) | 최근 컨콜.
 */
export function HomeUsPage() {
  useHashScroll()
  return <PageLayout mode="document">
    <h1 className="sr-only">미국 시장</h1>
    <div className="flex flex-col gap-4">
      <MarketHero market="us" />
      <Band label="시장 정리" cells={[[7, <OvernightCard />], [5, <UsFlowCard />]]} />
      <Band label="종목" cells={[[7, <UsTurnoverCard />], [5, <MomentumCard />]]} />
      <Band label="실적·이벤트" cells={[[7, <UsSeasonBlock />], [5, <CallsCard />]]} />
    </div>
  </PageLayout>
}

/** #retail·#actions·#us-briefing으로 들어오면 그 칸으로 — 띠 높이가 고정이라 데이터가 와도 위치가 그대로지만 첫 그리기 뒤에 한 번 더 맞춘다 */
function useHashScroll() {
  const { hash } = useLocation()
  useEffect(() => {
    if (!hash) return
    const go = () => document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView({ block: "start" })
    const timers = [150, 900].map(ms => window.setTimeout(go, ms))
    return () => timers.forEach(t => window.clearTimeout(t))
  }, [hash])
}
