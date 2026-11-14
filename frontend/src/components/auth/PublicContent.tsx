import { Link, useLocation } from 'react-router-dom'
import UsIndustryMap from '@/components/industry/UsIndustryMap'
import { MarketHero } from '@/components/home/MarketHero'
import { PageContainer } from '@/components/shared/PageContainer'
import { Button } from '@/components/ui/button'

/** Incremental public coverage. Never mount a private page behind a hidden UI. */
export function PublicContent() {
  const { pathname, search } = useLocation()
  if (pathname === '/industry' && new URLSearchParams(search).get('market') === 'us') {
    return <PageContainer><h1 className="text-xl font-medium">미국 산업 지도</h1>
      <UsIndustryMap bar={asOf => <p className="text-sm text-ink-2">섹터·업종 ETF · 비교 지수 S&amp;P500(SPY){asOf && ` · ${asOf} 종가`}</p>} />
    </PageContainer>
  }
  if (['/', '/home', '/home/kr', '/home/us'].includes(pathname)) {
    const market = pathname === '/home/us' ? 'us' : 'kr'
    return <PageContainer><h1 className="text-xl font-medium">{market === 'kr' ? '한국 시장' : '미국 시장'}</h1>
      <MarketHero market={market} />
    </PageContainer>
  }
  return <PageContainer><h1 className="text-xl font-medium">아직 공개되지 않은 화면입니다</h1>
    <p className="text-sm text-ink-2">현재 공개된 시장 정보와 미국 산업 지도를 둘러보세요.</p>
    <Button asChild variant="outline"><Link to="/home/kr">시장으로 이동</Link></Button>
    <Button asChild variant="outline"><Link to="/industry?market=us">미국 산업 지도</Link></Button>
  </PageContainer>
}
