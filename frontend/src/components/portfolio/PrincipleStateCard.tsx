import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/shared/ErrorState'
import { usePrincipleState } from '@/hooks/usePortfolio'
import { formatRelativeTime } from '@/utils/format'

/** 지금 어기고 있는 규칙(portfolio-intelligence §5) — 저장된 시세로 다시 판정만 한다. 알림은 여전히 텔레그램이 보낸다. */
export function PrincipleStateCard({ live }: { live: boolean }) {
  const state = usePrincipleState(live)
  const d = state.data
  const basis = d?.as_of ? (d.as_of.includes('T') ? `장중 ${d.as_of.slice(11, 16)} 시세` : `${d.as_of} 종가`) : null
  return <Card>
    <CardHeader>
      <CardTitle>지금 상태</CardTitle>
      <CardDescription>점검 규칙을 지금 계좌에 대 본 결과입니다{basis ? ` (${basis} 기준)` : ''}. 어긴 규칙은 장중 30분·장 마감 뒤 점검에서 텔레그램으로 한 번 알립니다.</CardDescription>
    </CardHeader>
    <CardContent>
      {state.isPending ? <Skeleton className="h-16 w-full" />
        : state.isError ? <ErrorState message="상태를 계산하지 못했습니다." onRetry={() => void state.refetch()} />
        : !d ? null : d.rules === 0 ? <p className="text-sm text-muted-foreground">점검할 수치 규칙이 아직 없습니다. 아래 ‘운용 원칙’에 원칙을 적으면 규칙으로 풀어 점검합니다.</p>
        : !d.items.length ? <p className="text-sm"><span className="font-medium text-foreground">어기고 있는 규칙이 없습니다.</span> <span className="text-muted-foreground">규칙 {d.rules}개를 점검했습니다.</span></p>
        : <ul className="divide-y" aria-label="어기고 있는 규칙">{d.items.map(v => <li key={v.key} className="flex flex-wrap items-start justify-between gap-2 py-2.5">
            <div className="min-w-0 space-y-0.5">
              <p className="text-sm font-medium text-down">{v.message}</p>
              <p className="text-caption text-muted-foreground">{v.rule}</p>
            </div>
            <Badge variant="outline" className="shrink-0 text-caption font-normal text-muted-foreground">
              {v.alerted_since ? `알림 보냄 · ${formatRelativeTime(v.alerted_since.replace(' ', 'T') + 'Z')}` : '다음 점검에서 알림'}</Badge>
          </li>)}</ul>}
    </CardContent>
  </Card>
}
