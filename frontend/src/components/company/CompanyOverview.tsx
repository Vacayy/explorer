import { toApiError } from '@/api/errors'
import { track } from "@/lib/usage"
import { useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Globe, LoaderCircle, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/shared/ErrorState'
import { InfoTip } from '@/components/shared/InfoTip'
import { useIsMobile } from '@/hooks/use-mobile'
import { formatNumber, formatRelativeTime } from '@/utils/format'
import type { CompanyWebProfile } from '@/types'

const KIND: Record<string, string> = { filing: '공시', ir: 'IR', news: '뉴스', report: '리포트', other: '기타' }
const profileKey = (code: string, market: string) => ['spine', 'company-profile', market, code] as const

export function useCompanyProfile(code: string, market: 'kr' | 'us' = 'kr') {
  return useQuery({ queryKey: profileKey(code, market), queryFn: async () => (await api.get<{ profile: CompanyWebProfile | null; reuse_hours: number }>(`/api/spine/company-profile/${code}`, { params: { market }, timeout: 180_000 })).data, staleTime: 60_000 })
}

function useBuildProfile(code: string, market: 'kr' | 'us') {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (body: { reason?: string; force?: boolean }) => {
      track('action', 'overview.make', { entity: code })
      try { return (await api.post<{ profile: CompanyWebProfile; reused: boolean; reuse_hours: number }>(`/api/spine/company-profile/${code}`, body, { params: { market }, timeout: 180_000 })).data }
      catch (error) {
        throw toApiError(error)
      }
    },
    onSuccess: data => client.setQueryData(profileKey(code, market), { profile: data.profile, reuse_hours: data.reuse_hours }),
  })
}

function Cited({ text, ids, sources }: { text: string; ids: number[]; sources: CompanyWebProfile['sources'] }) {
  return <span>{text}{ids.length > 0 && <span className="ml-1 text-caption text-muted-foreground">{ids.map(id => { const source = sources.find(s => s.id === id); return source ? <a key={id} className="mr-1 hover:underline" href={source.url} target="_blank" rel="noreferrer" title={source.title}>[{id}]</a> : null })}</span>}</span>
}

/** 사업 구성·제품·경쟁 등 개요 본문 — 넓은 화면은 왼쪽(개요·사업·제품·경쟁) | 오른쪽(동인·리스크·사건·확인 못 한 것) */
function ProfileBody({ profile, brief }: { profile: CompanyWebProfile; brief: boolean }) {
  const sources = profile.sources
  if (brief) return <div className="space-y-3 text-sm">
    <p className="line-clamp-4 leading-relaxed">{profile.overview}</p>
    {profile.drivers.length > 0 && <section aria-label="성장 동인" className="space-y-1"><h3 className="text-caption font-medium text-up-ink">성장 동인</h3>
      <ul className="list-disc space-y-1 pl-5">{profile.drivers.slice(0, 2).map((item, index) => <li key={index}><Cited text={item.text} ids={item.source_ids} sources={sources} /></li>)}</ul></section>}
  </div>
  return <div className="grid gap-x-8 gap-y-5 text-sm lg:grid-cols-2">
    <div className="min-w-0 space-y-4">
      <p className="leading-relaxed">{profile.overview}</p>
      {profile.business_lines.length > 0 && <section aria-label="사업 구성" className="space-y-1.5">
        <h3 className="text-caption font-medium text-muted-foreground">사업 구성</h3>
        <ul className="divide-y">{profile.business_lines.map((line, index) => <li key={index} className="space-y-0.5 py-2">
          <p className="flex flex-wrap items-baseline gap-x-2"><span className="font-medium">{line.name}</span>{line.share_pct != null && <span className="font-mono text-caption tabular-nums text-muted-foreground">{formatNumber(line.share_pct)}%</span>}</p>
          {line.description && <p className="text-muted-foreground"><Cited text={line.description} ids={line.source_ids} sources={sources} /></p>}
        </li>)}</ul>
      </section>}
      {profile.products_customers.length > 0 && <section aria-label="제품·고객" className="space-y-1"><h3 className="text-caption font-medium text-muted-foreground">제품·고객</h3><ul className="list-disc space-y-1 pl-5">{profile.products_customers.map((item, index) => <li key={index}><Cited text={item.text} ids={item.source_ids} sources={sources} /></li>)}</ul></section>}
      {profile.competitors.length > 0 && <section aria-label="경쟁사" className="space-y-1"><h3 className="text-caption font-medium text-muted-foreground">경쟁사</h3><div className="flex flex-wrap gap-1">{profile.competitors.map(name => <Badge key={name} variant="outline" className="font-normal">{name}</Badge>)}</div></section>}
    </div>
    <div className="min-w-0 space-y-4">
      {profile.drivers.length > 0 && <section aria-label="성장 동인" className="space-y-1"><h3 className="text-caption font-medium text-up-ink">성장 동인</h3><ul className="list-disc space-y-1 pl-5">{profile.drivers.map((item, index) => <li key={index}><Cited text={item.text} ids={item.source_ids} sources={sources} /></li>)}</ul></section>}
      {profile.risks.length > 0 && <section aria-label="리스크" className="space-y-1"><h3 className="text-caption font-medium text-down-ink">리스크</h3><ul className="list-disc space-y-1 pl-5">{profile.risks.map((item, index) => <li key={index}><Cited text={item.text} ids={item.source_ids} sources={sources} /></li>)}</ul></section>}
      {profile.recent_events.length > 0 && <section aria-label="최근 사건" className="space-y-1"><h3 className="text-caption font-medium text-muted-foreground">최근 사건</h3><ul className="divide-y">{profile.recent_events.map((event, index) => <li key={index} className="grid grid-cols-[5.5rem_1fr] gap-x-2 py-1.5"><span className="font-mono text-caption tabular-nums text-muted-foreground">{event.date ?? '-'}</span><Cited text={event.title} ids={event.source_ids} sources={sources} /></li>)}</ul></section>}
      {profile.gaps.length > 0 && <section aria-label="확인하지 못한 것" className="space-y-1 bg-muted/60 p-3 text-caption"><h3 className="font-medium">확인하지 못한 것</h3><ul className="list-disc space-y-0.5 pl-5">{profile.gaps.map((g, i) => <li key={i}>{g}</li>)}</ul></section>}
    </div>
    <section aria-label="출처" className="space-y-1 lg:col-span-2">
      <h3 className="text-caption font-medium text-muted-foreground">출처 {sources.length}건</h3>
      <ul className="divide-y border-t">{sources.map(source => <li key={source.id} className="flex flex-wrap items-baseline gap-x-2 py-1.5 text-caption">
        <span className="font-mono text-muted-foreground">[{source.id}]</span>
        <span className="text-muted-foreground">{KIND[source.kind] ?? source.kind} · {source.publisher}</span>
        <a className="min-w-0 flex-1 truncate hover:underline" href={source.url} target="_blank" rel="noreferrer" title={source.fetched ? '원문 확인' : '검색 요약만'}>{source.title || source.url}<ExternalLink className="ml-1 inline size-3" /></a>
        {source.published_at && <span className="font-mono tabular-nums text-muted-foreground">{source.published_at}</span>}
      </li>)}</ul>
    </section>
  </div>
}

