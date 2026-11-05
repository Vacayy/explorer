import { useEffect, type ReactNode } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { rememberRecentStock } from '@/lib/recentStocks'
import { useCompany } from '@/hooks/useCompanySearch'
import { useCompanyPrices } from '@/hooks/useCompanyPrices'
import { useBusinessSegments } from '@/hooks/useBusiness'
import { PageContainer } from '@/components/shared/PageContainer'
import { CompanyPriceResearch } from '@/components/company/CompanyPriceResearch'
import { CompanyEvidence } from '@/components/company/CompanyEvidence'
import { FinancialPreview } from '@/components/company/CompanyFinancials'
import { DiscoveryResearch } from '@/components/company/DiscoveryResearch'
import { CompanyOverviewCard } from '@/components/company/CompanyOverview'
import { StockActivityStrip } from '@/components/summary/StockActivityStrip'
import { StockActionsBlock } from '@/components/summary/StockActionsBlock'
import { TaiwanLinkCard } from '@/components/company/TaiwanLinkCard'

const EMPTY_PRICES: import('@/types').StockPriceItem[] = []

/**
 * 국내 도시에 개요 (ia-redesign §4.9 · 시안 Dossier-KR) — 머리·핵심 지표(App AnalyzePage) → 기업 개요 → 가격과 거래량
 * → 최근 분기 실적 | 연결 신호·최근 수집 자료 → 기업활동(#actions, 맨 아래 — 옛 /actions?code=X).
 */
export default function SummaryPage({ stockCode }: { stockCode: string }) {
  const { data: company } = useCompany(stockCode)
  const [sp] = useSearchParams()
  const { hash } = useLocation()
  const prices = useCompanyPrices(stockCode, 'kr')
  const segments = useBusinessSegments(stockCode)
  const year = Math.max(...(segments.data?.items.map((s) => s.bsns_year) || []))
  const names =
    segments.data?.items
      .filter((s) => s.bsns_year === year)
      .map((s) => s.segment_name) || []
  const research = sp.get('mode') === 'research'
  useEffect(() => { if (company?.corp_name) rememberRecentStock({ code: stockCode, name: company.corp_name, market: 'kr' }) }, [stockCode, company?.corp_name])
  // #actions(옛 /actions?code=X)로 들어오면 위 블록들이 그려진 뒤 기업활동으로 — 높이가 바뀌므로 한 번 더 맞춘다
  useEffect(() => {
    if (hash !== '#actions') return
    const go = () => document.getElementById('actions')?.scrollIntoView({ block: 'start' })
    const timers = [300, 1200].map((ms) => window.setTimeout(go, ms))
    return () => timers.forEach((t) => window.clearTimeout(t))
  }, [hash, stockCode])
  const discoveryId = sp.get('discovery')
  const priceResearch = (compact: boolean, overview?: ReactNode) => <CompanyPriceResearch
    key={stockCode}
    company={stockCode}
    prices={prices.data?.items || EMPTY_PRICES}
    loading={prices.isPending}
    error={prices.isError}
    retry={() => void prices.refetch()}
    compact={compact}
    overview={overview}
  />
  return (
    <PageContainer>
      {discoveryId ? <DiscoveryResearch
        key={discoveryId}
        caseId={discoveryId}
        stockCode={stockCode}
        priceContext={priceResearch(true)}
      /> : <>
        {!research && <CompanyOverviewCard stockCode={stockCode} fallback={<>
          <p>
            {company?.sector
              ? `${company.sector} 업종의 기업입니다.`
              : '사업 설명을 아직 확보하지 못했습니다.'}
            {names.length > 0 &&
              ` 저장된 사업부는 ${names.join(', ')}입니다 (${year}년).`}
          </p>
          <Link
            className="inline-block text-primary hover:underline"
            to={`/analyze/${stockCode}/mentions?source=disclosure&q=${encodeURIComponent('사업보고서')}`}
          >
            사업보고서 확인 ›
          </Link>
        </>} />}
        {priceResearch(false, (
          <div className="grid gap-3 lg:grid-cols-2">
            <FinancialPreview stockCode={stockCode} />
            <div className="min-w-0 space-y-3">
              <StockActivityStrip stockCode={stockCode} />
              <TaiwanLinkCard stockCode={stockCode} />
              <CompanyEvidence company={stockCode} preview moreTo={`/analyze/${stockCode}/mentions`} />
            </div>
          </div>
        ))}
      </>}
      <div id="actions" className="scroll-mt-4"><StockActionsBlock stockCode={stockCode} /></div>
    </PageContainer>
  )
}
