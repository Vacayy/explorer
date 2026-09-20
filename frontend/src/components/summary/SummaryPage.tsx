import { useQuery } from '@tanstack/react-query'
import api from '@/api/client'
import { Link, useSearchParams } from 'react-router-dom'
import { useCompany } from '@/hooks/useCompanySearch'
import { useWatchlist, useAddToWatchlist } from '@/hooks/useWatchlist'
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
export default function SummaryPage({
  stockCode,
  corpCode,
}: {
  stockCode: string
  corpCode: string
}) {
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
  const discoveryId = sp.get('discovery')
  return (
    <PageLayout
      header={
        <PageHeader
          title={company?.corp_name || stockCode}
          description={`${stockCode} · ${company?.market || '국내 상장'}${company?.sector ? ' · ' + company.sector : ''}`}
          actions={
            <>
              <WatchlistButton stockCode={stockCode} corpCode={corpCode} />
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
              <CardTitle>이 기업은 무엇을 하나</CardTitle>
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

function WatchlistButton({
  stockCode,
  corpCode,
}: {
  stockCode: string
  corpCode: string
}) {
  const { data: watchlist = [] } = useWatchlist()
  const addToWatchlist = useAddToWatchlist()
  const isInWatchlist = watchlist.some((w) => w.stock_code === stockCode)

  if (isInWatchlist) {
    return (
      <span className="text-xs text-muted-foreground flex items-center gap-1">
        <span className="text-amber-500">★</span> 워치리스트
      </span>
    )
  }

  return (
    <Button
      variant="outline"
      size="xs"
      onClick={() => {
        addToWatchlist.mutate(
          {
            stock_code: stockCode,
            corp_code: corpCode,
            corp_name: '',
            conviction: 3,
          },
          { onSuccess: () => toast.success('워치리스트에 추가되었습니다') },
        )
      }}
      disabled={addToWatchlist.isPending}
    >
      + 워치리스트
    </Button>
  )
}
