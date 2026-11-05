import { PageLayout } from "@/components/shared/PageLayout"
import { HomeSection } from "@/components/home/HomeSection"
import { useIsMobile } from "@/hooks/use-mobile"

/**
 * 산업 › 대만 공급망 (/follow/taiwan, 시안 Industry-TW, ia-redesign §4.8) — 대만 월매출 → 대만 → 한국 연결, 각각 전체 폭으로 위아래.
 * 본문은 홈 위젯(widgets/twRevenue)을 그대로 쓴다 — 블록 단위 오류 경계·기준 월·층(tw_layer)·회사 상세(tw)가 같이 온다.
 * 한국 시장 탭 아래에 임시로 있던 두 블록을 이 화면으로 옮겼다(§10.4a 3b).
 */
export default function TaiwanPage() {
  const mobile = useIsMobile()   // 좁은 화면은 막대·역할·근거 줄을 접는 좁은 본문
  const w = mobile ? 4 : 12
  return <PageLayout mode="document">
    <div className="flex flex-col">
      <HomeSection widget="explore.twRevenue" w={w} h={12} />
      <HomeSection widget="explore.twLinks" w={w} h={12} />
    </div>
  </PageLayout>
}
