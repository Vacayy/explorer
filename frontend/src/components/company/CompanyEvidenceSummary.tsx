import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/api/client'
import { Button } from '@/components/ui/button'
import type { EvidenceItem, EvidenceRange } from './CompanyEvidence'

interface Summary {
  points: { text: string; sources: number[] }[]
  sources: EvidenceItem[]
  used_count: number
  total: number
  title_only_count?: number
  truncated_count?: number
  generated_at: string | null
}
export function CompanyEvidenceSummary({ company, market, range, source, q, disabled, onRead }: {
  company: string; market: 'kr' | 'us'; range: EvidenceRange; source: string; q: string
  disabled: boolean; onRead: (item: EvidenceItem, trigger: HTMLButtonElement) => void
}) {
  const params = { company, market, start: range.start, end: range.end, cutoff: range.cutoff || 'end', after: !!range.after, source, q }
  const scope = JSON.stringify(params)
  const [openedScope, setOpenedScope] = useState('')
  const expanded = openedScope === scope
  const result = useQuery({
    queryKey: ['company-evidence-summary', params],
    queryFn: async ({ signal }) => (await api.post<Summary>('/api/spine/feed/company-evidence/summary', params, { signal, timeout: 300_000 })).data,
    enabled: false,
    staleTime: Infinity,
    gcTime: 30 * 60_000,
    retry: false,
  })
  const generate = () => { setOpenedScope(scope); void result.refetch() }
  return <section className="rounded-xl border bg-muted/30 p-4" aria-label="선택 구간 자료 요약">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <Button variant="outline" disabled={disabled || result.isFetching} onClick={() => {
        if (expanded) setOpenedScope('')
        else if (result.data) setOpenedScope(scope)
        else generate()
      }} aria-expanded={expanded}>
        {result.isFetching ? '요약하는 중…' : expanded ? '요약 접기' : result.data ? '요약 보기' : '이 구간 요약'}
      </Button>
      {expanded && result.data && <Button size="sm" variant="ghost" disabled={disabled || result.isFetching} onClick={generate}>최신 자료로 다시 요약</Button>}
    </div>
    <p className="mt-2 text-caption text-muted-foreground">현재 기간·출처·검색 조건 기준 · 최대 30건</p>
    {expanded && <div className="mt-4 space-y-3" aria-live="polite" aria-busy={result.isFetching}>
      {result.isFetching ? <p className="text-sm text-muted-foreground">자료를 읽고 있습니다. 날짜를 바꿔도 이 구간의 요약과 섞이지 않습니다.</p> : result.isError ? <div role="alert"><p className="text-sm">요약을 만들지 못했습니다. 자료는 그대로 읽을 수 있습니다.</p><Button variant="ghost" onClick={generate}>다시 시도</Button></div> : result.data && <>
        <p className="text-caption text-muted-foreground">AI 요약 · 조회 결과 {result.data.total}건 중 {result.data.used_count}건 사용{result.data.generated_at && ` · ${new Date(result.data.generated_at).toLocaleString('ko-KR')}`}</p>
        {result.data.points.length === 0 ? <p className="text-sm">요약할 자료가 없습니다.</p> : <ul className="space-y-4">{result.data.points.map((point, i) => <li key={i} className="text-sm leading-relaxed"><p>{point.text}</p><div className="mt-1 flex flex-wrap gap-1">{point.sources.map(n => {
          const item = result.data.sources[n-1]
          return item ? <button key={n} className="rounded border bg-background px-2 py-1 text-caption text-primary hover:underline" title={item.title} onClick={e => onRead(item, e.currentTarget)}>[{n}] {item.source_type === 'disclosure' ? '공시' : '자료'}{item.status === 'after' ? ' · 이후 공개' : item.status === 'uncertain' ? ' · 당시 공개 미확인' : ''}</button> : null
        })}</div></li>)}</ul>}
        <p className="text-caption text-muted-foreground">긴 본문은 발췌하여 사용합니다.{!!result.data.title_only_count && ` ${result.data.title_only_count}건은 제목만 확인했습니다.`} 해석은 근거 원문과 대조해 주세요.</p>
      </>}
    </div>}
  </section>
}
