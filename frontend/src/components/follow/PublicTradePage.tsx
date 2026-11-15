import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { PageContainer } from '@/components/shared/PageContainer'
import { QueryState } from '@/components/shared/QueryState'
import { ErrorState } from '@/components/shared/ErrorState'
import SegmentTabs from '@/components/shared/SegmentTabs'
import FilterChips from '@/components/shared/FilterChips'
import { MonitorCard, BigChart, StatGrid } from '@/components/industry/MonitorWall'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { usePublicTrade } from '@/hooks/usePublicTrade'
import { formatNumber, formatPercent, formatRatio, formatUsd } from '@/utils/format'
import type { PublicTradeRow, PublicTradeResponse } from '@/types'

const usd = (value: number | null) => value == null ? '-' : `${value < 0 ? '−' : ''}${formatUsd(Math.abs(value))}`
const percent = (value: number | null) => formatPercent(value == null ? null : value * 100)
const FLAG = { none: '', new: '비교값 0', surge: '급등', plunge: '급감' }

export function PublicTradePage({ hsCode }: { hsCode?: string }) {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const flow = params.get('flow') === 'import' ? 'import' : 'export'
  const months = params.get('months') === '24' ? 24 : 60
  const period = params.get('period') || null
  const group = params.get('group') ?? 'all'
  const search = params.get('q') ?? ''
  const selected = hsCode ?? params.get('hs')
  const query = usePublicTrade(flow, period, months)
  const set = (key: string, value: string) => setParams(previous => { const next = new URLSearchParams(previous); if (value) next.set(key, value); else next.delete(key); return next }, { replace: true })
  const listParams = new URLSearchParams(params); listParams.delete('hs')
  const suffix = listParams.size ? `?${listParams}` : ''
  const open = (code: string) => navigate(`/follow/trade/${encodeURIComponent(code)}${suffix}`)
  const label = flow === 'export' ? '수출' : '수입'
  return <PageContainer>
    <nav aria-label="위치" className="text-sm text-ink-3"><Link to="/industry">산업 지도</Link> › <Link to={`/follow/trade${suffix}`}>수출입</Link>{selected && ' › 품목 상세'}</nav>
    <h1 className="font-display text-page font-normal">공개 품목 수출입</h1>
    <p className="text-sm text-ink-2">고정 11개 HS 품목의 저장 통계입니다. 대한민국 전체 무역이나 개인 팔로우 목록을 나타내지 않습니다.</p>
    <div className="flex flex-wrap items-end gap-3">
      <div className="space-y-1"><p className="text-caption text-ink-3">거래 구분</p><SegmentTabs tabs={[{ value: 'export', label: '수출' }, { value: 'import', label: '수입' }]} value={flow} onChange={value => set('flow', value)} /></div>
      <div className="space-y-1"><p className="text-caption text-ink-3">차트 기간</p><SegmentTabs tabs={[{ value: '24', label: '2년' }, { value: '60', label: '5년' }]} value={String(months)} onChange={value => set('months', value)} /></div>
      <div className="min-w-0 space-y-1"><label htmlFor="public-trade-period" className="text-caption text-ink-3">통계월</label><Input id="public-trade-period" type="month" value={period ?? ''} max={query.data?.latest_period ?? undefined} onChange={event => set('period', event.target.value)} className="w-full sm:w-44" /></div>
      {period && <Button variant="outline" onClick={() => set('period', '')}>최신 통계월</Button>}
    </div>
    {query.error ? <ErrorState message="공개 수출입 통계를 확인하지 못했습니다. 이전 결과는 숨겼습니다." onRetry={() => void query.refetch()} retrying={query.isFetching} /> :
      <QueryState query={query} emptyMessage="저장된 공개 품목 통계가 없습니다.">{data => <>
        <p className="text-sm text-ink-3">선택 통계월 {data.period ?? '없음'} · {label} {data.valuation} · 금액 {data.unit} · 저장 시점 {data.fetched_at ?? '미확인'}</p>
        {data.partial && <p role="status" className="text-sm text-ink-3">일부 품목이나 월의 저장 자료가 부족합니다. 결측은 -와 차트의 빈 구간으로 표시하며 0으로 대체하지 않습니다.</p>}
        {data.empty ? <p role="status" className="border p-6 text-sm">저장된 공개 품목 통계가 없습니다.</p> : selected ? <>
          <Button asChild variant="outline"><Link to={`/follow/trade${suffix}`}>품목 목록으로</Link></Button>
          {data.rows.some(row => row.hs_code === selected) ? <TradeDetail row={data.rows.find(row => row.hs_code === selected)!} data={data} /> : <p role="status">공개 카탈로그에 없는 품목입니다.</p>}
        </> : <>
          <section aria-label="공개 카탈로그 집계" className="space-y-3 border p-4">
            <h2 className="text-section font-semibold">공개 카탈로그 {label} 관측 소계 · {usd(data.total.value)}</h2>
            <p className="text-caption text-ink-3">중복 세목을 제외한 {formatNumber(data.total.total_count)}개 중 {formatNumber(data.total.observed_count)}개 품목의 관측값입니다. 국가 전체 무역 총액이 아닙니다.{data.total.partial && ' 일부 품목이 없어 전체 합계로 해석할 수 없습니다.'}</p>
            <div className="grid min-w-0 gap-2 sm:grid-cols-2 lg:grid-cols-3">{data.groups.map(item => <Button key={item.group_label} variant="outline" className="h-auto min-w-0 flex-wrap justify-between gap-2 px-3 py-2 text-left" onClick={() => set('group', item.group_label)}>
              <span className="min-w-0 break-words">{item.group_label}</span><span className="font-mono tabular-nums">{usd(item.value)}</span>
              <span className="w-full text-caption font-normal text-ink-3">관측 {formatNumber(item.observed_count)}/{formatNumber(item.total_count)}개{item.partial ? ' · 일부 관측' : ''}</span>
            </Button>)}</div>
          </section>
          <div className="space-y-3 border-y py-3">
            <Input aria-label="공개 품목 이름 또는 HS 코드 검색" type="search" maxLength={100} value={search} onChange={event => set('q', event.target.value)} className="w-full sm:max-w-sm" />
            <FilterChips options={[{ value: 'all', label: '전체 품목' }, ...Array.from(new Set(data.rows.map(row => row.group_label))).map(value => ({ value, label: value }))]} value={group} onChange={value => set('group', value === 'all' ? '' : value)} />
          </div>
          <TradeCards rows={data.rows.filter(row => (group === 'all' || row.group_label === group) && `${row.item_name} ${row.hs_code}`.toLowerCase().includes(search.trim().toLowerCase()))} label={label} onOpen={open} />
        </>}
        <footer className="space-y-1 border-t pt-3 text-caption text-ink-3">
          <p><a href={data.source_url} target="_blank" rel="noopener noreferrer" className="underline">{data.source} · 품목별 수출입실적 원출처</a></p>
          <p>수출은 FOB, 수입은 CIF 기준이며 금액은 미국 달러(USD)입니다. 통계는 정정될 수 있습니다.</p>
          <p>{data.note}</p>
        </footer>
      </>}</QueryState>}
  </PageContainer>
}

