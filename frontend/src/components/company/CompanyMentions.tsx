import { useSearchParams } from 'react-router-dom'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/shared/ErrorState'
import { InfoTip } from '@/components/shared/InfoTip'
import { useCompanyEvidence } from '@/hooks/useCompanyEvidence'
import { pickedDay, shortDate } from '@/lib/dossier'
import { cn } from '@/lib/utils'
import { formatNumber } from '@/utils/format'
import { CompanyEvidence, sourceLabels } from '@/components/company/CompanyEvidence'

/**
 * 도시에 '자료' 탭(국내 /analyze/:code/mentions · 미국 /us/:t?tab=evidence, ia-redesign §4.13):
 * 30일 언급 흐름 막대(누르면 ?day= 그날) · 출처별 건수(누르면 ?source=) → 자료 목록.
 * 미국만 고른 날의 AI 요약 버튼을 둔다(국내 1일 요약은 11-04 결정으로 넣지 않는다).
 */
export function CompanyMentions({ company, market }: { company: string; market: 'kr' | 'us' }) {
  const [sp, setSp] = useSearchParams()
  const day = pickedDay(sp.get('day'))
  const source = sp.get('source') || ''
  const set = (key: string, value: string | null) => setSp((prev) => {
    const n = new URLSearchParams(prev)
    if (value) n.set(key, value); else n.delete(key)
    n.delete('page')
    return n
  }, { replace: true, preventScrollReset: true })
  return (
    <div className="space-y-3">
      <FlowCard company={company} market={market} day={day} source={source} onDay={(d) => set('day', d === day ? null : d)} onSource={(s) => set('source', s === source ? null : s)} />
      <CompanyEvidence key={`${company}:${day ?? ''}`} company={company} market={market}
        range={day ? { start: day, end: day } : {}} summary={market === 'us'} />
    </div>
  )
}

function FlowCard({ company, market, day, source, onDay, onSource }: {
  company: string; market: 'kr' | 'us'; day: string | null; source: string
  onDay: (d: string) => void; onSource: (s: string) => void
}) {
  const q = useCompanyEvidence({ company, market, size: 1 })
  const flow = q.data?.flow
  const max = Math.max(1, ...(flow?.days.map((d) => d.count) ?? [0]))
  const peak = flow?.days.reduce((a, b) => (b.count > a.count ? b : a), flow.days[0])
  const total = flow?.days.reduce((a, b) => a + b.count, 0) ?? 0
  return (
    <Card className="gap-0 py-0" aria-label="언급 흐름" data-mention-flow>
      <header className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 border-b px-4 py-3">
        <h2 className="text-section font-semibold">언급 흐름</h2>
        <span className="text-caption text-muted-foreground">최근 30일{flow ? ` · ${formatNumber(total)}건` : ''}</span>
        <InfoTip label="언급 흐름 설명">이 기업에 연결된 저장 자료를 {market === 'kr' ? '한국' : '미 동부'} 날짜로 셉니다. 막대를 누르면 그날 자료만, 출처를 누르면 그 출처만 봅니다.</InfoTip>
        <span className="ml-auto" />
        {day && <Button variant="ghost" size="sm" className="h-7" onClick={() => onDay(day)}>{shortDate(day)} 선택 지우기</Button>}
      </header>
      <div className="space-y-3 px-4 py-3">
        {q.isPending ? <Skeleton className="h-28 w-full" />
          : q.isError || !flow ? <ErrorState message="언급 흐름을 불러오지 못했습니다." onRetry={() => q.refetch()} />
          : total === 0 ? <p className="py-6 text-sm text-muted-foreground">최근 30일에 이 기업과 연결된 자료가 없습니다.</p>
          : <>
            <div className="flex h-28 items-end gap-[2px] sm:gap-1" role="group" aria-label="날짜별 자료 수">
              {flow.days.map((d) => {
                const on = d.date === day
                return (
                  <button key={d.date} type="button" onClick={() => onDay(d.date)} aria-pressed={on}
                    aria-label={`${shortDate(d.date)} ${d.count}건`} title={`${shortDate(d.date)} · ${d.count}건`}
                    className="group flex h-full min-w-0 flex-1 items-end focus-visible:outline-2 focus-visible:outline-ring">
                    <span className={cn('block w-full', d.count === 0 ? 'h-px bg-border' : on || (!day && d === peak) ? 'bg-foreground' : 'bg-muted-foreground/35 group-hover:bg-muted-foreground/60')}
                      style={d.count ? { height: `${Math.max(4, (d.count / max) * 100)}%` } : undefined} />
                  </button>
                )
              })}
            </div>
            <div className="flex justify-between font-mono text-caption tabular-nums text-muted-foreground">
              {[0, 7, 14, 21, 29].map((i) => <span key={i}>{shortDate(flow.days[i].date)}</span>)}
            </div>
            <div className="flex flex-wrap gap-1.5" aria-label="출처별 건수">
              {flow.sources.map((s) => (
                <Button key={s.source} size="xs" variant={source === s.source ? 'default' : 'outline'} aria-pressed={source === s.source}
                  className="rounded-full" onClick={() => onSource(s.source)}>
                  {sourceLabels[s.source] ?? s.source} <span className="font-mono tabular-nums">{formatNumber(s.count)}</span>
                </Button>
              ))}
            </div>
          </>}
      </div>
    </Card>
  )
}
