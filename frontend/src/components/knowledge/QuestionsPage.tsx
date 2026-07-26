import { PageContainer } from "@/components/shared/PageContainer"
import { NarrativeSubNav } from "@/components/explore/NarrativeSubNav"
import { QuestionsSection } from "@/components/knowledge/QuestionsSection"

/**
 * /questions — 미결 질문 탭 (D-071). 내러티브 상위 탭의 서브탭(내러티브↔질문).
 * 분할정복으로 추적하는 열린 질문 목록·콘솔·제안 큐. 상세는 /question/:id 허브(D-070).
 */
export default function QuestionsPage() {
  return (
    <PageContainer gap="sm">
      <NarrativeSubNav />
      <QuestionsSection />
    </PageContainer>
  )
}
