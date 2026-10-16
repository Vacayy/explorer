import { ArrowUpRight } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/shared/ErrorState'
import { usePortfolioAlerts } from '@/hooks/usePortfolio'

const KIND: Record<string, string> = { day: '급등락', avg: '평단 구간', tech: '기술적 신호', disc: '공시', summary: '마감 요약' }

/** 알림 이력 — 텔레그램으로 보낸 포트폴리오 알림(14일). 본문은 저장하지 않아 유형·종목·구간·시각만 보인다. */
export function AlertHistoryCard() {
  const alerts = usePortfolioAlerts(14)
  const items = alerts.data ?? []
  return <Card>
    <CardHeader>
      <CardTitle>알림 이력</CardTitle>
      <CardDescription>최근 14일 텔레그램으로 보낸 알림입니다. 원칙 위반 알림은 위 ‘지금 상태’에서 봅니다.</CardDescription>
    </CardHeader>
    <CardContent>
      {alerts.isPending ? <Skeleton className="h-32 w-full" />
        : alerts.isError ? <ErrorState onRetry={() => void alerts.refetch()} />
        : !items.length ? <p className="text-sm text-muted-foreground">최근 14일 보낸 알림이 없습니다.</p>
        : <ul className="divide-y" aria-label="보낸 알림">{items.map((a, i) => <li key={`${a.sent_at}-${a.kind}-${a.code ?? ''}-${i}`} className="flex items-center gap-3 py-2">
            <span className="w-24 shrink-0 font-mono text-caption tabular-nums text-muted-foreground">{a.sent_at.slice(5)}</span>
            <Badge variant="secondary" className="shrink-0 text-caption font-normal">{KIND[a.kind] ?? a.kind}</Badge>
            <span className="min-w-0 flex-1 truncate text-sm">
              {a.name && <span className="font-medium">{a.name} </span>}
              {a.url ? <a href={a.url} target="_blank" rel="noopener noreferrer" className="hover:underline">{a.label}<ArrowUpRight aria-hidden="true" className="ml-0.5 inline size-3" /></a>
                : <span className="text-muted-foreground">{a.label}</span>}
            </span>
          </li>)}</ul>}
    </CardContent>
  </Card>
}
