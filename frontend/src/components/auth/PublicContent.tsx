import UsDossierPage from "@/components/us/UsDossierPage"
import TranscriptPage from "@/components/follow/TranscriptPage"
import { SeasonView } from "@/components/follow/season/SeasonView"
import { SectorView } from "@/components/follow/season/SectorView"
import RetailHeatPage from "@/components/retail/RetailHeatPage"
import { KrSeasonView } from "@/components/follow/season/KrSeasonView"
import NarrativePage from "@/components/explore/NarrativePage"
import NarrativeHistory from "@/components/explore/NarrativeHistory"
import { PublicFeedPage } from '@/components/feed/PublicFeedPage'
import { isSearchView } from '@/lib/feed'
import { PublicTradePage } from '@/components/follow/PublicTradePage'
import { MemberSavedPage } from '@/components/follow/MemberSavedPage'
import { PublicMacroPage } from '@/components/home/PublicMacroPage'
import { PublicCompanySummary } from '@/components/company/PublicCompanySummary'
import { PublicKrSectorPage } from '@/components/industry/PublicKrSectorPage'
import { PublicFinancialSearch, PublicFinancialsPage } from '@/components/financials/PublicFinancialsPage'
import { Link, useLocation, useMatch } from 'react-router-dom'
import { PublicUsSectorPage } from '@/components/industry/PublicUsSectorPage'
import IndustryMapPage from '@/components/industry/IndustryMapPage'
import HomePage, { HomeKrPage, HomeUsPage } from '@/components/home/HomePage'
import { PageContainer } from '@/components/shared/PageContainer'
import { Button } from '@/components/ui/button'
import { PublicDocumentPage } from '@/components/doc/PublicDocumentPage'
import { MemberPrinciplesPage } from '@/components/portfolio/MemberPrinciplesPage'
import { MemberPortfolioPage } from '@/components/portfolio/MemberPortfolioPage'
import { PublicDocumentListPage } from '@/components/doc/PublicDocumentListPage'
import { PublicTrialChatPage } from '@/components/chat/PublicTrialChatPage'

/** Incremental public coverage. Never mount a private page behind a hidden UI. */
export function PublicContent() {
  const { pathname, search } = useLocation()
  const usCompany = useMatch('/us/:ticker')
  const sector = useMatch('/industry/us/:ticker')
  const krSector = useMatch('/industry/:sector')
  const summary = useMatch('/analyze/:stockCode/summary')
  const document = useMatch('/doc/:docId')
  const financial = useMatch('/analyze/:stockCode/financials')
  const trade = useMatch('/follow/trade/:hs')
  const params = new URLSearchParams(search)
  if (pathname === '/follow/transcripts' && params.get('view') === 'season') {
    if (params.get('market') === 'kr') return <PageContainer><KrSeasonView tabs={null} /></PageContainer>
    const sectorKey = params.get('sector')
    return <PageContainer>{sectorKey ? <SectorView sectorKey={sectorKey} /> : <SeasonView tabs={null} />}</PageContainer>
  }
  if (pathname === '/follow/transcripts') return <TranscriptPage />
  if (usCompany?.params.ticker) return <UsDossierPage ticker={usCompany.params.ticker} />
  if (pathname === '/follow/trade' || trade?.params.hs) return <PublicTradePage hsCode={trade?.params.hs} />
  if (summary?.params.stockCode) return <PublicCompanySummary stockCode={summary.params.stockCode} />
  if (krSector?.params.sector) return <PublicKrSectorPage sector={krSector.params.sector} />
  if (pathname === '/narrative') return <NarrativePage />
  if (pathname === '/narrative/history') return <NarrativeHistory />
  if (pathname === '/home/macro') return <PublicMacroPage />
  if (pathname === '/financials') return <PublicFinancialSearch />
  if (financial?.params.stockCode) return <PublicFinancialsPage stockCode={financial.params.stockCode} />
  if (pathname === '/chat') return <PublicTrialChatPage />
  if (pathname === '/feed/saved') return <MemberSavedPage />
  if (pathname === '/feed') return isSearchView(search) || new URLSearchParams(search).has('cursor') ? <PublicDocumentListPage /> : <PublicFeedPage />
  if (pathname === '/portfolio/principles') return <MemberPrinciplesPage />
  if (pathname === '/portfolio') return <MemberPortfolioPage />
  if (document?.params.docId) return <PublicDocumentPage docId={document.params.docId} />
  if (sector?.params.ticker) return <PublicUsSectorPage ticker={sector.params.ticker} />
  if (pathname === '/industry') return <IndustryMapPage />
  if (pathname === '/' || pathname === '/home') return <HomePage />
  if (pathname === '/retail') return <RetailHeatPage />
  if (pathname === '/home/kr') return <HomeKrPage />
  if (pathname === '/home/us') return <HomeUsPage />
  return <PageContainer><h1 className="text-xl font-medium">아직 공개되지 않은 화면입니다</h1>
    <p className="text-sm text-ink-2">현재 공개된 시장 정보와 미국 산업 지도를 둘러보세요.</p>
    <Button asChild variant="outline"><Link to="/home/kr">시장으로 이동</Link></Button>
    <Button asChild variant="outline"><Link to="/industry">한국 산업 지도</Link></Button>
    <Button asChild variant="outline"><Link to="/industry?market=us">미국 산업 지도</Link></Button>
  </PageContainer>
}
