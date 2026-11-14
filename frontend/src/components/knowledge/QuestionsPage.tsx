import { useSearchParams } from "react-router-dom"
import { PageContainer } from "@/components/shared/PageContainer"
import { JudgmentFrame } from "@/components/thesis/JudgmentFrame"
import { QuestionsSection } from "@/components/knowledge/QuestionsSection"
import { ProxyBoardsView } from "@/components/proxy/ProxyBoardsView"
import { TranscriptProxies } from "@/components/proxy/TranscriptProxies"

/**
 * /questions — Thesis › 내 판단의 기본 화면 (docs/specs/world-model.md §4, ia-redesign §4.10).
 * 보유 논지·관심 이유·논지 감사 승격·서사 도출이 모두 같은 질문 행이다 — 출처는 배지로 구분.
 * 상세는 /question/:id 허브(D-070). 논지 감사·리포트·지표 보드는 같은 틀의 보기 전환.
 * ?view=proxies = 지표 보드(옛 /proxy-boards) + 그 아래 컨콜에서 뽑은 지표(옛 탐색 › 컨콜 '프록시').
 */
export default function QuestionsPage() {
  const [params] = useSearchParams()
  const proxies = params.get("view") === "proxies"
  return (
    <PageContainer gap="sm">
      <JudgmentFrame />
      {proxies ? (
        <div className="flex flex-col gap-6">
          <ProxyBoardsView />
          <TranscriptProxies />
        </div>
      ) : <QuestionsSection />}
    </PageContainer>
  )
}
