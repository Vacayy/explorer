import { Link } from "react-router-dom"
import { ArrowRight, MessageCircleQuestion, Newspaper } from "lucide-react"
import { useCompany } from "@/hooks/useCompanySearch"
import { Card, CardContent } from "@/components/ui/card"

/**
 * 다음 질문 — dead-end 제거 규칙 (P2-3, product-v3.md §3).
 * 모든 도시에 탭의 마지막 섹션은 여정의 끝이 아니라 다음 질문으로 끝난다.
 * 전부 기존 링크 재조합 + 대화 프리필 — LLM 0토큰 (토큰 규약 ⓓ).
 */

const CONTEXT_QUESTIONS: Record<string, (name: string) => string[]> = {
  financials: (n) => [
    `${n} 최근 실적에 대한 시장 반응은 어때?`,
    `${n} 실적에서 언급된 리스크를 정리해줘`,
  ],
  valuation: (n) => [
    `${n} 밸류에이션에 대한 시장 시각은?`,
    `${n}이 저평가라는 언급이 있었어?`,
  ],
  business: (n) => [
    `${n}의 성장 동력은 뭐라고 언급돼?`,
    `${n} 사업 구조의 약점으로 지적되는 건?`,
  ],
  disclosures: (n) => [
    `${n} 최근 공시 중 주목할 것은?`,
    `${n} 공시가 주가에 미칠 영향은 어떻게 언급돼?`,
  ],
}

export default function NextQuestions({ stockCode, context }: {
  stockCode: string
  context: keyof typeof CONTEXT_QUESTIONS
}) {
  const { data: company } = useCompany(stockCode)
  const name = company?.corp_name ?? "이 종목"
  const questions = CONTEXT_QUESTIONS[context](name)

  return (
    <Card className="bg-muted/30 border-dashed">
      <CardContent className="py-3 flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-semibold text-muted-foreground shrink-0">다음 질문 →</span>
        {questions.map((q) => (
          <Link
            key={q}
            to={`/chat?q=${encodeURIComponent(q)}`}
            className="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-primary border rounded-full px-2.5 py-1 bg-background"
          >
            <MessageCircleQuestion className="h-3 w-3 text-hypothesis" /> {q}
          </Link>
        ))}
        <span className="flex-1" />
        <Link
          to={`/feed?stock=${stockCode}`}
          className="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-primary shrink-0"
        >
          <Newspaper className="h-3 w-3" /> 언급 문서 보기 <ArrowRight className="h-3 w-3" />
        </Link>
      </CardContent>
    </Card>
  )
}
