import { PageHeader, PageLayout } from "@/components/shared/PageLayout"
import { HomeSection } from "@/components/home/HomeSection"
import { formatKstLongDate } from "@/utils/format"

/**
 * 홈 › 대시보드 — 시스템 고정 화면 (docs/specs/home-widgets.md §0, ia-redesign §4.1).
 * 순서 고정: 시장 띠(지수·시장 요약) → Market Overnight | Market Today(같은 높이) → 이번 주 바뀐 서사 → 국면·리스크.
 * 사용자가 고르는 배치·편집·위젯 추가는 없다. 블록마다 따로 불러오고 따로 실패한다.
 */
export default function HomeDashboard() {
  return (
    <PageLayout mode="document" header={<PageHeader title={formatKstLongDate()} />}>
      <div className="@container/market">
        {/* 시장 띠 — 지수(장중 여부 점·1년 추이) 위, 환율·금리·원자재 아래 */}
        <div className="surface-stack flex flex-col">
          <HomeSection widget="market.indices" flat className="h-[92px]" />
          <HomeSection widget="market.context" flat className="h-[76px]" />
        </div>

        {/* 같은 높이 두 칸 — 넘치는 본문은 칸 안에서 스크롤 */}
        <div className="surface-grid grid lg:grid-cols-2">
          <HomeSection widget="market.us" w={6} h={9} link={{ to: "/home/us", label: "미국 시장" }} className="h-[560px] lg:h-[640px]" />
          <HomeSection widget="market.today" w={6} h={9} link={{ to: "/home/kr", label: "한국 시장" }} className="h-[560px] lg:h-[640px]" />
        </div>

        <HomeSection widget="world.changes" w={12} h={3} />

        <RiskBlock />
      </div>
    </PageLayout>
  )
}

/** 국면·리스크 — 상태 줄(국장·미장 포스처) + 지표 타일 넷(3개월 추이·20일 변화). 모바일은 VIX·공포탐욕만 */
function RiskBlock() {
  return (
    <section aria-label="국면·리스크">
      <HomeSection widget="risk.regime" w={12} h={2} title="국면·리스크" link={{ to: "/home/macro", label: "매크로" }} />
      <div className="surface-grid grid grid-cols-2 lg:grid-cols-4">
        <HomeSection widget="risk.vix" w={3} h={4} link={null} />
        <HomeSection widget="risk.fear" w={3} h={4} link={null} />
        <HomeSection widget="risk.hy" w={3} h={4} link={null} className="max-md:hidden" />
        <HomeSection widget="risk.curve" w={3} h={4} link={null} className="max-md:hidden" />
      </div>
    </section>
  )
}
