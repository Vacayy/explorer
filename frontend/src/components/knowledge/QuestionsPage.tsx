import { PageContainer } from "@/components/shared/PageContainer"
import { OutlookSubNav } from "@/components/explore/OutlookSubNav"
import { QuestionsSection } from "@/components/knowledge/QuestionsSection"

/**
 * /questions — 월드모델 › 내 판단의 기본 화면 (docs/specs/world-model.md §4).
 * 보유 논지·관심 이유·논지 감사 승격·서사 도출이 모두 같은 질문 행이다 — 출처는 배지로 구분.
 * 상세는 /question/:id 허브(D-070). 논지 감사·리포트는 같은 탭의 보기 전환.
 */
export default function QuestionsPage() {
  return (
    <PageContainer gap="sm">
      <OutlookSubNav />
      <div className="flex items-baseline gap-2">
        <h2 className="text-xl font-bold">내 판단</h2>
        <span className="text-[11px] text-muted-foreground">추적 중인 질문 — 보유 논지와 관심 이유도 같은 질문으로 쌓인다</span>
      </div>
      <QuestionsSection />
    </PageContainer>
  )
}
