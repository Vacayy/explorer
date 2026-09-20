import { useNavigate } from 'react-router-dom'
import { ArrowUpRight, LoaderCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useDiscoveryAction } from '@/hooks/useDiscovery'
import type { DiscoveryCase } from '@/components/analysis/discoveryTypes'
import type { AnalysisCandidate } from '@/components/analysis/types'

/** The explicit action queues research; opening/reloading the company only reads it. */
export function CandidateDiscovery({ runId, candidate }: { runId: string; candidate: AnalysisCandidate }) {
  const navigate = useNavigate()
  const create = useDiscoveryAction<DiscoveryCase>()
  async function submit() {
    if (create.isPending) return
    try {
      const item = await create.mutateAsync({
        path: '/cases',
        body: {
          run_id: runId,
          stock_code: candidate.code,
          question: `${candidate.name}에 관심이 모이는 배경은 무엇인가? 시장 담론, 전방 산업, 실적·콜, 수출입 자료에서 근거와 반대 근거를 찾아줘.`,
          start_research: true,
        },
      })
      const params = new URLSearchParams({ discovery: item.id })
      navigate(`/analyze/${item.stock_code}/summary?${params}`)
    } catch { /* The same request key is retained for network retries. */ }
  }
  return (
    <div className="space-y-2">
      <Button size="sm" onClick={() => void submit()} disabled={create.isPending} aria-label={`${candidate.name} 기업 조사`}>
        {create.isPending ? <LoaderCircle className="size-3.5 animate-spin" /> : <ArrowUpRight className="size-3.5" />}
        {create.isPending ? '조사 준비 중' : '기업 조사'}
      </Button>
      {create.error && <p role="alert" className="max-w-sm text-caption text-destructive">{create.error.message} 다시 누르면 같은 요청을 확인합니다.</p>}
    </div>
  )
}
