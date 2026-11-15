import { PublicFinancialSearch, PublicFinancialsPage } from '@/components/financials/PublicFinancialsPage'
import { Link, useLocation, useMatch } from 'react-router-dom'
import { PublicUsSectorPage } from '@/components/industry/PublicUsSectorPage'
import IndustryMapPage from '@/components/industry/IndustryMapPage'
import { MarketHero } from '@/components/home/MarketHero'
import { PageContainer } from '@/components/shared/PageContainer'
import { Button } from '@/components/ui/button'
import { PublicDocumentPage } from '@/components/doc/PublicDocumentPage'
import { MemberPrinciplesPage } from '@/components/portfolio/MemberPrinciplesPage'
import { MemberPortfolioPage } from '@/components/portfolio/MemberPortfolioPage'
import { PublicDocumentListPage } from '@/components/doc/PublicDocumentListPage'
import { PublicTrialChatPage } from '@/components/chat/PublicTrialChatPage'

/** Incremental public coverage. Never mount a private page behind a hidden UI. */
export function PublicContent() {
  const { pathname } = useLocation()
  const sector = useMatch('/industry/us/:ticker')
  const document = useMatch('/doc/:docId')
  const financial = useMatch('/analyze/:stockCode/financials')
  if (pathname === '/financials') return <PublicFinancialSearch />
  if (financial?.params.stockCode) return <PublicFinancialsPage stockCode={financial.params.stockCode} />
  if (pathname === '/chat') return <PublicTrialChatPage />
  if (pathname === '/feed') return <PublicDocumentListPage />
  if (pathname === '/portfolio/principles') return <MemberPrinciplesPage />
  if (pathname === '/portfolio') return <MemberPortfolioPage />
  if (document?.params.docId) return <PublicDocumentPage docId={document.params.docId} />
  if (sector?.params.ticker) return <PublicUsSectorPage ticker={sector.params.ticker} />
  if (pathname === '/industry') return <IndustryMapPage />
  if (['/', '/home', '/home/kr', '/home/us'].includes(pathname)) {
    const market = pathname === '/home/us' ? 'us' : 'kr'
    return <PageContainer><h1 className="text-xl font-medium">{market === 'kr' ? '한국 시장' : '미국 시장'}</h1>
      <Button variant="outline" asChild><Link to="/financials">기업 재무 조회</Link></Button>
      <MarketHero market={market} />
    </PageContainer>
  }
  return <PageContainer><h1 className="text-xl font-medium">아직 공개되지 않은 화면입니다</h1>
    <p className="text-sm text-ink-2">현재 공개된 시장 정보와 미국 산업 지도를 둘러보세요.</p>
    <Button asChild variant="outline"><Link to="/home/kr">시장으로 이동</Link></Button>
    <Button asChild variant="outline"><Link to="/industry">한국 산업 지도</Link></Button>
    <Button asChild variant="outline"><Link to="/industry?market=us">미국 산업 지도</Link></Button>
  </PageContainer>
}
