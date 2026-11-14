import { QueryState } from "@/components/shared/QueryState"
import { ArrowUpRight } from 'lucide-react'
import { BOUND_FIXED, BoundedArea } from '@/components/shared/Bounded'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { usePortfolioAlerts } from '@/hooks/usePortfolio'

const KIND: Record<string, string> = { day: '급등락', avg: '평단 구간', tech: '기술적 신호', disc: '공시', summary: '마감 요약', 'track-day': '추적 급등락', 'track-cond': '추적 조건' }

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
      <QueryState query={alerts} loading={<Skeleton className={cn('w-full', BOUND_FIXED.md)} />} isEmpty={() => false}>{() => (!items.length ? <p className="text-sm text-muted-foreground">최근 14일 보낸 알림이 없습니다.</p>
        : <BoundedArea size="md"><ul className="divide-y" aria-label="보낸 알림">{items.map((a, i) => <li key={`${a.sent_at}-${a.kind}-${a.code ?? ''}-${i}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 md:flex-nowrap">
            <span className="w-24 shrink-0 font-mono text-caption tabular-nums text-muted-foreground">{a.sent_at.slice(5)}</span>
            <Badge variant="secondary" className="shrink-0 text-caption font-normal">{KIND[a.kind] ?? a.kind}</Badge>
            {/* 좁은 화면은 본문을 다음 줄로 내려 자르지 않는다 */}
            <span className="min-w-0 basis-full text-sm md:flex-1 md:basis-auto md:truncate">
              {a.name && <span className="font-medium">{a.name} </span>}
              {a.url ? <a href={a.url} target="_blank" rel="noopener noreferrer" className="hover:underline">{a.label}<ArrowUpRight aria-hidden="true" className="ml-0.5 inline size-3" /></a>
                : <span className="text-muted-foreground">{a.label}</span>}
            </span>
          </li>)}</ul></BoundedArea>)}</QueryState>
    </CardContent>
  </Card>
}
