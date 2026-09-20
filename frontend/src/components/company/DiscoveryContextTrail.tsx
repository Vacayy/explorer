import { Link, useSearchParams } from 'react-router-dom'
import { ArrowLeft, BookOpen } from 'lucide-react'
import { useDiscoveryCase } from '@/hooks/useDiscovery'
import { Button } from '@/components/ui/button'
import { companyResearchSearch } from '@/components/layout/navConfig'

/** Shared context on company tabs. Reading this record never starts another job. */
export function DiscoveryContextTrail({ stockCode }: { stockCode: string }) {
  const [params] = useSearchParams()
  const id = params.get('discovery') ?? ''
  const { data: item } = useDiscoveryCase(id)
  if (!id || !item || item.stock_code !== stockCode) return null
  const back = `/discover?${new URLSearchParams({ run: item.source_run_id, candidate: stockCode })}`
  return <div className="mb-5 flex min-w-0 flex-wrap items-center gap-2 rounded-xl bg-muted/50 p-2" aria-label="종목 발견 맥락">
    <Button variant="ghost" size="sm" asChild><Link to={back}><ArrowLeft className="size-4" />검색 결과</Link></Button>
    <p className="min-w-0 flex-1 truncate px-2 text-caption text-muted-foreground">{item.discovery.question}</p>
    <Button variant="outline" size="sm" asChild><Link to={`/analyze/${stockCode}/summary${companyResearchSearch(params.toString())}`}><BookOpen className="size-4" />기업 조사로 돌아가기</Link></Button>
  </div>
}