function TradeCards({ rows, label, onOpen }: { rows: PublicTradeRow[]; label: string; onOpen: (code: string) => void }) {
  return <section className="space-y-3" aria-label="공개 품목 모니터">
    <h2 className="text-section font-semibold">품목 모니터 · {formatNumber(rows.length)}개</h2>
    <p className="text-caption text-ink-3">선택 월 {label}액 · 전년 대비 · 월별 막대와 12개월 평균선. 품목마다 차트의 세로축이 다릅니다.</p>
    {rows.length ? <div className="grid min-w-0 grid-cols-2 pr-px pb-px md:grid-cols-3 xl:grid-cols-4">{rows.map(row => <MonitorCard key={row.hs_code} onOpen={onOpen} d={{
      key: row.hs_code, name: row.item_name, group: row.group_label, value: usd(row.metrics.value), yoy: row.metrics.yoy == null ? null : row.metrics.yoy * 100,
      surge: row.metrics.flag === 'surge', badge: row.missing ? '자료 없음' : row.metrics.flag === 'new' ? '비교값 0' : undefined,
      bars: row.series.map(point => point.value), ma: row.series.map(point => point.ma12), connectNulls: false,
    }} />)}</div> : <p role="status" className="border p-6 text-sm">검색·그룹 조건에 맞는 공개 품목이 없습니다.</p>}
  </section>
}

