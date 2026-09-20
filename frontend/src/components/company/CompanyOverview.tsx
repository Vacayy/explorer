import { useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Globe, LoaderCircle, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/shared/ErrorState'
import { formatNumber, formatRelativeTime } from '@/utils/format'
import type { CompanyWebProfile } from '@/types'

const KIND: Record<string, string> = { filing: '공시', ir: 'IR', news: '뉴스', report: '리포트', other: '기타' }
const profileKey = (code: string, market: string) => ['spine', 'company-profile', market, code] as const

export function useCompanyProfile(code: string, market: 'kr' | 'us' = 'kr') {
  return useQuery({ queryKey: profileKey(code, market), queryFn: async () => (await api.get<{ profile: CompanyWebProfile | null; reuse_hours: number }>(`/api/spine/company-profile/${code}`, { params: { market } })).data, staleTime: 60_000 })
}

function useBuildProfile(code: string, market: 'kr' | 'us') {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (body: { reason?: string; force?: boolean }) => {
      try { return (await api.post<{ profile: CompanyWebProfile; reused: boolean; reuse_hours: number }>(`/api/spine/company-profile/${code}`, body, { params: { market } })).data }
      catch (error) {
        const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
        throw new Error(typeof detail === 'string' ? detail : '웹 조사를 마치지 못했습니다.')
      }
    },
    onSuccess: data => client.setQueryData(profileKey(code, market), { profile: data.profile, reuse_hours: data.reuse_hours }),
  })
}

function Cited({ text, ids, sources }: { text: string; ids: number[]; sources: CompanyWebProfile['sources'] }) {
  return <span>{text}{ids.length > 0 && <span className="ml-1 text-caption text-muted-foreground">{ids.map(id => { const source = sources.find(s => s.id === id); return source ? <a key={id} className="mr-1 hover:underline" href={source.url} target="_blank" rel="noreferrer" title={source.title}>[{id}]</a> : null })}</span>}</span>
}