/**
 * "기업 개요" 카드: 웹 조사(사업보고서·IR·뉴스·리포트)로 만든 구조화 개요 보고서(D-188, ia-redesign §4.9).
 * 머리 = 웹 조사 버전·조사일·출처 수·공식 보고서(ⓘ)·'웹으로 다시 조사'. 모바일은 접어서 개요 앞부분·성장 동인 두 줄만.
 */
export function CompanyOverviewCard({ stockCode, fallback, market = 'kr' }: { stockCode: string; fallback: ReactNode; market?: 'kr' | 'us' }) {
  const query = useCompanyProfile(stockCode, market)
  const build = useBuildProfile(stockCode, market)
  const mobile = useIsMobile()
  const [open, setOpen] = useState(false)
  const profile = query.data?.profile ?? null
  async function run(force: boolean) {
    try {
      const data = await build.mutateAsync({ force })
      toast.success(data.reused ? `최근 ${data.reuse_hours}시간 안의 보고서를 다시 불러왔습니다.` : `웹 조사를 마쳤습니다. 출처 ${data.profile.sources.length}건`)
    } catch (error) { toast.error(error instanceof Error ? error.message : '웹 조사를 마치지 못했습니다.') }
  }
  const action = <Button size="sm" variant={profile ? 'outline' : 'secondary'} disabled={build.isPending} onClick={() => void run(!!profile)}>
    {build.isPending ? <LoaderCircle className="size-4 animate-spin" /> : profile ? <RefreshCw className="size-4" /> : <Globe className="size-4" />}
    {build.isPending ? '웹 조사 중… (최대 3분)' : profile ? '웹으로 다시 조사' : '웹에서 조사해 개요 만들기'}
  </Button>
  const official = profile?.official_report
  const info = <>{market === 'us' ? 'SEC 10-K·IR·뉴스·애널리스트 기사를' : '사업보고서·IR·뉴스·리포트를'} 웹에서 찾아 구조화합니다. 버튼을 누를 때만 모델을 한 번 호출합니다.
    {official && <> 공식 자료: DART {official.report_nm}{official.rcept_dt ? `(접수 ${official.rcept_dt})` : ''}의 ‘사업의 내용’을 출처 [1]로 썼습니다.</>}
    {profile?.cost_usd != null && <> 조사 비용 ${profile.cost_usd.toFixed(2)}.</>}</>
  return <Card className="gap-0 py-0" aria-label="기업 개요" data-company-overview>
    <header className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 border-b px-4 py-3">
      <h2 className="text-section font-semibold">기업 개요</h2>
      {profile && <span className="text-caption text-muted-foreground">웹 조사 v{profile.version} · {formatRelativeTime(profile.created_at)} · 출처 {profile.sources.length}</span>}
      <InfoTip label="기업 개요 설명">{info}</InfoTip>
      <span className="ml-auto" />
      {!(mobile && profile) && action}
    </header>
    <div className="p-4">
      {query.isPending ? <div className="space-y-2" role="status" aria-label="기업 개요 불러오는 중"><Skeleton className="h-4 w-3/4" /><Skeleton className="h-4 w-1/2" /><Skeleton className="h-4 w-2/3" /></div>
        : query.isError ? <ErrorState message="기업 개요를 불러오지 못했습니다." onRetry={() => query.refetch()} />
        : !profile ? <div className="space-y-3 text-sm">{fallback}{build.error && <p role="alert" className="text-sm text-destructive">{build.error.message}</p>}</div>
        : mobile ? <Collapsible open={open} onOpenChange={setOpen}>
            {!open && <ProfileBody profile={profile} brief />}
            <CollapsibleContent><ProfileBody profile={profile} brief={false} /><div className="mt-3">{action}</div></CollapsibleContent>
            <CollapsibleTrigger asChild><Button variant="ghost" size="sm" className="mt-2 h-8 px-0 font-semibold">{open ? '접기' : '개요 전체 · 리스크 · 출처 ›'}</Button></CollapsibleTrigger>
          </Collapsible>
        : <ProfileBody profile={profile} brief={false} />}
    </div>
  </Card>
}
