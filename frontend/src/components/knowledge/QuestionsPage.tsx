import { PageContainer } from "@/components/shared/PageContainer"
import { OutlookSubNav } from "@/components/explore/OutlookSubNav"
import { QuestionsSection } from "@/components/knowledge/QuestionsSection"

/**
 * /questions — 미결 질문 탭 (D-071·D-073). 전망(미래·확률) 상위 탭의 서브탭(질문↔리포트).
 * 분할정복으로 추적하는 열린 질문 목록·콘솔·제안 큐. 상세는 /question/:id 허브(D-070).
 */
export default function QuestionsPage() {
  return (
    <PageContainer gap="sm">
      <OutlookSubNav />
      <QuestionsSection />
    </PageContainer>
  )
}