function TradeDetail({ row, data }: { row: PublicTradeRow; data: PublicTradeResponse }) {
  const label = data.flow === 'export' ? '수출' : '수입'
  return <section className="min-w-0 space-y-4 border p-4" aria-label="공개 품목 상세">
    <div className="flex flex-wrap items-baseline gap-2"><h2 className="text-xl font-semibold">{row.item_name}</h2><span className="text-sm text-ink-3">HS {row.hs_code} · {row.group_label}</span>{row.metrics.flag !== 'none' && <Badge variant="outline">{FLAG[row.metrics.flag]}</Badge>}</div>
    <p className="text-caption text-ink-3">통계월 {row.metrics.period} · 품목 저장 시점 {row.fetched_at ?? '미확인'}</p>
    <StatGrid large stats={[{ label: `${label}액 · USD`, value: usd(row.metrics.value) }, { label: '전월 대비', value: percent(row.metrics.mom), tone: row.metrics.mom }, { label: '전년 동월 대비', value: percent(row.metrics.yoy), tone: row.metrics.yoy }, { label: '3개월 합 전년 대비', value: percent(row.metrics.yoy3m), tone: row.metrics.yoy3m }]} />
    <StatGrid stats={[{ label: '수출 FOB · USD', value: usd(row.metrics.export_usd) }, { label: '수입 CIF · USD', value: usd(row.metrics.import_usd) }, { label: '무역수지 · USD', value: usd(row.metrics.balance_usd) }, { label: `${label} 12개월 평균`, value: usd(row.metrics.ma12) }]} />
    <StatGrid stats={[{ label: '직전 3개월 합 대비', value: percent(row.metrics.qoq), tone: row.metrics.qoq }, { label: '평소 대비 z', value: formatNumber(row.metrics.z) }, { label: '절대 증감 기여도', value: formatRatio(row.metrics.contribution == null ? null : row.metrics.contribution * 100) }, { label: '전년 동월 증감액 · USD', value: usd(row.metrics.delta_usd) }]} />
    <p className="text-caption text-ink-3">직전 3개월 합 대비는 최근 3개월 합과 그 앞 3개월 합의 비교이며, 달력상 분기 비교가 아닙니다. 절대 증감 기여도는 관측 가능한 품목의 전년 동월 대비 절대 증감액 합에서 차지하는 몫으로, 순증가 비율이 아닙니다.</p>
    {row.missing && <p role="status" className="text-sm text-ink-3">선택한 월의 관측값이 없습니다. 다른 달의 값으로 대신하지 않습니다.</p>}
    <BigChart data={row.series.map(point => ({ period: point.period, v: point.value, yoy: point.yoy == null ? null : point.yoy * 100 }))} height={320} barLabel={`월별 ${label}액 · USD`} fmt={formatUsd} connectNulls={false} />
    <p className="text-caption text-ink-3">전월·전년·3개월 비교는 해당 달의 자료가 있을 때만 표시합니다. 관측이 없는 달은 차트에서도 빈 구간으로 남습니다.</p>
    {row.metrics.reason && <p className="text-sm text-ink-3">{row.metrics.reason}</p>}
    {row.nested_in && <p className="text-caption text-ink-3">HS {row.nested_in}의 세목입니다. 상위 품목과 중복 합산하지 않습니다.</p>}
  </section>
}
