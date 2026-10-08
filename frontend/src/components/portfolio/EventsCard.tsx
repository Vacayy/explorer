import { ArrowUpRight } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { ErrorState } from '@/components/shared/ErrorState'
import { usePortfolioEvents } from '@/hooks/usePortfolio'

const KIND: Record<string, string> = { ir: 'IR', earnings_notice: '실적 예고', agm: '주총', earnings_est: '실적', report_deadline: '보고서', us_earnings: '해외 실적' }

function dday(date: string) {
  const today = new Date(new Date(Date.now() + 9 * 3600_000).toISOString().slice(0, 10))
  const n = Math.round((new Date(date).getTime() - today.getTime()) / 86_400_000)
  return n === 0 ? '오늘' : `D-${n}`
}

/** 다가오는 이벤트(45일) — 확정·예상·해외를 구분해 보인다(portfolio-intelligence §4). */
export function EventsCard() {
  const events = usePortfolioEvents()
  const items = events.data ?? []
  return <TooltipProvider><Card>
    <CardHeader>
      <CardTitle>다가오는 이벤트</CardTitle>
      <CardDescription>45일 안의 일정입니다. 공시로 확정된 것과 지난해 패턴으로 추정한 것을 구분합니다.</CardDescription>
    </CardHeader>
    <CardContent>
      {events.isPending ? <Skeleton className="h-48 w-full" />
        : events.isError ? <ErrorState onRetry={() => void events.refetch()} />
        : !items.length ? <p className="text-sm text-muted-foreground">45일 안에 확인된 일정이 없습니다. 일정 수집은 평일 16:50에 갱신됩니다.</p>
        : <ul className="divide-y">{items.map(e => <li key={`${e.date}-${e.kind}-${e.title}`} className="flex items-start gap-3 py-2.5">
            <div className="w-14 shrink-0 tabular-nums"><p className="text-sm font-medium">{e.date.slice(5)}</p><p className="text-caption text-muted-foreground">{dday(e.date)}</p></div>
            <div className="min-w-0 flex-1 space-y-1">
              <p className="text-sm">{e.url
                ? <a href={e.url} target="_blank" rel="noopener noreferrer" className="hover:underline">{e.title}<ArrowUpRight aria-hidden="true" className="ml-0.5 inline size-3" /></a>
                : e.title}</p>
              <div className="flex flex-wrap gap-1">
                <Badge variant="secondary" className="text-caption font-normal">{KIND[e.kind] ?? e.kind}</Badge>
                {e.estimated && <Tooltip><TooltipTrigger asChild><Badge variant="outline" className="text-caption font-normal text-muted-foreground">예상</Badge></TooltipTrigger>
                  <TooltipContent>{e.basis ?? '추정'}</TooltipContent></Tooltip>}
                {e.kind === 'us_earnings' && <Badge variant="outline" className="text-caption font-normal text-muted-foreground">관련 해외 기업</Badge>}
              </div>
            </div>
          </li>)}</ul>}
    </CardContent>
  </Card></TooltipProvider>
}
