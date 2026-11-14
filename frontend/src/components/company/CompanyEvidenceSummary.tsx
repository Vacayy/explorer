import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { InfoTip } from '@/components/shared/InfoTip'
import { shortDate } from '@/lib/dossier'
import { formatNumber } from '@/utils/format'
import { DetailLink } from '@/components/shared/DetailNavigation'
import type { EvidenceItem, EvidenceRange } from './CompanyEvidence'

export interface Summary {
  points: { text: string; sources: number[] }[]
  sources: EvidenceItem[]
  used_count: number
  total: number
  title_only_count?: number
  truncated_count?: number
  generated_at: string | null
}
export function CompanyEvidenceSummary({ company, market, range, source, q, disabled, total }: {
  company: string; market: 'kr' | 'us'; range: EvidenceRange; source: string; q: string
  disabled: boolean
  /** 이 조건의 자료 수(머리 줄 표기) */
  total?: number
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
  const span = range.start && range.end ? (range.start === range.end ? shortDate(range.start) : `${shortDate(range.start)} ~ ${shortDate(range.end)}`) : ''
  return <section className="border border-hypothesis/30 bg-hypothesis/5 px-4 py-3" aria-label="선택 기간 자료 요약" data-evidence-summary>
    <div className="flex flex-wrap items-center gap-2">
      <Badge variant="outline" className="border-hypothesis/40 text-[10px] font-normal text-hypothesis">AI 요약</Badge>
      <span className="text-sm text-muted-foreground">{span}{total != null && ` · 자료 ${formatNumber(total)}건`}</span>
      <InfoTip label="기간 요약 설명">지금 기간·출처·검색 조건의 자료를 최대 30건 읽어 무슨 얘기가 돌았는지 요약합니다. 요약 문장마다 근거 자료 번호가 붙습니다. 누를 때만 만듭니다.</InfoTip>
      <span className="ml-auto" />
      <Button variant="outline" size="sm" disabled={disabled || result.isFetching} onClick={() => {
        if (expanded) setOpenedScope('')
        else if (result.data) setOpenedScope(scope)
        else generate()
      }} aria-expanded={expanded}>
        {result.isFetching ? '요약하는 중…' : expanded ? '요약 접기' : result.data ? '요약 보기' : '기간 요약 만들기'}
      </Button>
    </div>
    {/* 요약은 블록 안에서 펼치지 않고 옆 시트로 — 아래 자료 목록이 밀리지 않게(높이 상한과 넘침) */}
    <Sheet open={expanded} onOpenChange={v => { if (!v) setOpenedScope('') }}>
      <SheetContent side="right" className="w-full gap-0 sm:max-w-xl">
        <SheetHeader className="border-b"><SheetTitle>선택 기간 자료 요약</SheetTitle><SheetDescription>{span}{total != null && ` · 자료 ${formatNumber(total)}건`}</SheetDescription>
          {result.data && <Button size="sm" variant="ghost" className="self-start" disabled={disabled || result.isFetching} onClick={generate}>최신 자료로 다시 요약</Button>}</SheetHeader>
        <ScrollArea className="min-h-0 flex-1" viewportClassName="[&>div]:!block"><div className="space-y-3 p-4" aria-live="polite" aria-busy={result.isFetching}>
      {result.isFetching ? <p className="text-sm text-muted-foreground">자료를 읽고 있습니다. 날짜를 바꿔도 이 구간의 요약과 섞이지 않습니다.</p> : result.isError ? <div role="alert"><p className="text-sm">요약을 만들지 못했습니다. 자료는 그대로 읽을 수 있습니다.</p><Button variant="ghost" onClick={generate}>다시 시도</Button></div> : result.data && <>
        <p className="text-caption text-muted-foreground">AI 요약 · 조회 결과 {result.data.total}건 중 {result.data.used_count}건 사용{result.data.generated_at && ` · ${new Date(result.data.generated_at).toLocaleString('ko-KR')}`}</p>
        {result.data.points.length === 0 ? <p className="text-sm">요약할 자료가 없습니다.</p> : <ul className="space-y-4">{result.data.points.map((point, i) => <li key={i} className="text-sm leading-relaxed"><p>{point.text}</p><div className="mt-1 flex flex-wrap gap-1">{point.sources.map(n => {
          const item = result.data.sources[n-1]
          if (!item) return null
          const chip = 'rounded border bg-background px-2 py-1 text-caption text-primary hover:underline'
          const text = `[${n}] ${item.source_type === 'disclosure' ? '공시' : '자료'}${item.status === 'after' ? ' · 이후 공개' : item.status === 'uncertain' ? ' · 당시 공개 미확인' : ''}`
          return item.doc_id ? <DetailLink key={n} className={chip} title={item.title} to={`/doc/${item.doc_id}`}>{text}</DetailLink>
            : /^https?:\/\//i.test(item.url) ? <a key={n} className={chip} title={item.title} href={item.url} target="_blank" rel="noopener noreferrer">{text} ↗</a>
            : <span key={n} className={chip} title={item.title}>{text}</span>
        })}</div></li>)}</ul>}
        <p className="text-caption text-muted-foreground">긴 본문은 발췌하여 사용합니다.{!!result.data.title_only_count && ` ${result.data.title_only_count}건은 제목만 확인했습니다.`} 해석은 근거 원문과 대조해 주세요.</p>
      </>}
    </div></ScrollArea>
      </SheetContent>
    </Sheet>
  </section>
}
