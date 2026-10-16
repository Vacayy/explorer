import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { rememberRecentStock } from '@/lib/recentStocks'
import api from '@/api/client'
import { Link, useSearchParams } from 'react-router-dom'
import { useCompany } from '@/hooks/useCompanySearch'
import { useDefaultWatchGroup, useToggleWatch } from '@/hooks/useGroups'
import { useBusinessSegments } from '@/hooks/useBusiness'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { PageHeader, PageLayout } from '@/components/shared/PageLayout'
import { CompanyPriceResearch } from '@/components/company/CompanyPriceResearch'
import { CompanyEvidence } from '@/components/company/CompanyEvidence'
import { FinancialPreview } from '@/components/company/CompanyFinancials'
import { DiscoveryResearch } from '@/components/company/DiscoveryResearch'
import { CompanyOverview } from '@/components/company/CompanyOverview'
import SaveButton from '@/components/shared/SaveButton'
import { toast } from 'sonner'

const EMPTY_PRICES: import('@/types').StockPriceItem[] = []
export default function SummaryPage({ stockCode }: { stockCode: string }) {
  const { data: company } = useCompany(stockCode)
  const [sp] = useSearchParams()
  const prices = useQuery({
    queryKey: ['company-prices', stockCode, 'kr'],
    queryFn: async ({ signal }) =>
      (
        await api.get<{ items: import('@/types').StockPriceItem[] }>(
          '/api/spine/feed/company-prices',
          { params: { company: stockCode, market: 'kr' }, signal },
        )
      ).data,
    staleTime: 300_000,
  })
  const segments = useBusinessSegments(stockCode)
  const year = Math.max(...(segments.data?.items.map((s) => s.bsns_year) || []))
  const names =
    segments.data?.items
      .filter((s) => s.bsns_year === year)
      .map((s) => s.segment_name) || []
  const research = sp.get('mode') === 'research'
  useEffect(() => { if (company?.corp_name) rememberRecentStock({ code: stockCode, name: company.corp_name, market: 'kr' }) }, [stockCode, company?.corp_name])
  const discoveryId = sp.get('discovery')
  return (
    <PageLayout
      header={
        <PageHeader
          title={company?.corp_name || stockCode}
          description={`${stockCode} · ${company?.market || '국내 상장'}${company?.sector ? ' · ' + company.sector : ''}`}
          actions={
            <>
              <WatchButton stockCode={stockCode} />
              <SaveButton
                kind="company"
                refId={stockCode}
                url={`/analyze/${stockCode}/summary`}
                title={company?.corp_name || stockCode}
                subtitle={stockCode}
              />
            </>
          }
        />
      }
    >
      <div className="space-y-6">
        {discoveryId ? <DiscoveryResearch
          key={discoveryId}
          caseId={discoveryId}
          stockCode={stockCode}
          priceContext={<CompanyPriceResearch
            key={stockCode}
            company={stockCode}
            prices={prices.data?.items || EMPTY_PRICES}
            loading={prices.isPending}
            error={prices.isError}
            retry={() => void prices.refetch()}
            compact
          />}
        /> : <>
        {!research && (
          <Card>
            <CardHeader>
              <CardTitle>기업 개요</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <CompanyOverview stockCode={stockCode} fallback={<>
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
                  사업보고서 확인 →
                </Link>
              </>} />
            </CardContent>
          </Card>
        )}
        <CompanyPriceResearch
          key={stockCode}
          company={stockCode}
          prices={prices.data?.items || EMPTY_PRICES}
          loading={prices.isPending}
          error={prices.isError}
          retry={() => void prices.refetch()}
          overview={
            <div className="space-y-6">
              <FinancialPreview stockCode={stockCode} />
              <div className="flex justify-end">
                <Link
                  className="text-sm text-primary hover:underline"
                  to={`/analyze/${stockCode}/mentions`}
                >
                  자료 전체 보기 →
                </Link>
              </div>
              <CompanyEvidence company={stockCode} preview />
            </div>
          }
        />
        </>}
      </div>
    </PageLayout>
  )
}

/** ★ — 기본 관심 묶음('관심 종목')에 넣고 뺀다. 관심 종목의 진실원천은 stock_groups 하나. */
function WatchButton({ stockCode }: { stockCode: string }) {
  const group = useDefaultWatchGroup()
  const toggle = useToggleWatch()
  if (!group.data) return null
  const watched = group.data.members.some((m) => m.stock_code === stockCode)
  return (
    <Button
      variant="outline"
      size="xs"
      aria-pressed={watched}
      disabled={toggle.isPending}
      onClick={() =>
        toggle.mutate(
          { stockCode, watched: !watched },
          {
            onSuccess: (detail) => toast.success(watched ? `‘${detail.name}’에서 뺐습니다` : `‘${detail.name}’에 추가했습니다`),
            onError: () => toast.error('관심 종목을 바꾸지 못했습니다'),
          },
        )
      }
    >
      <span className={watched ? 'text-amber-500' : undefined}>{watched ? '★' : '☆'}</span> 관심 종목
    </Button>
  )
}
