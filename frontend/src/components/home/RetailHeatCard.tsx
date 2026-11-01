import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/shared/ErrorState'
import { PctileBar, RegimeBadge, metricValue } from '@/components/retail/retailFormat'
import { useRetailSummary } from '@/hooks/useRetail'

const KEYS = ['credit_growth', 'deposit_growth', 'value_growth', 'indiv_share']

/** 홈 시장 탭 — 개인 투자 열기 요약(D-231). 국면과 핵심 4지표의 5년 백분위, 자세히는 /retail. */
export function RetailHeatCard() {
  const q = useRetailSummary()
  return <Card className="min-w-0">
    <CardHeader><div className="flex flex-wrap items-start justify-between gap-2">
      <div className="min-w-0 space-y-1"><CardTitle>개인 투자 열기</CardTitle>
        <p className="text-caption text-muted-foreground">빚투·대기자금·거래 열기의 변화 속도를 과거 5년과 비교합니다{q.data?.as_of ? ` · ${q.data.as_of} 기준` : ''}</p></div>
      <Button asChild variant="ghost" size="sm" className="shrink-0"><Link to="/retail">자세히<ArrowRight className="size-3.5" /></Link></Button>
    </div></CardHeader>
    <CardContent>
      {q.isPending ? <Skeleton className="h-32 w-full" />
        : q.isError ? <ErrorState message="개인 투자 열기를 불러오지 못했습니다." onRetry={() => void q.refetch()} />
        : !q.data.regime ? <p className="py-6 text-center text-sm text-muted-foreground">아직 수집된 자료가 없습니다. 평일 18:30에 금융투자협회 통계를 받습니다.</p>
        : <div className="grid gap-4 @3xl/market:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
          <div className="space-y-2">
            <RegimeBadge regime={q.data.regime} className="text-sm" />
            <ul className="space-y-1 text-caption text-muted-foreground">{q.data.regime.reasons.slice(0, 2).map(r => <li key={r}>{r}</li>)}</ul>
          </div>
          <dl className="grid grid-cols-1 gap-2">{KEYS.map(k => {
            const m = q.data.metrics.find(x => x.key === k)
            if (!m) return null
            return <div key={k} className="flex items-center justify-between gap-3 text-sm">
              <dt className="min-w-0 truncate text-muted-foreground max-sm:whitespace-normal max-sm:break-keep">{m.label}</dt>
              <dd className="flex shrink-0 items-center gap-3"><span className="w-16 text-right tabular-nums">{metricValue(m)}</span><PctileBar value={m.pctile} /></dd>
            </div>
          })}</dl>
        </div>}
    </CardContent>
  </Card>
}
