import { PeerPerformancePanel } from '@/components/peers/PeerPerformancePanel'
import PeriodToggle from '@/components/shared/PeriodToggle'
import { Link, useSearchParams } from 'react-router-dom'
import { ExternalLink, ChevronDown } from 'lucide-react'
import { PageContainer } from '@/components/shared/PageContainer'
import { PageHeader } from '@/components/shared/PageLayout'
import { QueryState } from '@/components/shared/QueryState'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { usePeerRuntime } from '@/hooks/usePeerRuntime'
import { formatNumber, formatKstDateTime } from '@/utils/format'
import { selectPeerPreset } from '@/lib/peerPresets'
import { selectPeerCompanies } from '@/lib/peerCatalog'
import type { PeerCatalog } from '@/types/peer'

function Catalog({ catalog }: { catalog: PeerCatalog }) {
  const [params, setParams] = useSearchParams()
  const groupId = params.get('group') ?? ''
  const query = params.get('q') ?? ''
  const group = catalog.groups.find(item => item.id === groupId)
  const unknownGroup = !!groupId && !group
  const companies = selectPeerCompanies(catalog, groupId, query)
  const setFilter = (key: string, value: string, replace = false) => {
    setParams(previous => {
      if (key === 'group') return selectPeerPreset(previous, value)
      const next = new URLSearchParams(previous)
      if (value) next.set(key, value)
      else next.delete(key)
      return next
    }, { replace })
  }
  const clear = () => setParams(previous => {
    const next = selectPeerPreset(previous, '')
    next.delete('q')
    return next
  })
  return <>
    <div className="flex flex-wrap items-center gap-2 text-caption text-muted-foreground">
      <Badge variant="outline">사업 근거 카탈로그</Badge>
      <span>조사 기준 {catalog.asOf} · {catalog.companies.length}개 기업 · {catalog.groups.length}개 그룹</span>
      <span>버전 {catalog.version} · 실시간 갱신 아님</span>
    </div>
    <div className="border border-border bg-muted/30 p-4 text-sm" role="note">
      제품·공정의 중첩을 연구자가 분류한 자료입니다. 회사 전체의 직접 경쟁 관계나 같은 매출 노출을 뜻하지 않습니다.
      <p className="mt-1 text-muted-foreground">성과 비교에서는 명시적 정규장 종가의 탐색용 가격변동률을 제공합니다. 기업행사 조정 미검증으로 자동 신호는 발행하지 않습니다.</p>
    </div>
    <div className="grid min-w-0 gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
      <div className="lg:hidden">
        <label className="mb-1 block text-caption" htmlFor="peer-group-select">비교 그룹</label>
        <Select value={unknownGroup ? '__invalid__' : groupId || '__all__'} onValueChange={value => setFilter('group', value === '__all__' ? '' : value)}>
          <SelectTrigger id="peer-group-select" className="w-full"><SelectValue /></SelectTrigger>
          <SelectContent>
            {unknownGroup && <SelectItem value="__invalid__" disabled>존재하지 않는 그룹</SelectItem>}
            <SelectItem value="__all__">전체 기업 · {catalog.companies.length}개</SelectItem>
            {catalog.groups.map(item => <SelectItem key={item.id} value={item.id}>{item.name} · {catalog.companies.filter(company => company.groupIds.includes(item.id)).length}개</SelectItem>)}
          </SelectContent>
        </Select>
      </div>
      <nav aria-label="Peer 그룹 선택" className="hidden max-h-[75vh] space-y-3 overflow-y-auto lg:sticky lg:top-4 lg:block">
        <Button variant={!groupId ? 'secondary' : 'ghost'} className="w-full justify-between" aria-pressed={!groupId} onClick={() => setFilter('group', '')}>
          전체 기업 <span>{catalog.companies.length}</span>
        </Button>
        {(['value_chain', 'product'] as const).map(scope => <div key={scope}>
          <h2 className="mb-2 text-caption font-medium text-muted-foreground">{scope === 'product' ? '제품·공정 관찰군' : '산업·밸류체인'}</h2>
          <div className="flex flex-wrap gap-1 lg:flex-col">
            {catalog.groups.filter(item => item.scope === scope).map(item => <Button key={item.id}
              variant={groupId === item.id ? 'secondary' : 'ghost'} aria-pressed={groupId === item.id}
              onClick={() => setFilter('group', item.id)} className="h-auto min-h-10 justify-between gap-2 whitespace-normal text-left text-caption">
              <span>{item.name}</span><span className="shrink-0 text-muted-foreground">{catalog.companies.filter(company => company.groupIds.includes(item.id)).length}</span>
            </Button>)}
          </div>
        </div>)}
      </nav>
      <section aria-label="그룹 구성 기업과 근거" className="min-w-0 space-y-3">
        <div className="border-b border-border pb-3">
          <h2 className="text-section font-semibold">{unknownGroup ? '그룹을 찾을 수 없습니다' : group?.name ?? '전체 조사 기업'}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{unknownGroup ? `존재하지 않는 그룹 ID: ${groupId}` : group?.interpretation ?? '여러 그룹에 속한 기업도 한 번만 표시합니다. 제품이나 기업명으로 검색해 비교 대상을 좁힐 수 있습니다.'}</p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-0 flex-1"><label htmlFor="peer-query" className="mb-1 block text-caption">기업명·종목코드·제품 검색</label>
            <Input id="peer-query" value={query} onChange={event => setFilter('q', event.target.value, true)} placeholder="예: 티에프이, 변압기, DRAM" />
          </div>
          <Button variant="outline" onClick={clear}>필터 초기화</Button>
        </div>
        <p role="status" aria-live="polite" className="text-caption text-muted-foreground">검색 결과 {companies.length}개 기업</p>
        {companies.length === 0 && <div className="border border-border p-6 text-sm text-muted-foreground">
          {unknownGroup ? '전체 기업을 선택하거나 필터를 초기화해 주세요.' : '이 그룹과 검색어에 맞는 조사 기업이 없습니다. 검색어를 바꾸거나 필터를 초기화해 주세요.'}
        </div>}
        {companies.map(company => <article key={company.code} className="border border-border bg-card p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-base font-semibold"><Link className="hover:underline focus-visible:outline-ring" to={`/analyze/${company.code}/summary`}>{company.name}</Link> <span className="text-caption font-normal text-muted-foreground">{company.code}</span></h3>
            <span className="text-caption text-muted-foreground">조사 {company.asOf}</span>
          </div>
          {company.aliases.length > 0 && <p className="mt-1 text-caption text-muted-foreground">이전 명칭·약칭: {company.aliases.join(' · ')}</p>}
          <p className="mt-2 text-sm">{company.products.join(' · ')}</p>
          <div className="mt-2 flex flex-wrap gap-1">
            {company.groupIds.map(id => <Button key={id} variant="outline" size="sm" className="h-auto min-h-8 whitespace-normal text-caption" onClick={() => setFilter('group', id)}>{catalog.groups.find(item => item.id === id)?.name}</Button>)}
          </div>
          {company.caveats.length > 0 && <ul className="mt-3 list-disc space-y-1 pl-4 text-caption text-muted-foreground">{company.caveats.map((item, index) => <li key={index}>{item}</li>)}</ul>}
          <Collapsible className="mt-3 border-t border-border pt-2">
            <CollapsibleTrigger asChild><Button variant="ghost" size="sm" className="gap-2"><ChevronDown className="size-4" aria-hidden="true" />사업 근거 {company.sources.length}건</Button></CollapsibleTrigger>
            <CollapsibleContent><ul className="mt-2 space-y-3 text-sm">{company.sources.map((source, index) => <li key={`${source.url}-${index}`}>
              <a href={source.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary underline underline-offset-4">{new URL(source.url).hostname}<ExternalLink className="size-3" aria-hidden="true" /><span className="sr-only"> 새 창</span></a>
              <p className="mt-1 text-muted-foreground">{source.claim}</p>
              {(source.period || source.publishedAt) && <p className="text-caption text-muted-foreground">{source.period}{source.publishedAt ? ` · 공개 ${source.publishedAt}` : " · 공개일 미확인"}</p>}
            </li>)}</ul><p className="mt-3 text-caption text-muted-foreground">출처는 사업 내용의 근거입니다. 그룹 편입은 연구자의 판단이며, 조사일을 과거 편입의 유효일로 사용하지 않습니다.</p></CollapsibleContent>
          </Collapsible>
        </article>)}
      </section>
    </div>
  </>
}

export default function PeerCatalogPage() {
  const runtime = usePeerRuntime()
  const [params, setParams] = useSearchParams()
  const view = params.get('view') ?? 'performance'
  return <PageContainer>
    <PageHeader title="Peer 그룹" description="그룹의 가격 흐름과 내부 종목의 상대성과를 비교하고, 사업 근거를 확인합니다." />
    <PeriodToggle value={view} onChange={value => setParams(previous => { const next = new URLSearchParams(previous); next.set('view', value); return next })} options={[{ value: 'performance', label: '성과 비교' }, { value: 'research', label: '사업 근거' }]} />
    <QueryState query={runtime} isEmpty={data => data.catalog.companies.length === 0} emptyMessage="아직 등록된 조사 기업이 없습니다.">
      {data => <>
        <div role="status" className="my-3 space-y-1 border border-border p-3 text-caption text-muted-foreground">
          <p>{data.origin === 'collector' ? '정기 수집본 · 평일 20:30 수집 예정' : '초기 배포본 · 정기 수집본 없음'} · 가격 기준 {data.prices.asOf} · {formatNumber(data.priceAgeDays)}달력일 경과</p>
          <p>가격 수집 {formatKstDateTime(data.prices.collectedAt)} KST {data.baselineOn && `· 관측 시작 ${data.baselineOn}`}</p>
          {data.lastAttempt && <p>마지막 수집 시도 {formatKstDateTime(data.lastAttempt.at)} KST · {data.lastAttempt.status === 'error' ? '실패 — 마지막 정상본 표시' : data.lastAttempt.status === 'skipped' ? '변경 없음' : '성공'}</p>}
          {data.snapshotAgeHours > 72 && <p>가격 스냅샷 생성 후 72시간이 지났습니다. 휴장 여부와 수집 상태를 확인해 주세요.</p>}
          <p>자동 신호 보류 · {data.signalHoldReason}</p>
        </div>
        {view === 'performance' ? <PeerPerformancePanel catalog={data.catalog} snapshot={data.prices} /> : view === 'research' ? <Catalog catalog={data.catalog} /> : <p role="status">존재하지 않는 보기입니다. 성과 비교 또는 사업 근거를 선택해 주세요.</p>}
      </>}
    </QueryState>
  </PageContainer>
}
