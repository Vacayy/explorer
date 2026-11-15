import { publicFeedUrl } from '@/lib/publicDocumentNavigation'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { useCompany } from '@/hooks/useCompanySearch'
import { usePublicCompanyPrices } from '@/hooks/usePublicCompanyPrices'
import { PageContainer } from '@/components/shared/PageContainer'
import { QueryState } from '@/components/shared/QueryState'
import { Button } from '@/components/ui/button'
import SegmentTabs from '@/components/shared/SegmentTabs'
import CandlestickChart from '@/components/charts/CandlestickChart'
import { useChartTheme } from '@/components/charts/chartTheme'
import { FinancialPreview } from '@/components/company/CompanyFinancials'
import { CompanyEvidence } from '@/components/company/CompanyEvidence'
import { PublicCompanyOverviewCard } from '@/components/company/CompanyOverview'
import { formatKrw, formatNumber } from '@/utils/format'

export function PublicCompanySummary({ stockCode }: { stockCode: string }) {
  const location = useLocation()
  const company = useCompany(stockCode)
  const [params] = useSearchParams()
  const sector = params.get('sector')
  const search = params.get('sector_query') ?? ''
  const back = sector ? `/industry/${encodeURIComponent(sector)}${search.startsWith('?') ? search : ''}` : '/industry'
  return <PageContainer>
    <Button variant="outline" asChild><Link to={back}>{sector ? `${sector} 섹터로` : '산업 지도로'}</Link></Button>
    <QueryState query={company} emptyMessage="등록되지 않은 종목입니다.">{value => <>
      <header className="space-y-2">
        <h1 className="text-xl font-medium">{value.corp_name} · {value.stock_code}</h1>
        <p className="text-sm text-muted-foreground">{value.market || '시장 구분 없음'} · {value.sector || '업종 분류 없음'}</p>
        <p className="text-sm text-muted-foreground">저장된 기업 설명·시세·공시 재무 및 공개 자료입니다. AI 분석의 공개 연결은 준비 중입니다.</p>
      </header>
      <Button asChild variant="outline"><Link to={publicFeedUrl(value.corp_name, null, location.pathname + location.search)}>기업명으로 공개 문서 검색</Link></Button>
      <PublicCompanyOverviewCard stockCode={stockCode} market="kr" />
      <CompanyEvidence company={stockCode} market="kr" preview />
      <PublicPrices stockCode={stockCode} />
      <FinancialPreview stockCode={stockCode} publicView />
    </>}</QueryState>
  </PageContainer>
}

function PublicPrices({ stockCode }: { stockCode: string }) {
  const prices = usePublicCompanyPrices(stockCode)
  const [params, setParams] = useSearchParams()
  const range = ['3m', '1y', 'all'].includes(params.get('price_range') ?? '') ? params.get('price_range')! : '3m'
  const theme = useChartTheme()
  return <section aria-label="저장 시세" className="min-w-0 space-y-3 border-t py-4">
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-lg font-medium">가격과 거래량</h2>
      <SegmentTabs tabs={[{ value: '3m', label: '3개월' }, { value: '1y', label: '1년' }, { value: 'all', label: '저장 전체' }]}
        value={range} onChange={value => setParams(previous => { const next = new URLSearchParams(previous); next.set('price_range', value); return next }, { replace: true })} />
    </div>
    <QueryState query={prices} isEmpty={data => data.items.length === 0} emptyMessage="저장된 시세가 없습니다.">{data => {
      const last = data.items.at(-1)!
      const from = new Date(`${last.trade_date}T00:00:00Z`)
      if (range === '3m') from.setUTCMonth(from.getUTCMonth() - 3)
      else from.setUTCFullYear(from.getUTCFullYear() - 1)
      const visible = data.items.filter(p => range === 'all' || p.trade_date >= from.toISOString().slice(0, 10))
      const valid = visible.filter(p => [p.open,p.high,p.low,p.close].every(v => v != null && Number.isFinite(v) && v > 0))
      return <>
        <p className="text-sm">{last.trade_date} 종가 {formatNumber(last.close)}원 · 시가총액 {formatKrw(last.market_cap)}</p>
        <p className="text-sm text-muted-foreground">저장 시세 최대 1,500개 · 실시간 아님 · 결측 거래일의 완전성은 확인되지 않았습니다.</p>
        {valid.length !== visible.length && <p role="status" className="text-sm text-muted-foreground">일부 시세가 없어 해당 날짜의 캔들을 표시하지 않았습니다.</p>}
        {valid.length ? <CandlestickChart data={valid.map(p => ({ time:p.trade_date, open:p.open!, high:p.high!, low:p.low!, close:p.close! }))}
          volumeData={valid.filter(p => p.volume != null).map(p => ({ time:p.trade_date, value:p.volume!, color:p.close! >= p.open! ? theme.up : theme.down }))}
          separateVolume height={320} /> : <p role="status">이 기간에 표시할 완전한 시세가 없습니다.</p>}
      </>
    }}</QueryState>
  </section>
}
