import { useState } from 'react'
import { Search } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { RUN_FILTERS, filterRuns, groupRunsByDay, runFilterCounts, runOutcome, runScope, runTitle, runWhen, type RunFilter } from '@/lib/discoverHistory'
import { cn } from '@/lib/utils'
import { formatNumber } from '@/utils/format'
import type { AnalysisRun, RunStatus } from '@/components/analysis/types'

/** 이전 검색 시트 본문 (ia-redesign §4.24 Discover-History) — 조건 이름 제목 · 날짜 묶음 · 이름 검색 · 결과 필터. 지금 보는 결과는 연한 면 + 테두리 */
export function RunHistory({ runs, selected, labels, status, onOpen }: {
  runs: AnalysisRun[]; selected: string | null; labels: Readonly<Record<string, string>>; status: Record<RunStatus, string>; onOpen: (id: string) => void
}) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<RunFilter>('all')
  const counts = runFilterCounts(runs)
  const visible = filterRuns(runs, filter, query, labels)
  return <div className="space-y-3">
    <div className="relative"><Search aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
      <Input type="search" aria-label="조건 이름으로 찾기" value={query} onChange={event => setQuery(event.target.value)} placeholder="조건 이름으로 찾기" className="pl-9" />
    </div>
    <ToggleGroup type="single" value={filter} onValueChange={value => { if (value) setFilter(value as RunFilter) }} size="sm" aria-label="결과로 거르기" className="flex-wrap justify-start gap-1.5 bg-transparent p-0">
      {RUN_FILTERS.map(option => <ToggleGroupItem key={option.id} value={option.id} className="h-7 rounded-full border border-line-2 px-2.5 text-xs shadow-none data-[state=on]:border-action data-[state=on]:bg-action data-[state=on]:text-action-ink data-[state=on]:shadow-none">{option.label} <span className="font-mono tabular-nums">{counts[option.id]}</span></ToggleGroupItem>)}
    </ToggleGroup>
    {!visible.length ? <p role="status" className="py-6 text-center text-sm text-muted-foreground">조건에 맞는 검색이 없습니다.</p>
      : groupRunsByDay(visible).map(group => <section key={group.day} aria-label={group.day} className="space-y-1">
        <h3 className="px-1 pt-2 text-caption font-semibold text-ink-2">{group.day} <span className="font-normal tabular-nums text-ink-3">{group.items.length}</span></h3>
        <ul className="space-y-1">{group.items.map(run => {
          const outcome = runOutcome(run)
          const current = run.id === selected
          return <li key={run.id}><button type="button" onClick={() => onOpen(run.id)} aria-current={current ? 'page' : undefined}
            className={cn('block w-full space-y-1 border border-transparent px-3 py-2.5 text-left hover:bg-muted/50', current && 'border-line-2 bg-surface-2')}>
            <span className="line-clamp-2 text-[13.5px] font-medium">{runTitle(run, labels)}</span>
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-caption text-muted-foreground">
              <Badge variant={outcome === 'error' ? 'warn' : 'neutral'}>{status[run.status]}</Badge>
              {run.spec?.mode !== 'catalog' && <span>문장 검색</span>}
              {run.result && <span>{outcome === 'matched' ? `후보 ${formatNumber(run.result.counts.matched)}개` : '후보 없음'}</span>}
              {run.spec?.mode === 'catalog' && <span>{runScope(run)}</span>}
              {current && <span className="font-medium text-foreground">지금 보는 결과</span>}
              <span className="ml-auto tabular-nums">{runWhen(run.created_at)}</span>
            </span>
          </button></li>
        })}</ul>
      </section>)}
  </div>
}