/** "기업 개요": 웹 조사(사업보고서·IR·뉴스·리포트)로 만든 구조화 개요 보고서. D-188. */
export function CompanyOverview({ stockCode, fallback, market = 'kr' }: { stockCode: string; fallback: ReactNode; market?: 'kr' | 'us' }) {
  const query = useCompanyProfile(stockCode, market)
  const build = useBuildProfile(stockCode, market)
  const [sourcesOpen, setSourcesOpen] = useState(false)
  const profile = query.data?.profile ?? null
  async function run(force: boolean) {
    try {
      const data = await build.mutateAsync({ force })
      toast.success(data.reused ? `최근 ${data.reuse_hours}시간 안의 보고서를 다시 불러왔습니다.` : `웹 조사를 마쳤습니다. 출처 ${data.profile.sources.length}건`)
    } catch (error) { toast.error(error instanceof Error ? error.message : '웹 조사를 마치지 못했습니다.') }
  }
  const action = <Button size="sm" variant={profile ? 'ghost' : 'secondary'} disabled={build.isPending} onClick={() => void run(!!profile)}>
    {build.isPending ? <LoaderCircle className="size-4 animate-spin" /> : profile ? <RefreshCw className="size-4" /> : <Globe className="size-4" />}
    {build.isPending ? '웹 조사 중… (최대 3분)' : profile ? '웹으로 다시 조사' : '웹에서 조사해 개요 만들기'}
  </Button>
  if (query.isPending) return <div className="space-y-2" role="status" aria-label="기업 개요 불러오는 중"><Skeleton className="h-4 w-3/4" /><Skeleton className="h-4 w-1/2" /></div>
  if (query.isError) return <ErrorState message="기업 개요를 불러오지 못했습니다." onRetry={() => query.refetch()} />
  if (!profile) return <div className="space-y-3 text-sm">{fallback}<div className="flex flex-wrap items-center gap-2">{action}<span className="text-caption text-muted-foreground">{market === 'us' ? 'SEC 10-K·IR·뉴스·애널리스트 기사를' : '사업보고서·IR·뉴스·리포트를'} 웹에서 찾아 구조화합니다. 누를 때만 모델을 한 번 호출합니다.</span></div>{build.error && <p role="alert" className="text-sm text-destructive">{build.error.message}</p>}</div>
  const sources = profile.sources
  return <div className="space-y-4 text-sm">
    <p className="leading-relaxed">{profile.overview}</p>
    {profile.official_report && <p className="text-caption text-muted-foreground">공식 자료: <a className="hover:underline" href={profile.official_report.url} target="_blank" rel="noreferrer">DART {profile.official_report.report_nm}{profile.official_report.rcept_dt ? ` (접수 ${profile.official_report.rcept_dt})` : ''}</a>의 ‘사업의 내용’ 본문을 출처 [1]로 사용했습니다.</p>}
    {profile.business_lines.length > 0 && <section aria-label="사업부" className="space-y-1.5">
      <h3 className="text-caption font-medium text-muted-foreground">사업 구성</h3>
      <ul className="space-y-1">{profile.business_lines.map((line, index) => <li key={index} className="flex flex-wrap items-baseline gap-x-2"><span className="font-medium">{line.name}</span>{line.share_pct != null && <Badge variant="outline" className="font-normal">매출 {formatNumber(line.share_pct)}%</Badge>}{line.description && <Cited text={line.description} ids={line.source_ids} sources={sources} />}</li>)}</ul>
    </section>}
    {(profile.products_customers.length > 0 || profile.competitors.length > 0) && <section aria-label="제품·고객·경쟁" className="grid gap-3 sm:grid-cols-2">
      {profile.products_customers.length > 0 && <div className="space-y-1"><h3 className="text-caption font-medium text-muted-foreground">제품·고객</h3><ul className="list-disc space-y-1 pl-5">{profile.products_customers.map((item, index) => <li key={index}><Cited text={item.text} ids={item.source_ids} sources={sources} /></li>)}</ul></div>}
      {profile.competitors.length > 0 && <div className="space-y-1"><h3 className="text-caption font-medium text-muted-foreground">경쟁사</h3><div className="flex flex-wrap gap-1">{profile.competitors.map(name => <Badge key={name} variant="secondary" className="font-normal">{name}</Badge>)}</div></div>}
    </section>}
    {(profile.drivers.length > 0 || profile.risks.length > 0) && <section aria-label="동인·리스크" className="grid gap-3 sm:grid-cols-2">
      <div className="space-y-1"><h3 className="text-caption font-medium text-up">성장 동인</h3><ul className="list-disc space-y-1 pl-5">{profile.drivers.map((item, index) => <li key={index}><Cited text={item.text} ids={item.source_ids} sources={sources} /></li>)}</ul></div>
      <div className="space-y-1"><h3 className="text-caption font-medium text-down">리스크</h3><ul className="list-disc space-y-1 pl-5">{profile.risks.map((item, index) => <li key={index}><Cited text={item.text} ids={item.source_ids} sources={sources} /></li>)}</ul></div>
    </section>}
    {profile.recent_events.length > 0 && <section aria-label="최근 사건" className="space-y-1"><h3 className="text-caption font-medium text-muted-foreground">최근 사건</h3><ul className="space-y-1">{profile.recent_events.map((event, index) => <li key={index} className="flex flex-wrap items-baseline gap-x-2"><span className="tabular-nums text-caption text-muted-foreground">{event.date ?? '날짜 미확인'}</span><Cited text={event.title} ids={event.source_ids} sources={sources} /></li>)}</ul></section>}
    {profile.gaps.length > 0 && <p className="rounded-lg bg-hypothesis/10 p-3 text-caption">확인하지 못한 것: {profile.gaps.join(' · ')}</p>}
    <Collapsible open={sourcesOpen} onOpenChange={setSourcesOpen}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <CollapsibleTrigger asChild><Button variant="ghost" size="sm" className="h-7 px-2 text-caption">출처 {sources.length}건 {sourcesOpen ? '접기' : '보기'}</Button></CollapsibleTrigger>
        <span className="text-caption text-muted-foreground">{formatRelativeTime(profile.created_at)} 웹 조사 · v{profile.version}{profile.cost_usd != null && ` · $${profile.cost_usd.toFixed(2)}`}</span>
        {action}
      </div>
      <CollapsibleContent><ul className="mt-2 space-y-1.5">{sources.map(source => <li key={source.id} className="flex flex-wrap items-baseline gap-x-2 text-caption"><span className="text-muted-foreground">[{source.id}]</span><Badge variant="outline" className="font-normal">{KIND[source.kind] ?? source.kind}</Badge><a className="min-w-0 truncate hover:underline" href={source.url} target="_blank" rel="noreferrer">{source.title || source.url}<ExternalLink className="ml-1 inline size-3" /></a><span className="text-muted-foreground">{source.publisher}{source.published_at ? ` · ${source.published_at}` : ''}{source.fetched ? ' · 원문 확인' : ' · 검색 요약만'}</span></li>)}</ul></CollapsibleContent>
    </Collapsible>
  </div>
}
